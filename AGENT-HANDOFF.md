# Agent handoff: install FreeDictate on Windows 11

Paste this whole folder to the agent. It has everything needed. No extra downloads except Python packages and the Whisper model.

## What to build

FreeDictate, a lightweight unlimited local dictation tool that works like Wispr Flow. Hold Ctrl+Win, speak, release. Text pastes at the cursor. 100 percent local through faster-whisper. No account, no cloud, no weekly limit.

Files in this folder:

- freedictate.py, the app. Hold Ctrl+Win to record, release to transcribe and paste. Esc cancels a take. Logs takes to transcripts.log.
- config.json, defaults. Model small.en, cpu/int8, language en, system default input, auto_paste true.
- requirements.txt, pinned Python packages.
- Install-FreeDictate.ps1, audit plus one step installer. Audit changes nothing. Install adds user packages and one Run key for autostart.
- Start-FreeDictate.cmd, double click launcher.
- README.md, human instructions for the owner.

## Safety rules

Follow these. They matter on a live Windows 11 PC.

- Start read only. Run the audit commands first and report what you found before changing anything.
- One controlled change at a time. Back up before any registry write. The installer already exports the Run key to backups/ before it writes.
- Never change mic routing, audio apps, comms apps, drivers, display settings, power plans, or services. Read the mic, do not set it.
- Ask before anything that needs a restart, signs the user out, or interrupts networking, audio, or display.
- Never stop or reconfigure the user's active audio chain unless they name that exact app and action.

## Install order

Run from the folder where these files live. Use PowerShell with ExecutionPolicy Bypass for the .ps1 only.

1. Check Python. Needs Windows Python 3.10 or newer from python.org, not the Store build.
   python --version
   Expected: 3.10 or higher.

2. Audit. Changes nothing.
   powershell -NoProfile -ExecutionPolicy Bypass -File Install-FreeDictate.ps1 -Audit
   python freedictate.py --audit
   python freedictate.py --list-devices
   Expected: all five packages show installed or missing, input device count above zero, default device named. If packages are missing, go to step 3. If the default input looks wrong, note it and ask the user which mic name to use. Do not change routing.

3. Install packages and autostart. This is the only step that writes.
   powershell -NoProfile -ExecutionPolicy Bypass -File Install-FreeDictate.ps1 -Install
   Expected: pip reports satisfied, audit prints model small.en, backup .reg written to backups/, one Run key named FreeDictate added. The Run key should point at pythonw.exe and freedictate.py.

4. Preload the model. First run downloads small.en once, about 500 MB, then caches it.
   python -c "from faster_whisper import WhisperModel; m=WhisperModel('small.en', device='cpu', compute_type='int8'); print('small.en load OK')"
   Expected: small.en load OK. If the PC has a working NVIDIA CUDA setup the user can ask for device cuda later. Default stays cpu.

5. Resolve the hotkey conflict. FreeDictate and Wispr Flow both listen to Ctrl+Win. Running both pastes twice.
   Ask the user to quit Wispr Flow or rebind its push to talk key to something unused. Confirm Wispr is out before starting FreeDictate. Do not kill anything else.

6. Start FreeDictate in the background.
   Start-Process -FilePath "pythonw.exe" -ArgumentList "`"FULL\PATH\TO\freedictate.py`"" -WorkingDirectory "FULL\PATH\TO\FOLDER"
   Replace both paths with the real folder. Then wait 10 seconds and confirm the process is alive:
   Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object {$_.CommandLine -match "freedictate"}
   Expected: one process row with freedictate.py in the command line.

7. Mic check. Ask the user to run this and speak for 5 seconds.
   python freedictate.py --mic-test 5
   Expected: peak bars move while speaking, max peak well above 0.005. If it warns the mic is very quiet, stop and help with Windows sound settings. Change nothing silently.

8. Live test. Ask the user to click any text field, hold Ctrl+Win, say one sentence, release. Confirm the text pastes and transcripts.log gains one line. Esc cancels a take with nothing pasted.

## Config options

Edit config.json only if the user asks. Keys: model, device, compute_type, language, input_device (substring match on device name, empty means system default), sample_rate, hotkey (fixed at ctrl+win in this build), auto_paste, paste_delay, beeps, min_seconds, silence_peak, remove_fillers. Keep language en unless the user dictates in another language. Keep device cpu unless CUDA is verified working.

## Rollback

- Stop: kill the pythonw process running freedictate.py, or Ctrl+C in its window if started in a console.
- Remove autostart: powershell -NoProfile -ExecutionPolicy Bypass -File Install-FreeDictate.ps1 -Uninstall, or merge the .reg backup in backups/.
- Remove the tool: delete this folder. Optional: pip uninstall faster-whisper sounddevice pynput pyperclip.
- Resume Wispr: start Wispr Flow from the Start Menu.
- No restart is needed for any of these.

## Report back

Tell the user: what you observed in audit, what you changed, what stayed unchanged, whether a restart is pending, how to undo each change, and what the live voice test showed. Mark the live test unverified until the user speaks a real sentence and confirms the paste. Do not claim success from a clean exit code alone.
