//! The settings window, rebuilt on the Fluent widget set (widgets.rs) from
//! the Python app's settings.py.
//!
//! The Python window is a nav rail plus one page per section; this is the
//! same shape: a rail of nav buttons on the left, the open section on the
//! right, scrolling when the section is long. Every row title, caption and
//! note is the Python wording, so both builds read the same.
//!
//! Every row binds a Message variant that exists in crate::ui; the Python
//! controls that this build has no message or helper for (the file dialogs,
//! the font completer, GPU support) stay as plain text and say so in their
//! row.

use iced::widget::{column, row, scrollable, Space};
use iced::{Alignment, Length};

use crate::ui::options::{self, Choice};
use crate::ui::theme::Palette;
use crate::ui::widgets;
use crate::ui::{App, Element, Message};

/// The nav rail: (key, glyph, label), in the order of the Python sidebar
/// (settings.py PAGES). The glyph is the Python icon name; the nav button
/// draws it as text, so the icon registry can be mapped onto it later.
pub const SECTIONS: &[(&'static str, &'static str, &'static str)] = &[
    // The Python sidebar opens on the dictation page. The App opens on
    // "general", so that page carries the "general" key and its content.
    ("general", "mic", "Dictation"),
    ("models", "cpu", "Speech model"),
    ("text", "text", "Text and pasting"),
    ("look", "palette", "Appearance"),
    ("history", "clock", "History"),
    // The Python's own "general" page (Startup, Updates, Your data) cannot
    // keep the key, so it is "startup" and keeps the Python label.
    ("startup", "sliders", "General"),
    ("about", "info", "About"),
];

/// The shortcut behaviour (settings.py _page_dictation).
const TRIGGER_MODES: &[(&str, &str)] = &[
    ("hold", "Hold"),
    ("toggle", "Press to start and stop"),
    ("both", "Both"),
];

/// Where the accent colour comes from (settings.py _page_look).
const ACCENT_SOURCES: &[(&str, &str)] = &[
    ("theme", "From the theme"),
    ("windows", "Windows accent"),
];

/// The window materials (settings.py _page_look, plus "none" for the Rust
/// build, which can paint a plain window with no material at all).
const BACKDROPS: &[(&str, &str)] = &[
    ("none", "None"),
    ("solid", "Solid"),
    ("mica", "Mica"),
    ("mica_alt", "Mica Alt"),
    ("acrylic", "Acrylic"),
    ("blur", "Blur"),
];

/// The recording bar rows (settings.py _page_dictation).
const OVERLAY_POSITIONS: &[(&str, &str)] = &[("bottom", "Bottom"), ("top", "Top")];
const OVERLAY_BACKDROPS: &[(&str, &str)] = &[
    ("mica_alt", "Mica Alt"),
    ("mica", "Mica"),
    ("acrylic", "Acrylic"),
    ("blur", "Blur"),
    ("solid", "Solid"),
];

/// The title bar the app draws (settings.py _page_look).
const TITLEBARS: &[(&str, &str)] = &[("custom", "FreeDictate"), ("windows", "Windows")];

/// The fonts the Rust build can use (the Python page lists every family on
/// the PC; iced fixes the font at boot, so the list is short here).
const FONTS: &[(&str, &str)] = &[
    ("Segoe UI Variable Text", "Segoe UI Variable Text"),
    ("Segoe UI", "Segoe UI"),
];

const MONTHS: [&str; 12] = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

// ------------------------------------------------------------- the window

pub fn view(app: &App) -> Element<'_> {
    let palette = app.palette();
    row(vec![
        nav_rail(app, &palette),
        section_content(app, &palette),
    ])
    .spacing(12)
    .width(Length::Fill)
    .height(Length::Fill)
    .into()
}

/// The rail on the left: the status card, one button per section and the
/// version (settings.py _build_sidebar).
fn nav_rail<'a>(app: &'a App, p: &Palette) -> Element<'a> {
    let mut items: Vec<Element<'a>> = Vec::new();

    // The status card: the engine's state and the pause button.
    let status = app.engine.status_text();
    let status_row = row(vec![
        widgets::status_dot(app.engine.state(), p).into(),
        widgets::body(&status, p).into(),
    ])
    .spacing(8);
    let pause = widgets::flat_button(
        if app.paused { "Resume" } else { "Pause" },
        Message::TogglePause,
        p,
    );
    items.push(widgets::card(vec![status_row.into(), pause.into()], p));

    for (key, glyph, label) in SECTIONS {
        items.push(widgets::nav_button(
            label,
            glyph,
            app.settings_section == *key,
            Message::SettingsSection((*key).to_string()),
            p,
        ));
    }

    items.push(Space::new().height(Length::Fill).into());
    items.push(widgets::sub(
        &format!("Version {}", crate::updater::VERSION),
        p,
    ));

    column(items)
        .spacing(4)
        .width(Length::Fixed(180.0))
        .height(Length::Fill)
        .into()
}

/// The page on the right: the open section's title and its cards.
fn section_content<'a>(app: &'a App, p: &Palette) -> Element<'a> {
    let key = app.settings_section.as_str();
    let label = SECTIONS
        .iter()
        .find(|(name, _, _)| *name == key)
        .map(|(_, _, label)| *label)
        .unwrap_or(SECTIONS[0].2);

    let mut items: Vec<Element<'a>> = vec![widgets::title(label, p)];
    items.push(Space::new().height(Length::Fixed(6.0)).into());

    let body: Vec<Element<'a>> = match key {
        "models" => models_section(app, p),
        "text" => text_section(app, p),
        "look" => look_section(app, p),
        "history" => history_section(app, p),
        "startup" => startup_section(app, p),
        "about" => about_section(p),
        _ => dictation_section(app, p),
    };
    items.extend(body);

    // The way back to the dictation page (the legacy view's Back button).
    items.push(Space::new().height(Length::Fixed(8.0)).into());
    items.push(
        row(vec![
            widgets::flat_button("Back", Message::CloseSettings, p).into(),
        ])
        .width(Length::Fill)
        .into(),
    );

    scrollable(column(items).spacing(8).width(Length::Fill))
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
}

// ------------------------------------------------------- the dictation page

