//! The FreeDictate window, ported to iced 0.14: a dictation page and a
//! settings page. The engine runs on its own threads and reports through
//! `emit`; a std channel carries those events to the app and one
//! subscription drains them. That subscription doubles as the tick that
//! refreshes the status text and download progress when no events arrive.
//!
//! Config propagation: Engine::new consumes a snapshot of the config and
//! keeps it for the engine's lifetime; Engine has no setter yet. Every
//! control here therefore saves its change to disk with cfg.update +
//! cfg.save and keeps the window in step with its own copy of the config.
//! Engine actions (pause, load, unload) are called directly on the engine.
//! Nothing here rebuilds the engine per keystroke.

use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use crate::config::{Config, DEFAULTS};
use crate::engine::Engine;
use iced::widget::{
    button, checkbox, column, container, pick_list, row, scrollable, slider, text, text_input,
};
use iced::Length;

mod options;

use options::Choice;

/// Events that reach the subscription while `run` is active.
static EVENT_QUEUE: OnceLock<Mutex<std::sync::mpsc::Receiver<(String, Value)>>> = OnceLock::new();

/// How often the status line and download progress refresh on their own.
const TICK: Duration = Duration::from_millis(500);
/// How long the event pump waits between polls while engine events are queued.
const POLL: Duration = Duration::from_millis(60);

/// One message per control that can change something.
#[derive(Debug, Clone)]
enum Message {
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
    Reset,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Page {
    Dictation,
    Settings,
}

/// A view element in the default theme and renderer.
type Element<'a> = iced::Element<'a, Message, iced::Theme, iced::Renderer>;

struct App {
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
    cpu_threads: Option<f32>,
    max_seconds: Option<f32>,
    beam_size: Option<f32>,
}

impl App {
    fn new(cfg: Config, engine: Engine) -> Self {
        let hotkey_draft = cfg.string_value("hotkey");
        let mut app = App {
            cfg,
            engine,
            page: Page::Dictation,
            paused: false,
            downloaded: Vec::new(),
            mics: Vec::new(),
            hotkey_draft,
            sound_volume: None,
            cpu_threads: None,
            max_seconds: None,
            beam_size: None,
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
            }
            Message::CloseSettings => {
                self.page = Page::Dictation;
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
            Message::Reset => {
                self.reset_to_defaults();
            }
        }
        iced::Task::none()
    }

    /// Save a batch of values and keep the engine config in step as far as
    /// this build can: the snapshot the engine holds replaces itself the
    /// next time it reloads its own copy, which today means a restart.
    fn apply(&mut self, values: Value) {
        self.cfg.update(&values);
        let _ = self.cfg.save();
    }

