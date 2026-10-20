//! The FreeDictate window, ported to iced 0.14: a dictation page and a
//! settings page. The engine runs on its own threads and reports through
//! `emit`; a std channel carries those events to the app and one
//! subscription drains them. That subscription doubles as the tick that
//! refreshes the status text and download progress when no events arrive.
//!
//! Config propagation: every control saves its change with cfg.update +
//! cfg.save, then hands the engine the new copy through set_config.
//! Engine actions (pause, load, unload) are called directly on the engine.
//! Nothing here rebuilds the engine per keystroke.

use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use crate::config::{Config, DEFAULTS};
use crate::engine::Engine;

pub(crate) mod chrome;
mod options;
pub(crate) mod pages;
pub(crate) mod theme;
pub(crate) mod widgets;
mod overlay;
mod icons;
pub(crate) mod level;
pub(crate) mod icon;

/// Events that reach the subscription while `run` is active.
static EVENT_QUEUE: OnceLock<Mutex<std::sync::mpsc::Receiver<(String, Value)>>> = OnceLock::new();

/// Side channel for UI-shell events that are not engine events: the tray
/// icon and the single-instance wake. Drained by the same event pump.
static AUX_QUEUE: OnceLock<Mutex<std::sync::mpsc::Receiver<(String, Value)>>> = OnceLock::new();

/// One-line results from the background worker threads (model verify, the
/// update check, library downloads). The app copy reads them on every tick.
static VERIFY_NOTE: OnceLock<Mutex<String>> = OnceLock::new();
static UPDATE_NOTE: OnceLock<Mutex<String>> = OnceLock::new();

/// Called from worker threads to publish a job's result line; the tick
/// copies it into the app fields that the rows render.
pub(crate) fn publish_note(verify: bool, text: &str) {
    let slot = if verify { &VERIFY_NOTE } else { &UPDATE_NOTE };
    if let Some(mutex) = slot.get() {
        *mutex.lock().expect("job note") = text.to_string();
    }
}

fn read_note(verify: bool) -> String {
    let slot = if verify { &VERIFY_NOTE } else { &UPDATE_NOTE };
    slot.get()
        .map(|m| m.lock().expect("job note").clone())
        .unwrap_or_default()
}

/// How often the status line and download progress refresh on their own.
const TICK: Duration = Duration::from_millis(500);
/// How long the event pump waits between polls while engine events are queued.
const POLL: Duration = Duration::from_millis(60);