/// The first Python page: the shortcut, the microphone, what happens while
/// dictating and the sounds (settings.py _page_dictation).
fn dictation_section<'a>(app: &'a App, p: &Palette) -> Vec<Element<'a>> {
    let cfg = &app.cfg;
    let mut out: Vec<Element<'a>> = Vec::new();

    // The welcome banner, shown until the first take is done.
    if !cfg.bool_value("first_run_done") {
        let hotkey = crate::hotkeys::label(&cfg.string_value("hotkey"));
        let model = crate::transcribe::CATALOG
            .iter()
            .find(|m| m.name == cfg.string_value("model"));
        let title = model.map(|m| m.title).unwrap_or_default();
        let size = model.map(|m| format!("{} MB", m.size_mb)).unwrap_or_default();
        out.push(widgets::banner(
            &format!(
                "Welcome to FreeDictate. Click where you want text, hold {hotkey}, talk, and let go. \
                 The {title} speech model ({size}) downloads once, then everything runs offline on this PC."
            ),
            false,
            p,
        ));
    }

    // The shortcut card.
    let mut rows: Vec<Element<'a>> = Vec::new();

    let draft = app.hotkey_draft.clone();
    let mut notes: Vec<Note> = Vec::new();
    if crate::hotkeys::is_valid(&draft) {
        notes.push(Note::Plain(crate::hotkeys::label(&draft)));
    } else {
        notes.push(Note::Danger(
            "Not a valid shortcut. Use key + key, for example Ctrl + Win.".to_string(),
        ));
    }
    let warning = crate::hotkeys::warning(&draft);
    if !warning.is_empty() {
        notes.push(Note::Warn(warning));
    }
    let shortcut = row(vec![
        widgets::hotkey_edit(&draft, Message::HotkeyChanged, p).into(),
        widgets::flat_button(
            "Reset",
            Message::HotkeyChanged("ctrl+win".to_string()),
            p,
        )
        .into(),
    ])
    .spacing(8)
    .into();
    rows.push(setting_row(
        "Dictation shortcut",
        "Click the box, then press the keys you want.",
        &notes,
        Some(shortcut),
        p,
    ));

    // The stop key: the same recorded-draft pattern as the shortcut, with
    // Python's overlap check on top (settings.py set_cancel). "esc" restores
    // the default, and saves the moment it parses.
    let cancel_draft = app.cancel_key_draft.clone();
    let mut cancel_notes: Vec<Note> = Vec::new();
    if crate::hotkeys::is_valid(&cancel_draft) {
        cancel_notes.push(Note::Plain(crate::hotkeys::label(&cancel_draft)));
    } else {
        cancel_notes.push(Note::Danger(
            "Not a valid shortcut. Use key + key, for example Ctrl + Win.".to_string(),
        ));
    }
    if crate::hotkeys::overlaps(&cancel_draft, &draft) {
        cancel_notes.push(Note::Warn(format!(
            "{} is already the dictation shortcut. Pick a different key.",
            crate::hotkeys::label(&cancel_draft)
        )));
    }
    let cancel_warning = crate::hotkeys::warning(&cancel_draft);
    if !cancel_warning.is_empty() {
        cancel_notes.push(Note::Warn(cancel_warning));
    }
    let cancel = row(vec![
        widgets::hotkey_edit(&cancel_draft, Message::CancelKeyChanged, p).into(),
        widgets::flat_button(
            "Reset",
            Message::CancelKeyChanged("esc".to_string()),
            p,
        )
        .into(),
    ])
    .spacing(8)
    .into();
    rows.push(setting_row(
        "Stop key",
        "Stops a take at any point: while you talk, or while it's being written out. \
         Click the box, then press the key you want.",
        &cancel_notes,
        Some(cancel),
        p,
    ));

    let mode = cfg.string_value("hotkey_mode");
    let mode_desc = match mode.as_str() {
        "toggle" => "Press once to start and again to finish. Good for long dictation.",
        "both" => "Hold to talk, or tap it quickly to keep listening until you tap again.",
        _ => "Hold the shortcut while you talk. Let go to finish.",
    };
    rows.push(setting_row(
        "How the shortcut works",
        mode_desc,
        &[],
        Some(widgets::segmented(
            TRIGGER_MODES,
            &mode,
            Message::TriggerModeSelected,
            p,
        )),
        p,
    ));
    out.extend(section_card("Shortcut", "", rows, p));

    // The microphone card.
    let mics = mic_choices(app);
    let current = cfg.string_value("input_device");
    let selected = options::select(&mics, &current)
        .cloned()
        .unwrap_or_else(|| mics[0].clone());
    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "Microphone",
        "System default picks the microphone Windows is using.",
        &[],
        Some(widgets::combo(
            mics,
            Some(selected),
            Message::MicSelected,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Test your microphone",
        "Speak normally. The bar should reach about halfway.",
        &[],
        Some(widgets::level_meter(app.level, p)),
        p,
    ));
    out.extend(section_card("Microphone", "", rows, p));

    // The recording card.
    let mut rows: Vec<Element<'a>> = Vec::new();

    let languages = options::choices(options::LANGUAGES);
    let language = cfg.string_value("language");
    let language_choice = options::select(&languages, &language).cloned();
    let mut language_notes: Vec<Note> = Vec::new();
    if let Some(info) = crate::transcribe::CATALOG
        .iter()
        .find(|m| m.name == cfg.string_value("model"))
    {
        if info.english_only && language != "en" {
            language_notes.push(Note::Warn(format!(
                "{} only understands English. Pick a multilingual model under Speech model \
                 to dictate in other languages.",
                info.title
            )));
        }
    }
    rows.push(setting_row(
        "Language",
        "",
        &language_notes,
        Some(combo_or_blank(languages, language_choice, Message::LanguageSelected, p)),
        p,
    ));

    // The vocabulary box: the saved words it should spell right. The Python
    // page keeps the same field in the Recording card (settings.py vocab).
    let vocabulary = cfg.string_value("vocabulary");
    rows.push(setting_row(
        "Words it should know",
        "Helps with names and terms it would otherwise misspell.",
        &[],
        Some(widgets::text_field(
            "Names, separated by commas",
            &vocabulary,
            300.0,
            Message::VocabularyChanged,
            p,
        )),
        p,
    ));

    // Only a press-to-start take can end on silence.
    if mode != "hold" {
        let quiet = options::auto_stop_options();
        let saved = cfg.number_value("auto_stop_silence");
        let choice = options::select(&quiet, &saved.to_string())
            .cloned()
            .or_else(|| options::select(&quiet, "0").cloned());
        rows.push(setting_row(
            "Stop when you go quiet",
            "Ends a press-to-start take after a pause.",
            &[],
            Some(combo_or_blank(
                quiet,
                choice,
                // The dropdown hands back "0"/"2"/…; the message carries the
                // seconds the config stores.
                |key| Message::AutoStopSelected(key.parse().unwrap_or(0)),
                p,
            )),
            p,
        ));
    }

    let seconds = app
        .max_seconds
        .unwrap_or(cfg.float_value("max_seconds") as f32);
    rows.push(setting_row(
        "Longest take",
        "A take this long finishes by itself.",
        &[Note::Plain(format!(
            "Longest take: {} (10 seconds to 1 hour)",
            seconds.round() as u32
        ))],
        Some(widgets::styled_slider(
            10.0..=3600.0,
            seconds,
            Message::MaxSecondsChanged,
            Message::MaxSecondsReleased,
            p,
        )),
        p,
    ));
    out.extend(section_card("Recording", "", rows, p));

    // What happens while dictating.
    let isolate = cfg.bool_value("isolate_output_while_dictating");
    let level = cfg.number_value("isolate_output_level");
    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "Keep my mic private",
        "Other apps, like calls, can't use the mic while I dictate. If the mic is busy, \
         dictation still works and they keep it.",
        &[],
        Some(widgets::toggle(
            cfg.bool_value("mic_privacy_while_dictating"),
            Message::MicPrivacyToggled,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Mute other apps' sound",
        "Other apps go quiet while I dictate and come back when I stop. Free Dictate's beeps still play.",
        &[Note::Plain("These switches apply on the next take.".to_string())],
        Some(widgets::toggle(isolate, Message::IsolateToggled, p)),
        p,
    ));
    if isolate {
        rows.push(setting_row(
            "What other apps do",
            "Only applies while the row above is on.",
            &[],
            Some(widgets::combo(
                options::level_options(),
                Some(options::level_selected(level)),
                Message::IsolateLevelSelected,
                p,
            )),
            p,
        ));
    } else {
        rows.push(setting_row(
            "What other apps do",
            "Only applies while the row above is on.",
            &[
                Note::Warn(
                    "The level below only shows while Mute other apps' sound is on.".to_string(),
                ),
                Note::Plain(options::level_menu_string(level).to_string()),
            ],
            None,
            p,
        ));
    }
    out.extend(section_card(
        "While I dictate",
        "These switch on when a take starts and back off when it ends.",
        rows,
        p,
    ));

    // The sounds and the recording bar.
    let volume = app
        .sound_volume
        .unwrap_or(cfg.float_value("sound_volume") as f32);
    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "Sounds",
        "A short tone when recording starts and stops, and when the text arrives.",
        &[],
        Some(widgets::toggle(
            cfg.bool_value("sounds"),
            Message::SoundsToggled,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Sound volume",
        "",
        &[Note::Plain(format!(
            "Sound volume: {}%",
            volume.round() as u32
        ))],
        Some(widgets::styled_slider(
            0.0..=100.0,
            volume,
            Message::SoundVolumeChanged,
            Message::SoundVolumeReleased,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Recording bar",
        "A small bar on screen while it listens and transcribes.",
        &[],
        Some(widgets::toggle(
            cfg.bool_value("overlay"),
            Message::OverlayToggled,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Bar position",
        "",
        &[],
        Some(widgets::segmented(
            OVERLAY_POSITIONS,
            &cfg.string_value("overlay_position"),
            Message::OverlayPositionSelected,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Bar material",
        "Uses the window's tint over a picture of what's behind the bar, taken as it appears.",
        &[],
        Some(widgets::segmented(
            OVERLAY_BACKDROPS,
            &cfg.string_value("overlay_backdrop"),
            Message::OverlayBackdropSelected,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Show the timer",
        "",
        &[],
        Some(widgets::toggle(
            cfg.bool_value("overlay_timer"),
            Message::OverlayTimerToggled,
            p,
        )),
        p,
    ));
    out.extend(section_card("Feedback", "", rows, p));

    out
}

// ------------------------------------------------------------ the models page

/// The speech model, the model library, the graphics card, the memory and
/// the fine tuning (settings.py _page_models).
fn models_section<'a>(app: &'a App, p: &Palette) -> Vec<Element<'a>> {
    let cfg = &app.cfg;
    let mut out: Vec<Element<'a>> = Vec::new();

    let (ms_status, active, done, total) = app.engine.model_status();
    let model_key = cfg.string_value("model");

    // The model list, with the state of every model in the label.
    let models: Vec<Choice> = crate::transcribe::CATALOG
        .iter()
        .map(|info| {
            let state = if !active.is_empty() && info.name == active {
                "in use".to_string()
            } else if app.downloaded.iter().any(|name| name == info.name) {
                "downloaded".to_string()
            } else {
                format!("{} MB", info.size_mb)
            };
            Choice {
                key: info.name.to_string(),
                label: format!("{} ({})", info.title, state),
            }
        })
        .collect();
    let model_choice = options::select(&models, &model_key).cloned();

    let mut notes: Vec<Note> = Vec::new();
    if let Some(info) = crate::transcribe::CATALOG
        .iter()
        .find(|m| m.name == model_key)
    {
        notes.push(Note::Plain(info.title.to_string()));
    }
    if ms_status == "downloading" && total > 0 {
        notes.push(Note::Warn(format!(
            "Downloading the speech model: {} of {}",
            mb(done),
            mb(total)
        )));
    }
    if !active.is_empty() && active == model_key {
        notes.push(Note::Ok(format!(
            "In use on the {}.",
            device_label(&cfg.string_value("device"))
        )));
    }
    notes.push(Note::Plain(downloaded_caption(app)));

    let controls = row(vec![
        combo_or_blank(models, model_choice, Message::ModelSelected, p).into(),
        widgets::primary_button("Download model", Message::DownloadModel, p).into(),
        widgets::flat_button("Drop the model now", Message::DropModel, p).into(),
    ])
    .spacing(8)
    .into();
    let rows: Vec<Element<'a>> = vec![setting_row(
        "Speech model",
        "",
        &notes,
        Some(controls),
        p,
    )];
    out.extend(section_card(
        "Models",
        "Larger models are more accurate and slower. Each downloads once.",
        rows,
        p,
    ));

    // The model library: every model with its state and the one valid
    // action, like Python _refresh_library and _library_clicked. The active
    // model gets no button; a downloaded one gets Remove and, when it is
    // not the configured one, Use. The verify line carries the one-line
    // results the background worker publishes.
    let mut rows: Vec<Element<'a>> = Vec::new();
    for info in crate::transcribe::CATALOG {
        let busy = app.lib_busy.iter().any(|name| name == info.name);
        let active_here = !active.is_empty() && info.name == active;
        let on_disk = busy
            || app.downloaded.iter().any(|name| name == info.name)
            || crate::transcribe::is_downloaded(info.name);
        let note = if busy {
            Note::Warn("Downloading…".to_string())
        } else if active_here {
            Note::Ok(format!(
                "In use · on the {}",
                device_label(&cfg.string_value("device"))
            ))
        } else if on_disk {
            Note::Ok("Downloaded".to_string())
        } else {
            Note::Danger(format!("Not downloaded · {} MB", info.size_mb))
        };
        let mut controls: Vec<Element<'a>> = Vec::new();
        if on_disk && !busy && info.name != model_key {
            controls.push(
                widgets::primary_button(
                    "Use",
                    Message::LibraryUseClicked(info.name.to_string()),
                    p,
                )
                .into(),
            );
        }
        if active_here {
            controls.push(Space::new().width(Length::Fixed(240.0)).into());
        } else {
            let label = if busy {
                "Downloading…"
            } else if on_disk {
                "Remove"
            } else {
                "Download"
            };
            controls.push(
                widgets::flat_button(label, Message::LibraryModelClicked(info.name.to_string()), p)
                    .into(),
            );
        }
        rows.push(setting_row(
            info.title,
            "",
            &[note],
            Some(row(controls).spacing(8).align_y(Alignment::Center).into()),
            p,
        ));
    }
    let verify_notes: Vec<Note> = if app.verify_note.is_empty() {
        Vec::new()
    } else {
        vec![Note::Plain(app.verify_note.clone())]
    };
    let verify_controls = row(vec![
        widgets::flat_button("Verify model files", Message::VerifyModels, p).into(),
        widgets::flat_button("Open folder", Message::OpenModelFolder, p).into(),
    ])
    .spacing(8)
    .into();
    rows.push(setting_row(
        "Model files",
        "Downloads are recorded with sizes and checksums and checked when this page opens. \
         This re-checks every byte of every file.",
        &verify_notes,
        Some(verify_controls),
        p,
    ));
    out.extend(section_card(
        "Model library",
        "Everything FreeDictate can run. Download what you need, remove what you don't. \
         Same files, same accuracy. Only the chip doing the work changes.",
        rows,
        p,
    ));

    // The graphics card.
    let devices = options::devices();
    let device = cfg.string_value("device");
    let device_choice = options::select(&devices, &device).cloned();
    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "GPU acceleration",
        "No NVIDIA graphics card found. FreeDictate runs on the processor.",
        &[],
        None,
        p,
    ));
    rows.push(setting_row(
        "Run the model on",
        "Automatic uses the graphics card when GPU support is installed.",
        &[],
        Some(combo_or_blank(devices, device_choice, Message::DeviceSelected, p)),
        p,
    ));
    out.extend(section_card(
        "Graphics card",
        "An NVIDIA graphics card makes the large models many times faster.",
        rows,
        p,
    ));

    // The memory.
    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "Free graphics memory when idle",
        "Unloads the models so games get the memory back. Right after each take is the default: \
         nothing sits in VRAM between takes, and the next take reloads while you're already \
         talking. Pausing unloads immediately.",
        &[Note::Plain("The model reloads on your next hotkey press.".to_string())],
        Some(widgets::toggle(
            cfg.bool_value("idle_unload"),
            Message::IdleUnloadToggled,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Keep models loaded for",
        "",
        &[],
        Some(widgets::body(
            &idle_seconds_label(cfg.number_value("idle_seconds")),
            p,
        )),
        p,
    ));
    // The silence threshold: the level the engine calls quiet.
    let peak = app
        .silence_peak
        .unwrap_or(cfg.float_value("silence_peak") as f32);
    rows.push(setting_row(
        "Silence threshold",
        "",
        &[Note::Plain("Quieter than this counts as silence.".to_string())],
        Some(widgets::styled_slider(
            0.0..=0.2,
            peak,
            Message::SilencePeakChanged,
            Message::SilencePeakReleased,
            p,
        )),
        p,
    ));
    out.extend(section_card(
        "Memory",
        "FreeDictate holds graphics memory while its models are loaded. Unloading gives it back \
         to games and other apps when you're not dictating.",
        rows,
        p,
    ));

    // The fine tuning.
    let compute_types = options::compute_types();
    let compute_key = cfg.string_value("compute_type");
    let compute_choice = options::select(&compute_types, &compute_key).cloned();
    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "Precision",
        "How the model's numbers are stored. Automatic picks the fastest for your hardware.",
        &[],
        Some(combo_or_blank(compute_types, compute_choice, Message::ComputeTypeSelected, p)),
        p,
    ));

    let beam = app.beam_size.unwrap_or(cfg.float_value("beam_size") as f32);
    rows.push(setting_row(
        "Search width",
        "Higher is slightly more accurate and slower. 5 is standard.",
        &[Note::Plain(format!(
            "Search width: {} (higher is slightly more accurate and slower)",
            beam.round() as u32
        ))],
        Some(widgets::styled_slider(
            1.0..=10.0,
            beam,
            Message::BeamSizeChanged,
            Message::BeamSizeReleased,
            p,
        )),
        p,
    ));

    let threads = app
        .cpu_threads
        .unwrap_or(cfg.float_value("cpu_threads") as f32);
    rows.push(setting_row(
        "Limit processor cores",
        "Caps how many processor cores dictation may use. The lower you set it, the longer a take \
         takes, and the fewer CPU spikes and audio crackles. Six cores measured just as fast as \
         every core, with the rest of the machine left alone.",
        &[],
        Some(on_off(cfg.number_value("cpu_threads") > 0, p)),
        p,
    ));
    rows.push(setting_row(
        "Processor cores",
        &format!(
            "This PC has {} threads. Dictation waits longer for your words the lower this is.",
            thread_count()
        ),
        &[Note::Plain(format!(
            "Processor cores used: {}",
            threads.round() as u32
        ))],
        Some(widgets::styled_slider(
            0.0..=64.0,
            threads,
            Message::CpuThreadsChanged,
            Message::CpuThreadsReleased,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Skip silent parts",
        "Cuts pauses before transcribing. Faster, and stops made-up words in silence.",
        &[],
        Some(on_off(cfg.bool_value("vad"), p)),
        p,
    ));
    out.extend(section_card("Fine-tuning", "Defaults suit most people.", rows, p));

    out
}

// -------------------------------------------------------------- the text page

/// How the text arrives, the clean up, the AI tidy-up and the word
/// replacements (settings.py _page_text).
fn text_section<'a>(app: &'a App, p: &Palette) -> Vec<Element<'a>> {
    let cfg = &app.cfg;
    let mut out: Vec<Element<'a>> = Vec::new();

    // The output card.
    let outputs = options::output_methods();
    let output = cfg.string_value("output");
    let output_choice = options::select(&outputs, &output).cloned();
    let output_desc = match output.as_str() {
        "paste_shift_insert" => "For terminals and apps where Ctrl+V does something else.",
        "type" => "Types each character. Slower, but works where pasting is blocked.",
        "clipboard" => "The text goes on the clipboard. Press Ctrl+V where you want it.",
        _ => "Fast and works in almost every app.",
    };
    let restore_notes: Vec<Note> = if output == "paste" || output == "paste_shift_insert" {
        Vec::new()
    } else {
        vec![Note::Warn(
            "This only applies when the text is pasted.".to_string(),
        )]
    };
    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "How the text arrives",
        output_desc,
        &[],
        Some(combo_or_blank(outputs, output_choice, Message::OutputSelected, p)),
        p,
    ));
    rows.push(setting_row(
        "Keep my clipboard",
        "Puts back whatever you had copied after pasting. Clipboard managers are asked to skip \
         the dictated text.",
        &restore_notes,
        Some(widgets::toggle(
            cfg.bool_value("restore_clipboard"),
            Message::RestoreClipboardToggled,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Add a space after",
        "So the next take doesn't run into this one.",
        &[],
        Some(widgets::toggle(
            cfg.bool_value("trailing_space"),
            Message::TrailingSpaceToggled,
            p,
        )),
        p,
    ));
    out.extend(section_card("Output", "", rows, p));

    // The clean up card.
    let cleanups = [
        (
            "capitalize",
            "Capital letter at the start",
            "",
        ),
        (
            "end_punctuation",
            "Full stop at the end",
            "Adds one when the sentence has none.",
        ),
        (
            "remove_fillers",
            "Remove um and uh",
            "Drops hesitation sounds. Words like \"like\" stay.",
        ),
        (
            "remove_repeats",
            "Remove repeated words",
            "Turns \"the the\" or \"I want, I want to\" into one. Words people repeat on purpose, \
             like \"really really\", stay.",
        ),
        (
            "voice_commands",
            "Spoken punctuation and lists",
            "Say \"comma\", \"full stop\", \"question mark\", \"colon\", \"hyphen\", \"open bracket\", \
             \"open quote\", \"dot point\", \"new line\" or \"new paragraph\". Say \"literal\" first \
             to type the word instead.",
        ),
        (
            "auto_submit",
            "\"Submit\" presses Enter",
            "End a take with the word \"submit\" and it's removed and Enter is sent — handy for \
             chat boxes. Off by default, and it stays off when output is clipboard-only.",
        ),
    ];
    let mut rows: Vec<Element<'a>> = Vec::new();
    for (key, title, desc) in cleanups {
        let notes: Vec<Note> = if desc.is_empty() {
            Vec::new()
        } else {
            vec![Note::Plain(desc.to_string())]
        };
        rows.push(setting_row(
            title,
            "",
            &notes,
            Some(widgets::toggle(
                cfg.bool_value(key),
                move |on| Message::TextCleanupToggled(key.to_string(), on),
                p,
            )),
            p,
        ));
    }
    out.extend(section_card("Cleanup", "", rows, p));

    // The AI tidy-up card.
    let ai_models = options::choices(&[
        ("light", "Light (faster)"),
        ("standard", "Standard (more accurate)"),
    ]);
    let ai_key = cfg.string_value("ai_model");
    let ai_choice = options::select(&ai_models, &ai_key).cloned().or_else(|| {
        options::select(&ai_models, "standard").cloned()
    });
    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "Tidy with AI",
        "Removes stumbles, false starts and repeats, and punctuates long run-on takes. Keeps your \
         words and their order. If the result doesn't match what you said, the plain transcript is \
         pasted instead.",
        &[],
        Some(widgets::toggle(
            cfg.bool_value("ai_tidy"),
            Message::AiTidyToggled,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Writing model",
        "",
        &[],
        Some(combo_or_blank(ai_models, ai_choice, Message::AiModelSelected, p)),
        p,
    ));
    out.extend(section_card(
        "AI tidy-up",
        "A small writing model on this PC rewrites each take after it's transcribed. \
         Nothing leaves your PC.",
        rows,
        p,
    ));

    // The replacements editor (settings.py _add_repl and _save_repl): one
    // field pair per draft row, plus the scratch rows still being typed.
    // Saving drops rows with a blank "when it writes", and the app keeps
    // saved rows and drafts in step on every change.
    let mut rows: Vec<Element<'a>> = Vec::new();
    for (index, (find, replace)) in app.replacements_draft.iter().enumerate() {
        rows.push(
            row(vec![
                widgets::text_field(
                    "When it writes",
                    find,
                    180.0,
                    move |text| Message::ReplacementFindChanged(index, text),
                    p,
                )
                .into(),
                widgets::sub("→", p).into(),
                widgets::text_field(
                    "Use this instead",
                    replace,
                    180.0,
                    move |text| Message::ReplacementReplaceChanged(index, text),
                    p,
                )
                .into(),
                widgets::flat_button("✕", Message::ReplacementRemove(index), p).into(),
            ])
            .spacing(8)
            .align_y(Alignment::Center)
            .into(),
        );
    }
    rows.push(
        row(vec![
            widgets::flat_button("Add replacement", Message::ReplacementAdd, p).into(),
            widgets::primary_button("Save", Message::ReplacementsSaved, p).into(),
        ])
        .spacing(8)
        .into(),
    );
    out.extend(section_card(
        "Replacements",
        "Fix words it keeps getting wrong. Matches whole words, any case. \
         Rows with a blank \"when it writes\" are dropped when you save.",
        rows,
        p,
    ));

    out
}

// ---------------------------------------------------------- the appearance page

/// The colours, the window material and the motion (settings.py _page_look).
fn look_section<'a>(app: &'a App, p: &Palette) -> Vec<Element<'a>> {
    let cfg = &app.cfg;
    let mut out: Vec<Element<'a>> = Vec::new();

    // The colours card.
    let themes: Vec<Choice> = crate::ui::theme::theme_names()
        .into_iter()
        .map(|name| Choice {
            key: name.clone(),
            label: name,
        })
        .collect();
    let theme_choice = options::select(&themes, &app.theme_name).cloned();
    let accent = cfg.string_value("accent_source");
    let fonts = options::choices(FONTS);
    let font_choice = options::select(&fonts, &cfg.string_value("font")).cloned();

    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "Theme",
        "",
        &[],
        Some(combo_or_blank(themes, theme_choice, Message::ThemeSelected, p)),
        p,
    ));
    rows.push(setting_row(
        "Accent colour",
        "Buttons, switches and highlights.",
        &[],
        Some(widgets::segmented(
            ACCENT_SOURCES,
            &accent,
            Message::AccentSourceSelected,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Font",
        "Type to search the fonts on this PC.",
        &[Note::Plain("(applies on restart)".to_string())],
        Some(combo_or_blank(fonts, font_choice, Message::FontSelected, p)),
        p,
    ));
    out.extend(section_card("Colours", "", rows, p));

    // The window material card.
    let backdrops = options::choices(BACKDROPS);
    let backdrop = cfg.string_value("backdrop");
    let backdrop_choice = options::select(&backdrops, &backdrop).cloned();
    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "Material",
        &material_desc(&backdrop),
        &[],
        Some(combo_or_blank(backdrops, backdrop_choice, Message::BackdropSelected, p)),
        p,
    ));
    let tint = cfg.float_value("tint") as f32;
    rows.push(setting_row(
        "Tint",
        "How much of the theme colour covers the material. Lower lets more through.",
        &[Note::Plain(format!(
            "Tint: {}%",
            tint.round() as u32
        ))],
        Some(widgets::styled_slider(
            0.0..=100.0,
            tint,
            Message::TintChanged,
            Message::TintReleased,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Keep the effect in the background",
        "Windows normally swaps the material for a flat colour when you switch to another window.",
        &[],
        Some(on_off(cfg.bool_value("backdrop_when_inactive"), p)),
        p,
    ));
    rows.push(setting_row(
        "Title bar",
        "Windows uses the standard title bar, buttons and menu.",
        &[],
        Some(widgets::segmented(
            TITLEBARS,
            &cfg.string_value("titlebar"),
            Message::TitlebarSelected,
            p,
        )),
        p,
    ));
    out.extend(section_card("Window material", "", rows, p));

    // The motion card.
    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "Reduce motion",
        "Turns off fades and sliding switches.",
        &[],
        Some(widgets::toggle(
            cfg.bool_value("reduce_motion"),
            Message::ReduceMotionToggled,
            p,
        )),
        p,
    ));
    out.extend(section_card("Motion", "", rows, p));

    out
}

