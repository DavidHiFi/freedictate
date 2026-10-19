# Implementation Report: FreeDictate Rust Settings Page Port

Slice 3 of the four-agent Fluent rebuild wave. One file owned, one file written.

## Files Created/Modified

### 1. `rust-rewrite/src/ui/pages/settings.rs` (replaced the shim)
The shim (three lines, delegating to `App::settings_view`) is gone. The file now
holds the whole settings window, built on the widget contract in
`rust-rewrite/src/ui/widgets.rs` and the wording of
`src/freedictate/ui/settings.py`.

Nothing else was touched: no edits to `theme.rs`, `chrome.rs`, `widgets.rs`,
`pages/dictation.rs`, `src/ui/mod.rs`, `Cargo.toml`, `options.rs`, `icons.rs`
or `overlay.rs`.

### Shape
- `pub fn view(app: &App) -> Element<'_>` — unchanged signature, so the page
  goes live as soon as it compiles (`src/ui/mod.rs` already routes
  `Page::Settings` here).
- Left rail (180px) + scrolling content on the right, in one row.
- The rail carries the Python sidebar: a status card (engine state dot, status
  text, Pause/Resume), one nav button per section, and the version line.
- The content is the open section: page title, then one card per group, with
  hairline dividers between the rows, exactly like `Page.section()` and
  `Card.add()` in the Python page.

### `pub const SECTIONS: &[(&'static str, &'static str, &'static str)]`
(key, glyph, label), in the order of the Python sidebar (`settings.py PAGES`):

| # | key | glyph | label | Python page |
|---|-----|-------|-------|-------------|
| 1 | `general` | mic | Dictation | `_page_dictation` |
| 2 | `models` | cpu | Speech model | `_page_models` |
| 3 | `text` | text | Text and pasting | `_page_text` |
| 4 | `look` | palette | Appearance | `_page_look` |
| 5 | `history` | clock | History | `_page_history` |
| 6 | `startup` | sliders | General | `_page_general` |
| 7 | `about` | info | About | `_page_about` |

**Section key mismatch, as instructed.** The Python sidebar's first entry is
`dictation`, not `general`. The App opens on `settings_section == "general"`,
so the dictation page carries the `general` key and its content, and the
Python's own "general" page (Startup, Updates, Your data) is keyed `startup`
while keeping the Python label "General". Everything else mirrors the Python
order, labels and icon names.

The section switches on `Message::SettingsSection`, which sets
`app.settings_section`.

## Controls carried over

Every control the legacy `settings_view` bound is still bound, and every row
the Python page shows is present. The 41 settings message variants in
`crate::ui::Message` are all constructed by this file (the compiler confirms
it: only `Tick`, `Engine` and `OpenSettings` remain unconstructed here, and
those belong to the event pump and the dictation page).

### Shortcut (Python `_page_dictation`)
- Dictation shortcut — hotkey box (`Message::HotkeyChanged`), a Reset button
  that puts `ctrl+win` back, the shortcut label, and the invalid-shortcut
  and single-key warnings from `crate::hotkeys`.
- Stop key — the key a take stops with, plus its warning.
- How the shortcut works — segmented control (`hold` / `toggle` / `both`) with
  the Python's description of the chosen mode.

### Microphone
- Microphone — dropdown of the devices from `app.mics` with "System default"
  first, plus a "(not connected)" entry for a saved device that is gone.
- Test your microphone — the level meter.

### Recording
- Language — dropdown of the 29 languages, with the Python note that an
  English-only model cannot dictate other languages.
- Words it should know — the vocabulary.
- Stop when you go quiet — only shown outside Hold mode, like the Python.
- Longest take — the slider, with the "10 seconds to 1 hour" note.

### While I dictate
- Keep my mic private, Mute other apps' sound, What other apps do (the level
  menu, with the level hidden and explained while the mute switch is off),
  and the "These switches apply on the next take." note.

### Feedback
- Sounds, Sound volume (slider with the percentage note).
- Recording bar, Bar position, Bar material, Show the timer — read-only (see
  the gaps below).

### Models (Python `_page_models`)
- Speech model — the dropdown with the state of every model in the label
  ("in use", "downloaded", the size), the "Download model" and "Drop the model
  now" buttons, the download progress from `engine.model_status()` and the
  "Downloaded on this PC" line from `app.downloaded`.
- Model library — one row per catalog model with its state, and the "Model
  files" row.
- Graphics card — GPU acceleration row, and "Run the model on".
- Memory — "Free graphics memory when idle", "Keep models loaded for" and the
  silence threshold slider.
- Fine-tuning — Precision, Search width, Limit processor cores, Processor
  cores, Skip silent parts.

### Text and pasting (Python `_page_text`)
- Output — "How the text arrives" with the Python description of the method,
  "Keep my clipboard", "Add a space after".
- Cleanup — all six switches with the Python wording.
- AI tidy-up — "Tidy with AI" and the writing model dropdown.
- Replacements — the saved word list, read-only.