/// One message per control that can change something.
#[derive(Debug, Clone)]
pub(crate) enum Message {
    Tick,
    Engine(String, Value),
    TogglePause,
    OpenSettings,
    CloseSettings,
    HotkeyChanged(String),
    TriggerModeSelected(String),
    MicSelected(String),
    SoundsToggled(bool),
    SoundVolumeChanged(f32),
    SoundVolumeReleased,
    ModelSelected(String),
    DownloadModel,
    DropModel,
    LanguageSelected(String),
    OutputSelected(String),
    RestoreClipboardToggled(bool),
    MicPrivacyToggled(bool),
    IsolateToggled(bool),
    IsolateLevelSelected(String),
    DeviceSelected(String),
    ComputeTypeSelected(String),
    CpuThreadsChanged(f32),
    CpuThreadsReleased,
    MaxSecondsChanged(f32),
    MaxSecondsReleased,
    BeamSizeChanged(f32),
    BeamSizeReleased,
    StartWithWindowsToggled(bool),
    TextCleanupToggled(String, bool),
    AiTidyToggled(bool),
    AiModelSelected(String),
    HistoryToggled(bool),
    TrailingSpaceToggled(bool),
    IdleUnloadToggled(bool),
    SilencePeakChanged(f32),
    SilencePeakReleased,
    ClearHistory,
    Reset,
    // The Fluent shell: theme picker, backdrop and the settings nav rail.
    // Constructed by the rebuilt pages.
    #[allow(dead_code)]
    ThemeSelected(String),
    #[allow(dead_code)]
    SettingsSection(String),
    /// Live mic level from the audio lock (0..1), emitted by ui::level.
    Level(f32),
    #[allow(dead_code)]
    AccentSourceSelected(String),
    #[allow(dead_code)]
    FontSelected(String),
    #[allow(dead_code)]
    BackdropSelected(String),
    // The display-only rows made interactive: stop key, vocabulary, the
    // recording overlay bar, the model library, the look rows, updates,
    // history extras and the word-replacement editor.
    CancelKeyChanged(String),
    VocabularyChanged(String),
    AutoStopSelected(u32),
    OverlayToggled(bool),
    OverlayPositionSelected(String),
    OverlayTimerToggled(bool),
    OverlayBackdropSelected(String),
    /// The tray icon was clicked, or a second launch woke us up; the same
    /// raise action answers both. QuitFromTray ends the app.
    ShowFromTray,
    QuitFromTray,
    /// A model-library row's button: download when absent, remove when on
    /// disk. The engine load/unload controls stay on ModelSelected.
    LibraryModelClicked(String),
    /// Switch dictation to a model the row knows is downloaded.
    LibraryUseClicked(String),
    VerifyModels,
    OpenModelFolder,
    OpenAppFolder,
    OpenLink(String),
    TintChanged(f32),
    TintReleased,
    TitlebarSelected(String),
    ReduceMotionToggled(bool),
    RunElevatedToggled(bool),
    UpdateCheckToggled(bool),
    UpdatePrereleasesToggled(bool),
    CheckUpdates,
    /// "Keep models loaded for" (idle_seconds) and "Delete dictations
    /// older than" (history_days), ported as combos like Python.
    IdleSecondsSelected(u32),
    HistoryDaysSelected(u32),
    /// "Limit processor cores": on hands back the old core count (or a
    /// gentle default), off stores 0, and the slider row shows or hides.
    CpuLimitToggled(bool),
    /// "Skip silent parts": whisper.cpp's VAD filter, model fetched on
    /// first use like the Python side's model fetch.
    VadToggled(bool),
    /// "Keep the effect in the background": the DWM material drops to a
    /// plain solid while the window is unfocused.
    BackdropWhenInactiveToggled(bool),
    /// Focus change pushed by the window-events subscription.
    WindowFocus(bool),
    ExportHistory,
    ImportHistory,
    HistoryQueryChanged(String),
    /// The trash button on one history row.
    HistoryDeleteSelected(i64),
    ReplacementAdd,
    ReplacementRemove(usize),
    ReplacementFindChanged(usize, String),
    ReplacementReplaceChanged(usize, String),
    ReplacementsSaved,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Page {
    Dictation,
    Settings,
}

/// A view element in the app theme and renderer.
pub(crate) type Element<'a> = iced::Element<'a, Message, iced::Theme, iced::Renderer>;

pub(crate) struct App {
    cfg: Config,
    engine: Engine,
    page: Page,
    // toggle_pause is the only way pause flips, so the window caches the
    // answer after each call.
    paused: bool,
    // Model catalog names already on disk, refreshed on every tick.
    downloaded: Vec<String>,
    // Cached so the view does not rescan the audio tree on every frame.
    mics: Vec<crate::audio::Device>,
    // Text under the hotkey box while the user types; saved the moment it
    // parses. The saved hotkey only moves through here.
    hotkey_draft: String,
    // Positions while a slider is being dragged; None shows the stored value.
    sound_volume: Option<f32>,
    silence_peak: Option<f32>,
    cpu_threads: Option<f32>,
    max_seconds: Option<f32>,
    beam_size: Option<f32>,
    // Read from the Run key once at start; the registry is the truth.
    start_with_windows: bool,
    // The configured palette name ("Match Windows" resolves live) and the
    // settings nav section currently open.
    theme_name: String,
    settings_section: String,
    // Live microphone level (0..1) pushed by the audio level subscription.
    level: f32,
    // The stop key box mirrors the hotkey box: draft while typing, save the
    // moment it parses.
    cancel_key_draft: String,
    // The replacement-editing rows: (find, replace) drafts plus whether the
    // saved config differs from them (the Save button's state).
    replacements_draft: Vec<(String, String)>,
    // The history list: the search box text and the rows a refresh pulled.
    history_query: String,
    history_rows: Vec<crate::history::Entry>,
    // Model-library rows with a download running (button shows a spinner
    // state until the tick sees the file on disk).
    lib_busy: Vec<String>,
    // One-line results of the background jobs (verify, update check); Tick
    // copies them in from statics the worker threads write.
    verify_note: String,
    update_note: String,
}

impl App {
    fn new(cfg: Config, engine: Engine) -> Self {
        let _ = VERIFY_NOTE.set(Mutex::new(String::new()));
        let _ = UPDATE_NOTE.set(Mutex::new(String::new()));
        // Python checks for updates at start when check_updates wants it;
        // the Rust port does the same once per session, in the background,
        // and the result line lands in the update row on the next tick.
        if cfg.bool_value("check_updates") {
            let prereleases = cfg.bool_value("update_prereleases");
            std::thread::Builder::new()
                .name("update-auto".to_string())
                .spawn(move || {
                    std::thread::sleep(Duration::from_secs(10));
                    publish_note(false, &crate::updater::check_note(prereleases));
                })
                .ok();
        }
        let hotkey_draft = cfg.string_value("hotkey");
        // Reopen on the page the user last had open, like the Python app.
        let page = if cfg.string_value("window_page") == "settings" {
            Page::Settings
        } else {
            Page::Dictation
        };
        let theme_name = cfg.string_value("theme");
        let replacements_draft = crate::textproc::replacements_from_config(cfg.get("replacements"))
            .into_iter()
            .map(|r| (r.find, r.replace))
            .collect();
        let cancel_key_draft = cfg.string_value("cancel_key");
        // Reopen the settings window on the section last opened.
        let settings_section = {
            let saved = cfg.string_value("settings_section");
            if saved.is_empty() { "general".to_string() } else { saved }
        };
        let mut app = App {
            cfg,
            engine,
            page,
            paused: false,
            downloaded: Vec::new(),
            mics: Vec::new(),
            hotkey_draft,
            sound_volume: None,
            silence_peak: None,
            cpu_threads: None,
            max_seconds: None,
            beam_size: None,
            start_with_windows: crate::autostart::is_enabled(),
            theme_name,
            settings_section,
            level: 0.0,
            cancel_key_draft,
            replacements_draft,
            history_query: String::new(),
            history_rows: Vec::new(),
            lib_busy: Vec::new(),
            verify_note: String::new(),
            update_note: String::new(),
        };
        app.refresh_downloaded();
        app.refresh_mics();
        app.refresh_history();
        app
    }

