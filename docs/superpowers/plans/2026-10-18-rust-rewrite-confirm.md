# Rust rewrite interface confirmation (Task 1)

Source of truth: `src/freedictate/` in this worktree. Version 3.6.1, commit `da17936`.

## Confirmed app state

- Installed executable: `C:\Users\localuser\AppData\Local\Programs\FreeDictate\FreeDictate.exe`
  - FileVersion 3.6.1, ProductVersion 3.6.1.
- Settings at `%APPDATA%\FreeDictate\settings.json`:
  - `mic_privacy_while_dictating`: `True`
  - `isolate_output_while_dictating`: `True`
  - `isolate_output_level`: `0`

## Locked interface names

The Rust names below keep the Python names so the two codebases can be compared side by side.

- `audio`
  - `audio.refresh_devices()` -> `audio::refresh_devices()`
  - `Recorder.start(device_name, exclusive)` -> `audio::Recorder::start(device_name: &str, exclusive: bool)`
  - `Recorder.stop()` -> `audio::Recorder::stop()`
- `engine`
  - `Engine.start()` -> `engine::Engine::start()`
  - `Engine._begin()` -> `engine::Engine::begin(exclusive: bool)`
  - `Engine._end(cancelled)` -> `engine::Engine::end(cancelled: bool)`
- `ducking`
  - `ducking.start(level)` -> `ducking::start(level: u32)`
  - `ducking.stop()` -> `ducking::stop()`
  - `ducking.recover()` -> `ducking::recover()`
- `config`
  - `Config.load()` -> `config::Config::load()`
  - `Config.save()` -> `config::Config::save()`
  - `Config.update(values)` -> `config::Config::update(values)`
- `ui`
  - `SettingsWindow.save_geometry()` -> `ui::SettingsWindow::save_geometry()`
  - Privacy rows keep the exact label text:
    - "Keep my mic private"
    - "Mute other apps' sound"
    - "What other apps do"

## Behaviour that must survive the rewrite

- `mic_privacy_while_dictating` uses exclusive capture when it can, and still starts dictation if it cannot.
- `isolate_output_while_dictating` silences or lowers other apps while a take runs and restores them exactly.
- `isolate_output_level` is 0 by default, which means "go silent", not "leave volume alone".
- The stop key works in every busy state.
- The settings window keeps the same plain wording.

## Evidence

- `work/reports/2026-10-18-freedictate-privacy-evidence.md`
- `work/reports/2026-10-18-freedictate-probe/settings-while-i-dictate.png` (34,531 bytes)

No source file has been changed by this task. This document only records the confirmed state.
