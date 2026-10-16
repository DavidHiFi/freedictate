# FreeDictate

Unlimited local speech-to-text dictation for Windows 11. Hold a shortcut, speak, let go — the text lands at your cursor. No account, no cloud, no weekly limit. Audio never leaves your PC.

<p align="center">
  <img src="docs/images/dictation.png" alt="FreeDictate settings — Dictation page" width="720">
</p>
<p align="center">
  <img src="docs/images/models.png" alt="Speech model page" width="360">
  &nbsp;
  <img src="docs/images/look.png" alt="Appearance page" width="360">
</p>

## How it works

1. Click any text field.
2. Hold **Ctrl+Win** (the default hotkey) and speak.
3. Release. The transcript is pasted at your cursor.

**Esc** cancels a take. In *toggle* mode a short press starts and a second press stops; in *both* mode a tap latches and holding pushes to talk. A small overlay near your cursor shows the input level and a timer while you speak.

## Download

Grab the newest release from [github.com/DavidHiFi/freedictate/releases/latest](https://github.com/DavidHiFi/freedictate/releases/latest). Every release ships two builds:

| File | What it is |
| --- | --- |
| `FreeDictate-<version>-Setup.exe` | The installer. Per-user by default, no admin prompt. |
| `FreeDictate-<version>-Portable.zip` | Portable build. Extract anywhere and run `FreeDictate.exe`. |
| `SHA256SUMS` | Checksums for the files above. |

No Python, no dependencies: both builds are frozen executables that bundle everything, the Visual C++ runtime included, so nothing else needs installing. They run on 64-bit Windows 10 1809 or later; the window materials need Windows 11 22H2. GPU acceleration is optional: on a PC with an NVIDIA card, Settings → *Speech model* downloads NVIDIA's libraries in one click (only the NVIDIA driver is needed).

## Install

Run `FreeDictate-<version>-Setup.exe`. It installs to your profile by default (no admin needed; you can pick *all users* on the first page), offers a startup shortcut and an optional desktop icon, and adds an entry to *Apps › Installed apps* for clean removal. On the first launch, pick a voice model in Settings — it downloads once, then dictation is fully offline.

Updating is built in: Settings → *General* → *Check for updates*. FreeDictate downloads the new build from GitHub Releases, verifies it against `SHA256SUMS`, and restarts itself.

## Portable

Extract the zip wherever you like — a USB stick works — and run `FreeDictate.exe`. A `portable.txt` marker next to the exe tells FreeDictate to keep everything (settings, history, downloaded models) in a `data\` folder beside it, so the whole folder moves with you and nothing is written to the registry or AppData. The portable build can update itself the same way, keeping your `data\` folder.

## Settings

Everything lives in one window with seven pages:

- **Dictation**: hotkey and mode, microphone with a live level test, sounds (start, stop, and a tone when the text arrives) and volume, auto-stop on silence for press-to-start takes, vocabulary hints passed to the model, pause.
- **Speech model**: pick a model, from Whisper *Tiny* (75 MB, fastest) to *Large v3*, or NVIDIA's *Parakeet v2* for English. CPU or NVIDIA GPU. One list picks the model; a second deletes models you no longer use. A fallback model keeps dictation working while a new one downloads.
- **Text and pasting**: filler removal, repeated-word removal ("the the" becomes "the"), capitalization, end punctuation, spoken punctuation and lists ("comma", "full stop", "question mark", "hyphen", "open bracket", "dot point", "new line", "new paragraph"; say "literal" first to type the word), an optional AI tidy-up, find-and-replace rules, output method (paste / Shift+Insert / type / clipboard only) and clipboard restore.
- **Appearance** — ten themes plus *Match Windows*, the Windows accent colour, any installed font, and the window material: **Mica Alt, Mica, Acrylic, Blur** or solid, with a tint slider. Every slider has a value box you can type a number into. Backdrops need Windows 11 22H2 and transparency turned on; otherwise you get the solid look automatically. The title bar can be FreeDictate's own or the standard Windows one; with the Windows title bar the material runs under it and the tint covers the body (Windows can't tint its own caption, which keeps the raw material).
- **History**: searchable dictation history in SQLite on your PC, retention in days, clear or export. When the AI tidy-up changed a take, you can copy what you originally said. Transcribe audio and video files here too.
- **General** — start at login (normal or elevated), update settings, prerelease channel, export/import settings.
- **About** — version, licences, links.

## Models

| Model | Size | Good for |
| --- | --- | --- |
| Tiny | 75 MB | Short notes, slow PCs |
| Base | 145 MB | Fast and decent |
| Small | 484 MB | The default; good balance |
| Medium | 1.5 GB | More accuracy |
| Distil Large v3.5 | 1.5 GB | English. About as accurate as Large v3, and faster |
| Parakeet v2 | 661 MB | English. The most accurate here, and fast on the CPU alone. Doesn't use vocabulary hints |
| Large v3 Turbo | 1.6 GB | Close to Large v3, much faster; best with a GPU |
| Large v3 | 3.1 GB | The most accurate Whisper model, any language; best with a GPU |
| multilingual variants | — | 30+ languages via *Detect automatically* |

With an NVIDIA GPU, Settings offers a one-click CUDA support download. Without it, everything runs on CPU.

Accuracy, measured on 30 LibriSpeech clips and 21 accented clips (Scottish, Irish, southern British, Indian English) from EdAcc, as word error rate (lower is better):

| Model | Clean speech | Accented speech |
| --- | --- | --- |
| Parakeet v2 (CPU, int8) | 2.6% | 9.5% |
| Large v3 (GPU) | 4.2% | 10.2% |
| Distil Large v3.5 (GPU) | 5.1% | 10.9% |

## AI tidy-up

Optional, under *Text and pasting*. A small writing model on your PC removes stumbles, false starts and repeats, and punctuates run-on takes, keeping your words and their order. If the answer drops much of what you said, changes a number, or reads like a reply rather than your words, FreeDictate pastes the plain transcript instead.

FreeDictate runs the model itself with [llama.cpp](https://github.com/ggml-org/llama.cpp) (MIT licence). Settings downloads the engine (32 MB, checked against a pinned SHA-256) together with one of two models: *Light* (1.1 GB, for graphics cards under 6 GB) or *Standard* (2.5 GB, about a second per take on a recent card). It needs a graphics card from any maker; on the processor alone a clean-up takes about 11 seconds, so the setting says so and stays off. The writing model loads only for takes that need it and leaves graphics memory after a few minutes without one (5 by default, adjustable under *Speech model › Memory*).

## Privacy

Recording, transcription, history and settings stay on your PC. The AI tidy-up runs on your own PC. The only network traffic is the model downloads you choose and the optional update check against the GitHub Releases API, both visible and switchable in Settings. No telemetry, no accounts.

## If you also use Wispr Flow

Quit Wispr Flow or rebind its push-to-talk key before starting FreeDictate. Both listen for the same hotkey, so running both pastes twice.

## Building from source

```powershell
pwsh -File scripts\build.ps1
```

runs the test suite, freezes the app with PyInstaller, self-tests the frozen exe, compiles the Inno Setup installer, and zips the portable build into `dist\`. Pass `-SkipInstaller`, `-SkipTests` or `-Python <path>` as needed; see the header of `scripts\build.ps1`. Source layout: `src\freedictate` (core), `src\freedictate\ui` (settings window and overlay), `tests\`, `packaging\`.

## Contributing

Bug reports, feature ideas and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, checks and what to include.

## Star history

⭐ Thanks to everyone using FreeDictate, reporting dictation bugs and sending fixes.

<a href="https://www.star-history.com/?repos=DavidHiFi%2Ffreedictate&amp;type=date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=DavidHiFi/freedictate&amp;type=date&amp;theme=dark&amp;legend=top-left" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=DavidHiFi/freedictate&amp;type=date" />
    <img alt="DavidHiFi/freedictate GitHub star history" src="https://api.star-history.com/chart?repos=DavidHiFi/freedictate&amp;type=date" />
  </picture>
</a>

## License

[MIT](LICENSE)