    fn update(&mut self, message: Message) -> iced::Task<Message> {
        // Most arms finish synchronously; a few return real tasks (window
        // focus/geometry). The optional slot collects those.
        let mut task: Option<iced::Task<Message>> = None;
        match message {
            Message::Tick => {
                self.refresh_downloaded();
                self.refresh_mics();
                self.refresh_geometry();
                self.refresh_notes();
                self.refresh_history();
            }
            Message::Engine(_kind, _data) => {
                // Model and state events already carry the facts; both the
                // status text and the progress read live from the engine in
                // the view, so a repaint is all that is needed.
                self.refresh_downloaded();
            }
            Message::TogglePause => {
                self.paused = self.engine.toggle_pause();
            }
            Message::OpenSettings => {
                self.page = Page::Settings;
                self.apply(json!({ "window_page": "settings" }));
            }
            Message::CloseSettings => {
                self.page = Page::Dictation;
                self.apply(json!({ "window_page": "dictation" }));
            }
            Message::HotkeyChanged(text) => {
                self.hotkey_draft = text.clone();
                if crate::hotkeys::is_valid(&text) {
                    // Store the normalised form, like hotkeys.normalize.
                    let saved = crate::hotkeys::normalize(&text);
                    self.hotkey_draft = saved.clone();
                    self.apply(json!({ "hotkey": saved }));
                }
            }
            Message::TriggerModeSelected(key) => {
                self.apply(json!({ "hotkey_mode": key }));
            }
            Message::MicSelected(name) => {
                self.apply(json!({ "input_device": name }));
            }
            Message::SoundsToggled(on) => {
                self.apply(json!({ "sounds": on }));
            }
            Message::SoundVolumeChanged(volume) => {
                self.sound_volume = Some(volume);
            }
            Message::SoundVolumeReleased => {
                // The slider stopped being dragged: store the last position.
                if let Some(volume) = self.sound_volume.take() {
                    self.apply(json!({ "sound_volume": volume.round() as u32 }));
                }
            }
            Message::ModelSelected(name) => {
                self.apply(json!({ "model": name }));
            }
            Message::DownloadModel => {
                self.engine.load_model_async();
            }
            Message::DropModel => {
                self.engine.unload_model_now();
            }
            Message::LanguageSelected(code) => {
                self.apply(json!({ "language": code }));
            }
            Message::OutputSelected(method) => {
                self.apply(json!({ "output": method }));
            }
            Message::RestoreClipboardToggled(on) => {
                self.apply(json!({ "restore_clipboard": on }));
            }
            Message::MicPrivacyToggled(on) => {
                self.apply(json!({ "mic_privacy_while_dictating": on }));
            }
            Message::IsolateToggled(on) => {
                self.apply(json!({ "isolate_output_while_dictating": on }));
            }
            Message::IsolateLevelSelected(key) => {
                let level = options::level_from_choice(&key);
                self.apply(json!({ "isolate_output_level": level }));
            }
            Message::DeviceSelected(key) => {
                self.apply(json!({ "device": key }));
            }
            Message::ComputeTypeSelected(key) => {
                self.apply(json!({ "compute_type": key }));
            }
            Message::CpuThreadsChanged(value) => {
                self.cpu_threads = Some(value);
            }
            Message::CpuThreadsReleased => {
                if let Some(value) = self.cpu_threads.take() {
                    self.apply(json!({ "cpu_threads": value.round() as u32 }));
                }
            }
            Message::MaxSecondsChanged(value) => {
                self.max_seconds = Some(value);
            }
            Message::MaxSecondsReleased => {
                if let Some(value) = self.max_seconds.take() {
                    self.apply(json!({ "max_seconds": value.round() as u32 }));
                }
            }
            Message::BeamSizeChanged(value) => {
                self.beam_size = Some(value);
            }
            Message::BeamSizeReleased => {
                if let Some(value) = self.beam_size.take() {
                    self.apply(json!({ "beam_size": value.round() as u32 }));
                }
            }
            Message::StartWithWindowsToggled(on) => {
                if let Ok(exe) = std::env::current_exe() {
                    if crate::autostart::set_enabled(on, &exe).is_ok() {
                        self.start_with_windows = on;
                    }
                }
            }
            Message::TextCleanupToggled(key, on) => {
                self.apply(json!({ (key.as_str()): on }));
            }
            Message::AiTidyToggled(on) => {
                self.apply(json!({ "ai_tidy": on }));
            }
            Message::AiModelSelected(name) => {
                self.apply(json!({ "ai_model": name }));
            }
            Message::HistoryToggled(on) => {
                self.apply(json!({ "history_enabled": on }));
            }
            Message::TrailingSpaceToggled(on) => {
                self.apply(json!({ "trailing_space": on }));
            }
            Message::IdleUnloadToggled(on) => {
                self.apply(json!({ "idle_unload": on }));
            }
            Message::SilencePeakChanged(v) => {
                self.silence_peak = Some(v);
            }
            Message::SilencePeakReleased => {
                if let Some(v) = self.silence_peak.take() {
                    self.apply(json!({ "silence_peak": v }));
                }
            }
            Message::ClearHistory => {
                crate::engine::clear_history();
            }
            Message::Reset => {
                self.reset_to_defaults();
            }
            Message::ThemeSelected(name) => {
                self.theme_name = name.clone();
                self.apply(json!({ "theme": name }));
                self.refresh_chrome();
            }
            Message::Level(value) => {
                self.level = value;
            }
            Message::ShowFromTray => {
                // Tray click / second-instance wake: raise the existing
                // window the way QSystemTrayIcon.activated did. The oldest
                // window is the one iced booted with.
                task = Some(iced::window::oldest().then(|maybe| match maybe {
                    Some(id) => iced::window::gain_focus(id),
                    None => iced::Task::none(),
                }));
            }
            Message::QuitFromTray => {
                // Exit closes the window; iced returns from run() and the
                // process ends (the engine joins its threads at drop).
                task = Some(iced::window::latest().then(|maybe| match maybe {
                    Some(id) => iced::window::close(id),
                    None => iced::Task::none(),
                }));
            }
            Message::SettingsSection(section) => {
                self.settings_section = section.clone();
                // Save the open section for the next start; this is view
                // state, so it does not need to reach the engine.
                self.cfg.update(&json!({ "settings_section": section }));
                let _ = self.cfg.save();
            }
            Message::AccentSourceSelected(source) => {
                self.apply(json!({ "accent_source": source }));
                self.refresh_chrome();
            }
            Message::FontSelected(family) => {
                // iced fixes the default font at boot; the new family
                // applies on the next start.
                self.apply(json!({ "font": family }));
            }
            Message::BackdropSelected(backdrop) => {
                self.apply(json!({ "backdrop": backdrop }));
                self.refresh_chrome();
            }
            // -------------------------------------------------- stop key
            Message::CancelKeyChanged(text) => {
                // Same flow as the main hotkey: the box holds the draft,
                // a valid key saves at once.
                self.cancel_key_draft = text.clone();
                if crate::hotkeys::is_valid(&text) {
                    self.apply(json!({ "cancel_key": crate::hotkeys::normalize(&text) }));
                }
            }
            // --------------------------------------------------- writing
            Message::VocabularyChanged(text) => {
                self.apply(json!({ "vocabulary": text }));
            }
            Message::ReplacementAdd => {
                self.replacements_draft.push((String::new(), String::new()));
            }
            Message::ReplacementRemove(index) => {
                if index < self.replacements_draft.len() {
                    self.replacements_draft.remove(index);
                }
            }
            Message::ReplacementFindChanged(index, text) => {
                if let Some(row) = self.replacements_draft.get_mut(index) {
                    row.0 = text;
                }
            }
            Message::ReplacementReplaceChanged(index, text) => {
                if let Some(row) = self.replacements_draft.get_mut(index) {
                    row.1 = text;
                }
            }
            Message::ReplacementsSaved => {
                // Blank finds are editor scratch rows that never reach the
                // saved list, matching the old app's save pass.
                let rows: Vec<Value> = self
                    .replacements_draft
                    .iter()
                    .filter(|(find, _)| !find.trim().is_empty())
                    .map(|(find, replace)| json!({ "find": find, "replace": replace }))
                    .collect();
                self.apply(json!({ "replacements": rows }));
                // Drop the scratch rows from the editor once they are saved.
                self.replacements_draft.retain(|(find, _)| !find.trim().is_empty());
            }
            Message::AutoStopSelected(seconds) => {
                self.apply(json!({ "auto_stop_silence": seconds }));
            }
            // --------------------------------------------------- overlay
            Message::OverlayToggled(on) => {
                self.apply(json!({ "overlay": on }));
            }
            Message::OverlayPositionSelected(position) => {
                self.apply(json!({ "overlay_position": position }));
            }
            Message::OverlayTimerToggled(on) => {
                self.apply(json!({ "overlay_timer": on }));
            }
            Message::OverlayBackdropSelected(backdrop) => {
                self.apply(json!({ "overlay_backdrop": backdrop }));
            }
            // --------------------------------------------- model library
            Message::LibraryModelClicked(name) => {
                if crate::transcribe::is_downloaded(&name) {
                    if let Some(path) = crate::transcribe::local_path(&name) {
                        if let Err(e) = std::fs::remove_file(&path) {
                            publish_note(true, &format!("Removing {name} failed: {e}"));
                        }
                        self.refresh_downloaded();
                    }
                } else if !self.lib_busy.iter().any(|busy| busy == &name) {
                    self.lib_busy.push(name.clone());
                    let note_mirror = name.clone();
                    std::thread::Builder::new()
                        .name("model-download".to_string())
                        .spawn(move || {
                            let cancel = std::sync::atomic::AtomicBool::new(false);
                            match crate::transcribe::download(&note_mirror, &|_, _| {}, &cancel) {
                                Ok(_) => publish_note(true, ""),
                                Err(e) => publish_note(true, &format!("{note_mirror}: {e}")),
                            }
                        })
                        .ok();
                }
            }
            Message::LibraryUseClicked(name) => {
                self.apply(json!({ "model": name }));
                self.engine.load_model_async();
            }
            Message::VerifyModels => {
                std::thread::Builder::new()
                    .name("model-verify".to_string())
                    .spawn(|| {
                        publish_note(true, &crate::engine::verify_models());
                    })
                    .ok();
            }
            Message::OpenModelFolder => {
                open_in_explorer(&crate::transcribe::models_dir());
            }
            Message::OpenAppFolder => {
                let dir = std::env::var("APPDATA")
                    .map(std::path::PathBuf::from)
                    .unwrap_or_default()
                    .join("FreeDictate-Rust");
                open_in_explorer(&dir);
            }
            Message::OpenLink(url) => {
                // Start-before-empty-title is the canonical shell link open;
                // failures are ignored (an offline box loses nothing).
                let _ = std::process::Command::new("cmd")
                    .args(["/C", "start", "", &url])
                    .spawn();
            }
            // ------------------------------------------------------ look
            Message::TintChanged(value) => {
                // Slide live: only the render-side tint moves; the saved
                // value and the DWM chrome update on release.
                self.cfg
                    .update(&json!({ "tint": (value.round() as u32).max(0).min(100) }));
                self.refresh_chrome();
            }
            Message::TintReleased => {
                let tint = self.cfg.number_value("tint");
                self.apply(json!({ "tint": tint }));
                self.refresh_chrome();
            }
            Message::TitlebarSelected(titlebar) => {
                self.apply(json!({ "titlebar": titlebar }));
                self.refresh_chrome();
            }
            Message::ReduceMotionToggled(on) => {
                self.apply(json!({ "reduce_motion": on }));
            }
            Message::RunElevatedToggled(on) => {
                self.apply(json!({ "run_elevated": on }));
            }
            // --------------------------------------------------- updates
            Message::UpdateCheckToggled(on) => {
                self.apply(json!({ "check_updates": on }));
            }
            Message::UpdatePrereleasesToggled(on) => {
                self.apply(json!({ "update_prereleases": on }));
            }
            Message::CheckUpdates => {
                let allow = self.cfg.bool_value("update_prereleases");
                std::thread::Builder::new()
                    .name("update-check".to_string())
                    .spawn(move || {
                        let note = crate::updater::check_note(allow);
                        publish_note(false, &note);
                    })
                    .ok();
            }
            // --------------------------------------------------- history
            Message::ExportHistory => {
                let base = std::env::var("APPDATA")
                    .map(std::path::PathBuf::from)
                    .unwrap_or_default()
                    .join("FreeDictate-Rust");
                let target = base.join("history-export.txt");
                let count = crate::engine::history_export(&target);
                let note = if count >= 0 {
                    format!("Exported {count} entries to {}", target.display())
                } else {
                    "Export failed: could not write the file.".to_string()
                };
                publish_note(true, &note);
            }
            Message::ImportHistory => {
                let base = std::env::var("APPDATA")
                    .map(std::path::PathBuf::from)
                    .unwrap_or_default()
                    .join("FreeDictate-Rust");
                let source = base.join("transcripts.log");
                let count = crate::engine::history_import(&source);
                publish_note(
                    true,
                    &if count > 0 {
                        format!("Imported {count} entries from {}", source.display())
                    } else {
                        format!("Nothing imported from {} (missing or empty).", source.display())
                    },
                );
            }
            Message::HistoryQueryChanged(query) => {
                self.history_query = query;
                self.refresh_history();
            }
            Message::HistoryDeleteSelected(id) => {
                crate::engine::history_delete(id);
                self.refresh_history();
            }
            Message::IdleSecondsSelected(seconds) => {
                self.apply(json!({ "idle_seconds": seconds }));
            }
            Message::CpuLimitToggled(on) => {
                // Python's limit toggle: on restores the previous cap (or
                // six cores as the gentle default), off stores 0 (unlimited).
                let value = if on {
                    let cores =
                        std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1) as f64;
                    self.cfg.float_value("cpu_threads").max(cores.min(6.0))
                } else {
                    0.0
                };
                self.apply(json!({ "cpu_threads": value }));
            }
            Message::HistoryDaysSelected(days) => {
                self.apply(json!({ "history_days": days }));
                // Python prunes on the daily cycle; the port also prunes
                // once here so the row's effect is immediate.
                std::thread::Builder::new()
                    .name("history-prune-now".to_string())
                    .spawn(move || {
                        if days > 0 {
                            crate::engine::history_prune(days);
                        }
                    })
                    .ok();
            }
            Message::VadToggled(on) => {
                self.apply(json!({ "vad": on }));
                if on {
                    // Fetch the silero model once; the next take uses it.
                    std::thread::Builder::new()
                        .name("vad-model".to_string())
                        .spawn(|| {
                            if crate::transcribe::local_path(crate::transcribe::VAD_MODEL_NAME)
                                .is_some()
                            {
                                return;
                            }
                            let cancel = std::sync::atomic::AtomicBool::new(false);
                            match crate::transcribe::download(
                                crate::transcribe::VAD_MODEL_NAME,
                                &|_, _| {},
                                &cancel,
                            ) {
                                Ok(_) => publish_note(true, ""),
                                Err(e) => publish_note(
                                    true,
                                    &format!("VAD model: {e} Takes stay unfiltered."),
                                ),
                            }
                        })
                        .ok();
                }
            }
            Message::BackdropWhenInactiveToggled(on) => {
                self.apply(json!({ "backdrop_when_inactive": on }));
                // Going off restores the full material at once; going on
                // takes effect at the next unfocus.
                if !on {
                    self.refresh_chrome();
                }
            }
            Message::WindowFocus(focused) => {
                // Keep the material only with focus, when the row wants
                // that; every other case is the window's normal look.
                let keep_when_inactive = self.cfg.bool_value("backdrop_when_inactive");
                if focused || !keep_when_inactive {
                    self.refresh_chrome();
                } else {
                    chrome::request(self.palette(), "solid".to_string());
                }
            }
        }
        task.unwrap_or_else(iced::Task::none)
    }

