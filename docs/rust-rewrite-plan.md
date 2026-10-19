# FreeDictate → Rust rewrite — plan summary (2026-10-18)

Thread: new, same workspace (`work/repo-standard/freedictate`), model `openrouter/free` via `work/reports/free-models-router.py`. Previous thread (privacy fix) settled; evidence preserved.
Status: implementation started. The privacy settings, audio session ducking and Rust skeleton are in place; the full rewrite is still incomplete.

What the plan actually covers (honest scope):

1. Source audit complete (read-only). Key files inspected: `engine.py`, `audio.py`, `ducking.py`, `config.py`, `ui/settings.py`. `tests/test_privacy_options.py` passes.
2. Resource-heavy paths identified: audio capture (16 kHz numpy buffers), Whisper model load/offload, Qt event loop, heavy thread pools.
3. Rust equivalents mapped honestly: `cpal`/`rodio` for capture; `tokio`/`rayon` for concurrency; `whisper.cpp` bindings for transcription; `iced`/`tauri` for GUI; `windows-rs` for mic-privacy and session control.
4. Honest limits: REA is for shipped binaries / decompilation, not for writing Rust from source. Since full Python source exists, source audit is the correct path. No binary was decompiled; the installed `FreeDictate.exe` (3.6.1) was only read via settings file and version info, not reconstructed.
5. Perfection claim: this document does not promise perfection. It lists what must work (mic privacy, session mute, hotkey, model load, settings) and notes that a Rust rewrite must pass the same tests (`test_privacy_options.py` equivalent) before any claim of improvement holds.

Next step: finish the remaining Rust modules (`audio`, `engine`, `ui`) and then run the same privacy tests against the Rust build.
