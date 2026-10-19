//! The dictation engine: hotkey polling, recording, model loading,
//! transcription and delivery. Port of engine.py.
//!
//! Qt-free. It reports through `emit(event, payload)`; the app forwards
//! events to the GUI thread. Threads:
//!
//!   hotkey poller   reads the keyboard every 10 ms and drives recording
//!   transcriber     decodes takes one at a time from a queue
//!   model loader    downloads and loads models off the other two threads
//!   idle watcher    unloads the model after a while without dictation
//!
//! Not ported from engine.py: history writes, the writer/textproc AI tidy-up
//! (textproc is not in this build), and the ducking mid-take re-scan (this
//! build's ducking module has no rescan).

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

use serde_json::json;

use crate::config::Config;
use crate::ducking;
use crate::hotkeys::{self, Matcher};
use crate::transcribe::{self, Voice};

/// Whisper's favourite inventions on near-silent input.
const PHANTOMS: [&str; 7] = [
    "thank you.",
    "thanks for watching!",
    "thank you for watching.",
    "you",
    "you.",
    "bye.",
    ".",
];
/// "both" mode: a press shorter than this starts a toggle take.
const TAP_SECONDS: f32 = 0.35;
/// How long a take waits for a reloading model before giving up.
const MODEL_WAIT_SECS: f64 = 120.0;

pub type EmitFn = Arc<dyn Fn(&str, serde_json::Value) + Send + Sync>;

// Shared: one status struct plus the things two threads must reach. Lock
// ordering is always status -> voice, never the reverse, so no cycles.
struct EngineShared {
    cfg: Arc<Mutex<Config>>,
    emit: EmitFn,
    status: Mutex<Status>,
    voice: Arc<Mutex<Option<Voice>>>,
    stop: Arc<AtomicBool>,
    jobs_tx: Mutex<Option<mpsc::Sender<TakeJob>>>,
    jobs_pending: Mutex<usize>,
    serial: AtomicU64,
    cancel: Mutex<Arc<AtomicBool>>,
}

struct TakeJob {
    samples: Vec<f32>,
    seconds: f64,
    // Order of the take, so the stop key can drop it; 0 is never dropped.
    seq: u64,
}

pub struct Engine {
    shared: Arc<EngineShared>,
}

struct Status {
    // loading | ready | listening | transcribing | error
    state: &'static str,
    paused: bool,
    suspended: bool,
    wanted: String,
    active: String,
    // idle | downloading | loading | failed
    ms_status: &'static str,
    progress: (u64, u64),
    error: String,
    take_seq: u64,
    cancelled_upto: u64,
    last_used: Instant,
}

impl Status {
    fn new() -> Self {
        Status {
            state: "loading",
            paused: false,
            suspended: false,
            wanted: String::new(),
            active: String::new(),
            ms_status: "idle",
            progress: (0, 0),
            error: String::new(),
            take_seq: 0,
            cancelled_upto: 0,
            last_used: Instant::now(),
        }
    }
}

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    // A panic in one thread must not wedge every thread forever.
    m.lock().unwrap_or_else(|e| e.into_inner())
}

fn title_of(name: &str) -> String {
    transcribe::CATALOG
        .iter()
        .find(|m| m.name == name)
        .map(|m| m.title.to_string())
        .unwrap_or_else(|| name.to_string())
}

/// First line of an error message, as in _short() in engine.py.
fn short(err: &str) -> String {
    let line = err.trim().lines().next().unwrap_or("Error");
    line.chars().take(240).collect()
}

fn sound_volume(cfg: &Config) -> u32 {
    if cfg.bool_value("sounds") {
        cfg.number_value("sound_volume")
    } else {
        0
    }
}

impl Engine {
    pub fn new(cfg: Config, emit: EmitFn) -> Self {
        let shared = EngineShared {
            cfg: Arc::new(Mutex::new(cfg)),
            emit,
            status: Mutex::new(Status::new()),
            voice: Arc::new(Mutex::new(None)),
            stop: Arc::new(AtomicBool::new(false)),
            jobs_tx: Mutex::new(None),
            jobs_pending: Mutex::new(0),
            serial: AtomicU64::new(0),
            cancel: Mutex::new(Arc::new(AtomicBool::new(false))),
        };
        Engine {
            shared: Arc::new(shared),
        }
    }