    /// Re-apply the window chrome after a look change: the palette and the
    /// backdrop both live in config, and the DWM attributes take them live.
    fn refresh_chrome(&self) {
        chrome::request(self.palette(), self.cfg.string_value("backdrop"));
    }

    /// Copy the background jobs' result lines into the fields the rows
    /// render, and clear library busy-marks the tick can see finished.
    fn refresh_notes(&mut self) {
        self.verify_note = read_note(true);
        self.update_note = read_note(false);
        // A busy model whose file now exists (or vanished) is done busy.
        self.lib_busy
            .retain(|name| !crate::transcribe::is_downloaded(name));
    }

    /// Pull the history list for the rows: the search text filters it,
    /// newest first, capped at what the page shows.
    fn refresh_history(&mut self) {
        self.history_rows = crate::engine::history_search(&self.history_query, 20);
    }

    /// The palette the window currently draws with: resolve() plus the
    /// Windows accent override, from the saved config keys.
    fn palette(&self) -> theme::Palette {
        theme::effective(
            &self.theme_name,
            &self.cfg.string_value("accent_source"),
        )
    }

    /// Save a batch of values and hand the engine the new config.
    fn apply(&mut self, values: Value) {
        self.cfg.update(&values);
        let _ = self.cfg.save();
        self.engine.set_config(self.cfg.clone());
    }

