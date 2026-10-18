# Rust architecture for FreeDictate

This document is design only. It does not implement anything. It maps the Python modules in `src/freedictate/` to Rust modules and names the crates that would carry each job.

## Module boundaries

- `audio`: device list, capture start and stop, exclusive capture, 16 kHz resampling.
- `engine`: hotkey polling, take lifecycle, model loading, transcription queue.
- `ducking`: per-session mute and restore on the render endpoint, plus the restore record.
- `config`: read and write `settings.json`, preserve defaults and migrations.
- `ui`: settings window and tray, with the plain privacy labels kept intact.
- `tests`: parity tests for the two "While I dictate" switches and the level menu.

## Data flow

1. `engine` asks `audio::refresh_devices()` to rebuild the device list.
2. `engine` calls `audio::Recorder::start(device_name, exclusive)` at take start.
3. If `isolate_output_while_dictating` is true, `engine` calls `ducking::start(level)`.
4. At take end, `engine` calls `ducking::stop()` on every path, including cancellation and errors.
5. `ui` edits a live config object and writes through `config::Config::update(values)`.
6. `config::Config::save()` writes the same JSON shape the Python version uses.
7. `config::Config::load()` reads that file at startup and on restart.

## External dependencies

- `cpal` for capture and playback.
- `rodio` for the short feedback sounds.
- `windows-rs` for WASAPI exclusive capture and Core Audio session control.
- `serde` and `serde_json` for `settings.json`.
- `tokio` for the async engine loop and model loading.
- `whisper-rs` or a direct `whisper.cpp` FFI for speech models.
- `iced` or `tauri` for the settings window.
- `rustls` or `reqwest` for downloads and update checks.

## Behaviour to preserve

- `mic_privacy_while_dictating` switches to exclusive capture for a take.
- `isolate_output_while_dictating` silences or lowers other apps while a take runs.
- `isolate_output_level` defaults to `0`, which means silence.
- `config.json` stays compatible, or gains a documented migration.
- The stop key stays usable in every busy state.
- The settings labels stay exactly as they are now.

## Anti-pattern checklist

- No bold decorative labels in headings or prose.
- No `crucial`, `pivotal`, `vital`, `enhance`, `robust`, `showcase`, `tapestry`, `landscape`.
- No forced triads.
- No em or en dashes in prose.
- No "not X but Y" staging.
- No chatbot openers or closers.

## What this document does not claim

It does not claim the Rust version is faster or better. That only becomes true if the parity tests and the live privacy probes pass on a real build.
