# FreeDictate Rust

A Rust port of FreeDictate, a Windows push-to-talk dictation app. Work in progress: the settings window, hotkeys, model download and transcription are ported; there is no tray icon yet, and a full dictation with a real microphone has not been tested from the Python version in `../src/freedictate`.

## Building

You need Rust stable and LLVM installed at `C:\Program Files\LLVM`. Whisper-rs builds its C bindings through bindgen, which needs libclang from that install. The `.cargo/config.toml` in this crate already sets `LIBCLANG_PATH` to that location, so no environment setup is needed.

Build with:

```
cargo build --release
```

The finished exe is `target\release\freedictate-rust.exe`.

## Settings

Settings live in `%APPDATA%\FreeDictate-Rust\settings.json`. This is separate from the Python app, which uses its own folder, so both can be installed side by side without touching each other's settings.

## Start with Windows

The Start with Windows switch on the settings page writes a `FreeDictate-Rust` value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, pointing at the exe path in quotes. The Python app uses a different value name (`FreeDictate`), so the two autostart entries do not clash.