    /// Back to the shipped values, keeping the window bookkeeping only:
    /// reset also restores the default hotkey, but never touches
    /// first_run_done, window_geometry or the open page.
    fn reset_to_defaults(&mut self) {
        let defaults: Value = serde_json::from_str(DEFAULTS).expect("DEFAULTS parses as json");
        let mut reset = serde_json::Map::new();
        if let Some(object) = defaults.as_object() {
            for (key, value) in object {
                if matches!(
                    key.as_str(),
                    "first_run_done" | "window_geometry" | "window_page"
                    | "settings_section"
                ) {
                    continue;
                }
                reset.insert(key.clone(), value.clone());
            }
        }
        self.apply(Value::Object(reset));
        self.hotkey_draft = self.cfg.string_value("hotkey");
        self.sound_volume = None;
        self.cpu_threads = None;
        self.max_seconds = None;
        self.beam_size = None;
        self.refresh_downloaded();
    }

    fn refresh_downloaded(&mut self) {
        self.downloaded = crate::transcribe::CATALOG
            .iter()
            .filter(|m| crate::transcribe::is_downloaded(m.name))
            .map(|m| m.name.to_string())
            .collect();
    }

    fn refresh_mics(&mut self) {
        self.mics = crate::audio::input_devices();
    }

    /// Persist the window rect on change, so a restart reopens where the
    /// user left it. GetWindowRect is microseconds; doing it inline on the
    /// tick keeps this off any window-event plumbing iced does not expose.
    fn refresh_geometry(&mut self) {
        if let Some((x, y, w, h)) = chrome::current_geometry() {
            let next = format!("{x},{y},{w},{h}");
            if self.cfg.string_value("window_geometry") != next {
                self.apply(json!({ "window_geometry": next }));
            }
        }
    }