// ------------------------------------------------------------- the history page

/// Keeping the dictations (settings.py _page_history and HistoryItem).
fn history_section<'a>(app: &'a App, p: &Palette) -> Vec<Element<'a>> {
    let cfg = &app.cfg;
    let mut out: Vec<Element<'a>> = Vec::new();

    // The Python toolbar above the card: the search box and the buttons.
    // "Transcribe a file" has no message in this build, so the toolbar keeps
    // the search and Clear all; export and import live in their own card.
    out.push(
        row(vec![
            widgets::text_field(
                "Search your dictations",
                &app.history_query,
                280.0,
                Message::HistoryQueryChanged,
                p,
            )
            .into(),
            Space::new().width(Length::Fill).into(),
            widgets::danger_button("Clear all", Message::ClearHistory, p).into(),
        ])
        .spacing(8)
        .into(),
    );

    // The list a tick last pulled (newest first): one row per dictation,
    // with Python HistoryItem's meta line and its delete button.
    if app.history_rows.is_empty() {
        let note = if !app.history_query.is_empty() {
            format!("Nothing matches \"{}\".", app.history_query)
        } else if !cfg.bool_value("history_enabled") {
            "History is off. Turn on \"Save my dictations\" below to keep a record here."
                .to_string()
        } else {
            format!(
                "No dictations yet. Hold {} anywhere, talk, and let go. Each one shows up here.",
                crate::hotkeys::label(&cfg.string_value("hotkey"))
            )
        };
        out.push(widgets::sub(&note, p));
    } else {
        let mut rows: Vec<Element<'a>> = Vec::new();
        for entry in &app.history_rows {
            let mut meta = vec![
                timestamp_label(entry.ts),
                format!("{:.0} s", entry.seconds),
            ];
            if !entry.app.is_empty() {
                meta.push(entry.app.trim_end_matches(".exe").to_string());
            }
            let text = if entry.text.chars().count() < 600 {
                entry.text.clone()
            } else {
                format!(
                    "{}...",
                    entry
                        .text
                        .chars()
                        .take(600)
                        .collect::<String>()
                        .trim_end()
                )
            };
            let left = column(vec![
                widgets::sub(&meta.join("  ·  "), p),
                widgets::body(&text, p),
            ]);
            rows.push(
                row(vec![
                    left.width(Length::Fill).into(),
                    widgets::danger_button(
                        "Delete",
                        Message::HistoryDeleteSelected(entry.id),
                        p,
                    )
                    .into(),
                ])
                .spacing(10)
                .align_y(Alignment::Center)
                .into(),
            );
        }
        out.push(widgets::card(rows, p));
    }

    // Export and import: fixed paths in the data folder (this build has no
    // file dialog), and the one-line result published after either job.
    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "Export and import",
        "Export writes every dictation to history-export.txt in the data folder. Import reads \
         transcripts.log from the same folder.",
        &[],
        Some(
            row(vec![
                widgets::flat_button("Export", Message::ExportHistory, p).into(),
                widgets::flat_button("Import", Message::ImportHistory, p).into(),
            ])
            .spacing(8)
            .into(),
        ),
        p,
    ));
    out.extend(section_card("Export and import", "", rows, p));
    if !app.verify_note.is_empty() {
        out.push(widgets::sub(&app.verify_note, p));
    }

    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "Save my dictations",
        "Stored only on this PC.",
        &[],
        Some(widgets::toggle(
            cfg.bool_value("history_enabled"),
            Message::HistoryToggled,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Delete dictations older than",
        "",
        &[],
        Some(widgets::body(
            &history_days_label(cfg.number_value("history_days")),
            p,
        )),
        p,
    ));
    out.extend(section_card("Keeping history", "", rows, p));

    out
}

