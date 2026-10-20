//! Microphone capture, device list and feedback sounds. Port of audio.py.
//!
//! WASAPI is reached through cpal. cpal 0.18's WASAPI host only opens capture
//! devices in shared mode: `build_input_stream` always passes
//! `AUDCLNT_SHAREMODE_SHARED` to `IAudioClient::Initialize`
//! (src/host/wasapi/device.rs), and neither the host nor the device API
//! exposes exclusive mode. So `Recorder::start(.., exclusive = true)` opens
//! the best shared-mode capture available: a plain 16 kHz mono stream when the
//! device and Windows' audio engine accept it, otherwise the device's default
//! mix format, downmixed to mono and resampled to 16 kHz with rubato's streaming
//! sinc filter (the filter state is carried across capture blocks, so there is
//! no aliasing and no drift at block edges, like the soxr stream in audio.py).
//! Startup fails only when no microphone can be opened at all.
//!
//! Feedback sounds are rendered to small WAV files under
//! `%APPDATA%\FreeDictate-Rust\sounds`, cached by name and volume, and played
//! asynchronously with `PlaySoundW`.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{BufferSize, StreamConfig};
use rubato::audioadapter_buffers::direct::SequentialSliceOfVecs;
use rubato::{Async, FixedAsync, Indexing, Resampler, SincInterpolationParameters, WindowFunction};

pub const RATE: u32 = 16000;

const RECV_TIMEOUT: Duration = Duration::from_secs(10);
const STOP_POLL: Duration = Duration::from_millis(20);

/// Process-wide live mic level for the UI (0..1 RMS from the running
/// capture stream; 0.0 when idle). One atomic write per callback block;
/// the settings mic meter and the dictation meter read it through the
/// ui::level subscription, replacing the take-boundary-only snapshots.
static LIVE_LEVEL: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);

/// Publish a live level (called only from the capture/data callback path).
fn live_set(value: f32) {
    LIVE_LEVEL.store((value.max(0.0).min(1.0)).to_bits(), Ordering::Relaxed);
}

/// The live level (0..1) the running capture stream hears; 0.0 when idle.
/// Stays independent of any one Recorder, so every window in the app can
/// read it.
pub fn live_level() -> f32 {
    f32::from_bits(LIVE_LEVEL.load(Ordering::Relaxed))
}

/// Stored device name + display name. cpal's WASAPI host reports the full
/// friendly name directly, so the 31-character MME truncation in audio.py
/// never applies and name == label.
#[derive(Debug, Clone)]
pub struct Device {
    pub name: String,
    pub label: String,
    pub is_default: bool,
}

/// PortAudio re-scanned the device tree here. cpal enumerates fresh on every
/// `input_devices()` call, so there is nothing to refresh.
pub fn refresh_devices() {}

/// Input devices on the default cpal host (WASAPI on Windows), no Sound
/// Mapper entry, deduplicated by name, default flag from the host's default.
pub fn input_devices() -> Vec<Device> {
    let host = cpal::default_host();
    let default_name = host.default_input_device().map(|d| d.to_string());
    let mut out = Vec::new();
    let mut seen: Vec<String> = Vec::new();
    let Ok(devices) = host.input_devices() else {
        return out;
    };
    for dev in devices {
        let name = dev.to_string().trim_end().to_string();
        if name.starts_with("Microsoft Sound Mapper") || seen.contains(&name) {
            continue;
        }
        seen.push(name.clone());
        out.push(Device {
            is_default: default_name.as_deref() == Some(name.as_str()),
            label: name.clone(),
            name,
        });
    }
    out
}