    /// The iced theme: opaque while no material is active, transparent
    /// clear colour when Mica/Acrylic/blur runs behind the window.
    fn theme(&self) -> iced::Theme {
        let p = self.palette();
        if chrome::material_active(&self.cfg.string_value("backdrop")) {
            theme::to_iced_transparent(&p)
        } else {
            theme::to_iced(&p)
        }
    }

    fn subscription(&self) -> iced::Subscription<Message> {
        // The event pump doubles as the 500 ms tick; the level subscription
        // samples the mic level separately at 50 ms for the meters; the
        // window-events subscription feeds the focus for the
        // backdrop-when-inactive look.
        iced::Subscription::batch(vec![
            iced::Subscription::run(events_stream),
            level::subscribe(),
            window_focus_stream(),
        ])
    }

    // ------------------------------------------------------------- view

    fn view(&self) -> Element<'_> {
        match self.page {
            Page::Dictation => pages::dictation::view(self),
            Page::Settings => pages::settings::view(self),
        }
    }

}


/// Focus changes from the window manager. The
/// backdrop-when-inactive look is focus-driven in Python too (look.py's
/// set_look listens on the window's focus); here the two window events
/// become one message.
fn window_focus_stream() -> iced::Subscription<Message> {
    iced::window::events().filter_map(|(_id, event)| match event {
        iced::window::Event::Focused => Some(Message::WindowFocus(true)),
        iced::window::Event::Unfocused => Some(Message::WindowFocus(false)),
        _ => None,
    })
}

