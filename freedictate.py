"""FreeDictate: lightweight unlimited local dictation for Windows.

Hold Ctrl+Win, speak, release. Text pastes at cursor.
100% local via faster-whisper. No account, no cloud, no weekly limit.

Usage:
  python freedictate.py                 # hold Ctrl+Win to dictate
  python freedictate.py --list-devices  # show input devices, changes nothing
  python freedictate.py --mic-test 5    # 5s level meter, changes nothing
  python freedictate.py --audit         # read-only checks, changes nothing
  python freedictate.py --preload       # download and cache the model once
  python freedictate.py --model small.en --device cpu

Config file config.json next to this script overrides defaults.
Mic is never changed. Default input device is used unless
input_device substring is set in config.
"""
import argparse
import json
import sys
import time
import threading
import queue
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
HISTORY_PATH = HERE / "transcripts.log"

DEFAULTS = {
    "model": "base.en",
    "device": "cpu",
    "compute_type": "int8",
    "language": "en",
    "input_device": "",
    "sample_rate": 16000,
    "hotkey": "ctrl+win",
    "auto_paste": True,
    "paste_delay": 0.15,
    "beeps": True,
    "min_seconds": 0.5,
    "silence_peak": 0.005,
    "remove_fillers": True,
}

FILLERS = ["um", "uh", "er", "ah", "you know", "basically", "like,"]


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"Config read failed, using defaults: {e}")
    return cfg


def beep(freq=880, ms=120, enabled=True):
    if not enabled:
        return
    try:
        import winsound
        winsound.Beep(freq, ms)
    except Exception:
        pass


def list_devices():
    import sounddevice as sd
    print("Input devices (index: name, channels):")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            default = " [DEFAULT]" if i == sd.default.device[0] else ""
            print(f"  {i}: {d['name']} ({d['max_input_channels']}ch){default}")


def mic_test(seconds=5, device=None):
    import sounddevice as sd
    import numpy as np
    print(f"Mic test {seconds}s. Speak now.")
    dev = None
    if device:
        for i, d in enumerate(sd.query_devices()):
            if device.lower() in d["name"].lower() and d["max_input_channels"] > 0:
                dev = i
                print(f"Using input: {d['name']}")
                break
    peaks = []
    def cb(indata, frames, t, status):
        peak = float(abs(indata).max())
        peaks.append(peak)
        bar = "#" * min(50, int(peak * 200))
        print(f"\rpeak {peak:.3f} {bar}   ", end="")
    with sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                        device=dev, callback=cb):
        time.sleep(seconds)
    print()
    if peaks and max(peaks) < 0.005:
        print("WARNING: mic very quiet. Check Windows sound settings. Nothing changed.")
    else:
        print(f"OK. Max peak {max(peaks):.3f}. Nothing changed.")


def audit(cfg):
    print("FreeDictate audit. Read only, changes nothing.")
    print(f"  Python: {sys.version.split()[0]}")
    for mod in ["sounddevice", "faster_whisper", "pyperclip", "pynput", "numpy"]:
        try:
            __import__(mod)
            print(f"  {mod}: installed")
        except Exception:
            print(f"  {mod}: MISSING (run Install-FreeDictate.ps1)")
    print(f"  Model: {cfg['model']} device={cfg['device']} lang={cfg['language']}")
    print(f"  Hotkey: {cfg['hotkey']} (hold to talk, release to paste)")
    print(f"  Auto-paste: {cfg['auto_paste']}")
    print("  Protected apps untouched: Discord, Ableton, VB-Audio Matrix, Stream Deck.")
    print("  Mic routing untouched. Override only via config input_device.")
    try:
        import sounddevice as sd
        d = sd.query_devices()
        ins = [x["name"] for x in d if x["max_input_channels"] > 0]
        print(f"  Found {len(ins)} input devices. Default index {sd.default.device[0]}.")
    except Exception as e:
        print(f"  Audio query failed: {e}")