/// Direct device for a stored name, or the system default when `want` is
/// empty or matches nothing (same fallback as resolve() in audio.py).
fn resolve_device(
    host: &cpal::platform::Host,
    want: &str,
) -> Result<cpal::platform::Device, String> {
    let devices: Vec<cpal::platform::Device> = host
        .input_devices()
        .map_err(|e| format!("input devices: {e}"))?
        .into_iter()
        .collect();
    let want = want.trim_end().to_lowercase();
    if want.is_empty() {
        return host
            .default_input_device()
            .ok_or_else(|| "No input microphone found".to_string());
    }
    let lower: Vec<(String, cpal::platform::Device)> = devices
        .into_iter()
        .map(|d| (d.to_string().trim_end().to_lowercase(), d))
        .collect();
    if let Some((_, d)) = lower.iter().find(|(n, _)| *n == want) {
        return Ok(d.clone());
    }
    if let Some((_, d)) = lower.iter().find(|(n, _)| n.contains(&want)) {
        return Ok(d.clone());
    }
    host.default_input_device()
        .ok_or_else(|| format!("Microphone {want:?} not found and no default input exists"))
}

fn lock_state(state: &Mutex<State>) -> MutexGuard<'_, State> {
    state.lock().unwrap_or_else(|e| e.into_inner())
}

/// Average the channels of an interleaved capture buffer down to mono.
fn downmix(data: &[f32], channels: usize) -> Vec<f32> {
    if channels <= 1 || data.len() <= channels {
        data.to_vec()
    } else {
        data.chunks_exact(channels)
            .map(|frame| frame.iter().sum::<f32>() / channels as f32)
            .collect()
    }
}

/// Latency-correcting chain from a device's native rate to 16 kHz mono.
/// Feed it downmixed mono data; it appends 16 kHz samples to `out`.
/// Without a resampler (device already at 16 kHz) it just passes through.
struct Chain {
    res: Option<Async<f32>>,
    pending: Vec<f32>,
    // Output frames of filter startup silence still to drop, counted
    // against the very first output samples of the take.
    delay_left: usize,
    // 16 kHz frames produced per input frame, 1.0 without a resampler.
    ratio: f64,
    // Real input frames received and real 16 kHz frames emitted.
    total_in: usize,
    produced: usize,
}

impl Chain {
    fn new(rate_in: u32) -> Result<Self, String> {
        let mut chain = Chain {
            res: None,
            pending: Vec::new(),
            delay_left: 0,
            ratio: 1.0,
            total_in: 0,
            produced: 0,
        };
        if rate_in == RATE {
            return Ok(chain);
        }
        let ratio = RATE as f64 / rate_in as f64;
        let params = SincInterpolationParameters::new(256, WindowFunction::BlackmanHarris2);
        let res = Async::<f32>::new_sinc(ratio, 1.1, &params, 1024, 1, FixedAsync::Input)
            .map_err(|e| format!("Resampling {rate_in} Hz to {RATE} Hz failed: {e}"))?;
        let delay = res.output_delay();
        chain.res = Some(res);
        chain.ratio = ratio;
        chain.delay_left = delay;
        Ok(chain)
    }

    // Process one full (or final partial) input chunk; return false when
    // rubato rejected the chunk. Consumed real frames go via `pending`/feed.
    fn pump(
        res: &mut Async<f32>,
        chunk: &[f32],
        real_len: usize,
        delay_left: &mut usize,
        produced: &mut usize,
        out: &mut Vec<f32>,
    ) -> bool {
        let buf = [chunk.to_vec()];
        let Ok(adapter) = SequentialSliceOfVecs::new(&buf, 1, buf[0].len()) else {
            return false;
        };
        let indexing = Indexing::new().partial_len(real_len);
        let Ok(result) = res.process(&adapter, Some(&indexing)) else {
            return false;
        };
        let mut samples = result.take_data();
        if *delay_left > 0 {
            let skip = (*delay_left).min(samples.len());
            samples.drain(..skip);
            *delay_left -= skip;
        }
        if samples.is_empty() {
            return true;
        }
        *produced += samples.len();
        out.extend_from_slice(&samples);
        true
    }

    fn feed(&mut self, data: &[f32], out: &mut Vec<f32>) {
        self.total_in += data.len();
        let Some(res) = self.res.as_mut() else {
            out.extend_from_slice(data);
            return;
        };
        self.pending.extend_from_slice(data);
        let need = res.input_frames_next();
        while self.pending.len() >= need {
            let chunk: Vec<f32> = self.pending.drain(..need).collect();
            if !Self::pump(
                res,
                &chunk,
                need,
                &mut self.delay_left,
                &mut self.produced,
                out,
            ) {
                break;
            }
        }
    }