    pub fn start(&mut self) {
        ducking::recover();
        let (tx, rx) = mpsc::channel::<TakeJob>();
        *lock(&self.shared.jobs_tx) = Some(tx);
        let shared = Arc::clone(&self.shared);
        let _ = std::thread::Builder::new()
            .name("freedictate-transcriber".to_string())
            .spawn(move || transcribe_loop(shared, rx));
        let shared = Arc::clone(&self.shared);
        let _ = std::thread::Builder::new()
            .name("freedictate-hotkey".to_string())
            .spawn(move || poll_loop(shared));
        let shared = Arc::clone(&self.shared);
        let _ = std::thread::Builder::new()
            .name("freedictate-idle".to_string())
            .spawn(move || idle_loop(shared));
        // Instant unload keeps nothing in memory between takes: start unloaded
        // and load on the first hotkey press. Recording starts before the
        // model finishes reloading, so no speech is lost.
        let shared = Arc::clone(&self.shared);
        let instant = {
            let cfg = lock(&shared.cfg);
            bool_cfg(&cfg, "idle_unload", true) && idle_seconds(&cfg) <= 0.0
        };
        if instant {
            let want = { lock(&shared.cfg).string_value("model") };
            lock(&shared.status).wanted = want;
            set_state(&shared, "ready");
        } else {
            self.load_model_async();
        }
    }

    /// Swap in a changed config. The worker threads read it live, so the
    /// next poll and the next take use the new values.
    pub fn set_config(&self, cfg: Config) {
        *lock(&self.shared.cfg) = cfg;
    }

    pub fn shutdown(&mut self) {
        let shared = &self.shared;
        shared.stop.store(true, Ordering::Relaxed);
        lock(&shared.cancel).store(true, Ordering::Relaxed);
        if let Some(tx) = lock(&shared.jobs_tx).take() {
            // A take in flight still finishes its delivery; history is not in
            // this build, so the receiver only exits on the sentinel.
            let _ = tx.send(TakeJob {
                samples: Vec::new(),
                seconds: 0.0,
                seq: 0,
            });
            // The transcriber exits on stop anyway; the sentinel free slot is simpler.
        }
        {
            // Free the model's memory right away.
            let mut voice = lock(&shared.voice);
            voice.take();
        }
        ducking::stop();
    }

    pub fn toggle_pause(&mut self) -> bool {
        let shared = &self.shared;
        let paused = {
            let mut st = lock(&shared.status);
            st.paused = !st.paused;
            st.paused
        };
        let instant = {
            let cfg = lock(&shared.cfg);
            bool_cfg(&cfg, "idle_unload", true) && idle_seconds(&cfg) <= 0.0
        };
        if paused && bool_cfg_cfg(shared, "idle_unload", true) {
            // Paused means no dictation for a while: give the memory back now
            // instead of waiting for the idle timeout.
            unload_model(shared);
        } else if !paused && !instant && bool_cfg_cfg(shared, "idle_unload", true) {
            let (no_model, idle) = {
                let st = lock(&shared.status);
                // engine.py resumes the preload only from an idle model, not
                // a failed one.
                (
                    lock(&shared.voice).is_none(),
                    st.ms_status == "idle",
                )
            };
            if no_model && idle {
                // Resume preloads so the next take is fast again. With instant
                // unload there's no point: it would load now and drop right
                // after the take, so it loads on the hotkey press instead.
                load_model_async_on(shared);
            }
        }
        let state = lock(&shared.status).state;
        (shared.emit)("state", json!({ "state": state }));
        paused
    }

    pub fn status_text(&self) -> String {
        let shared = &self.shared;
        let (hotkey, mode) = {
            let cfg = lock(&shared.cfg);
            (cfg.string_value("hotkey"), cfg.string_value("hotkey_mode"))
        };
        let hk = hotkeys::label(&hotkey);
        let st = lock(&shared.status);
        if st.paused {
            return "Paused".to_string();
        }
        let verb = match mode.as_str() {
            "hold" => "Hold",
            "toggle" => "Press",
            "both" => "Hold or tap",
            _ => "Hold",
        };
        match st.state {
            "loading" => {
                if st.ms_status == "downloading" {
                    let pct = pct_of(st.progress);
                    return format!("Downloading {}{}", title_of(&st.wanted), pct);
                }
                if lock(&shared.voice).is_none()
                    && st.ms_status == "idle"
                    && !st.wanted.is_empty()
                    && st.active.is_empty()
                {
                    return format!("Loading {}", title_of(&st.wanted));
                }
                "Getting the speech model ready".to_string()
            }
            "error" => "Not working. Open Settings for details".to_string(),
            "listening" => "Listening".to_string(),
            "transcribing" => "Transcribing".to_string(),
            _ => {
                if lock(&shared.voice).is_none() && st.ms_status == "idle" {
                    // Unloaded after a while without dictation to give VRAM/RAM
                    // back. The next take reloads it automatically.
                    return format!("Unloaded to save VRAM. {verb} {hk} to dictate");
                }
                if st.ms_status == "downloading" && st.wanted != st.active {
                    let (done, total) = st.progress;
                    let pct = if total > 0 {
                        format!(" ({}%)", done * 100 / total)
                    } else {
                        String::new()
                    };
                    return format!("Ready. Downloading {}{}", title_of(&st.wanted), pct);
                }
                format!("Ready. {verb} {hk} to dictate")
            }
        }
    }

