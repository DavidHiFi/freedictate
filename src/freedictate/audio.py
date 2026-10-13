"""Microphone capture, device list and feedback sounds."""
from __future__ import annotations

import io
import math
import struct
import threading
import time
import wave
from dataclasses import dataclass

import numpy as np

from . import paths
from .log import log

RATE = 16000


@dataclass(frozen=True)
class Device:
    name: str     # what we store and match on (MME name, which Windows may cut to 31 chars)
    label: str    # full name for display
    default: bool


def _sd():
    import sounddevice as sd
    return sd


def refresh_devices() -> None:
    """PortAudio caches the device list; re-scan so newly plugged mics appear."""
    sd = _sd()
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        log.debug("PortAudio re-scan failed", exc_info=True)


def input_devices() -> list[Device]:
    sd = _sd()
    apis = sd.query_hostapis()
    mme = next((i for i, a in enumerate(apis) if a["name"] == "MME"), None)
    wasapi_names = [d["name"] for d in sd.query_devices()
                    if d["max_input_channels"] > 0 and apis[d["hostapi"]]["name"] == "Windows WASAPI"]
    try:
        default_index = sd.default.device[0]
    except Exception:
        default_index = -1
    out, seen = [], set()
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] <= 0 or d["hostapi"] != mme:
            continue
        name = d["name"]
        if name in seen or name.startswith("Microsoft Sound Mapper"):
            continue
        seen.add(name)
        full = next((w for w in wasapi_names if w.startswith(name.rstrip())), name)
        out.append(Device(name, full, i == default_index))
    return out


def resolve(name: str) -> int | None:
    """Device index for a stored name, or None for the system default."""
    if not name:
        return None
    sd = _sd()
    want = name.lower()
    candidates = [(i, d) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
    for i, d in candidates:
        if d["name"].lower() == want and sd.query_hostapis(d["hostapi"])["name"] == "MME":
            return i
    for i, d in candidates:
        if want in d["name"].lower() and sd.query_hostapis(d["hostapi"])["name"] == "MME":
            return i
    log.warning("Microphone %r not found; using the system default.", name)
    return None


class Recorder:
    """One take at a time. The stream is opened per take so Windows only shows
    the microphone-in-use indicator while you are actually dictating."""

    def __init__(self):
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream = None
        self.level = 0.0          # recent RMS, 0..1
        self.peak = 0.0           # loudest sample in the take
        self.started = 0.0
        self.last_voice = 0.0
        self.voice_threshold = 0.01

    @property
    def active(self) -> bool:
        return self._stream is not None

    def elapsed(self) -> float:
        return time.monotonic() - self.started if self.active else 0.0

    def _callback(self, indata, frames, t, status):
        chunk = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0
        with self._lock:
            self._chunks.append(chunk)
        self.level = rms
        p = float(np.abs(chunk).max()) if len(chunk) else 0.0
        if p > self.peak:
            self.peak = p
        if rms > self.voice_threshold:
            self.last_voice = time.monotonic()

    def start(self, device_name: str) -> None:
        sd = _sd()
        self.stop()
        with self._lock:
            self._chunks = []
        self.level = self.peak = 0.0
        stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                                device=resolve(device_name), callback=self._callback, blocksize=800)
        stream.start()
        self._stream = stream
        self.started = self.last_voice = time.monotonic()

    def stop(self) -> tuple[np.ndarray | None, float]:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.debug("Closing the input stream failed", exc_info=True)
        with self._lock:
            chunks, self._chunks = self._chunks, []
        self.level = 0.0
        if not chunks:
            return None, 0.0
        audio = np.concatenate(chunks)
        return audio, len(audio) / RATE

    def silent_for(self) -> float:
        return time.monotonic() - self.last_voice if self.active else 0.0


class LevelMeter:
    """Short mic test for Settings: opens the device and reports the level."""

    def __init__(self):
        self._stream = None
        self.level = 0.0
        self.peak = 0.0

    def start(self, device_name: str) -> None:
        sd = _sd()
        self.stop()
        self.level = self.peak = 0.0

        def cb(indata, frames, t, status):
            x = indata[:, 0]
            self.level = float(np.sqrt(np.mean(x * x)))
            self.peak = max(self.peak, float(np.abs(x).max()))

        self._stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                                      device=resolve(device_name), callback=cb, blocksize=800)
        self._stream.start()

    def stop(self) -> None:
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                log.debug("Closing the level stream failed", exc_info=True)

    @property
    def running(self) -> bool:
        return self._stream is not None


def decode_file(path: str) -> np.ndarray:
    """Any audio or video file as 16 kHz mono float32. faster-whisper's own
    decode_audio passes an option PyAV 19 removed, so it can't be used."""
    import av
    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=RATE)
    parts = []
    with av.open(path, mode="r") as container:
        for frame in container.decode(audio=0):
            try:
                for out in resampler.resample(frame):
                    parts.append(out.to_ndarray().reshape(-1))
            except av.error.InvalidDataError:
                continue
        for out in resampler.resample(None):
            parts.append(out.to_ndarray().reshape(-1))
    if not parts:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(parts).astype(np.float32) / 32768.0


# ------------------------------------------------------------------ sounds

_SOUNDS = {
    # name: list of (frequency Hz, duration s) notes, played back to back
    "start": [(660, 0.05), (990, 0.07)],
    "stop": [(990, 0.05), (740, 0.07)],
    "cancel": [(520, 0.06), (390, 0.09)],
    "error": [(330, 0.09), (262, 0.14)],
    "done": [(880, 0.04), (1175, 0.04), (1568, 0.09)],
}
# Bump when a tone above changes, so cached WAVs from older versions are not reused.
_SOUND_REV = 2
_sound_files: dict[tuple[str, int], str] = {}


def _render(notes, volume: float) -> bytes:
    sr = 44100
    frames = bytearray()
    for freq, dur in notes:
        n = int(sr * dur)
        attack, release = int(sr * 0.006), int(sr * 0.03)
        for i in range(n):
            env = min(1.0, i / attack) * min(1.0, (n - i) / release)
            # a little second harmonic makes it sound less like a test tone
            s = math.sin(2 * math.pi * freq * i / sr) + 0.18 * math.sin(4 * math.pi * freq * i / sr)
            frames += struct.pack("<h", int(s * env * volume * 0.32 * 32767))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def play(name: str, volume: int) -> None:
    """Fire-and-forget. winsound cannot play from memory asynchronously, so the
    rendered tones are cached as small WAV files."""
    if volume <= 0:
        return
    try:
        import winsound
        key = (name, volume)
        path = _sound_files.get(key)
        if path is None:
            d = paths.LOGS.parent / "sounds"
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"{name}-{volume}-r{_SOUND_REV}.wav"
            if not f.exists():
                f.write_bytes(_render(_SOUNDS[name], volume / 100))
            path = _sound_files[key] = str(f)
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        log.debug("Sound %s failed", name, exc_info=True)