    // Push the last real frames plus silence padding through the filter so
    // the whole take reaches the expected output length, then trim the
    // padding overshoot off the end of `out`.
    fn flush(&mut self, out: &mut Vec<f32>) {
        let Some(res) = self.res.as_mut() else {
            return;
        };
        let expected = (self.total_in as f64 * self.ratio).round() as usize;
        // Feed the remaining buffered frames as a final partial chunk; rubato
        // pads the rest of the chunk with silence.
        let real = self.pending.len();
        if real > 0 {
            let chunk = std::mem::take(&mut self.pending);
            Self::pump(
                res,
                &chunk,
                real,
                &mut self.delay_left,
                &mut self.produced,
                out,
            );
        } else {
            self.pending.clear();
        }
        // Pump silence until the real signal has left the filter.
        let need = res.input_frames_next();
        let silence = vec![0.0f32; need];
        let mut guard = 0;
        while self.produced < expected && guard < 256 {
            if !Self::pump(
                res,
                &silence,
                need,
                &mut self.delay_left,
                &mut self.produced,
                out,
            ) {
                break;
            }
            guard += 1;
        }
        // The padding that overshot `expected` is trailing silence; cut it.
        let excess = self.produced.saturating_sub(expected);
        if excess > 0 {
            let cut = excess.min(out.len());
            out.truncate(out.len() - cut);
            self.produced -= cut;
        }
    }
}

/// One take's samples, metering and clock. Shared between the engine thread
/// and the capture thread's data callback through a single mutex.
struct State {
    threshold: f32,
    started: Instant,
    last_voice: Instant,
    level: f32,
    peak: f32,
    chunks: Vec<Vec<f32>>,
    chain: Chain,
}

impl State {
    fn new() -> Self {
        let now = Instant::now();
        State {
            threshold: 0.01,
            started: now,
            last_voice: now,
            level: 0.0,
            peak: 0.0,
            chunks: Vec::new(),
            chain: Chain::new(RATE).expect("pass-through chain never fails"),
        }
    }

    // Mirror _accept() in audio.py: store the chunk, refresh the meter, and
    // stamp last voice when the block is above threshold.
    fn accept_out(&mut self, chunk: &[f32]) {
        if chunk.is_empty() {
            return;
        }
        let sum_sq: f32 = chunk.iter().map(|x| x * x).sum();
        let rms = (sum_sq / chunk.len() as f32).sqrt();
        let peak = chunk.iter().fold(0.0f32, |m, x| m.max(x.abs()));
        self.chunks.push(chunk.to_vec());
        self.level = rms;
        live_set(rms);
        if peak > self.peak {
            self.peak = peak;
        }
        if rms > self.threshold {
            self.last_voice = Instant::now();
        }
    }
}

/// One take at a time. The stream is opened per take so Windows only shows
/// the microphone-in-use indicator while you are actually dictating.
///
/// `level` and `peak` are snapshots updated when a take starts or stops;
/// poll `level()` / `peak()` for the live values from the capture stream.
pub struct Recorder {
    pub level: f32,
    pub peak: f32,
    state: Arc<Mutex<State>>,
    capture: Option<CaptureHandle>,
}

struct CaptureHandle {
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<()>>,
}

impl Recorder {
    pub fn new() -> Self {
        Recorder {
            level: 0.0,
            peak: 0.0,
            state: Arc::new(Mutex::new(State::new())),
            capture: None,
        }
    }

    pub fn active(&self) -> bool {
        self.capture.is_some()
    }

    /// Seconds since the take started; 0 when not capturing.
    pub fn elapsed(&self) -> f32 {
        if !self.active() {
            return 0.0;
        }
        lock_state(&self.state).started.elapsed().as_secs_f32()
    }

    /// Seconds since the level last rose above the voice threshold; 0 when
    /// not capturing.
    pub fn silent_for(&self) -> f32 {
        if !self.active() {
            return 0.0;
        }
        lock_state(&self.state).last_voice.elapsed().as_secs_f32()
    }