    pub fn state(&self) -> &'static str {
        lock(&self.shared.status).state
    }

    /// (ms_status, active model, done bytes, total bytes) for the UI.
    pub fn model_status(&self) -> (String, String, u64, u64) {
        let st = lock(&self.shared.status);
        (
            st.ms_status.to_string(),
            st.active.clone(),
            st.progress.0,
            st.progress.1,
        )
    }

    /// The audio decode of a file is not reachable in this build (audio.py's
    /// decode_file is not ported), so this says so right away and keeps the
    /// caller's on_text contract.
    pub fn transcribe_file(&mut self, _path: &str, on_text: Box<dyn FnOnce(&str) + Send>) {
        (self.shared.emit)(
            "error",
            json!({
                "title": "File transcription isn't available in this build",
                "text": "Files cannot be decoded yet.",
            }),
        );
        on_text("error: file transcription is not available yet");
    }

    pub fn load_model_async(&mut self) {
        load_model_async_on(&self.shared);
    }

    /// Drop the speech model so its VRAM/RAM goes back to the system. Only
    /// unloads when nothing is using it: not recording, transcribing, loading
    /// or downloading, with an empty queue. Reload happens on the next take.
    pub fn unload_model_now(&mut self) {
        unload_model(&self.shared);
    }
}

// ------------------------------------------------------------------ helpers

fn bool_cfg(cfg: &Config, key: &str, default: bool) -> bool {
    match cfg.get(key) {
        Some(serde_json::Value::Bool(b)) => *b,
        Some(_) => default,
        None => default,
    }
}

fn bool_cfg_cfg(shared: &EngineShared, key: &str, default: bool) -> bool {
    bool_cfg(&lock(&shared.cfg), key, default)
}

/// Seconds without dictation before the model unloads. 0 (the default)
/// unloads the moment each take is delivered, so nothing sits in memory
/// between takes.
fn idle_seconds(cfg: &Config) -> f64 {
    let s = match cfg.get("idle_seconds").and_then(serde_json::Value::as_f64) {
        Some(s) => s,
        None => match cfg.get("idle_seconds").and_then(serde_json::Value::as_i64) {
            Some(v) => v as f64,
            None => 0.0,
        },
    };
    s.clamp(0.0, 3600.0)
}

fn instant_unload(shared: &EngineShared) -> bool {
    bool_cfg_cfg(shared, "idle_unload", true) && idle_seconds_cfg(shared) <= 0.0
}

fn idle_seconds_cfg(shared: &EngineShared) -> f64 {
    idle_seconds(&lock(&shared.cfg))
}

fn pct_of(progress: (u64, u64)) -> String {
    let (done, total) = progress;
    if total > 0 {
        format!(" {}%", done * 100 / total)
    } else {
        String::new()
    }
}

fn set_state(shared: &EngineShared, s: &'static str) {
    let mut st = lock(&shared.status);
    if st.state != s {
        st.state = s;
        let payload = json!({ "state": s });
        drop(st);
        (shared.emit)("state", payload);
    }
}

fn touch(shared: &EngineShared) {
    lock(&shared.status).last_used = Instant::now();
}

/// Make the configured model the active one. The current model keeps working
/// until its replacement is ready, so dictation never goes dark.
fn load_model_async_on(shared: &Arc<EngineShared>) {
    let want = lock(&shared.cfg).string_value("model");
    {
        let mut st = lock(&shared.status);
        let has_voice = lock(&shared.voice).is_some();
        if has_voice && st.active == want {
            return;
        }
        // The loader worker can race a newer request: only the highest serial
        // may finish a download or commit a model. Stop a download for a
        // model no longer wanted.
        let serial = shared.serial.fetch_add(1, Ordering::SeqCst) + 1;
        let old_cancel = lock(&shared.cancel);
        old_cancel.store(true, Ordering::Relaxed);
        drop(old_cancel);
        let cancel = Arc::new(AtomicBool::new(false));
        *lock(&shared.cancel) = cancel.clone();
        st.wanted = want.clone();
        let should_load_state =
            st.state == "ready" && lock(&shared.voice).is_none() && st.ms_status == "idle";
        drop(st);
        if should_load_state {
            set_state(shared, "loading");
        }
        let shared = Arc::clone(shared);
        let _ = std::thread::Builder::new()
            .name("freedictate-loader".to_string())
            .spawn(move || load_worker(shared, want, serial, cancel));
    }
    touch(shared);
}