// ------------------------------------------------------------- the general page

/// The startup, the updates and the data (settings.py _page_general).
fn startup_section<'a>(app: &'a App, p: &Palette) -> Vec<Element<'a>> {
    let cfg = &app.cfg;
    let mut out: Vec<Element<'a>> = Vec::new();

    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "Start with Windows",
        "Starts quietly in the tray when you sign in.",
        &[],
        Some(widgets::toggle(
            app.start_with_windows,
            Message::StartWithWindowsToggled,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Run as administrator",
        "Lets it paste into apps that run as administrator. Windows blocks that otherwise. \
         Asks for permission once.",
        &[],
        Some(widgets::toggle(
            cfg.bool_value("run_elevated"),
            Message::RunElevatedToggled,
            p,
        )),
        p,
    ));
    out.extend(section_card("Startup", "", rows, p));

    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "Check for updates automatically",
        "Once a day, from GitHub. Nothing installs without you.",
        &[],
        Some(widgets::toggle(
            cfg.bool_value("check_updates"),
            Message::UpdateCheckToggled,
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Include test versions",
        "Get pre-releases early. They may have bugs.",
        &[],
        Some(widgets::toggle(
            cfg.bool_value("update_prereleases"),
            Message::UpdatePrereleasesToggled,
            p,
        )),
        p,
    ));
    // The manual check plus the note the background job publishes (an
    // available version, an up-to-date line, or an error).
    let mut update_notes: Vec<Note> = Vec::new();
    if !app.update_note.is_empty() {
        update_notes.push(Note::Plain(app.update_note.clone()));
    }
    rows.push(setting_row(
        &format!("FreeDictate {}", crate::updater::VERSION),
        &format!(
            "Last checked: {}.",
            timestamp_label(cfg.float_value("last_update_check"))
        ),
        &update_notes,
        Some(widgets::primary_button(
            "Check for updates",
            Message::CheckUpdates,
            p,
        )),
        p,
    ));
    out.extend(section_card("Updates", "", rows, p));

    // The folder button: this build has no file dialog, so the backups rows
    // keep the paths and the exported files in one place the user can open.
    let data = cfg
        .path
        .parent()
        .map(|folder| folder.display().to_string())
        .unwrap_or_default();
    let mut rows: Vec<Element<'a>> = Vec::new();
    let data_controls = row(vec![
        widgets::body(&data, p).into(),
        widgets::flat_button("Open folder", Message::OpenAppFolder, p).into(),
    ])
    .spacing(8)
    .into();
    rows.push(setting_row(
        "Settings and history",
        "",
        &[],
        Some(data_controls),
        p,
    ));
    rows.push(setting_row(
        "Logs",
        "What to attach when you report a problem.",
        &[],
        None,
        p,
    ));
    rows.push(setting_row(
        "Back up your settings",
        "Save them to a file, or load them on another PC.",
        &[],
        None,
        p,
    ));
    rows.push(setting_row(
        "Reset all settings",
        "History and downloaded models are kept.",
        &[],
        Some(widgets::danger_button("Reset", Message::Reset, p)),
        p,
    ));
    out.extend(section_card("Your data", "", rows, p));

    out
}

