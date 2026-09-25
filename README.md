# FreeDictate

Unlimited local speech-to-text dictation for Windows 11. Same push-to-talk feel as Wispr Flow, with no account, no cloud, and no weekly limit. Audio never leaves your PC.

Hold **Ctrl+Win**, speak, release. The text pastes at your cursor.

## Install

Needs Windows 11 and Python 3.10 or newer from [python.org](https://www.python.org/downloads/) (tick *Add python.exe to PATH* during setup). Not the Microsoft Store build.

**One line.** Open PowerShell and paste:

```powershell
irm https://github.com/DavidHiFi/freedictate/releases/latest/download/Install.ps1 | iex
```

That downloads the release into `%LOCALAPPDATA%\FreeDictate`, installs the Python packages, fetches the Whisper model once (about 500 MB), and adds a single autostart entry.

**Or by hand.** Download `freedictate.zip` from the [releases page](https://github.com/DavidHiFi/freedictate/releases), extract it anywhere, then:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-FreeDictate.ps1 -Install
```

Add `-Audit` instead of `-Install` to check first without changing anything.

## Use

1. Click any text field.
2. Hold Ctrl+Win and speak.
3. Release. Text pastes at the cursor and stays on the clipboard for a Ctrl+V fallback.
4. Esc cancels a take with nothing pasted.

Beeps mark the state: one beep when listening starts, a higher beep when text pastes, a low beep when a take is discarded or cancelled.

## Start and stop

- **Start:** double click `Start-FreeDictate.cmd`, or log in again and the autostart entry launches it silently.
- **Stop:** Ctrl+C in its window, or end the `pythonw` process running `freedictate.py` in Task Manager.
- Takes append to `transcripts.log` in the install folder. Delete that file any time to clear history.

## If you also use Wispr Flow

Quit Wispr Flow or rebind its push-to-talk key before starting FreeDictate. Both listen to Ctrl+Win, so running both pastes twice.

## Configure

Edit `config.json` next to `freedictate.py`, then restart the app.

| Key | Default | Meaning |
| --- | --- | --- |
| `model` | `small.en` | Whisper model. `tiny.en` is faster, `medium.en` is more accurate. |
| `device` | `cpu` | Set `cuda` only if NVIDIA CUDA works on your PC. |
| `compute_type` | `int8` | Quantization. Leave it unless you know why. |
| `language` | `en` | Dictation language. |
| `input_device` | `""` | Mic name substring. Empty means the system default. |
| `hotkey` | `ctrl+win` | Fixed in this build. |
| `auto_paste` | `true` | `false` leaves text on the clipboard instead of pasting. |
| `paste_delay` | `0.15` | Seconds between copying and pasting. |
| `beeps` | `true` | Audible state cues. |
| `min_seconds` | `0.5` | Takes shorter than this are discarded. |
| `silence_peak` | `0.005` | Below this a take counts as silence and is discarded. |
| `remove_fillers` | `true` | Drops um, uh, you know, basically from transcripts. |

FreeDictate reads your microphone. It never changes mic routing, audio apps, drivers, display settings, or services.

## Commands

```text
python freedictate.py                 hold Ctrl+Win to dictate
python freedictate.py --audit         read-only checks, changes nothing
python freedictate.py --list-devices  show input devices, changes nothing
python freedictate.py --mic-test 5    5 second level meter, changes nothing
python freedictate.py --preload       download and cache the model once
```

## Uninstall

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-FreeDictate.ps1 -Uninstall
```

Then delete the install folder. No restart needed. `pip uninstall faster-whisper sounddevice numpy pyperclip pynput` clears the packages too.

## How it works

`pynput` watches Ctrl+Win, `sounddevice` records while you hold it, `faster-whisper` transcribes locally, and `pyperclip` plus a Ctrl+V keystroke pastes the result. The model downloads from Hugging Face on first run and caches in your user profile. No server, no API key, no telemetry.

## License

[MIT](LICENSE)
