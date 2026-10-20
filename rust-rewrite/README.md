# FreeDictate Rust

FreeDictate Rust - A Rust port of FreeDictate, a Windows push-to-talk dictation app. The engine (capture, Whisper transcription, text cleanup, delivery) is ported line-for-line from the Python original; the window is a native iced port of the Qt UI. Everything runs in one process: an engine on its own threads, a dictation window, a settings window, a tray icon and a single-instance guard.

## Building

You need Rust stable and LLVM installed at `C:\Program Files\LLVM`. Whisper-rs builds its C bindings through bindgen, which needs libclang from that install. The `.cargo/config.toml` in this crate already sets `LIBCLANG_PATH` to that location, so no environment setup is needed.

Build with:

```
cargo build --release
```

The finished exe is `target\release\freedictate-rust.exe`.

Configuration and history live in `%APPDATA%\FreeDictate-Rust` (separate from the Python app). Models are downloaded to `%APPDATA%\FreeDictate-Rust\models`.

## The window

- Dictation page: engine status, pause control, hotkey and stop-key hints, and a live mic meter fed from the capture stream at ~50 ms.
- Settings page: the full section set (Dictation, Models, Text, Look, History, General, About) of the Python app, every row interactive: hotkey and stop-key editors, vocabulary and word-replacement editors, silence auto-stop, overlay recording-bar preferences, the model library (per-model download/remove/verify), tint and title bar, update switches with a manual check, history search with per-row delete, and export/import through fixed paths (no file dialogs in this port yet).
- Settings open on the section you last used; the window reopens where you left it; the taskbar and Alt-tab icon are the real app icon.
- Chromium DWM chrome runs live: the configured theme tint and backdrop (Mica/Mica Alt/Acrylic/blur) are applied when the look rows change.

## Settings

Settings live in `%APPDATA%\FreeDictate-Rust\settings.json`. This is separate from the Python app, which uses its own folder, so both can be installed side by side without touching each other's settings.

## Start with Windows

The Start with Windows switch on the settings page writes a `FreeDictate-Rust` value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, pointing at the exe path in quotes. The Python app uses a different value name (`FreeDictate`), so the two autostart entries do not clash.

## Tray and single instance

The tray icon shows on start (left click raises the window; right click has Settings and Exit). A second launch wakes the running window and exits instead — the tray's hidden window doubles as the wake target. When `check_updates` is on, the app checks GitHub for a release once per session in the background and shows the result on the update rows; the Check button does the same on demand.

## Module Map

- audio: Microphone capture, device list and feedback sounds through cpal's WASAPI shared mode, with resampled mono output at 16 kHz and the process-wide live level feed the meters read.
- config: Configuration parser for settings.json with defaults and validation.
- ducking: Audio ducking for lowering system volume during dictation.
- engine: Engine state management and timer-driven recording with auto-stop after silence; the model library, history and verify helpers live here too.
- hotkeys: Global hotkey handling for push-to-talk activation, including the stop-key matcher the engine uses to cancel a running dictation.
- transcribe: Whisper-based speech recognition; the model catalog, streamed downloads, and load/unload.
- textproc: Text post-processing: fillers, spoken punctuation, capitalization, word replacements (parsed from settings), AI tidy-up passes.
- output: Clipboard paste and typing with foreground-window detection and privacy helpers.
- ui: The iced windows: dictation page, full settings page, live level subscription, runtime window icon, Fluent theming and the DWM chrome glue.
- autostart: Manage Windows autostart registry entry for automatic launch.
- history: SQLite history storage, search, export and import.
- writer: AI tidy-up model management and text rewriting (GPU/local engine download).
- updater: Application updater: release check, download verification and installation.
- tray: System tray icon, context menu, and the wake window for the single-instance guard.
- single_instance: Mutex-based single-instance guard (`FreeDictate-Rust-<user>`), separate from the Python app's name.

## Test Map

- test_audio.rs: Capture chain tests, resampler verification and sound rendering.
- test_autostart.rs: Registry entry creation and removal.
- test_config.rs: Configuration parser behavior and default values.
- test_engine.rs: Engine state, timing, silence detection and auto-stop logic.
- test_history.rs: SQLite history storage, search, export and import.
- test_hotkeys.rs: Hotkey parsing, matching and validation.
- test_idle_unload.rs: Model unload timing after periods of inactivity.
- test_models.rs: Model download, verification and loading logic.
- test_output.rs: Clipboard handling, text delivery and modifier key detection.
- test_privacy_options.rs: Microphone privacy and audio isolation settings.
- test_replacements.rs: Word-replacement config parsing and whole-word replace passes.
- test_single_instance.rs: Mutex-based single instance enforcement.
- test_stop_key.rs: Cancel key handling during recording.
- test_textproc.rs: Text cleaning, filler removal and spoken command processing.
- test_transcribe.rs: Whisper inference tests and transcription accuracy checks.
- test_tray.rs: System tray icon lifecycle and context menu.
- test_ui.rs: Settings view rendering and control interactions.
- test_updater.rs: GitHub release checking, download verification and installation.
- test_writer.rs: AI model management, text rewriting and plausibility checking.

## Known Gaps

- The overlay recording bar (overlay.py: the always-on-top bar on the screen edge while dictating) has its view layer ported but is not wired to a second window yet; iced 0.14's simple application builder renders the same content in every window, and the shell is not a multi-window Program yet.
- The live-mic meter idles at zero when nothing is captured (by design: it samples the running capture stream; between takes the engine is not capturing).
- `run_elevated` and `reduce_motion` settings are saved but only advisory in this port: the Python app re-executes itself elevated on start and slows Qt's window animations; iced has neither path wired.
- History export/import use fixed paths under `%APPDATA%\FreeDictate-Rust` (no native file dialogs without an extra dependency).
- Verify-model checks presence and size only (no sha256 manifest like Python's verify.py).
- WASAPI exclusive capture not reachable via cpal 0.18 (exclusive flag uses best shared-mode available).
- GPU support is informational: whisper-rs here is CPU-only, so the CUDA download path is not offered.
- Live-mic end-to-end (real microphone in, text out) has not been scripted; transcription end-to-end via WAV passes ("Free dictate end-to-end check, working.", load 93 ms, transcribe 567 ms on ggml-tiny.en).