    /// Live capture-level RMS from the running stream (0.0 when not capturing).
    pub fn level(&self) -> f32 {
        lock_state(&self.state).level
    }

    /// Live loudest sample of the take so far.
    pub fn peak(&self) -> f32 {
        lock_state(&self.state).peak
    }

    /// Setter matching `recorder.voice_threshold = max(0.004, silence_peak*2)`.
    /// The capture callback reads it under the shared lock, so it applies
    /// while a take is running.
    pub fn voice_threshold(&mut self, t: f32) {
        lock_state(&self.state).threshold = t;
    }

    /// Open a capture stream. `device_name` is a stored device name from
    /// `input_devices()`; empty means the system default. When the name
    /// matches nothing, capture falls back to the system default like
    /// resolve() in audio.py. Exclusive WASAPI capture is not reachable
    /// through cpal, so `exclusive` just means "use the best available
    /// shared-mode capture"; see the module comment. `max_seconds` and the
    /// silence auto-stop live in the engine layer, fed by `elapsed()` and
    /// `silent_for()`.
    pub fn start(&mut self, device_name: &str, exclusive: bool) -> Result<(), String> {
        self.stop();
        let state = self.state.clone();
        let stop = Arc::new(AtomicBool::new(false));
        let thread_stop = stop.clone();
        let (tx, rx) = mpsc::channel::<Result<(), String>>();
        let name = device_name.to_string();
        let handle = std::thread::Builder::new()
            .name("freedictate-capture".to_string())
            .spawn(move || capture_thread_main(name, exclusive, state, thread_stop, tx))
            .map_err(|e| format!("Capture thread failed to start: {e}"))?;
        match rx.recv_timeout(RECV_TIMEOUT) {
            Ok(Ok(())) => {
                self.capture = Some(CaptureHandle {
                    stop,
                    join: Some(handle),
                });
                let snapshot = lock_state(&self.state);
                self.level = snapshot.level;
                self.peak = snapshot.peak;
                Ok(())
            }
            Ok(Err(e)) => {
                let _ = handle.join();
                Err(e)
            }
            Err(_) => {
                stop.store(true, Ordering::Relaxed);
                let _ = handle.join();
                Err("Capture did not start in time".to_string())
            }
        }
    }

    /// Stop the stream and return the whole take as 16 kHz mono samples and
    /// its length in seconds, or None when nothing was captured.
    pub fn stop(&mut self) -> Option<(Vec<f32>, f64)> {
        let chunks = self.stop_capture()?;
        if chunks.is_empty() {
            return None;
        }
        let all: Vec<f32> = chunks.concat();
        let duration = all.len() as f64 / RATE as f64;
        Some((all, duration))
    }

    // Shared tail of stop() and the discard at the top of start(): take down
    // the stream, wait for the capture thread to flush the resampler tail,
    // then move the chunks out. None when there was no take running.
    fn stop_capture(&mut self) -> Option<Vec<Vec<f32>>> {
        let cap = self.capture.take()?;
        cap.stop.store(true, Ordering::Relaxed);
        if let Some(h) = cap.join {
            let _ = h.join();
        }
        let mut snapshot = lock_state(&self.state);
        snapshot.level = 0.0;
        self.level = 0.0;
        live_set(0.0);
        // Peak keeps the take's value, like stop() in audio.py.
        self.peak = snapshot.peak;
        Some(std::mem::take(&mut snapshot.chunks))
    }
}

// ----------------------------------------------------------------- capture