/// Open a folder in Explorer; failures (no session desktop, sandbox) are
/// ignored, the same way the Python app's Explorer call behaves.
fn open_in_explorer(path: &std::path::Path) {
    if path.exists() {
        let _ = std::process::Command::new("explorer")
            .arg(path.as_os_str())
            .spawn();
    }
}

/// Entry point the main.rs binary calls. Boots the config, starts the engine
/// and opens the window; tests never get here.
pub fn run(cfg_path: Option<std::path::PathBuf>) -> iced::Result {
    let cfg = match cfg_path {
        Some(path) => Config::load_from(path),
        None => Config::load(),
    };
    let (tx, rx) = std::sync::mpsc::channel::<(String, Value)>();
    let _ = EVENT_QUEUE.set(Mutex::new(rx));
    // Shell events (tray, wake) get their own tiny queue; a converter
    // thread maps tray events onto it.
    let (aux_tx, aux_rx) = std::sync::mpsc::channel::<(String, Value)>();
    let _ = AUX_QUEUE.set(Mutex::new(aux_rx));
    let (tray_tx, tray_rx) = std::sync::mpsc::channel::<crate::tray::TrayEvent>();
    // The Tray handle must stay alive for the process lifetime (dropping
    // it would remove the icon and stop the wake window).
    let _tray = crate::tray::spawn(tray_tx);
    std::thread::Builder::new()
        .name("tray-events".to_string())
        .spawn(move || {
            for event in tray_rx {
                let action = match event {
                    crate::tray::TrayEvent::ShowSettings => "show",
                    crate::tray::TrayEvent::Quit => "quit",
                };
                let _ = aux_tx.send(("tray".to_string(), Value::from(action)));
            }
        })
        .ok();
    // The engine calls this from its poller and transcriber threads; sending
    // onto the std channel is the only thing it does, and if the window is
    // not there the event is dropped.
    let emit = Arc::new(move |kind: &str, data: Value| {
        let _ = tx.send((kind.to_string(), data));
    });
    let mut engine = Engine::new(cfg.clone(), emit);
    engine.start();
    let state = std::sync::Mutex::new(Some(App::new(cfg.clone(), engine)));
    // Fluent chrome: dark/tinted title bar and the configured backdrop. The
    // window does not exist until iced opens it, so request retries.
    let boot_palette = theme::effective(&cfg.string_value("theme"), &cfg.string_value("accent_source"));
    chrome::request(boot_palette, cfg.string_value("backdrop"));
    let font_family = cfg.string_value("font");
    // Reopen where the user left the window; the default matches the
    // original app (settings.py resizes to 960x700 and centers it).
    let geometry = chrome::parse_geometry(&cfg.string_value("window_geometry"));
    let builder = iced::application(
        move || {
            state
                .lock()
                .expect("boot state mutex")
                .take()
                .expect("boot called once")
        },
        App::update,
        App::view,
    )
    .title("FreeDictate")
    .theme(App::theme)
    .default_font(iced::Font::with_name(std::boxed::Box::leak(font_family.into_boxed_str())))
    .subscription(App::subscription)
    .window(iced::window::Settings {
        // The taskbar/Alt-tab icon for the window iced owns; the exe
        // resource only covers Explorer's view.
        icon: icon::window_icon(),
        // Transparent so the DWM backdrop (Mica/Acrylic/blur) can read
        // through; the palette paints every surface itself when the
        // backdrop is solid or none.
        transparent: true,
        size: match geometry {
            Some((_, _, w, h)) => iced::Size::new(w as f32, h as f32),
            None => iced::Size::new(960.0, 700.0),
        },
        position: match geometry {
            Some((x, y, _, _)) => {
                iced::window::Position::Specific(iced::Point::new(x as f32, y as f32))
            }
            None => iced::window::Position::Centered,
        },
        ..iced::window::Settings::default()
    });
    builder.run()
}