// --------------------------------------------------------------- the about page

/// The app name, the links and the credits (settings.py _page_about).
fn about_section<'a>(p: &Palette) -> Vec<Element<'a>> {
    let mut out: Vec<Element<'a>> = Vec::new();
    out.push(widgets::name_label("FreeDictate", p));
    out.push(widgets::sub(
        &format!("Version {}", crate::updater::VERSION),
        p,
    ));
    out.push(widgets::sub(
        "Speak, and the words appear where you're typing. Offline, private, and free.",
        p,
    ));

    let repo = format!("https://github.com/{}", crate::updater::REPO);
    let mut rows: Vec<Element<'a>> = Vec::new();
    rows.push(setting_row(
        "Project page",
        "Source code, documentation and releases.",
        &[],
        Some(widgets::link_button(
            "Open",
            Message::OpenLink(repo.clone()),
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "Report a problem",
        "Attach the log file from General > Your data.",
        &[],
        Some(widgets::link_button(
            "Open",
            Message::OpenLink(format!("{repo}/issues/new")),
            p,
        )),
        p,
    ));
    rows.push(setting_row(
        "What's new",
        "Changes in every version.",
        &[],
        Some(widgets::link_button(
            "Open",
            Message::OpenLink(format!("{repo}/releases")),
            p,
        )),
        p,
    ));
    out.extend(section_card("Links", "", rows, p));

    out.push(widgets::section("Built with", p));
    out.push(widgets::card(
        vec![widgets::sub(
            "Speech recognition by OpenAI Whisper, run through faster-whisper (SYSTRAN) and \
             CTranslate2 (OpenNMT), and NVIDIA Parakeet through onnx-asr. AI tidy-up by Qwen3 \
             models (Apache 2.0) run with llama.cpp. Interface built with Qt for Python. Audio \
             through PortAudio and sounddevice. FreeDictate is open source under the MIT license.",
            p,
        )],
        p,
    ));

    out
}

// ------------------------------------------------------------------ the rows

/// The kind of note under a row: the Python Row.set_note roles.
enum Note {
    Plain(String),
    Warn(String),
    Ok(String),
    Danger(String),
}

/// A card with a heading, an optional description and its rows, separated by
/// hairlines (settings.py Page.section and Card.add).
fn section_card<'a>(
    heading: &str,
    desc: &str,
    rows: Vec<Element<'a>>,
    p: &Palette,
) -> Vec<Element<'a>> {
    let mut out: Vec<Element<'a>> = vec![widgets::section(heading, p)];
    if !desc.is_empty() {
        out.push(widgets::sub(desc, p));
    }
    let mut body: Vec<Element<'a>> = Vec::new();
    for (index, row) in rows.into_iter().enumerate() {
        if index > 0 {
            body.push(widgets::divider(p));
        }
        body.push(row);
    }
    out.push(widgets::card(body, p));
    out
}

