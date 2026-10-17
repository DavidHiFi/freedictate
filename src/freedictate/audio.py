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


MME_NAME_MAX = 31   # MME (waveIn) device names are cut to 31 characters


def _wavein_endpoints() -> list[tuple[str, str]]:
    """[(MME name, Core Audio endpoint ID)] for every waveIn device, in waveIn
    order. The endpoint ID is the host-API-independent identity of the
    physical input (DRV_QUERYFUNCTIONINSTANCEID). Empty on failure."""
    import ctypes
    from ctypes import wintypes

    class WAVEINCAPSW(ctypes.Structure):
        _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", ctypes.c_uint),
                    ("szPname", ctypes.c_wchar * 32), ("dwFormats", wintypes.DWORD),
                    ("wChannels", wintypes.WORD), ("wReserved1", wintypes.WORD)]

    DRV_QUERYFUNCTIONINSTANCEID = 0x0800 + 17
    DRV_QUERYFUNCTIONINSTANCEIDSIZE = 0x0800 + 18
    try:
        winmm = ctypes.WinDLL("winmm")
        winmm.waveInGetNumDevs.restype = ctypes.c_uint
        winmm.waveInGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.c_void_p, ctypes.c_uint]
        winmm.waveInGetDevCapsW.restype = ctypes.c_uint
        winmm.waveInMessage.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        winmm.waveInMessage.restype = ctypes.c_uint
        out = []
        for i in range(winmm.waveInGetNumDevs()):
            caps = WAVEINCAPSW()
            if winmm.waveInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) != 0:
                return []
            size = ctypes.c_size_t(0)
            if winmm.waveInMessage(ctypes.c_void_p(i), DRV_QUERYFUNCTIONINSTANCEIDSIZE, ctypes.byref(size), None) != 0:
                return []
            buf = ctypes.create_unicode_buffer(size.value // 2 + 1)
            if winmm.waveInMessage(ctypes.c_void_p(i), DRV_QUERYFUNCTIONINSTANCEID, buf,
                                   ctypes.c_void_p(size.value)) != 0:
                return []
            out.append((caps.szPname, buf.value))
        return out
    except Exception:
        log.debug("waveIn endpoint query failed", exc_info=True)
        return []


def _endpoint_names() -> dict[str, str]:
    """{endpoint ID: full friendly name} for capture endpoints. The friendly
    name is what PortAudio's WASAPI host API shows. Empty on failure."""
    try:
        import comtypes
        try:
            comtypes.CoInitialize()
        except OSError:
            pass   # already initialised in another apartment model on this thread
        from pycaw.constants import DEVICE_STATE, EDataFlow
        from pycaw.pycaw import AudioUtilities
        return {d.id: d.FriendlyName for d in
                AudioUtilities.GetAllDevices(EDataFlow.eCapture.value, DEVICE_STATE.ACTIVE.value)
                if d.id and d.FriendlyName}
    except Exception:
        log.debug("Capture endpoint names unavailable", exc_info=True)
        return {}


def _full_name(mme_index: int) -> str | None:
    """Full friendly name of the physical device behind a PortAudio MME input,
    through its endpoint ID; None when Windows can't say."""
    sd = _sd()
    devices = sd.query_devices()
    name = devices[mme_index]["name"]
    mme = devices[mme_index]["hostapi"]
    # The k-th MME device with this name is the k-th waveIn device with it.
    ordinal = sum(1 for i, d in enumerate(devices[:mme_index])
                  if d["hostapi"] == mme and d["name"] == name)
    ids = [eid for pname, eid in _wavein_endpoints() if pname == name]
    if ordinal >= len(ids):
        return None
    return _endpoint_names().get(ids[ordinal])


def _wasapi_native(name: str) -> tuple[int, float, int] | None:
    """(index, native rate, channels) of the WASAPI input that is the same
    physical device as the MME input shared capture would open.

    Exclusive capture must open at the device's own format; shared-mode
    16 kHz opens fail on many interfaces (paInvalidSampleRate). With no
    device configured this follows the MME default, not WASAPI's own
    default, so both modes record the same microphone. When the device
    can't be identified exactly this returns None and the take falls back
    to shared capture rather than open the wrong microphone."""
    sd = _sd()
    apis = sd.query_hostapis()
    wasapi = next((i for i, a in enumerate(apis) if a["name"] == "Windows WASAPI"), None)
    mme = next((i for i, a in enumerate(apis) if a["name"] == "MME"), None)
    if wasapi is None or mme is None:
        return None
    mme_index = resolve(name) if name else apis[mme]["default_input_device"]
    if mme_index is None or mme_index < 0:
        return None
    devices = sd.query_devices()
    mme_name = devices[mme_index]["name"].rstrip()
    inputs = [(i, d) for i, d in enumerate(devices)
              if d["hostapi"] == wasapi and d["max_input_channels"] > 0
              and not d["name"].rstrip().endswith("[Loopback]")]   # an output's loopback, not a mic
    full = _full_name(mme_index)
    if full:
        matches = [(i, d) for i, d in inputs if d["name"].rstrip() == full.rstrip()]
    elif len(devices[mme_index]["name"]) < MME_NAME_MAX:
        matches = [(i, d) for i, d in inputs if d["name"].rstrip() == mme_name]
    else:
        matches = [(i, d) for i, d in inputs if d["name"].startswith(mme_name)]
    if len(matches) != 1:
        log.warning("No unique WASAPI input for microphone %r (%d candidates)", mme_name, len(matches))
        return None
    i, d = matches[0]
    return i, float(d["default_samplerate"]), int(d["max_input_channels"])


class Recorder:
    """One take at a time. The stream is opened per take so Windows only shows
    the microphone-in-use indicator while you are actually dictating."""

    def __init__(self):
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream = None
        self._native_rate = RATE   # device rate while capturing exclusively
        self._resampler = None     # soxr stream: native rate -> 16 kHz, state carried across blocks
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
        self._accept(indata[:, 0].copy())

    def _exclusive_callback(self, indata, frames, t, status):
        """Native-format blocks arrive at the device rate; reduce to 16 kHz mono
        here so the recogniser pipeline never sees the difference. One
        streaming resampler carries its filter state across blocks: it
        low-pass filters before decimating (no aliasing) and loses no samples
        at block edges (no drift)."""
        x = indata.mean(axis=1) if indata.shape[1] > 1 else indata[:, 0]
        rs = self._resampler
        if rs is None:
            self._accept(np.ascontiguousarray(x, dtype=np.float32))
            return
        chunk = rs.resample_chunk(np.ascontiguousarray(x, dtype=np.float32))
        if len(chunk):
            self._accept(chunk)

    def _flush_resampler(self) -> None:
        rs, self._resampler = self._resampler, None
        if rs is not None:
            try:
                tail = rs.resample_chunk(np.zeros(0, dtype=np.float32), last=True)
            except Exception:
                log.debug("Resampler flush failed", exc_info=True)
                return
            if len(tail):
                with self._lock:
                    self._chunks.append(tail)

    def _accept(self, chunk: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0
        with self._lock:
            self._chunks.append(chunk)
        self.level = rms
        p = float(np.abs(chunk).max()) if len(chunk) else 0.0
        if p > self.peak:
            self.peak = p
        if rms > self.voice_threshold:
            self.last_voice = time.monotonic()

    def start(self, device_name: str, exclusive: bool = False) -> None:
        sd = _sd()
        self.stop()
        with self._lock:
            self._chunks = []
        self.level = self.peak = 0.0
        if exclusive:
            native = _wasapi_native(device_name)
            if native is None:
                raise RuntimeError("No WASAPI input matches the configured microphone")
            index, rate, channels = native
            if channels < 1:
                channels = 1
            self._native_rate = rate
            self._resampler = None
            if int(round(rate)) != RATE:
                import soxr
                self._resampler = soxr.ResampleStream(rate, RATE, 1, dtype="float32", quality="HQ")
            try:
                wasapi = sd.WasapiSettings(exclusive=True)
            except Exception:
                wasapi = None
            if wasapi is None:
                raise RuntimeError("WASAPI exclusive capture is unavailable")
            stream = sd.InputStream(samplerate=rate, channels=channels, dtype="float32",
                                    device=index, callback=self._exclusive_callback,
                                    blocksize=800, extra_settings=wasapi)
        else:
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
        self._flush_resampler()   # the callback has stopped; emit the filter's tail
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
