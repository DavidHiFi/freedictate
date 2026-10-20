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
}

impl App {
    fn new(cfg: Config, engine: Engine) -> Self {
        let hotkey_draft = cfg.string_value("hotkey");
        // Reopen on the page the user last had open, like the Python app.
        let page = if cfg.string_value("window_page") == "settings" {
            Page::Settings
        } else {
            Page::Dictation
        };
        let theme_name = cfg.string_value("theme");
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
        };
        app.refresh_downloaded();
        app.refresh_mics();
        app
    }

    fn update(&mut self, message: Message) -> iced::Task<Message> {
        match message {
            Message::Tick => {
                self.refresh_downloaded();
                self.refresh_mics();
                self.refresh_geometry();
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
        }
        iced::Task::none()
    }

    /// Re-apply the window chrome after a look change: the palette and the
    /// backdrop both live in config, and the DWM attributes take them live.
    fn refresh_chrome(&self) {
        chrome::request(self.palette(), self.cfg.string_value("backdrop"));
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
        // samples the mic level separately at 50 ms for the meters.
        iced::Subscription::batch(vec![
            iced::Subscription::run(events_stream),
            level::subscribe(),
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


/// Entry point the main.rs binary calls. Boots the config, starts the engine
/// and opens the window; tests never get here.
pub fn run(cfg_path: Option<std::path::PathBuf>) -> iced::Result {
    let cfg = match cfg_path {
        Some(path) => Config::load_from(path),
        None => Config::load(),
    };
    let (tx, rx) = std::sync::mpsc::channel::<(String, Value)>();
    let _ = EVENT_QUEUE.set(Mutex::new(rx));
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
                if Instant::now() >= next_tick {
                    next_tick = Instant::now() + TICK;
                    let _ = out.send(Message::Tick).await;
                }
            }
        },
    )
}