/// One setting: the title, the description and the note on the left, the
/// control on the right (settings.py Row).
fn setting_row<'a>(
    title: &str,
    desc: &str,
    notes: &[Note],
    control: Option<Element<'a>>,
    p: &Palette,
) -> Element<'a> {
    if notes.is_empty() {
        return widgets::row_item(title, desc, control, p);
    }
    let mut labels = column(vec![widgets::name_label(title, p)]);
    if !desc.is_empty() {
        labels = labels.push(widgets::sub(desc, p));
    }
    for note in notes {
        labels = labels.push(match note {
            Note::Plain(text) => widgets::sub(text, p),
            Note::Warn(text) => widgets::warn_text(text, p),
            Note::Ok(text) => widgets::ok_text(text, p),
            Note::Danger(text) => widgets::danger_text(text, p),
        });
    }
    let mut items: Vec<Element<'a>> = vec![labels.width(Length::Fill).into()];
    if let Some(control) = control {
        items.push(control);
    }
    row(items)
        .align_y(Alignment::Center)
        .spacing(12)
        .width(Length::Fill)
        .into()
}

/// The value of a switch that this build cannot change yet.
fn on_off<'a>(value: bool, p: &Palette) -> Element<'a> {
    widgets::body(if value { "On" } else { "Off" }, p)
}