fn capture_thread_main(
    device_name: String,
    exclusive: bool,
    state: Arc<Mutex<State>>,
    stop: Arc<AtomicBool>,
    ready: mpsc::Sender<Result<(), String>>,
) {
    let host = cpal::default_host();
    {
        // Fresh take: clear leftovers and open a new clock before anything
        // can push samples, like the top half of start() in audio.py.
        let mut snapshot = lock_state(&state);
        *snapshot = State::new();
    }
    let device = match resolve_device(&host, &device_name) {
        Ok(d) => d,
        Err(e) => {
            let _ = ready.send(Err(e));
            return;
        }
    };

    // First try a plain 16 kHz mono stream; that works when the device or
    // Windows' audio engine already runs at 16 kHz. Otherwise fall back to
    // the device's own mix format and resample.
    let opened = match try_build(&device, RATE, 1, &state, &stop) {
        Ok(s) => Ok(s),
        Err(e16) => match device.default_input_config() {
            Ok(def) => {
                let rate = def.sample_rate();
                let channels = def.channels() as usize;
                try_build(&device, rate, channels, &state, &stop)
                    .map_err(|e2| format!("{e16}; default format also failed: {e2}"))
            }
            Err(e) => Err(format!("{e16}; no default input format: {e}")),
        },
    };

    let stream = match opened {
        Ok(s) => s,
        Err(e) => {
            let msg = if exclusive {
                format!("Exclusive capture is unavailable; shared capture failed: {e}")
            } else {
                e
            };
            let _ = ready.send(Err(msg));
            return;
        }
    };
    if let Err(e) = stream.play() {
        let msg = if exclusive {
            format!("Exclusive capture is unavailable; shared capture failed to start: {e}")
        } else {
            format!("Capture failed to start: {e}")
        };
        let _ = ready.send(Err(msg));
        return;
    }
    let _ = ready.send(Ok(()));

    // Park until the engine asks for the take back; the data callback keeps
    // running on cpal's own audio thread.
    while !stop.load(Ordering::Relaxed) {
        std::thread::sleep(STOP_POLL);
    }
    // Dropping the stream stops cpal's audio thread and its callbacks, so
    // the flush below cannot race a live callback.
    drop(stream);
    {
        let mut snapshot = lock_state(&state);
        let mut tail = Vec::new();
        snapshot.chain.flush(&mut tail);
        if !tail.is_empty() {
            snapshot.accept_out(&tail);
        }
    }
}

// Build and return (not start) one input stream at a fixed rate and channel
// count. Replaces the chain in shared state to match, so a failed attempt
// leaves no stale resampler behind for the next attempt.
fn try_build(
    device: &cpal::platform::Device,
    rate: u32,
    channels: usize,
    state: &Arc<Mutex<State>>,
    _stop: &Arc<AtomicBool>,
) -> Result<cpal::platform::Stream, String> {
    let chain = Chain::new(rate)?;
    {
        let mut snapshot = lock_state(state);
        snapshot.chain = chain;
    }
    let state = Arc::clone(state);
    let config = StreamConfig {
        channels: channels as u16,
        sample_rate: rate,
        buffer_size: BufferSize::Default,
    };
    let data_cb = move |data: &[f32], _: &cpal::InputCallbackInfo| {
        let mono = downmix(data, channels);
        let mut snapshot = lock_state(&state);
        let mut outs = Vec::new();
        snapshot.chain.feed(&mono, &mut outs);
        snapshot.accept_out(&outs);
    };
    let error_cb = move |_e: cpal::Error| {
        // A dying device closes the take from the engine side; audio.py also
        // just logged stream errors at debug level.
    };
    device
        .build_input_stream::<f32, _, _>(config, data_cb, error_cb, None)
        .map_err(|e| e.to_string())
}

// ----------------------------------------------------------------- sounds

// name: list of (frequency Hz, duration s) notes, played back to back.
const SOUNDS: &[(&str, &[(u32, f32)])] = &[
    ("start", &[(660, 0.05), (990, 0.07)]),
    ("stop", &[(990, 0.05), (740, 0.07)]),
    ("cancel", &[(520, 0.06), (390, 0.09)]),
    ("error", &[(330, 0.09), (262, 0.14)]),
    ("done", &[(880, 0.04), (1175, 0.04), (1568, 0.09)]),
];
// Bump when a tone above changes, so cached WAVs from older versions are not reused.
const SOUND_REV: u32 = 2;