    /// Back to the shipped values, keeping the window bookkeeping only:
    /// reset also restores the default hotkey, but never touches
    /// first_run_done, window_geometry or the open page.
    fn reset_to_defaults(&mut self) {
        let defaults: Value =
            serde_json::from_str(DEFAULTS).expect("DEFAULTS parses as json");
        let mut reset = serde_json::Map::new();
        if let Some(object) = defaults.as_object() {
            for (key, value) in object {
                if matches!(
                    key.as_str(),
                    "first_run_done" | "window_geometry" | "window_page"
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

    fn theme(&self) -> iced::Theme {
        iced::Theme::Light
    }

    fn subscription(&self) -> iced::Subscription<Message> {
        iced::Subscription::run(events_stream)
    }

    // ------------------------------------------------------------- view

    fn view(&self) -> Element<'_> {
        let content = match self.page {
            Page::Dictation => self.dictation_view(),
            Page::Settings => self.settings_view(),
        };
        container(content).padding(14).width(Length::Fill).into()
    }

    fn dictation_view(&self) -> Element<'_> {
        let hotkey = crate::hotkeys::label(&self.cfg.string_value("hotkey"));
        let mut items: Vec<Element> = Vec::new();
        items.push(text("Dictation").size(22).into());
        items.push(text(self.engine.status_text()).into());
        items.push(
            button(if self.paused { "Resume" } else { "Pause" })
                .on_press(Message::TogglePause)
                .into(),
        );
        items.push(
            text(format!(
                "Hold {hotkey} anywhere to dictate. The text arrives where the cursor is."
            ))
            .into(),
        );
        items.push(button("Open Settings").on_press(Message::OpenSettings).into());
        column(items).spacing(10).width(Length::Fill).into()
    }

    fn settings_view(&self) -> Element<'_> {
        let mut items: Vec<Element> = Vec::new();
        items.push(text("Settings").size(22).into());

        // Shortcut
        let valid = crate::hotkeys::is_valid(&self.hotkey_draft);
        items.push(heading("Shortcut"));
        items.push(
            text_input("Ctrl + Win", &self.hotkey_draft)
                .on_input(Message::HotkeyChanged)
                .width(220.0)
                .into(),
        );
        let warning = crate::hotkeys::warning(&self.hotkey_draft);
        if !valid {
            items.push(caption("Not a valid shortcut. Use key + key, for example Ctrl + Win."));
        } else {
            items.push(caption(&crate::hotkeys::label(&self.hotkey_draft)));
        }
        if !warning.is_empty() {
            items.push(caption(&warning));
        }

        // Hotkey trigger mode
        items.push(heading("Hotkey trigger mode"));
        let modes = options::trigger_modes();
        let mode = options::select(&modes, &self.cfg.string_value("hotkey_mode")).cloned();
        items.push(
            pick_list(modes, mode, |c: Choice| Message::TriggerModeSelected(c.key)).into(),
        );

        // Microphone
        items.push(heading("Microphone"));
        let mics = self.mic_options();
        let current = self.cfg.string_value("input_device");
        let selected = mic_choice(&mics, &current);
        items.push(
            pick_list(mics.clone(), Some(selected.clone()), |c: Choice| Message::MicSelected(c.key))
                .into(),
        );
        items.push(caption("System default picks the microphone Windows is using."));

        // Sounds
        items.push(heading("Sounds"));
        items.push(
            checkbox(self.cfg.bool_value("sounds"))
                .label("Play sounds")
                .on_toggle(Message::SoundsToggled)
                .into(),
        );
        let volume = self
            .sound_volume
            .unwrap_or(self.cfg.float_value("sound_volume") as f32);
        items.push(volume_caption(volume));
        items.push(
            slider(0.0..=100.0, volume, Message::SoundVolumeChanged)
                .on_release(Message::SoundVolumeReleased)
                .width(220.0)
                .into(),
        );
        items.push(caption("A short tone when recording starts and stops, and when the text arrives."));

        // Speech model
        items.push(heading("Speech model"));
        let models: Vec<Choice> = crate::transcribe::CATALOG
            .iter()
            .map(|m| Choice {
                key: m.name.to_string(),
                label: m.title.to_string(),
            })
            .collect();
        let model_key = self.cfg.string_value("model");
        if let Some(choice) = options::select(&models, &model_key).cloned() {
            items.push(
                pick_list(models.clone(), Some(choice.clone()), |c| {
                    Message::ModelSelected(c.key)
                })
                .into(),
            );
            items.push(caption(&choice.label));
        }
        items.push(caption(&self.downloaded_caption()));
        items.push(
            row([
                button("Download model")
                    .on_press(Message::DownloadModel)
                    .into(),
                button("Drop the model now")
                    .on_press(Message::DropModel)
                    .into(),
            ])
            .spacing(10)
            .into(),
        );
        let progress = self.model_progress();
        if !progress.is_empty() {
            items.push(caption(&progress));
        }

        // Language
        items.push(heading("Language"));
        let languages = options::choices(options::LANGUAGES);
        let language = self.cfg.string_value("language");
        if let Some(choice) = options::select(&languages, &language).cloned() {
            items.push(
                pick_list(languages, Some(choice.clone()), |c| {
                    Message::LanguageSelected(c.key)
                })
                .into(),
            );
        }

        // Output method
        items.push(heading("Output method"));
        let outputs = options::output_methods();
        let output = self.cfg.string_value("output");
        if let Some(choice) = options::select(&outputs, &output).cloned() {
            items.push(
                pick_list(outputs, Some(choice.clone()), |c| {
                    Message::OutputSelected(c.key)
                })
                .into(),
            );
        }
        items.push(
            checkbox(self.cfg.bool_value("restore_clipboard"))
                .label("Restore the clipboard afterwards")
                .on_toggle(Message::RestoreClipboardToggled)
                .into(),
        );

        // Privacy
        items.push(heading("Privacy"));
        items.push(
            checkbox(self.cfg.bool_value("mic_privacy_while_dictating"))
                .label("Keep my mic private")
                .on_toggle(Message::MicPrivacyToggled)
                .into(),
        );
        let isolate = self.cfg.bool_value("isolate_output_while_dictating");
        items.push(
            checkbox(isolate)
                .label("Mute other apps' sound")
                .on_toggle(Message::IsolateToggled)
                .into(),
        );
        // iced 0.14 pick lists have no disabled state, so the level menu
        // only shows while the mute switch is on; the caption explains it.
        if options::level_enabled(isolate) {
            let level = self.cfg.number_value("isolate_output_level");
            items.push(
                pick_list(options::level_options(), Some(options::level_selected(level)), |c| {
                    Message::IsolateLevelSelected(c.key)
                })
                .into(),
            );
        } else {
            items.push(caption("The level below only shows while Mute other apps' sound is on."));
            items.push(caption(options::level_menu_string(self.cfg.number_value("isolate_output_level"))));
        }
        items.push(caption("These switches apply on the next take."));

        // Graphics card or processor
        items.push(heading("Graphics card or processor"));
        let devices = options::devices();
        let device = self.cfg.string_value("device");
        if let Some(choice) = options::select(&devices, &device).cloned() {
            items.push(
                pick_list(devices, Some(choice.clone()), |c| Message::DeviceSelected(c.key))
                    .into(),
            );
        }
        let compute = options::compute_types();
        let compute_key = self.cfg.string_value("compute_type");
        if let Some(choice) = options::select(&compute, &compute_key).cloned() {
            items.push(
                pick_list(compute, Some(choice.clone()), |c| {
                    Message::ComputeTypeSelected(c.key)
                })
                .into(),
            );
        }
        let threads = self
            .cpu_threads
            .unwrap_or(self.cfg.float_value("cpu_threads") as f32);
        items.push(caption_cpu(threads));
        items.push(
            slider(0.0..=64.0, threads, Message::CpuThreadsChanged)
                .on_release(Message::CpuThreadsReleased)
                .width(220.0)
                .into(),
        );

        // Engine tuning
        items.push(heading("Engine tuning"));
        let seconds = self
            .max_seconds
            .unwrap_or(self.cfg.float_value("max_seconds") as f32);
        items.push(caption_max(seconds));
        items.push(
            slider(10.0..=3600.0, seconds, Message::MaxSecondsChanged)
                .on_release(Message::MaxSecondsReleased)
                .width(220.0)
                .into(),
        );
        let beam = self
            .beam_size
            .unwrap_or(self.cfg.float_value("beam_size") as f32);
        items.push(caption_beam(beam));
        items.push(
            slider(1.0..=10.0, beam, Message::BeamSizeChanged)
                .on_release(Message::BeamSizeReleased)
                .width(220.0)
                .into(),
        );
        items.push(caption("Defaults suit most people."));

        // Window buttons
        items.push(
            row([
                button("Back").on_press(Message::CloseSettings).into(),
                button("Reset").on_press(Message::Reset).into(),
            ])
            .spacing(10)
            .into(),
        );

        let settings_column = column(items).spacing(8).width(Length::Fill);
        scrollable(settings_column).into()
    }

    fn mic_options(&self) -> Vec<Choice> {
        let mut out = vec![Choice {
            key: String::new(),
            label: "System default".to_string(),
        }];
        for device in &self.mics {
            out.push(Choice {
                key: device.name.clone(),
                label: device.label.clone(),
            });
        }
        let saved = self.cfg.string_value("input_device");
        if !saved.is_empty() && !out.iter().any(|c| c.key == saved) {
            out.push(Choice {
                key: saved.clone(),
                label: format!("{saved} (not connected)"),
            });
        }
        out
    }

    fn downloaded_caption(&self) -> String {
        let mut titles: Vec<&'static str> = Vec::new();
        for info in crate::transcribe::CATALOG {
            if self.downloaded.iter().any(|name| name == info.name) {
                titles.push(info.title);
            }
        }
        if titles.is_empty() {
            "No models downloaded yet; the first take downloads one.".to_string()
        } else {
            format!("Downloaded on this PC: {}", titles.join(", "))
        }
    }

    /// The line under the model buttons, from engine.model_status().
    fn model_progress(&self) -> String {
        let (status, _active, done, total) = self.engine.model_status();
        if status == "downloading" && total > 0 {
            format!("Downloading the speech model: {} of {}", mb(done), mb(total))
        } else {
            // status_text() carries everything else.
            String::new()
        }
    }
}

fn heading(label: &str) -> Element<'static> {
    text(label.to_string()).size(17).into()
}

fn caption(label: &str) -> Element<'static> {
    text(label.to_string()).size(12).into()
}