/// The subscription: drain the engine queue and raise Tick every 500 ms.
/// Polling with recv_timeout keeps the whole thing off any executor-specific
/// timer API, so it works on every backend.
fn events_stream() -> impl iced::futures::Stream<Item = Message> {
    use iced::futures::SinkExt as _;
    use std::sync::mpsc::RecvTimeoutError;

    iced::stream::channel(
        64,
        |out: iced::futures::channel::mpsc::Sender<Message>| async move {
            let mut out = out;
            let mut next_tick = Instant::now() + TICK;
            loop {
                match EVENT_QUEUE.get() {
                    Some(rx) => match {
                        let received = rx.lock().expect("event queue").recv_timeout(POLL);
                        received
                    } {
                        Ok((kind, data)) => {
                            let _ = out.send(Message::Engine(kind, data)).await;
                        }
                        Err(RecvTimeoutError::Timeout) => {}
                        Err(RecvTimeoutError::Disconnected) => break,
                    },
                    // run() has not installed the queue yet; idle until it does.
                    None => std::thread::sleep(POLL),
                }
                // Shell events (tray clicks, the single-instance wake) ride
                // their own queue; drain what arrived during this poll. The
                // guard is dropped before the sends, so the loop's futures
                // stay Send.
                let mut shell: Vec<Message> = Vec::new();
                if let Some(rx) = AUX_QUEUE.get() {
                    loop {
                        let attempt = rx.lock().expect("aux queue").try_recv();
                        match attempt {
                            Ok((kind, value)) if kind == "tray" => match value.as_str() {
                                Some("show") => shell.push(Message::ShowFromTray),
                                Some("quit") => shell.push(Message::QuitFromTray),
                                _ => {}
                            },
                            Ok(_) => {}
                            Err(_) => break,
                        }
                    }
                }
                for shell_message in shell {
                    let _ = out.send(shell_message).await;
                }
                if Instant::now() >= next_tick {
                    next_tick = Instant::now() + TICK;
                    let _ = out.send(Message::Tick).await;
                }
            }
        },
    )
}