def clean_text(t, remove_fillers):
    t = " ".join(t.strip().split())
    if remove_fillers:
        low = f" {t.lower()} "
        for f in FILLERS:
            low = low.replace(f" {f} ", " ")
        t = " ".join(low.split())
        if t:
            t = t[0].upper() + t[1:] if len(t) > 1 else t.upper()
    if t and t[-1] not in ".!?":
        t += "."
    return t


class Recorder:
    def __init__(self, cfg):
        import sounddevice as sd
        self.cfg = cfg
        self.sr = int(cfg["sample_rate"])
        self.q = queue.Queue()
        self.frames = []
        self.stream = None
        self.device = self._resolve(sd, cfg["input_device"])

    def _resolve(self, sd, want):
        if not want:
            return None
        for i, d in enumerate(sd.query_devices()):
            if want.lower() in d["name"].lower() and d["max_input_channels"] > 0:
                print(f"Input: {d['name']}")
                return i
        print(f"Mic '{want}' not found, using system default. Nothing changed.")
        return None

    def _cb(self, indata, frames, t, status):
        self.q.put(indata.copy())

    def start(self):
        import sounddevice as sd
        self.frames = []
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break
        self.stream = sd.InputStream(samplerate=self.sr, channels=1,
                                     dtype="float32", device=self.device,
                                     callback=self._cb)
        self.stream.start()

    def stop(self):
        import numpy as np
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        while not self.q.empty():
            try:
                self.frames.append(self.q.get_nowait())
            except queue.Empty:
                break
        if not self.frames:
            return None, 0.0
        audio = np.concatenate(self.frames, axis=0).flatten()
        return audio, len(audio) / float(self.sr)


def preload(cfg):
    from faster_whisper import WhisperModel
    device = "cuda" if cfg["device"] == "auto" else cfg["device"]
    print(f"Preloading whisper {cfg['model']} on {device} ({cfg['compute_type']})...")
    try:
        WhisperModel(cfg["model"], device=device, compute_type=cfg["compute_type"])
    except Exception as e:
        if device == "cuda":
            print(f"CUDA load failed ({e}), falling back to cpu/int8.")
            WhisperModel(cfg["model"], device="cpu", compute_type="int8")
        else:
            raise
    print(f"Model {cfg['model']} cached. It will not download again.")


def load_model(cfg):
    from faster_whisper import WhisperModel
    device = cfg["device"]
    if device == "auto":
        device = "cuda"
    print(f"Loading whisper {cfg['model']} on {device} ({cfg['compute_type']})...")
    try:
        m = WhisperModel(cfg["model"], device=device, compute_type=cfg["compute_type"])
    except Exception as e:
        if device == "cuda":
            print(f"CUDA load failed ({e}), falling back to cpu/int8.")
            m = WhisperModel(cfg["model"], device="cpu", compute_type="int8")
        else:
            raise
    # Warmup so first dictation feels instant.
    import numpy as np
    try:
        m.transcribe(np.zeros(16000, dtype=np.float32), language=cfg["language"])
    except Exception:
        pass
    print("Model ready. Hold Ctrl+Win to dictate. Esc cancels a take. Ctrl+C quits.")
    return m


def paste_text(text, cfg):
    import pyperclip
    import time as _t
    try:
        old = pyperclip.paste()
    except Exception:
        old = ""
    try:
        pyperclip.copy(text)
    except Exception as e:
        print(f"Clipboard write failed: {e}")
        return
    if not cfg["auto_paste"]:
        print("Auto-paste off. Text left on clipboard.")
        return
    _t.sleep(float(cfg.get("paste_delay", 0.15)))
    try:
        from pynput.keyboard import Key, Controller
        kb = Controller()
        with kb.pressed(Key.ctrl):
            kb.press("v")
            kb.release("v")
    except Exception as e:
        print(f"Paste keystroke failed, press Ctrl+V manually: {e}")
    # Keep transcript on clipboard so a missed paste is recoverable.
    _ = old