/// Dictate with an already-downloaded model while the chosen one downloads.
fn load_fallback(shared: &EngineShared, want: &str, serial: u64) {
    for name in transcribe::FALLBACK_ORDER {
        if name == want {
            continue;
        }
        let Some(path) = transcribe::local_path(name) else {
            continue;
        };
        let Ok(voice) = Voice::load(&path) else {
            continue;
        };
        if serial != shared.serial.load(Ordering::SeqCst) {
            return;
        }
        let mut st = lock(&shared.status);
        if st.active.is_empty() {
            *lock(&shared.voice) = Some(voice);
            st.active = name.to_string();
            drop(st);
            set_state(shared, "ready");
        }
        return;
    }
}

fn load_worker(shared: Arc<EngineShared>, want: String, serial: u64, cancel: Arc<AtomicBool>) {
    let outcome = (|| -> Result<(), String> {
        if !transcribe::is_downloaded(&want) {
            if lock(&shared.voice).is_none() {
                load_fallback(&shared, &want, serial);
            }
            let total = {
                let mut st = lock(&shared.status);
                st.ms_status = "downloading";
                let total = transcribe::CATALOG
                    .iter()
                    .find(|m| m.name == want)
                    .map(|m| m.size_mb * 1_000_000)
                    .unwrap_or(0);
                st.progress = (0, total);
                total
            };
            (shared.emit)("model", json!({}));
            let progress = |done: u64, total: u64| {
                if serial == shared.serial.load(Ordering::SeqCst) {
                    lock(&shared.status).progress = (done, total);
                    (shared.emit)(
                        "download",
                        json!({ "done": done, "total": total, "name": want }),
                    );
                }
            };
            transcribe::download(&want, &progress, &cancel)?;
            let _ = total;
            if serial != shared.serial.load(Ordering::SeqCst) {
                return Ok(());
            }
        }
        {
            let mut st = lock(&shared.status);
            st.ms_status = "loading";
        }
        (shared.emit)("model", json!({}));
        let path = transcribe::local_path(&want).ok_or("Downloaded model file is missing")?;
        let voice = Voice::load(&path)?;
        if serial != shared.serial.load(Ordering::SeqCst) {
            return Ok(());
        }
        let switched;
        {
            let mut st = lock(&shared.status);
            let mut v = lock(&shared.voice);
            switched = v.is_some() && !st.active.is_empty() && st.active != want;
            *v = Some(voice);
            st.active = want.clone();
            st.ms_status = "idle";
            st.progress = (0, 0);
            st.last_used = Instant::now();
        }
        let st = lock(&shared.status);
        let was = st.state;
        drop(st);
        if was == "loading" || was == "error" {
            set_state(&shared, "ready");
        }
        (shared.emit)("model", json!({ "ready": true }));
        if switched {
            (shared.emit)(
                "notice",
                json!({ "title": "Model ready", "text": format!("Now using {}.", title_of(&want)) }),
            );
        }
        Ok(())
    })();
    if let Err(e) = outcome {
        if e == "Download cancelled" || serial != shared.serial.load(Ordering::SeqCst) {
            return; // superseded; the newer worker owns the state from here
        }
        let text = short(&e);
        {
            let mut st = lock(&shared.status);
            st.ms_status = "failed";
            st.error = text.clone();
        }
        let no_voice = lock(&shared.voice).is_none();
        if no_voice {
            set_state(&shared, "error");
        }
        (shared.emit)("model", json!({}));
        (shared.emit)(
            "error",
            json!({
                "title": format!("Couldn't get {} ready", title_of(&want)),
                "text": text,
            }),
        );
    }
}