/// A dropdown for a saved value, or an empty label when the saved value is
/// not in the list. The palette stays out of the closure on purpose: the
/// element must outlive the borrow.
fn combo_or_blank<'a>(
    options: Vec<Choice>,
    selected: Option<Choice>,
    on_select: impl Fn(String) -> Message + Clone + 'a,
    p: &Palette,
) -> Element<'a> {
    match selected {
        Some(choice) => widgets::combo(options, Some(choice), on_select, p),
        None => widgets::body("", p),
    }
}

// ------------------------------------------------------------- the value labels

/// The microphones: the system default first, then every device (settings.py
/// _fill_mics).
fn mic_choices(app: &App) -> Vec<Choice> {
    let mut out = vec![Choice {
        key: String::new(),
        label: "System default".to_string(),
    }];
    for device in &app.mics {
        out.push(Choice {
            key: device.name.clone(),
            label: device.label.clone(),
        });
    }
    let saved = app.cfg.string_value("input_device");
    if !saved.is_empty() && !out.iter().any(|choice| choice.key == saved) {
        out.push(Choice {
            key: saved.clone(),
            label: format!("{saved} (not connected)"),
        });
    }
    out
}

/// The models already on this PC (the Python page's downloaded list).
fn downloaded_caption(app: &App) -> String {
    let mut titles: Vec<&'static str> = Vec::new();
    for info in crate::transcribe::CATALOG {
        if app.downloaded.iter().any(|name| name == info.name) {
            titles.push(info.title);
        }
    }
    if titles.is_empty() {
        "No models downloaded yet; the first take downloads one.".to_string()
    } else {
        format!("Downloaded on this PC: {}", titles.join(", "))
    }
}