def run_loop(cfg):
    from pynput import keyboard
    rec = Recorder(cfg)
    model = load_model(cfg)
    state = {"ctrl": False, "win": False, "recording": False,
             "cancel": False, "start_t": 0.0}
    lock = threading.Lock()

    def is_hotkey():
        return state["ctrl"] and state["win"]

    def norm(k, is_press):
        name = ""
        try:
            if isinstance(k, keyboard.Key):
                name = k.name.lower() if hasattr(k, "name") else str(k).lower()
            elif hasattr(k, "vk") and k.vk in (91, 92):
                name = "cmd"
        except Exception:
            pass
        s = str(k).lower()
        is_ctrl = name.startswith("ctrl") or "ctrl" in s
        is_win = name.startswith("cmd") or "win" in s or "super" in s or "meta" in s
        with lock:
            if is_ctrl:
                state["ctrl"] = is_press
            if is_win:
                state["win"] = is_press
            if is_press and isinstance(k, keyboard.Key) and k == keyboard.Key.esc:
                if state["recording"]:
                    state["cancel"] = True
            return is_hotkey(), state["recording"]

    def do_transcribe(audio, secs):
        import numpy as np
        peak = float(abs(audio).max()) if len(audio) else 0.0
        if secs < float(cfg["min_seconds"]):
            print("Take too short, discarded.")
            return
        if peak < float(cfg["silence_peak"]):
            print("Near silence, discarded. Check mic. Nothing pasted.")
            beep(220, 200, cfg["beeps"])
            return
        print(f"Transcribing {secs:.1f}s...")
        segs, _ = model.transcribe(audio, language=cfg["language"], beam_size=5,
                                   vad_filter=True)
        raw = "".join(s.text for s in segs).strip()
        if not raw:
            print("Empty transcript, nothing pasted.")
            return
        text = clean_text(raw, cfg.get("remove_fillers", True))
        print(f"> {text}")
        try:
            with open(HISTORY_PATH, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{secs:.1f}s] {text}\n")
        except Exception:
            pass
        paste_text(text, cfg)
        beep(1320, 90, cfg["beeps"])

    def on_press(k):
        hot, recording = norm(k, True)
        with lock:
            if hot and not recording:
                state["recording"] = True
                state["cancel"] = False
                state["start_t"] = time.time()
        if hot and not recording:
            rec.start()
            print("Listening... (release Ctrl+Win to paste, Esc cancels)")
            beep(880, 90, cfg["beeps"])

    def on_release(k):
        _, was_rec = norm(k, False)
        still_hot = state["ctrl"] and state["win"]
        if was_rec and not still_hot:
            with lock:
                state["recording"] = False
                cancelled = state["cancel"]
            audio, secs = rec.stop()
            if cancelled:
                print("Cancelled. Nothing pasted.")
                beep(330, 150, cfg["beeps"])
                return
            if audio is None:
                print("No audio captured.")
                return
            threading.Thread(target=do_transcribe, args=(audio, secs),
                             daemon=True).start()

    print("FreeDictate running. No limits, audio stays on this PC.")
    with keyboard.Listener(on_press=on_press, on_release=on_release) as L:
        L.join()


def main():
    ap = argparse.ArgumentParser(description="FreeDictate local unlimited dictation")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--mic-test", type=int, default=0, metavar="SEC")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--preload", action="store_true")
    ap.add_argument("--model", default=None)
    ap.add_argument("--device", default=None)
    a = ap.parse_args()
    cfg = load_config()
    if a.model:
        cfg["model"] = a.model
    if a.device:
        cfg["device"] = a.device
    if a.list_devices:
        list_devices()
        return
    if a.mic_test:
        mic_test(a.mic_test, cfg["input_device"])
        return
    if a.audit:
        audit(cfg)
        return
    if a.preload:
        preload(cfg)
        return
    run_loop(cfg)


if __name__ == "__main__":
    main()