// Same samples as _render() in audio.py: 44.1 kHz 16-bit mono PCM with a short
// attack and release and a touch of second harmonic.
fn render(notes: &[(u32, f32)], volume: f64) -> Vec<u8> {
    const SR: u32 = 44100;
    const ATTACK: usize = (SR as f64 * 0.006) as usize;
    const RELEASE: usize = (SR as f64 * 0.03) as usize;
    let mut data: Vec<u8> = Vec::new();
    for &(freq, dur) in notes {
        let n = (SR as f32 * dur).round() as usize;
        for i in 0..n {
            let env =
                1.0f64.min(i as f64 / ATTACK as f64) * 1.0f64.min((n - i) as f64 / RELEASE as f64);
            let s = (2.0 * std::f64::consts::PI * freq as f64 * i as f64 / SR as f64).sin()
                + 0.18 * (4.0 * std::f64::consts::PI * freq as f64 * i as f64 / SR as f64).sin();
            let sample = (s * env * volume * 0.32 * 32767.0).clamp(-32767.0, 32767.0) as i16;
            data.extend_from_slice(&sample.to_le_bytes());
        }
    }
    let mut wav = Vec::with_capacity(44 + data.len());
    wav.extend_from_slice(b"RIFF");
    wav.extend_from_slice(&(36 + data.len() as u32).to_le_bytes());
    wav.extend_from_slice(b"WAVE");
    wav.extend_from_slice(b"fmt ");
    wav.extend_from_slice(&16u32.to_le_bytes());
    wav.extend_from_slice(&1u16.to_le_bytes()); // PCM
    wav.extend_from_slice(&1u16.to_le_bytes()); // mono
    wav.extend_from_slice(&SR.to_le_bytes());
    wav.extend_from_slice(&(SR * 2).to_le_bytes());
    wav.extend_from_slice(&2u16.to_le_bytes());
    wav.extend_from_slice(&16u16.to_le_bytes());
    wav.extend_from_slice(b"data");
    wav.extend_from_slice(&(data.len() as u32).to_le_bytes());
    wav.extend_from_slice(&data);
    wav
}

// Path of the cached WAV for one sound; render and write on first use.
fn sound_file(name: &str, volume: u32, notes: &[(u32, f32)]) -> Option<PathBuf> {
    let appdata = std::env::var_os("APPDATA")?;
    let dir = PathBuf::from(appdata)
        .join("FreeDictate-Rust")
        .join("sounds");
    let path = dir.join(format!("{name}-{volume}-r{SOUND_REV}.wav"));
    if !path.exists() {
        std::fs::create_dir_all(&dir).ok()?;
        let tmp = path.with_extension("wav.tmp");
        if std::fs::write(&tmp, render(notes, volume as f64 / 100.0)).is_ok() {
            // Another module may have written it first; its copy is equally valid.
            let _ = std::fs::rename(&tmp, &path);
        }
        let _ = std::fs::remove_file(&tmp);
    }
    Some(path)
}

/// Fire-and-forget tone like play() in audio.py. `volume` is 0..100; 0 or an
/// unknown sound name does nothing.
pub fn play(name: &str, volume: u32) {
    if volume == 0 {
        return;
    }
    let Some((_, notes)) = SOUNDS.iter().find(|(n, _)| *n == name) else {
        return;
    };
    let notes = *notes;
    // Play on a throwaway thread: the null-terminated path must outlive the
    // asynchronous PlaySoundW call, and the engine should never block on a
    // beep.
    let name = name.to_string();
    std::thread::Builder::new()
        .name("freedictate-sound".to_string())
        .spawn(move || {
            let Some(path) = sound_file(&name, volume, notes) else {
                return;
            };
            use std::os::windows::ffi::OsStrExt;
            let mut wide: Vec<u16> = path.as_os_str().encode_wide().collect();
            wide.push(0);
            use windows::Win32::Media::Audio::{
                PlaySoundW, SND_ASYNC, SND_FILENAME, SND_NODEFAULT,
            };
            let pw = windows::core::PCWSTR::from_raw(wide.as_ptr());
            unsafe {
                let _ = PlaySoundW(pw, None, SND_FILENAME | SND_ASYNC | SND_NODEFAULT);
            }
        })
        .ok();
}