fn volume_caption(volume: f32) -> Element<'static> {
    text(format!("Sound volume: {}%", volume.round() as u32))
        .size(13)
        .into()
}

fn caption_cpu(threads: f32) -> Element<'static> {
    text(format!("Processor cores used: {}", threads.round() as u32))
        .size(13)
        .into()
}

fn caption_max(seconds: f32) -> Element<'static> {
    text(format!(
        "Longest take: {} (10 seconds to 1 hour)",
        seconds.round() as u32
    ))
    .size(13)
    .into()
}

fn caption_beam(beam: f32) -> Element<'static> {
    text(format!(
        "Search width: {} (higher is slightly more accurate and slower)",
        beam.round() as u32
    ))
    .size(13)
    .into()
}

fn mic_choice(mics: &[Choice], saved: &str) -> Choice {
    options::select(mics, saved)
        .cloned()
        .unwrap_or(Choice {
            key: String::new(),
            label: "System default".to_string(),
        })
}

fn mb(bytes: u64) -> String {
    let size = bytes as f64 / 1_000_000.0;
    if size >= 10.0 {
        format!("{size:.0} MB")
    } else {
        format!("{size:.1} MB")
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
    let state = std::sync::Mutex::new(Some(App::new(cfg, engine)));
    iced::application(
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
    .subscription(App::subscription)
    .window(iced::window::Settings {
        size: iced::Size::new(640.0, 560.0),
        ..iced::window::Settings::default()
    })
    .centered()
    .run()
}

/// The subscription: drain the engine queue and raise Tick every 500 ms.
/// Polling with recv_timeout keeps the whole thing off any executor-specific
/// timer API, so it works on every backend.
fn events_stream() -> impl iced::futures::Stream<Item = Message> {
    use iced::futures::SinkExt as _;
    use std::sync::mpsc::RecvTimeoutError;

    iced::stream::channel(64, |out: iced::futures::channel::mpsc::Sender<Message>| async move {
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
    })
}
