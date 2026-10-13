"""The dictation engine: hotkey, recording, model management, transcription, delivery.

Qt-free. It reports through ``emit(event, payload)``; the app forwards events
to the GUI thread. Threads:

  hotkey poller   reads the keyboard every 10 ms and drives recording
  transcriber     decodes takes one at a time from a queue
  model loader    downloads and loads models off the other two threads
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from . import audio, hotkeys, models, output, textproc, tidy
from .config import Config
from .history import History
from .log import log

# Whisper's favourite inventions on near-silent input.
_PHANTOMS = {"thank you.", "thanks for watching!", "thank you for watching.", "you", "you.", "bye.", "."}
TAP_SECONDS = 0.35  # "both" mode: a press shorter than this starts a toggle take


@dataclass
class ModelState:
    active: str = ""              # model in use
    device: str = ""              # cpu | cuda
    compute: str = ""
    wanted: str = ""              # model the settings ask for
    status: str = "idle"          # idle | downloading | loading | failed
    progress: tuple[int, int] = (0, 0)
    error: str = ""


@dataclass
class Take:
    audio: Any
    seconds: float
    app: str = ""
    file: str = ""                # set when transcribing a file instead of a take
    on_text: Callable[[str], None] | None = field(default=None, repr=False)


class Engine:
    def __init__(self, cfg: Config, history: History, emit: Callable[[str, dict], None]):
        self.cfg = cfg
        self.history = history
        self.emit = emit
        self.recorder = audio.Recorder()
        self.state = "loading"     # loading | ready | listening | transcribing | error
        self.paused = False
        self.model = None
        self.ms = ModelState()
        self._jobs: queue.Queue[Take | None] = queue.Queue()
        self._stop = threading.Event()
        self._load_lock = threading.Lock()     # guards the actual model load
        self._serial_lock = threading.Lock()   # guards the serial/cancel swap only
        self._load_serial = 0
        self._download_cancel = threading.Event()
        self._matcher = hotkeys.Matcher(cfg["hotkey"]) if hotkeys.is_valid(cfg["hotkey"]) else hotkeys.Matcher("ctrl+win")
        self._take_app = ""
        self.suspended = False     # True while Settings records a new hotkey
        self._tidy_warned = False  # "Ollama isn't running" is said once per session
        cfg.on_change(self._config_changed)

    # ---------------------------------------------------------------- state
    def _set_state(self, s: str) -> None:
        if s != self.state:
            self.state = s
            self.emit("state", {"state": s})

    def status_text(self) -> str:
        hk = hotkeys.label(self.cfg["hotkey"])
        if self.paused:
            return "Paused"
        ms = self.ms
        if self.state == "loading":
            if ms.status == "downloading":
                done, total = ms.progress
                pct = f" {done * 100 // total}%" if total else ""
                return f"Downloading {_title(ms.wanted)}{pct}"
            return "Getting the speech model ready"
        if self.state == "error":
            return "Not working. Open Settings for details"
        if self.state == "listening":
            return "Listening"
        if self.state == "transcribing":
            return "Transcribing"
        if ms.status == "downloading" and ms.wanted != ms.active:
            done, total = ms.progress
            pct = f" ({done * 100 // total}%)" if total else ""
            return f"Ready. Downloading {_title(ms.wanted)}{pct}"
        mode = self.cfg["hotkey_mode"]
        verb = {"hold": "Hold", "toggle": "Press", "both": "Hold or tap"}[mode]
        return f"Ready. {verb} {hk} to dictate"

    # -------------------------------------------------------------- startup
    def start(self) -> None:
        self._transcriber = threading.Thread(target=self._transcribe_loop, daemon=True, name="transcriber")
        self._transcriber.start()
        threading.Thread(target=self._poll_loop, daemon=True, name="hotkey").start()
        self.ensure_model()
        if self.cfg["ai_tidy"]:
            self.prepare_tidy()

    def prepare_tidy(self) -> None:
        """Start Ollama and load the tidy-up model in the background, so the
        first take doesn't wait for it."""
        model = self.cfg["ai_model"]

        def work():
            if tidy.start() and tidy.has_model(model):
                tidy.warm(model)
        threading.Thread(target=work, daemon=True, name="tidy-warm").start()

    def shutdown(self) -> None:
        self._stop.set()
        self._download_cancel.set()
        self.recorder.stop()
        self._jobs.put(None)
        t = getattr(self, "_transcriber", None)
        if t is not None and t is not threading.current_thread() and t.is_alive():
            # Let a take in flight finish writing history before App.quit() closes the db.
            t.join(timeout=2.0)

    def _config_changed(self, keys: set[str]) -> None:
        if "hotkey" in keys and hotkeys.is_valid(self.cfg["hotkey"]):
            self._matcher = hotkeys.Matcher(self.cfg["hotkey"])
        if keys & {"model", "device", "compute_type", "cpu_threads"}:
            self.ensure_model(force="model" not in keys)
        if keys & {"hotkey", "hotkey_mode", "model"}:
            self.emit("state", {"state": self.state})
        if keys & {"ai_tidy", "ai_model"} and self.cfg["ai_tidy"]:
            self._tidy_warned = False
            self.prepare_tidy()

    # --------------------------------------------------------------- models
    def ensure_model(self, force: bool = False) -> None:
        """Make the configured model the active one. The current model keeps
        working until its replacement is ready, so dictation never goes dark."""
        want = self.cfg["model"]
        if not force and want == self.ms.active and self.model is not None:
            return
        with self._serial_lock:   # the GPU download worker can call this concurrently
            self._load_serial += 1
            serial = self._load_serial
            self._download_cancel.set()          # stop a download for a model no longer wanted
            self._download_cancel = threading.Event()
            cancel = self._download_cancel
        self.ms.wanted = want
        threading.Thread(target=self._load_worker, args=(want, serial, cancel), daemon=True,
                         name="model-loader").start()

    def _load_worker(self, want: str, serial: int, cancel: threading.Event) -> None:
        cfg = self.cfg
        try:
            if not models.is_downloaded(want):
                if self.model is None:
                    self._load_fallback(want, serial)
                self.ms.status = "downloading"
                self.ms.progress = (0, models.BY_NAME[want].size_mb * 1_000_000 if want in models.BY_NAME else 0)
                self.emit("model", {})

                def progress(done, total):
                    if serial == self._load_serial:
                        self.ms.progress = (done, total)
                        self.emit("download", {"done": done, "total": total, "name": want})

                models.download(want, progress, cancel)
                if serial != self._load_serial:
                    return
            self.ms.status = "loading"
            self.emit("model", {})
            with self._load_lock:
                if serial != self._load_serial:
                    return
                m, dev, ct = models.load(want, cfg["device"], cfg["compute_type"], cfg["cpu_threads"])
            if serial != self._load_serial:
                return
            switched = self.model is not None and self.ms.active and self.ms.active != want
            self.model = m
            self.ms.active, self.ms.device, self.ms.compute = want, dev, ct
            self.ms.status, self.ms.error = "idle", ""
            log.info("Ready with %s on %s (%s)", want, dev, ct)
            if self.state in ("loading", "error"):
                self._set_state("ready")
            self.emit("model", {"ready": True})
            if switched:
                self.emit("notice", {"title": "Model ready", "text": f"Now using {_title(want)}."})
        except InterruptedError:
            log.info("Download of %s cancelled", want)
        except Exception as e:
            if serial != self._load_serial:
                return
            log.error("Model %s failed:\n%s", want, traceback.format_exc())
            self.ms.status, self.ms.error = "failed", _short(e)
            if self.model is None:
                self._set_state("error")
            self.emit("model", {})
            self.emit("error", {"title": f"Couldn't get {_title(want)} ready", "text": _short(e)})

    def _load_fallback(self, want: str, serial: int) -> None:
        """Dictate with an already-downloaded model while the chosen one downloads."""
        for name in models.FALLBACK_ORDER:
            if name == want or not models.is_downloaded(name):
                continue
            try:
                m, dev, ct = models.load(name, self.cfg["device"], self.cfg["compute_type"], self.cfg["cpu_threads"])
            except Exception:
                log.exception("Fallback model %s failed", name)
                continue
            if serial != self._load_serial:
                return
            self.model = m
            self.ms.active, self.ms.device, self.ms.compute = name, dev, ct
            log.info("Using %s until %s finishes downloading", name, want)
            self._set_state("ready")
            return

    def cancel_download(self) -> None:
        self._download_cancel.set()
        if self.ms.status == "downloading":
            self.ms.status = "idle"
            if self.ms.active:
                self.ms.wanted = self.ms.active
            else:
                # Nothing active to fall back to (first run): an empty wanted
                # would leave the "getting ready" state up forever. Show the
                # retryable error instead.
                self.ms.wanted = self.cfg["model"]
                self.ms.error = "Download cancelled. Pick a model and press Download to try again."
                self._set_state("error")
            self.emit("model", {})

    # ---------------------------------------------------------------- input
    def _usable(self) -> bool:
        return self.model is not None and not self.paused and not self.suspended

    def _poll_loop(self) -> None:
        recording = False
        tap_toggle = False           # current take is latched (toggle, or a tap in "both")
        pressed_at = 0.0
        hot_was = esc_was = False
        cancel = False
        while not self._stop.is_set():
            try:
                hot = self._matcher.held()
                esc = hotkeys.key_down(hotkeys.VK_ESCAPE)
                mode = self.cfg["hotkey_mode"]
                now = time.monotonic()
                press = hot and not hot_was
                release = hot_was and not hot

                if not recording:
                    if press and self._usable():
                        if self._begin():
                            recording, cancel, pressed_at = True, False, now
                            tap_toggle = mode == "toggle"
                else:
                    if (esc and not esc_was) or self.paused:
                        cancel = True
                    stop = cancel
                    if mode == "hold" or (mode == "both" and not tap_toggle):
                        if release:
                            if mode == "both" and now - pressed_at < TAP_SECONDS:
                                tap_toggle = True      # quick tap: keep listening until the next press
                            else:
                                stop = True
                    elif press:
                        stop = True
                    if self.recorder.elapsed() >= self.cfg["max_seconds"]:
                        stop = True
                    silence = self.cfg["auto_stop_silence"]
                    if tap_toggle and silence and self.recorder.elapsed() > 1.5 \
                            and self.recorder.silent_for() >= silence:
                        stop = True
                    if stop:
                        recording = False
                        self._end(cancel)
                hot_was, esc_was = hot, esc
            except Exception:
                log.exception("Hotkey loop error")
                time.sleep(0.5)
            time.sleep(0.01)

    def _begin(self) -> bool:
        try:
            self._take_app = output.foreground_process()[1]
            self.recorder.voice_threshold = max(0.004, float(self.cfg["silence_peak"]) * 2)
            self.recorder.start(self.cfg["input_device"])
        except Exception as e:
            log.exception("Microphone failed to open")
            self.emit("error", {"title": "Couldn't open the microphone", "text": _short(e)})
            audio.play("error", self.cfg["sound_volume"] if self.cfg["sounds"] else 0)
            return False
        self._set_state("listening")
        audio.play("start", self.cfg["sound_volume"] if self.cfg["sounds"] else 0)
        return True

    def _end(self, cancelled: bool) -> None:
        data, secs = self.recorder.stop()
        vol = self.cfg["sound_volume"] if self.cfg["sounds"] else 0
        if cancelled:
            self._set_state("ready")
            audio.play("cancel", vol)
            self.emit("cancelled", {})
            return
        audio.play("stop", vol)
        if data is None or secs < float(self.cfg["min_seconds"]):
            self._set_state("ready")
            return
        self._set_state("transcribing")
        self._jobs.put(Take(data, secs, self._take_app))

    def toggle_pause(self) -> bool:
        self.paused = not self.paused  # the hotkey loop cancels a take in progress
        log.info("Paused" if self.paused else "Resumed")
        self.emit("state", {"state": self.state})
        return self.paused

    def transcribe_file(self, path: str, on_text: Callable[[str], None]) -> None:
        self._jobs.put(Take(None, 0.0, "", file=path, on_text=on_text))

    # --------------------------------------------------------- transcription
    def _transcribe_loop(self) -> None:
        while True:
            take = self._jobs.get()
            if take is None:
                return
            try:
                if take.file:
                    self._do_file(take)
                else:
                    self._do_take(take)
            except Exception as e:
                log.error("Transcription failed:\n%s", traceback.format_exc())
                self.emit("error", {"title": "Transcription failed", "text": _short(e)})
            finally:
                if self.state == "transcribing" and self._jobs.empty():
                    self._set_state("ready" if self.model is not None else "error")

    def _decode(self, data) -> str:
        cfg = self.cfg
        lang = cfg["language"]
        info = models.BY_NAME.get(self.ms.active)
        if info and info.english_only:
            lang = "en"
        segments, _ = self.model.transcribe(
            data, language=None if lang == "auto" else lang, beam_size=int(cfg["beam_size"]),
            vad_filter=bool(cfg["vad"]), initial_prompt=cfg["vocabulary"].strip() or None,
            condition_on_previous_text=False)
        return "".join(s.text for s in segments).strip()

    def _clean(self, raw: str) -> str:
        c = self.cfg
        return textproc.clean(raw, remove_fillers=c["remove_fillers"], voice_commands=c["voice_commands"],
                              capitalize=c["capitalize"], end_punctuation=c["end_punctuation"],
                              repeats=c["remove_repeats"], replacements=c["replacements"])

    def _do_take(self, take: Take) -> None:
        cfg = self.cfg
        vol = cfg["sound_volume"] if cfg["sounds"] else 0
        peak = float(abs(take.audio).max()) if len(take.audio) else 0.0
        if peak < float(cfg["silence_peak"]):
            log.info("Near silence (peak %.4f); nothing pasted", peak)
            self.emit("nothing", {"reason": "silence"})
            audio.play("error", vol)
            return
        t0 = time.monotonic()
        raw = self._decode(take.audio)
        took = time.monotonic() - t0
        if not raw or (raw.lower() in _PHANTOMS and peak < 0.05):
            log.info("Nothing recognised in %.1fs of audio", take.seconds)
            self.emit("nothing", {"reason": "empty"})
            return
        text = self._clean(raw)
        if not text:
            self.emit("nothing", {"reason": "empty"})
            return
        log.info("Transcribed %.1fs in %.2fs: %d chars", take.seconds, took, len(text))
        before_tidy = ""
        tidied = self._tidy(text)
        if tidied:
            before_tidy, text = text, tidied
            took = time.monotonic() - t0
        if cfg["history_enabled"]:
            try:
                self.history.add(text, take.seconds, self.ms.active, take.app, raw=before_tidy)
            except Exception:
                log.exception("History write failed")
        delivered = text + (" " if cfg["trailing_space"] and cfg["output"] != "clipboard" and not text.endswith("\n") else "")
        outcome = output.deliver(delivered, cfg["output"], cfg["restore_clipboard"], int(cfg["paste_delay_ms"]))
        self.emit("result", {"text": text, "outcome": outcome, "seconds": take.seconds, "took": took})
        if outcome != "blocked":
            audio.play("done", vol)
        if outcome == "blocked":
            self.emit("error", {"title": "That window runs as administrator",
                                "text": "Windows blocks pasting into it. The text is on your clipboard. "
                                        "Turn on Run as administrator in Settings to paste there."})

    def _tidy(self, text: str) -> str | None:
        cfg = self.cfg
        if not cfg["ai_tidy"]:
            return None
        if not tidy.running() and not tidy.start(wait=8):
            if not self._tidy_warned:
                self._tidy_warned = True
                self.emit("error", {"title": "AI tidy-up is off for now",
                                    "text": "Ollama isn't running or isn't installed, so the plain "
                                            "transcript was pasted. See Text and pasting in Settings."})
            return None
        out = tidy.rewrite(text, cfg["ai_model"], cfg["vocabulary"])
        return textproc.apply_replacements(out, cfg["replacements"]) if out else None

    def _do_file(self, take: Take) -> None:
        self.emit("file", {"status": "working", "path": take.file})
        try:
            data = audio.decode_file(take.file)
            text = self._clean(self._decode(data))
        except Exception as e:
            # The caller waits for on_text either way, or its banner never clears.
            log.exception("Transcribing %s failed", take.file)
            text = f"error: {e}"
        if take.on_text:
            take.on_text(text)


def _title(name: str) -> str:
    info = models.BY_NAME.get(name)
    return info.title if info else name


def _short(e: BaseException) -> str:
    s = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return s[:240]