/// Drop the speech model so its VRAM/RAM goes back to the system. Returns
/// true when something was actually freed.
fn unload_model(shared: &EngineShared) -> bool {
    {
        let st = lock(&shared.status);
        if matches!(st.state, "listening" | "transcribing") {
            return false;
        }
        if matches!(st.ms_status, "downloading" | "loading") {
            return false;
        }
        if *lock(&shared.jobs_pending) > 0 {
            return false;
        }
    }
    let mut voice = match shared.voice.try_lock() {
        Ok(v) => v,
        Err(_) => return false, // a file transcription is decoding right now
    };
    if voice.is_none() {
        return false;
    }
    *voice = None;
    drop(voice);
    lock(&shared.status).active = String::new();
    (shared.emit)("model", json!({ "unloaded": true }));
    true
}

/// With idle_seconds 0 (the default), drop everything the moment a take is
/// delivered, so no VRAM is held between takes. The idle watcher is still the
/// backstop for the other paths.
fn release_after_take(shared: &EngineShared) {
    if !instant_unload(shared) {
        return;
    }
    // Another take is queued or being recorded; keep working.
    if *lock(&shared.jobs_pending) > 0 {
        return;
    }
    let st = lock(&shared.status);
    if matches!(st.state, "listening" | "transcribing") {
        return;
    }
    drop(st);
    unload_model(shared);
}