### Appearance (Python `_page_look`)
- Theme dropdown (`theme::theme_names()`), accent source segmented control
  ("From the theme" / "Windows accent"), font dropdown ("Segoe UI Variable
  Text" / "Segoe UI") with the "(applies on restart)" note.
- Window material — material dropdown (None, Solid, Mica, Mica Alt, Acrylic,
  Blur) with the Python description of the material, plus Tint, "Keep the
  effect in the background" and Title bar.
- Motion — Reduce motion.

### History (Python `_page_history`)
- "Clear all" (danger button), "Save my dictations", "Delete dictations older
  than".

### General (Python `_page_general`)
- Startup — "Start with Windows", "Run as administrator".
- Updates — "Check for updates automatically", "Include test versions", the
  version row with the last-check time.
- Your data — the data folder, Logs, "Back up your settings", and "Reset all
  settings" (danger button, `Message::Reset`).

### About (Python `_page_about`)
- The app name, version and the one-line description.
- Links — Project page, Report a problem, What's new.
- Built with — the credits paragraph.

### Page furniture
- A "Back" button at the foot of every section (`Message::CloseSettings`),
  which is the legacy view's Back button.

## What could not be ported, and why

No new `Message` variant was invented. Where the Python page has a control
and the Rust message set has none, the row is still shown with the Python
wording, and the current value is shown as plain text.

| Python control | Why | What the page shows |
|---|---|---|
| "Got it" on the welcome banner | no message for `first_run_done` | the banner text only |
| Stop key box, its Reset button | no message for `cancel_key` | the key it stops with |
| Microphone refresh button | the Rust re-reads the device list on every tick | the dropdown |
| Microphone "Test" button | the engine emits no live level | the level meter |
| Vocabulary box | no message | the vocabulary text |
| "Stop when you go quiet" dropdown | no message for `auto_stop_silence` | the current value |
| Recording bar switches (bar, position, material, timer) | no message for the overlay keys | the current value |
| Per-model library buttons, "Verify model files", "Download GPU support" | no message for model removal, verification or the GPU support | the model rows with their state |
| "Keep models loaded for" dropdown | no message for `idle_seconds` | the current value |
| "Limit processor cores" switch | the Rust uses the cores slider instead | On/Off |
| "Skip silent parts" switch | no message for `vad` | On/Off |
| Writing model Download and Delete buttons | no message for the writer model | the writing model dropdown |
| "Add replacement" button and the replacement boxes | no message for `replacements` | the saved list |
| Tint slider | no message for `tint` | the value |
| "Keep the effect in the background" | no message | On/Off |
| Title bar switch | no message | the current choice |
| Reduce motion switch | no message | On/Off |
| "Run as administrator" and "Restart now" | no message | On/Off |
| Update switches and "Check now" | no message | On/Off |
| "Open folder", "Open logs", Export, Import | no message | the data folder path |
| History search box, "Transcribe a file", "Export", "Show more", the list | the App holds no history handle | "Clear all" only |
| The About "Open" buttons | no message for opening a URL | the URL as text |

Three smaller differences worth knowing:

- The Python microphone entry is "Windows default (device)"; the task asked for
  "System default" as the first entry, so that is what it says, with the
  legacy caption "System default picks the microphone Windows is using."
- The Python has a discrete "Longest take" dropdown; the Rust keeps the
  legacy slider (10 seconds to 1 hour) and the Python's own sentence as the
  description.
- The "Processor cores" line counts threads, not physical cores: the Rust
  build has no way to read the physical core count the way the Python page's
  `psutil` call does.
- The Python's "materials need Windows 11 22H2" and "transparency effects are
  off" notes need a native helper that `chrome.rs` does not expose yet, so
  the material row carries the material description only.

## Verification

### `cargo check` — pass
```
cargo check --message-format short
    Finished `dev` profile [unoptimized + debuginfo] target(s)
```
No warnings and no errors from `pages/settings.rs`.

### `cargo test` — pass, 21 test binaries
```
cargo test
    Finished `test` profile [unoptimized + debuginfo] target(s)
    test result: ok. 160 passed; 0 failed; 18 ignored
```
Every binary green: `freedictate_rust` unit tests (17), `main` (0),
test_audio (6), test_autostart (1), test_config (15), test_engine (4),
test_history (9), test_hotkeys (10), test_idle_unload (5), test_models (8),
test_output (2), test_privacy_options (4), test_single_instance (4),
test_stop_key (10), test_textproc (22), test_transcribe (5), test_tray (3),
test_ui (4), test_updater (21), test_writer (10), doc-tests (0).

The run was blocked three times by other slices' in-flight edits, all fixed
by their owners before the final run:

1. `src/ui/icons.rs` had a raw string that did not parse
   (`r#"stroke="#000000""#`), which broke the library's own test target.
2. `Cargo.toml` had `hound = "3.5"` pushed under `[build-dependencies]`, so
   the audio and transcribe tests lost their dev-dependency.
3. `Cargo.toml` was missing the `Win32_UI_Composition` windows feature that
   `src/ui/chrome.rs` needs for `SetWindowCompositionAttribute`, so every
   test binary failed to link.

`pages/settings.rs` was clean in every one of those runs: no errors and no
warnings from it.


## Notes for whoever owns `src/ui/mod.rs`

- `Message::SettingsSection` only sets `app.settings_section`; it does not
  save it, and the App starts every run on "general". The Python saves the
  open page in `window_page`, but that config key only knows
  "dictation" and "settings" (`config::CHOICES`), so per-section restoring
  needs a new key or a wider one.
- The App's `palette()` is private to `crate::ui` but reachable from the
  pages module, so this file uses it directly instead of re-deriving the
  palette.
- The slider drag positions (`app.sound_volume`, `app.silence_peak`,
  `app.cpu_threads`, `app.max_seconds`, `app.beam_size`) are read here, the
  same way the legacy view read them. Without them a slider would snap back
  to the stored value on every frame while it is being dragged.

