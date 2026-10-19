# Rust rewrite build checkpoint (2026-10-19)

This is the live build log for finishing the Rust rewrite. Update it as steps land.

## Done

- 23970f1 skeleton plus config/ducking/privacy (4 Rust tests green).
- 2026-10-19: Cargo.toml deps finalised (cpal 0.18, whisper-rs 0.16, ureq 3, iced 0.14, windows 0.62 with keyboard/clipboard/security features).
- 2026-10-19: config/mod.rs carries the full Python DEFAULTS/CHOICES/RANGES set; stored settings stay in `%APPDATA%\FreeDictate-Rust\settings.json` so the installed Python app keeps `%APPDATA%\FreeDictate\settings.json` untouched. `rust-rewrite/.cargo/config.toml` sets `LIBCLANG_PATH` for whisper-rs' bindgen; LLVM 23 installed at `C:\Program Files\LLVM` (winget LLVM.LLVM) because whisper-rs-sys could not bindgen without libclang.
- 2026-10-19: src/output.rs delivers text (clipboard, restore, paste, shift-insert, type, blocked/admin detection), ported from src/freedictate/output.py. cargo check clean, cargo test 4/4 green.

## Slices (one subagent each)

- audio: rust-rewrite/src/audio/mod.rs only. cpal capture, 16 kHz mono f32, exclusive WASAPI fallback to shared, level/peak/silent_for, beeps via winmm PlaySound. Python reference: src/freedictate/audio.py.
- engine: rust-rewrite/src/engine/mod.rs + new src/hotkeys/mod.rs and src/transcribe/mod.rs. GetAsyncKeyState polling every 10 ms, hold/toggle/both, stop key, ggml catalog + download (ureq files from huggingface, progress + cancel) + whisper-rs load/transcribe/offload, transcriber loop, calls output::deliver. Python reference: engine.py, hotkeys.py, models.py.
- ui: rust-rewrite/src/ui/mod.rs (iced 0.14) with the same settings page, including the plain-language privacy toggles. Python reference: ui/settings.py.

Main agent owns Cargo.toml, lib.rs, main.rs, config, output, ducking, tests/test_privacy_options.rs and all commits.

## Next

1. Integrate audio + hotkeys/transcribe + ui as their agents land, one commit each.
2. cargo build --release must finish; cargo test green.
3. Run the exe, screenshot the settings window (desktop locked via coop), PNG in work/reports/, attach through t3_attachment_prepare_upload -> POST -> t3_thread_send_attachments.
4. README section for start with Windows; tray icon only if trivial.