/// Wait for a reloading model after an idle unload. True when ready.
fn wait_for_model(shared: &EngineShared, abort: &dyn Fn() -> bool) -> bool {
    let end = Instant::now() + Duration::from_secs_f64(MODEL_WAIT_SECS);
    while Instant::now() < end {
        if shared.stop.load(Ordering::Relaxed) || abort() {
            return false;
        }
        if lock(&shared.voice).is_some() {
            return true;
        }
        if lock(&shared.status).ms_status == "failed" {
            return false;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    lock(&shared.voice).is_some()
}

// ------------------------------------------------------------------- poller

fn poll_loop(shared: Arc<EngineShared>) {
    let mut recorder = crate::audio::Recorder::new();
    let mut recording = false;
    // Current take is latched (toggle, or a tap in "both").
    let mut tap_toggle = false;
    let mut pressed_at = Instant::now();
    let mut hot_was = false;
    let mut stop_was = false;
    let mut cancel = false;
    let mut matcher = Matcher::new("");
    let mut matcher_text = String::new();
    let mut cancel_matcher = Matcher::new("");
    let mut cancel_text = String::new();
    while !shared.stop.load(Ordering::Relaxed) {
        let outcome = poll_step(
            &shared,
            &mut recorder,
            &mut recording,
            &mut cancel,
            &mut tap_toggle,
            &mut pressed_at,
            &mut matcher,
            &mut matcher_text,
            &mut cancel_matcher,
            &mut cancel_text,
            &mut hot_was,
            &mut stop_was,
        );
        if let Err(e) = outcome {
            eprintln!("hotkey loop error: {e}");
            std::thread::sleep(Duration::from_millis(500));
            continue;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    // Stop flag set while a take is running: take the recorder down cleanly.
    if recording {
        let _ = recorder.stop();
        ducking::stop();
    }
}

#[allow(clippy::too_many_arguments)]
fn poll_step(
    shared: &Arc<EngineShared>,
    recorder: &mut crate::audio::Recorder,
    recording: &mut bool,
    cancel: &mut bool,
    tap_toggle: &mut bool,
    pressed_at: &mut Instant,
    matcher: &mut Matcher,
    matcher_text: &mut String,
    cancel_matcher: &mut Matcher,
    cancel_text: &mut String,
    hot_was: &mut bool,
    stop_was: &mut bool,
) -> Result<(), String> {
    let cfg_now = {
        let cfg = lock(&shared.cfg);
        (cfg.string_value("hotkey"), cfg.string_value("cancel_key"))
    };
    if *matcher_text != cfg_now.0 {
        *matcher_text = cfg_now.0.clone();
        // An invalid hotkey keeps dictation alive on ctrl+win, like the
        // fallback matcher in engine.py.
        let key = if hotkeys::is_valid(&cfg_now.0) {
            cfg_now.0.clone()
        } else {
            "ctrl+win".to_string()
        };
        *matcher = Matcher::new(&key);
    }
    if *cancel_text != cfg_now.1 {
        *cancel_text = cfg_now.1.clone();
        let key = if hotkeys::is_valid(&cfg_now.1) {
            cfg_now.1.clone()
        } else {
            "esc".to_string()
        };
        *cancel_matcher = Matcher::new(&key);
    }
    let hot = matcher.held();
    let suspended = lock(&shared.status).suspended;
    let stop_key = cancel_matcher.held() && !suspended;
    let stop_press = stop_key && !*stop_was;
    let mode = lock(&shared.cfg).string_value("hotkey_mode");
    let now = Instant::now();
    let press = hot && !*hot_was;
    let release = *hot_was && !hot;

    if !*recording {
        if press && usable(shared) && begin(shared, recorder) {
            *recording = true;
            *cancel = false;
            *pressed_at = now;
            *tap_toggle = mode == "toggle";
        } else if stop_press {
            cancel_queued(shared);
        }
    } else {
        if stop_press || lock(&shared.status).paused {
            *cancel = true;
        }
        let mut stop = *cancel;
        if mode == "hold" || (mode == "both" && !*tap_toggle) {
            if release {
                if mode == "both" && now.duration_since(*pressed_at).as_secs_f32() < TAP_SECONDS {
                    // Quick tap: keep listening until the next press.
                    *tap_toggle = true;
                } else {
                    stop = true;
                }
            }
        } else if press {
            stop = true;
        }
        let max_seconds = lock(&shared.cfg).number_value("max_seconds") as f32;
        if recorder.elapsed() >= max_seconds {
            stop = true;
        }
        let silence = lock(&shared.cfg).float_value("auto_stop_silence") as f32;
        if *tap_toggle
            && silence > 0.0
            && recorder.elapsed() > 1.5
            && recorder.silent_for() >= silence
        {
            stop = true;
        }
        if stop {
            *recording = false;
            end_take(shared, recorder, *cancel);
        }
    }
    *hot_was = hot;
    *stop_was = stop_key;
    Ok(())
}

/// True when the hotkey may start a take. Paused or suspended blocks; an
/// unloaded or failed model still lets the take start, when instant/idle
/// unload is configured: audio records while the model reloads, then
/// transcription waits for it.
fn usable(shared: &EngineShared) -> bool {
    let st = lock(&shared.status);
    if st.paused || st.suspended {
        return false;
    }
    if lock(&shared.voice).is_some() {
        return true;
    }
    bool_cfg_cfg(shared, "idle_unload", true) && matches!(st.ms_status, "idle" | "failed")
}

fn begin(shared: &Arc<EngineShared>, recorder: &mut crate::audio::Recorder) -> bool {
    let cfg = {
        let c = lock(&shared.cfg);
        (
            c.bool_value("isolate_output_while_dictating"),
            c.number_value("isolate_output_level"),
            c.float_value("silence_peak") as f32,
            c.bool_value("mic_privacy_while_dictating"),
            c.string_value("input_device"),
        )
    };
    let result = (|| {
        if cfg.0 {
            ducking::start(cfg.1).map_err(|e| e.to_string())?;
        }
        recorder.voice_threshold((0.004f32).max(cfg.2 * 2.0));
        recorder.start(&cfg.4, cfg.3)
    })();
    if let Err(e) = result {
        // Exclusive capture failure would retry a shared start in engine.py,
        // but this build's audio module always captures shared: a failure
        // here is a plain mic-open failure. Never leave other apps' audio
        // ducked.
        ducking::stop();
        (shared.emit)(
            "error",
            json!({ "title": "Couldn't open the microphone", "text": short(&e) }),
        );
        crate::audio::play("error", sound_volume_cfg(shared));
        return false;
    }
    touch(shared);
    if lock(&shared.voice).is_none() {
        // Reloading after an idle unload (or a failed load). Recording
        // already runs so no speech is lost; the transcriber waits.
        load_model_async_on(shared);
    }
    set_state(shared, "listening");
    crate::audio::play("start", sound_volume_cfg(shared));
    true
}

fn sound_volume_cfg(shared: &EngineShared) -> u32 {
    sound_volume(&lock(&shared.cfg))
}

/// The stop key while a take is being written out. The decode itself can't be
/// interrupted, so it finishes in the background and its text is dropped; the
/// app is ready again at once.
fn cancel_queued(shared: &EngineShared) {
    if lock(&shared.status).state != "transcribing" {
        return;
    }
    {
        let mut st = lock(&shared.status);
        st.cancelled_upto = st.take_seq;
    }
    crate::audio::play("cancel", sound_volume_cfg(shared));
    (shared.emit)("cancelled", json!({}));
    let ms_busy = {
        let st = lock(&shared.status);
        st.ms_status == "downloading" || st.ms_status == "loading"
    };
    set_state(shared, if ms_busy { "loading" } else { "ready" });
}

/// A finished (or cancelled) take: hand the audio back to the transcriber and
/// restore the other apps' audio exactly once, here.
fn end_take(shared: &Arc<EngineShared>, recorder: &mut crate::audio::Recorder, cancelled: bool) {
    let vol = sound_volume_cfg(shared);
    let data_secs = recorder.stop();
    if cancelled {
        // The stop key also drops takes still waiting behind this one.
        {
            let mut st = lock(&shared.status);
            st.cancelled_upto = st.take_seq;
        }
        set_state(shared, "ready");
        crate::audio::play("cancel", vol);
        (shared.emit)("cancelled", json!({}));
        ducking::stop();
        return;
    }
    crate::audio::play("stop", vol);
    let (samples, secs) = match data_secs {
        Some(x) if secs_ok(shared, x.1) => x,
        _ => {
            set_state(shared, "ready");
            ducking::stop();
            return;
        }
    };
    touch(shared);
    set_state(shared, "transcribing");
    let seq = {
        let mut st = lock(&shared.status);
        st.take_seq += 1;
        st.take_seq
    };
    {
        let mut pending = lock(&shared.jobs_pending);
        *pending += 1;
    }
    if let Some(tx) = lock(&shared.jobs_tx).as_ref() {
        let _ = tx.send(TakeJob {
            samples,
            seconds: secs,
            seq,
        });
    }
    ducking::stop();
}

fn secs_ok(shared: &EngineShared, secs: f64) -> bool {
    let min = lock(&shared.cfg).float_value("min_seconds");
    secs >= min
}

// --------------------------------------------------------------- transcriber

fn transcribe_loop(shared: Arc<EngineShared>, rx: mpsc::Receiver<TakeJob>) {
    while let Ok(take) = rx.recv() {
        if shared.stop.load(Ordering::Relaxed) {
            // Shutdown sentinel: the empty job exists only to wake this loop.
            break;
        }
        let dropped = {
            let st = lock(&shared.status);
            take.seq != 0 && take.seq <= st.cancelled_upto
        };
        if dropped {
            // log: "Take stopped before transcription"
            finish_job(&shared, take);
            continue;
        }
        run_take(&shared, &take);
        finish_job(&shared, take);
    }
}

/// The loop-back bookkeeping engine.py does in its finally block: ready again
/// when the queue drained, plus the instant unload.
fn finish_job(shared: &Arc<EngineShared>, _take: TakeJob) {
    {
        let mut pending = lock(&shared.jobs_pending);
        if *pending > 0 {
            *pending -= 1;
        }
    }
    let state_now = lock(&shared.status).state;
    if state_now == "transcribing" && *lock(&shared.jobs_pending) == 0 {
        if lock(&shared.voice).is_some() {
            set_state(shared, "ready");
        } else {
            let busy = {
                let st = lock(&shared.status);
                st.ms_status == "downloading" || st.ms_status == "loading"
            };
            if busy {
                set_state(shared, "loading");
            } else {
                set_state(shared, "error");
            }
        }
    }
    release_after_take(shared);
}

fn run_take(shared: &Arc<EngineShared>, take: &TakeJob) {
    let cfg = {
        let c = lock(&shared.cfg);
        (
            c.float_value("silence_peak"),
            c.string_value("language"),
            c.bool_value("trailing_space"),
            c.string_value("output"),
            c.bool_value("restore_clipboard"),
            c.number_value("paste_delay_ms"),
        )
    };
    let vol = sound_volume_cfg(shared);
    let peak = take.samples.iter().fold(0.0f32, |m, x| m.max(x.abs()));
    if peak < cfg.0 as f32 {
        (shared.emit)("nothing", json!({ "reason": "silence" }));
        crate::audio::play("error", vol);
        return;
    }
    touch(shared);
    if lock(&shared.voice).is_none() {
        // The model was unloaded while idle. It reloads on hotkey press, but a
        // slow load can still be running when the take lands here.
        (shared.emit)("state", json!({ "state": lock(&shared.status).state }));
        let aborted = || {
            let st = lock(&shared.status);
            take.seq != 0 && take.seq <= st.cancelled_upto
        };
        if !wait_for_model(shared, &aborted) {
            if aborted() {
                return;
            }
            (shared.emit)(
                "error",
                json!({
                    "title": "The speech model is still loading",
                    "text": "Hold the shortcut again in a few seconds.",
                }),
            );
            let busy = {
                let st = lock(&shared.status);
                st.ms_status == "downloading" || st.ms_status == "loading"
            };
            if !busy {
                set_state(shared, "error");
            }
            return;
        }
    }
    let t0 = Instant::now();
    // An English-only model forces "en" no matter what the setting says.
    let active = lock(&shared.status).active.clone();
    let english_only = transcribe::CATALOG
        .iter()
        .find(|m| m.name == active)
        .map(|m| m.english_only)
        .unwrap_or(false);
    let mut lang = cfg.1.clone();
    if english_only {
        lang = "en".to_string();
    }
    let text = {
        // Held for the decode; unload_model_now tries this lock first and
        // gives up rather than dropping a running transcription.
        let v = lock(&shared.voice);
        let _ = v.is_some();
        match v.as_ref() {
            Some(voice) => voice.transcribe(
                &take.samples,
                if lang == "auto" {
                    None
                } else {
                    Some(lang.as_str())
                },
            ),
            None => Err("The speech model was unloaded.".to_string()),
        }
    };
    let took = t0.elapsed().as_secs_f64();
    touch(shared);
    let raw: String = match text {
        Ok(t) => t.trim().to_string(),
        Err(e) => {
            (shared.emit)(
                "error",
                json!({ "title": "Transcription failed", "text": short(&e) }),
            );
            return;
        }
    };
    let st = lock(&shared.status);
    let dropped = take.seq != 0 && take.seq <= st.cancelled_upto;
    drop(st);
    if dropped {
        return; // "Take stopped while transcribing; text dropped"
    }
    if raw.is_empty() || (peak < 0.05 && PHANTOMS.contains(&raw.to_ascii_lowercase().as_str())) {
        (shared.emit)("nothing", json!({ "reason": "empty" }));
        return;
    }
    // Text clean-up (textproc) is now ported: apply the same cleaning as in Python engine.py
    let mut cleaned = raw.clone();
    // Build options from engine config
    let opts = crate::textproc::Options {
        remove_fillers: lock(&shared.cfg).bool_value("remove_fillers"),
        voice_commands: lock(&shared.cfg).bool_value("voice_commands"),
        capitalize: lock(&shared.cfg).bool_value("capitalize"),
        end_punctuation: lock(&shared.cfg).bool_value("end_punctuation"),
        repeats: lock(&shared.cfg).bool_value("remove_repeats"),
        replacements: vec![],       // replacements not yet configured in this build
        language: Some(lock(&shared.cfg).string_value("language")),
    };
    // Check if active model forces English-only language for cleaning
    let english_only = transcribe::CATALOG
        .iter()
        .find(|m| m.name == active)
        .map(|m| m.english_only)
        .unwrap_or(false);
    let lang = if english_only { "en".to_string() } else { opts.language.as_deref().unwrap_or("").to_string() };
    let mut opts = opts;
    opts.language = Some(lang);
    cleaned = crate::textproc::clean(&cleaned, &opts);
    let delivered = if cfg.2 && cfg.3 != "clipboard" && !cleaned.ends_with('\n') {
        format!("{cleaned} ")
    } else {
        cleaned.clone()
    };
    let outcome = crate::output::deliver(&delivered, &cfg.3, cfg.4, cfg.5);
    (shared.emit)(
        "result",
        json!({
            "text": cleaned,
            "outcome": outcome,
            "seconds": take.seconds,
            "took": took,
        }),
    );
    (shared.emit)(
        "result",
        json!({
            "text": raw,
            "outcome": outcome,
            "seconds": take.seconds,
            "took": took,
        }),
    );
    if outcome != "blocked" {
        crate::audio::play("done", vol);
    }
    if outcome == "blocked" {
        (shared.emit)(
            "error",
            json!({
                "title": "That window runs as administrator",
                "text": "Windows blocks pasting into it. The text is on your clipboard. \
                        Turn on Run as administrator in Settings to paste there.",
            }),
        );
    }
}

// ---------------------------------------------------------------- idle loop

fn idle_loop(shared: Arc<EngineShared>) {
    // Background watcher: unload the speech model after a while without
    // dictation, so games and other apps get the VRAM back. Sleeps in small
    // steps so shutdown doesn't wait long.
    loop {
        if shared.stop.load(Ordering::Relaxed) {
            return;
        }
        let do_check = {
            let st = lock(&shared.status);
            bool_cfg_cfg(&shared, "idle_unload", true)
                && st.ms_status == "idle"
                && (st.state == "ready" || st.state == "error")
                && *lock(&shared.jobs_pending) == 0
                && lock(&shared.voice).is_some()
                && st.last_used.elapsed() >= Duration::from_secs_f64(idle_seconds_cfg(&shared))
        };
        if do_check {
            unload_model(&shared);
        }
        for _ in 0..15 {
            if shared.stop.load(Ordering::Relaxed) {
                return;
            }
            std::thread::sleep(Duration::from_secs(1));
        }
    }
}
