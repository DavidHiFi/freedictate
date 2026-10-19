# FreeDictate Rust

FreeDictate Rust - A Rust port of FreeDictate, a Windows push-to-talk dictation app.

## Building

You need Rust stable and LLVM installed at `C:\Program Files\LLVM`. Whisper-rs builds its C bindings through bindgen, which needs libclang from that install. The `.cargo/config.toml` in this crate already sets `LIBCLANG_PATH` to that location, so no environment setup is needed.

Build with:

```
cargo build --release
```

The finished exe is `target\release\freedictate-rust.exe`.

Configuration and history live in `%APPDATA%\FreeDictate-Rust` (separate from the Python app). Models are downloaded to `%APPDATA%\FreeDictate-Rust\models`.

## Settings

Settings live in `%APPDATA%\FreeDictate-Rust\settings.json`. This is separate from the Python app, which uses its own folder, so both can be installed side by side without touching each other's settings.

## Start with Windows

The Start with Windows switch on the settings page writes a `FreeDictate-Rust` value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, pointing at the exe path in quotes. The Python app uses a different value name (`FreeDictate`), so the two autostart entries do not clash.

## Module Map

- audio: Microphone capture, device list and feedback sounds through cpal's WASAPI, with resampled mono output at 16 kHz.
- config: Configuration parser for settings.json with defaults and validation.
- ducking: Audio ducking for lowering system volume during dictation.
- engine: Engine state management and timer-driven recording with auto-stop after silence.
- hotkeys: Global hotkey handling for push-to-talk activation.
- transcribe: Whisper-based speech recognition engine.
- textproc: Text post-processing and formatting of transcribed text.
- output: Speech synthesis and text-to-speech output, clipboard paste and typing.
- ui: Settings UI for configuring hotkeys, devices and audio.
- autostart: Manage Windows autostart registry entry for automatic launch.
- history: Conversation history storage and retrieval.
- writer: AI tidy-up for improving transcription accuracy.
- updater: Application updater checking for newer releases.
- tray: System tray icon and right-click context menu.
- single_instance: Enforce single instance to prevent multiple launches.

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
- test_single_instance.rs: Mutex-based single instance enforcement.
- test_stop_key.rs: Cancel key handling during recording.
- test_textproc.rs: Text cleaning, filler removal and spoken command processing.
- test_transcribe.rs: Whisper inference tests and transcription accuracy checks.
- test_tray.rs: System tray icon lifecycle and context menu.
- test_ui.rs: Settings view rendering and control interactions.
- test_updater.rs: GitHub release checking, download verification and installation.
- test_writer.rs: AI model management, text rewriting and plausibility checking.

## Known Gaps

- replacements config not parsed into textproc
- WASAPI exclusive capture not reachable via cpal 0.18 (exclusive flag uses best shared-mode available)
- live-mic end-to-end not scripted (transcription e2e via WAV: "Free dictate end-to-end check, working.", load 93 ms, transcribe 567 ms on the downloaded ggml-tiny.en.bin)
- Full dictation with a real microphone has not been tested (the tray icon and window are captured from the running release exe)