/// Offline capture simulation used by the parity tests. Feed interleaved
/// native-rate samples through the same chain the device callback uses,
/// exactly as PortAudio would call it, then flush and return the 16 kHz mono
/// take plus its length in seconds. No audio device is opened.
pub fn simulate_capture(
    rate: u32,
    channels: usize,
    block: usize,
    samples: &[f32],
) -> (Vec<f32>, f64) {
    let mut chain = Chain::new(rate).expect("test chain never fails");
    let mut out = Vec::new();
    let mut i = 0;
    while i < samples.len() {
        let end = (i + block).min(samples.len());
        let mut interleaved: Vec<f32> = Vec::with_capacity((end - i) * channels);
        for &s in &samples[i..end] {
            for _ in 0..channels {
                interleaved.push(s);
            }
        }
        let mono = downmix(&interleaved, channels);
        chain.feed(&mono, &mut out);
        i = end;
    }
    chain.flush(&mut out);
    let secs = out.len() as f64 / RATE as f64;
    (out, secs)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn downmix_average_and_passthrough() {
        assert_eq!(downmix(&[0.5, 0.25], 1), vec![0.5, 0.25]);
        assert_eq!(downmix(&[1.0, 0.0, 0.0, 1.0], 2), vec![0.5, 0.5]);
        assert_eq!(
            downmix(&[1.0, 1.0, 2.0, 2.0, 3.0, 3.0], 2),
            vec![1.0, 2.0, 3.0]
        );
    }

    #[test]
    fn accept_out_tracks_level_peak_and_voice() {
        let mut st = State::new();
        st.threshold = 0.05;
        let before = st.last_voice;
        st.accept_out(&[0.5, -0.5, 0.5, -0.5]);
        assert!((st.level - 0.5).abs() < 1e-6, "level {}", st.level);
        assert!((st.peak - 0.5).abs() < 1e-6, "peak {}", st.peak);
        assert!(st.last_voice >= before);
        st.accept_out(&[]);
        assert!((st.level - 0.5).abs() < 1e-6, "empty chunk must be ignored");
        st.accept_out(&[0.001, -0.001]);
        assert!(st.level < st.threshold);
        assert!(st.last_voice <= Instant::now());
    }

    #[test]
    fn render_wav_layout_and_content() {
        let notes: &[(u32, f32)] = &[(440, 0.05), (520, 0.02)];
        let wav = render(notes, 0.5);
        assert_eq!(&wav[0..4], b"RIFF");
        assert_eq!(&wav[8..12], b"WAVE");
        assert_eq!(&wav[36..40], b"data");
        let frames = 2205 + 882; // 44100 * 0.05 + 44100 * 0.02
        assert_eq!(wav.len(), 44 + frames * 2);
        assert!(wav[44..]
            .chunks(2)
            .any(|s| i16::from_le_bytes([s[0], s[1]]) != 0));
    }

    #[test]
    fn render_zero_volume_is_silent() {
        let wav = render(&[(440, 0.05)], 0.0);
        assert!(wav[44..].iter().all(|b| *b == 0));
    }

    #[test]
    fn chain_48k_to_16k_passes_signal() {
        let mut chain = Chain::new(48000).unwrap();
        let mut out = Vec::new();
        let block = vec![0.5f32; 1000];
        for _ in 0..48 {
            chain.feed(&block, &mut out);
        }
        chain.flush(&mut out);
        assert_eq!(out.len(), 16000, "round(48000/3) frames expected");
        let middle = out[1000..15000].iter().sum::<f32>() / 14000.0;
        assert!((middle - 0.5).abs() < 0.02, "mean {middle}");
    }

    #[test]
    fn chain_short_slice_flushes_tail() {
        let mut chain = Chain::new(48000).unwrap();
        let mut out = Vec::new();
        chain.feed(&vec![0.25f32; 500], &mut out);
        assert_eq!(out.len(), 0, "full chunk not yet buffered");
        chain.flush(&mut out);
        assert_eq!(out.len(), 167, "round(500/3) frames expected");
    }

    #[test]
    fn chain_passthrough_at_target_rate() {
        let mut chain = Chain::new(RATE).unwrap();
        let mut out = Vec::new();
        chain.feed(&[0.1, 0.2, 0.3], &mut out);
        chain.flush(&mut out);
        assert_eq!(out, vec![0.1, 0.2, 0.3]);
    }
}