/// "the graphics card" or "the processor".
fn device_label(device: &str) -> &'static str {
    if device == "cuda" {
        "graphics card"
    } else {
        "processor"
    }
}

/// A file size the way the Python page writes it.
fn mb(bytes: u64) -> String {
    if bytes >= 1_000_000_000 {
        format!("{:.1} GB", bytes as f64 / 1e9)
    } else {
        format!("{:.0} MB", bytes as f64 / 1e6)
    }
}

/// How long the models stay loaded.
fn idle_seconds_label(seconds: u32) -> String {
    match seconds {
        0 => "Right after each take".to_string(),
        30 => "30 seconds".to_string(),
        60 => "1 minute".to_string(),
        120 => "2 minutes".to_string(),
        300 => "5 minutes".to_string(),
        600 => "10 minutes".to_string(),
        1800 => "30 minutes".to_string(),
        3600 => "1 hour".to_string(),
        other => format!("{other} seconds"),
    }
}

/// The window material, in the Python page's words.
fn material_desc(backdrop: &str) -> &'static str {
    match backdrop {
        "mica_alt" => "Mica Alt: a deeper tint of your wallpaper. Windows uses it for tabbed apps.",
        "mica" => "Mica: a subtle tint of your wallpaper.",
        "acrylic" => "Acrylic: frosted glass that blurs what's behind the window.",
        "blur" => "Blur: a clear, smooth blur of what's behind the window, without Acrylic's grain.",
        "solid" => "Solid: a plain theme colour.",
        _ => "None: a plain theme colour, with no material behind the window.",
    }
}

/// How long the dictations are kept.
fn history_days_label(days: u32) -> String {
    match days {
        0 => "Forever".to_string(),
        365 => "1 year".to_string(),
        90 => "90 days".to_string(),
        30 => "30 days".to_string(),
        7 => "7 days".to_string(),
        1 => "1 day".to_string(),
        other => format!("{other} days"),
    }
}

/// The processor threads of this PC.
fn thread_count() -> usize {
    std::thread::available_parallelism()
        .map(|count| count.get())
        .unwrap_or(8)
}

/// A "21 Oct 2026, 3:44 PM" stamp from a Unix timestamp, like the Python
/// page's time.strftime. UTC: the Rust build has no timezone helper.
fn timestamp_label(epoch: f64) -> String {
    if epoch <= 0.0 {
        return "never".to_string();
    }
    let total = epoch as i64;
    let days = total.div_euclid(86_400);
    let secs = total.rem_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    let hour24 = secs / 3600;
    let minute = (secs % 3600) / 60;
    let ampm = if hour24 < 12 { "AM" } else { "PM" };
    let hour12 = match hour24 % 12 {
        0 => 12,
        hour => hour,
    };
    format!(
        "{day} {} {year}, {hour12}:{minute:02} {ampm}",
        MONTHS[(month - 1) as usize]
    )
}

/// The civil date from a day count since the epoch (Howard Hinnant's
/// days-from-civil, inverted).
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = trunc_div(if z >= 0 { z } else { z - 146_096 }, 146_097);
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let year = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let month = if mp < 10 {
        (mp + 3) as u32
    } else {
        (mp - 9) as u32
    };
    let year = if month <= 2 { year + 1 } else { year };
    (year, month, day)
}

/// Integer division that cuts towards zero.
fn trunc_div(a: i64, b: i64) -> i64 {
    let quotient = a.abs() / b.abs();
    if (a < 0) != (b < 0) {
        -quotient
    } else {
        quotient
    }
}
