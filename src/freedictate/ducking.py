"""Output isolation and microphone privacy while dictating.

While a take runs, every render-endpoint audio session except our own is
muted (or turned down to a fixed percent), and with mic privacy every other
app's capture session is muted, on every audio device. Both are restored
exactly when the take ends.

All Windows Core Audio work happens on one worker thread so every session
control is created and used inside the same COM apartment. The worker also
re-scans by itself while a take runs, a short pause after each scan ends, so
sessions that appear mid-take are caught and scans can never queue up in
front of the restore. They used to: the hotkey loop queued a scan every
250 ms, a scan took up to 185 ms, and long takes ended with 8 s restore
timeouts that left other apps muted (2026-10-24).

Crash safety: the pre-take snapshot is written to ``audio-restore.json`` (and
``mic-privacy-restore.json``) in the app data folder before anything is
changed, and removed only after a successful restore. If the app dies
mid-take, the next start re-applies the restore from those files. A restore
that fails while the app runs is retried on the worker every second.

Mic privacy works at three levels. Each foreign capture session is muted.
Every other recording device that an app is reading is then held open in
exclusive mode, which cuts its readers off at the driver; a device that
refuses the hold gets the endpoint mute Windows itself uses instead. Mutes
alone are not enough: VB-Audio Matrix's VAIO devices ignore both the session
and the endpoint mute, and a Discord call kept hearing the user through them
(measured 2026-10-24). Readers reopen the device on their own once the hold
ends; Discord takes about half a second. The device the take records from is
never touched, nor is a device an audio router (Voicemeeter, VB-Audio
Matrix, ...) is reading, since that router may be what feeds our input.

Restore is keyed per session by its instance identifier: a process can own
several sessions (Flow.Launcher held two) and can open a new one mid-take,
so a per-pid record would leave the extras muted. The endpoint master volume
is never touched.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections import deque

from . import paths
from .log import log

RECORD = paths.DATA / "audio-restore.json"
MIC_RECORD = paths.DATA / "mic-privacy-restore.json"
# Apps and devices FreeDictate muted and has not yet seen unmuted again. A
# mute on this list is never taken for the user's own: Windows keeps an app's
# session mute for its next launch, and a mute read as "already there" at the
# start of a take used to be put back after it, so one stuck mute stuck for good.
OWED = paths.DATA / "mic-privacy-owed.json"
_OWED_INTERVAL = 2.0      # pause between checks for an owed app that is not running
_RESCAN_INTERVAL = 0.25   # pause between the end of one mid-take scan and the next
_RETRY_INTERVAL = 1.0     # pause between retries of a restore that failed
_MAX_RETRIES = 30         # then the record files wait for the next start
_MIDTAKE_REV = 3          # record format: sessions carry their key
_DEVICE_STATE_ACTIVE = 1
_RENDER, _CAPTURE = 0, 1  # EDataFlow
# Processes that read a microphone to feed a virtual one. A device they read
# keeps its endpoint mute off: our own input may come through them.
_ROUTERS = ("voicemeeter", "vbaudiomatrix", "vbcable", "nvidia broadcast", "sonar",
            "wavelink", "krisp", "equalizerapo", "audiorelay")

_worker: _Worker | None = None
_worker_lock = threading.Lock()
_capture_failure = threading.Event()
_local = threading.local()


def _get_worker() -> _Worker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = _Worker()
        return _worker


class _Worker:
    """Runs every COM call on one thread. Created lazily on first use."""

    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        self._t = threading.Thread(target=self._run, daemon=True, name="audio-ducking")
        self._t.start()

    def _run(self) -> None:
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            log.debug("COM init failed for the ducking thread", exc_info=True)
        state = _State()
        while True:
            wait = None
            if state.busy():
                wait = max(0.0, state.tick_at - time.monotonic())
            try:
                fn = self._q.get(timeout=wait)
            except queue.Empty:
                fn = _tick   # queued work always goes first; upkeep runs when the queue is idle
            if fn is None:
                return
            try:
                fn(state)
            except Exception:
                log.debug("Ducking operation failed", exc_info=True)

    def post(self, fn) -> None:
        """Fire-and-forget. fn receives the thread's _State."""
        self._q.put(fn)

    def call(self, fn, timeout: float = 8.0):
        """Run fn(state) synchronously; returns (ok, result-or-exception)."""
        done = threading.Event()
        box: list = []

        def wrap(state) -> None:
            try:
                box.append((True, fn(state)))
            except Exception as e:      # noqa: BLE001 - reported to the caller
                box.append((False, e))
            finally:
                done.set()

        self._q.put(wrap)
        if not done.wait(timeout):
            return False, TimeoutError("audio-ducking thread did not answer")
        return box[0] if box else (False, RuntimeError("no result"))


class _State:
    """Lives on the worker thread. Holds live session controls."""

    def __init__(self):
        self.active = False
        self.level = 0                       # 0 = mute, 1-100 = volume percent
        # session key -> (pid, original volume, original mute, control); an
        # entry stays until its restore succeeded or its app is gone
        self.ducked: dict[str, tuple[int, float, bool, object]] = {}
        self.capture_active = False
        self.capture_muted: dict[str, tuple[int, float, bool, object]] = {}
        # endpoint id -> IAudioEndpointVolume we muted (it was unmuted before)
        self.endpoints_muted: dict[str, object] = {}
        # endpoint id -> running exclusive IAudioClient; dropping it lets go
        self.held: dict[str, object] = {}
        self.hold_refused: set[str] = set()          # not retried until the next take
        self.own_endpoint: str | None = None
        self.endpoint_before: dict[str, bool] = {}   # device mute when the take began
        self.endpoint_layer = True
        self.owed_apps, self.owed_endpoints = _load_owed()
        self.tick_at = 0.0
        self.retries = 0

    def busy(self) -> bool:
        """A take is running, or a restore still owes sessions."""
        return (self.active or self.capture_active or bool(self.ducked) or bool(self.capture_muted)
                or bool(self.endpoints_muted) or bool(self.held) or bool(self.owed_apps))


# ------------------------------------------------------------------ helpers

def available() -> bool:
    try:
        import pycaw  # noqa: F401
        import comtypes  # noqa: F401
        return True
    except ImportError:
        return False


def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        return True


def _app_of(pid: int) -> str | None:
    try:
        import psutil
        return psutil.Process(pid).name().lower()
    except Exception:
        return None


def _load_owed() -> tuple[set[str], set[str]]:
    try:
        rec = json.loads(OWED.read_text(encoding="utf-8"))
        return set(rec.get("apps", [])), set(rec.get("endpoints", []))
    except (OSError, ValueError, AttributeError):
        return set(), set()


def _save_owed(state: "_State") -> None:
    try:
        if not (state.owed_apps or state.owed_endpoints):
            OWED.unlink(missing_ok=True)
            return
        paths.DATA.mkdir(parents=True, exist_ok=True)
        tmp = OWED.with_suffix(f".json.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"apps": sorted(state.owed_apps),
                                   "endpoints": sorted(state.owed_endpoints)}), encoding="utf-8")
        os.replace(tmp, OWED)
    except OSError:
        log.warning("Could not write %s", OWED, exc_info=True)


def _settle_owed(state: "_State") -> None:
    """Unmute what FreeDictate muted and still finds muted: devices, and every
    session of an owed app, including one that restarted with the mute Windows
    kept for it. An app that isn't running stays owed until it comes back."""
    if not (state.owed_apps or state.owed_endpoints):
        return
    before = (set(state.owed_apps), set(state.owed_endpoints))
    present = set()
    for device_id, control, _readers in _enumerate_capture_endpoints():
        present.add(device_id)
        if device_id in state.owed_endpoints:
            try:
                if bool(control.GetMute()):
                    control.SetMute(False, None)
                state.owed_endpoints.discard(device_id)
            except Exception:
                log.debug("Could not unmute owed device %s", device_id, exc_info=True)
    state.owed_endpoints &= present     # an unplugged device owes nothing
    if state.owed_apps:
        seen = set()
        try:
            live = _enumerate_capture()
        except Exception:
            live = []                  # unreadable now: still owed, next check retries
        for _key, pid, _volume, muted, control in live:
            app = _app_of(pid) if pid != os.getpid() else None
            if app not in state.owed_apps:
                continue
            try:
                if muted:
                    control.SetMute(False, None)
                    log.info("Microphone privacy: unmuted %s, left muted after a take", app)
                seen.add(app)
            except Exception:
                log.debug("Could not unmute owed app %s", app, exc_info=True)
        state.owed_apps -= seen
    if before != (state.owed_apps, state.owed_endpoints):
        _save_owed(state)


def _session_key(control, pid: int, ordinal: int) -> str:
    """Stable identity of one audio session across re-enumerations. The
    instance identifier is unique per session and carries the pid; the pid
    plus its enumeration ordinal is the fallback when it can't be read."""
    try:
        ident = control.GetSessionInstanceIdentifier()
        if ident:
            return str(ident)
    except Exception:
        pass
    return f"pid:{pid}#{ordinal}"


def _device_enumerator():
    """One IMMDeviceEnumerator per thread (COM objects stay in their apartment)."""
    e = getattr(_local, "enumerator", None)
    if e is None:
        import comtypes
        from pycaw.constants import CLSID_MMDeviceEnumerator
        from pycaw.pycaw import IMMDeviceEnumerator
        e = _local.enumerator = comtypes.CoCreateInstance(
            CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)
    return e


def _sessions(flow: int, strict: bool):
    """[(key, pid, volume, muted, ISimpleAudioVolume)] for every session on
    every active endpoint of one direction. Reads only ids, pids and volumes:
    pycaw's device list also reads every property of every device, which made
    one scan about ten times slower (measured: 120-185 ms against 10-14 ms).
    With ``strict`` an unreadable endpoint or session raises instead of being
    skipped. Runs on the worker thread."""
    import comtypes
    from pycaw.pycaw import IAudioSessionControl2, IAudioSessionManager2, ISimpleAudioVolume

    out = []
    devices = _device_enumerator().EnumAudioEndpoints(flow, _DEVICE_STATE_ACTIVE)
    for i in range(devices.GetCount()):
        try:
            device = devices.Item(i)
            device_id = device.GetId()
            sessions = device.Activate(IAudioSessionManager2._iid_, comtypes.CLSCTX_INPROC_SERVER, None) \
                .QueryInterface(IAudioSessionManager2).GetSessionEnumerator()
        except Exception:
            if strict:
                raise
            log.debug("No session manager on audio endpoint %s; skipping", i, exc_info=True)
            continue
        per_pid: dict[int, int] = {}
        for index in range(sessions.GetCount()):
            try:
                control = sessions.GetSession(index).QueryInterface(IAudioSessionControl2)
                pid = int(control.GetProcessId())
                volume = control.QueryInterface(ISimpleAudioVolume)
                n = per_pid[pid] = per_pid.get(pid, -1) + 1
                out.append((f"{device_id}|{_session_key(control, pid, n)}", pid,
                            float(volume.GetMasterVolume()), bool(volume.GetMute()), volume))
            except Exception:
                if strict:
                    raise
                log.debug("Session %s unreadable on %s; skipping", index, device_id, exc_info=True)
    return out


def _enumerate():
    """Every session on every playback device. GetAllSessions() only sees the
    default device, which misses audio playing through headsets and virtual
    cables."""
    return _sessions(_RENDER, strict=False)


def _enumerate_capture():
    """Every app session on every recording device. Any read failure is fatal:
    privacy must not claim success partially."""
    return [s for s in _sessions(_CAPTURE, strict=True) if s[1] > 0]


def _enumerate_capture_endpoints():
    """[(endpoint id, IAudioEndpointVolume, {lower-case process names reading
    it})] for every active recording device. Runs on the worker thread."""
    import comtypes
    import psutil
    from pycaw.pycaw import IAudioEndpointVolume

    readers: dict[str, set[str]] = {}
    mine = os.getpid()
    for key, pid, _volume, _muted, _control in _sessions(_CAPTURE, strict=False):
        if pid in (0, mine):
            continue           # Windows' own session, or our take and holds
        try:
            name = psutil.Process(pid).name().lower()
        except Exception:
            continue
        readers.setdefault(key.split("|", 1)[0], set()).add(name)
    out = []
    devices = _device_enumerator().EnumAudioEndpoints(_CAPTURE, _DEVICE_STATE_ACTIVE)
    for i in range(devices.GetCount()):
        try:
            device = devices.Item(i)
            device_id = device.GetId()
            control = device.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_INPROC_SERVER, None) \
                .QueryInterface(IAudioEndpointVolume)
        except Exception:
            log.debug("No endpoint volume on recording device %s; skipping", i, exc_info=True)
            continue
        out.append((device_id, control, readers.get(device_id, set())))
    return out


_AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED = -2004287463   # 0x88890019


def _exclusive_formats(mix):
    """Formats to try for an exclusive open: the device's own mix format, then
    integer PCM at its rate and channel count and the common fallbacks, each
    as an extensible header (VB-Audio's drivers refuse the plain one)."""
    import ctypes
    from ctypes.wintypes import DWORD, WORD
    from comtypes import GUID
    from pycaw.api.audioclient.depend import WAVEFORMATEX

    # Packed like mmreg.h; pycaw's WAVEFORMATEX is padded to 20 bytes, which
    # shifts every extensible field and gets each format refused.
    class WAVEFORMATEXTENSIBLE(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("wFormatTag", WORD), ("nChannels", WORD), ("nSamplesPerSec", DWORD),
                    ("nAvgBytesPerSec", DWORD), ("nBlockAlign", WORD), ("wBitsPerSample", WORD),
                    ("cbSize", WORD), ("wValidBitsPerSample", WORD),
                    ("dwChannelMask", DWORD), ("SubFormat", GUID)]

    pcm = GUID("{00000001-0000-0010-8000-00AA00389B71}")
    yield mix
    for rate in dict.fromkeys((mix.contents.nSamplesPerSec, 48000, 44100)):
        for channels in dict.fromkeys((mix.contents.nChannels, 2, 1)):
            for bits in (16, 24, 32):
                block = channels * bits // 8
                f = WAVEFORMATEXTENSIBLE(0xFFFE, channels, rate, rate * block, block, bits, 22,
                                         bits, 0x3 if channels == 2 else 0x4, pcm)
                yield ctypes.cast(ctypes.pointer(f), ctypes.POINTER(WAVEFORMATEX)), f


def _hold_exclusive(device_id: str):
    """Open one recording device in exclusive mode and start it. Windows then
    cuts off every app reading it and refuses new readers until we let go;
    Discord reopens its mic about half a second after (measured 2026-10-24).
    Returns the running IAudioClient. Raises when no format is accepted or
    the device doesn't allow exclusive use."""
    import ctypes
    import comtypes
    from pycaw.pycaw import IAudioClient

    device = _device_enumerator().GetDevice(device_id)

    def client():
        return device.Activate(IAudioClient._iid_, comtypes.CLSCTX_INPROC_SERVER, None) \
            .QueryInterface(IAudioClient)

    probe = client()
    period, _minimum = probe.GetDevicePeriod()
    # Only the text of a refusal is kept: a stored exception's traceback holds
    # this frame, and with it the running client, so the device stayed held
    # after release until the garbage collector ran (measured 2026-10-24).
    last = ""
    for fmt in _exclusive_formats(probe.GetMixFormat()):
        pointer = fmt[0] if isinstance(fmt, tuple) else fmt   # the tuple keeps its struct alive
        c = client()
        try:
            c.Initialize(1, 0, period, period, pointer, None)
        except comtypes.COMError as e:
            last = str(e)
            if e.hresult != _AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED:
                continue
            frames = c.GetBufferSize()
            aligned = round(10_000_000 * frames / pointer.contents.nSamplesPerSec)
            c = client()
            try:
                c.Initialize(1, 0, aligned, aligned, pointer, None)
            except comtypes.COMError as e2:
                last = str(e2)
                continue
        c.Start()
        return c
    raise RuntimeError(f"no exclusive format accepted ({last})")


def _apply_duck(v, level: int, original: float, volume: float, muted: bool) -> None:
    """Put one session at the duck level, never louder than it was. Skipped
    when it's already there, so apps aren't sent a volume-change notice on
    every re-scan. pycaw 20260927 exposes the raw ISimpleAudioVolume: both
    setters take an LPCGUID EventContext we do not need."""
    if level <= 0:
        if not muted:
            v.SetMute(True, None)
        return
    target = min(original, level / 100.0)
    if abs(volume - target) > 0.001:
        v.SetMasterVolume(target, None)


def _restore_one(v, volume: float, muted: bool) -> bool:
    try:
        v.SetMasterVolume(volume, None)
        v.SetMute(muted, None)
        return abs(float(v.GetMasterVolume()) - volume) <= 0.001 and bool(v.GetMute()) == muted
    except Exception:
        log.debug("Session restore failed", exc_info=True)
        return False


def _write_record(state: _State) -> None:
    """Persist the original values of everything currently ducked."""
    sessions = [{"key": key, "pid": pid, "volume": volume, "muted": muted}
                for key, (pid, volume, muted, _v) in state.ducked.items()]
    rec = {"version": _MIDTAKE_REV, "saved": time.time(), "sessions": sessions}
    try:
        paths.DATA.mkdir(parents=True, exist_ok=True)
        tmp = RECORD.with_suffix(f".json.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
        os.replace(tmp, RECORD)
    except OSError:
        log.exception("Could not write the audio restore record to %s", RECORD)


# ------------------------------------------------------------- worker ops

def _duck_sessions(state: _State) -> None:
    """Record sessions that are new to this take, then put every foreign
    session at the duck level. The record is written before anything changes."""
    mine = os.getpid()
    live = [s for s in _enumerate() if s[1] != mine]
    new = False
    for key, pid, volume, muted, v in live:
        if key not in state.ducked:
            state.ducked[key] = (pid, volume, muted, v)
            new = True
    if new:
        _write_record(state)
    for key, _pid, volume, muted, v in live:
        try:
            _apply_duck(v, state.level, state.ducked[key][1], volume, muted)
        except Exception:
            log.debug("Ducking a session failed", exc_info=True)


def _restore_output(state: _State) -> bool:
    """Put every ducked session back. True when nothing is left owed."""
    restored = 0
    for key, (pid, volume, muted, v) in list(state.ducked.items()):
        if _restore_one(v, volume, muted) or not _pid_alive(pid):
            del state.ducked[key]
            restored += 1
    if state.ducked:
        _write_record(state)
        return False
    try:
        RECORD.unlink(missing_ok=True)
    except OSError:
        log.exception("Could not remove the audio restore record %s", RECORD)
    log.info("Output isolation off: %d session(s) restored", restored)
    return True


def _stop_op(state: _State) -> None:
    was = state.active
    state.active = False
    if not was and not state.ducked:
        return
    if not _restore_output(state):
        log.warning("Output isolation: %d session(s) not restored yet; retrying", len(state.ducked))
        state.tick_at = time.monotonic() + _RETRY_INTERVAL


def _write_mic_record(state: _State) -> None:
    sessions = [{"key": key, "pid": pid, "volume": volume, "muted": muted}
                for key, (pid, volume, muted, _v) in state.capture_muted.items()]
    record = {"version": 1, "sessions": sessions, "endpoints": list(state.endpoints_muted)}
    try:
        paths.DATA.mkdir(parents=True, exist_ok=True)
        tmp = MIC_RECORD.with_suffix(f".json.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(record, indent=1), encoding="utf-8")
        os.replace(tmp, MIC_RECORD)
    except OSError:
        log.exception("Could not write the microphone privacy restore record to %s", MIC_RECORD)
        raise


def _mute_capture_sessions(state: _State) -> None:
    """Record capture sessions that are new to this take, then mute every
    foreign one and check it took. Raises if any session refuses."""
    mine = os.getpid()
    live = [s for s in _enumerate_capture() if s[1] != mine]
    new = False
    for key, pid, volume, muted, control in live:
        if key not in state.capture_muted:
            app = _app_of(pid)
            if muted and app in state.owed_apps:
                muted = False          # our own leftover, not the user's mute
            state.capture_muted[key] = (pid, volume, muted, control)
            if not muted and app and app not in state.owed_apps:
                state.owed_apps.add(app)
                _save_owed(state)
            new = True
    if new:
        _write_mic_record(state)
    for key, pid, _volume, muted, control in live:
        if not muted:
            if state.capture_active and not state.capture_muted[key][2]:
                log.info("Microphone privacy: app %d unmuted its mic mid-take; muting it again", pid)
            control.SetMute(True, None)
            if not bool(control.GetMute()):
                raise RuntimeError(f"capture session {pid} did not accept mute")
    _mute_capture_endpoints(state)


def _mute_capture_endpoints(state: _State) -> None:
    """Hold every other recording device an app is reading, except those an
    audio router reads; mute the ones that refuse the hold. Best effort:
    session mute already covers each app, so a device that refuses both is
    logged, not fatal."""
    if not state.own_endpoint:
        return
    devices = _enumerate_capture_endpoints()
    for device_id, control, _readers in devices:
        if device_id not in state.endpoint_before:
            try:
                state.endpoint_before[device_id] = (bool(control.GetMute())
                                                    and device_id not in state.owed_endpoints)
            except Exception:
                state.endpoint_before[device_id] = True    # unreadable: leave it alone
    _hold_capture_endpoints(state, devices)
    if not state.endpoint_layer:
        return
    for device_id, control, readers in devices:
        if device_id == state.own_endpoint or state.endpoint_before[device_id]:
            continue               # ours, or muted by the user and not ours to restore
        if device_id in state.held or any(r in name for name in readers for r in _ROUTERS):
            continue
        try:
            if bool(control.GetMute()):
                continue
            if device_id not in state.endpoints_muted:
                state.endpoints_muted[device_id] = control
                _write_mic_record(state)
                _owe_endpoint(state, device_id)
            control.SetMute(True, None)
            if not bool(control.GetMute()):
                raise RuntimeError("mute did not stick")
        except Exception as e:
            log.warning("Microphone privacy: could not mute recording device %s (%s)", device_id, e)
    # Some drivers give several devices one mute switch (VB-Audio's VAIO
    # devices do), so muting one mutes its siblings, ours included. Record
    # every device that went quiet so the restore puts each one back.
    changed = False
    for device_id, control, _readers in devices:
        if device_id in state.endpoints_muted or state.endpoint_before[device_id]:
            continue
        try:
            if bool(control.GetMute()):
                state.endpoints_muted[device_id] = control
                _owe_endpoint(state, device_id)
                changed = True
        except Exception:
            continue
    if changed:
        _write_mic_record(state)


def _owe_endpoint(state: _State, device_id: str) -> None:
    if device_id not in state.owed_endpoints:
        state.owed_endpoints.add(device_id)
        _save_owed(state)


def _hold_capture_endpoints(state: _State, devices) -> None:
    """Take an exclusive hold on each other device with a foreign reader. A
    device nobody reads over WASAPI is left alone: Matrix reads the hardware
    inputs over ASIO, and holding those could upset its clock (untested)."""
    for device_id, _control, readers in devices:
        if (device_id == state.own_endpoint or device_id in state.held or device_id in state.hold_refused
                or not readers or any(r in name for name in readers for r in _ROUTERS)):
            continue
        try:
            state.held[device_id] = _hold_exclusive(device_id)
        except Exception as e:
            state.hold_refused.add(device_id)
            log.warning("Microphone privacy: could not hold recording device %s (%s); muting it instead",
                        device_id, e)


def _release_holds(state: _State) -> None:
    for device_id, client in list(state.held.items()):
        try:
            client.Stop()
        except Exception:
            pass               # dropping the client releases the device either way
        del state.held[device_id]


def _capture_is_shared(state: _State) -> None:
    """Our take records in shared mode, where our own device's mute silences
    it. If muting another device muted ours too, give up device mute for this
    take; each app's session stays muted."""
    if state.own_endpoint not in state.endpoints_muted:
        return
    state.endpoint_layer = False
    failures = _restore_endpoints(state)
    log.warning("Microphone privacy: your recording device shares its mute with another device; "
                "only app mutes are used for this take%s", " (restore failed)" if failures else "")
    _write_mic_record(state)


def _restore_endpoints(state: _State) -> list[Exception]:
    failures = []
    for device_id, control in list(state.endpoints_muted.items()):
        try:
            control.SetMute(False, None)
        except Exception as e:
            # A device unplugged mid-take is gone; only a live one is owed.
            if device_id in {d for d, _c, _r in _enumerate_capture_endpoints()}:
                failures.append(e)
                continue
        del state.endpoints_muted[device_id]
    return failures


def _restore_capture(state: _State) -> None:
    """Put every muted capture session back; a session whose app has exited
    counts as restored. Raises while anything live is still owed."""
    _release_holds(state)
    failures: list[Exception] = _restore_endpoints(state)
    restored = 0
    for key, (pid, volume, muted, control) in list(state.capture_muted.items()):
        try:
            control.SetMasterVolume(volume, None)
            control.SetMute(muted, None)
            if abs(float(control.GetMasterVolume()) - volume) > 0.001 or bool(control.GetMute()) != muted:
                raise RuntimeError(f"capture session {key} did not restore original settings")
        except Exception as e:
            if _pid_alive(pid):
                failures.append(e)
                continue
        del state.capture_muted[key]
        restored += 1
    if failures:
        try:
            _write_mic_record(state)
        except OSError:
            pass
        raise RuntimeError(f"could not restore {len(failures)} capture session(s)") from failures[0]
    MIC_RECORD.unlink(missing_ok=True)
    log.info("Microphone privacy off: %d capture session(s) restored", restored)
    _settle_owed(state)


def _start_capture_privacy(state: _State, own_endpoint: str | None = None) -> None:
    if state.capture_active:
        return
    state.own_endpoint = own_endpoint
    state.endpoint_before = {}
    state.hold_refused = set()
    state.endpoint_layer = True
    _capture_failure.clear()
    try:
        _mute_capture_sessions(state)
    except Exception:
        try:
            _restore_capture(state)
        finally:
            _capture_failure.set()
        raise
    state.capture_active = True
    state.retries = 0
    state.tick_at = time.monotonic() + _RESCAN_INTERVAL
    log.info("Microphone privacy on: %d capture session(s) muted, %d other device(s) held, %d muted",
             len(state.capture_muted), len(state.held), len(state.endpoints_muted))


def _stop_capture_privacy(state: _State) -> None:
    state.capture_active = False
    if not (state.capture_muted or state.endpoints_muted or state.held):
        return
    try:
        _restore_capture(state)
    except Exception:
        state.tick_at = time.monotonic() + _RETRY_INTERVAL
        raise


def _tick(state: _State) -> None:
    """The worker's own upkeep, run whenever its queue is idle and a pause has
    passed: during a take, catch sessions that appeared since the last scan;
    after one, retry restores that failed."""
    if state.capture_active:
        try:
            _mute_capture_sessions(state)
        except Exception:
            log.exception("Microphone privacy was lost during a take; restoring sessions")
            _capture_failure.set()
            state.capture_active = False
            try:
                _restore_capture(state)
            except Exception:
                pass
    if state.active:
        _duck_sessions(state)
    if state.active or state.capture_active:
        state.tick_at = time.monotonic() + _RESCAN_INTERVAL
        return
    if not (state.ducked or state.capture_muted or state.endpoints_muted):
        if state.owed_apps:
            _settle_owed(state)
            state.tick_at = time.monotonic() + _OWED_INTERVAL
        return
    # A restore at the end of a take failed: try again, then leave it to the
    # record files and the next start.
    state.retries += 1
    if state.capture_muted or state.endpoints_muted:
        try:
            _restore_capture(state)
        except Exception:
            pass
    if state.ducked:
        _restore_output(state)
    owed = len(state.ducked) + len(state.capture_muted) + len(state.endpoints_muted)
    if owed and state.retries >= _MAX_RETRIES:
        log.error("Gave up restoring %d audio session(s); the next start restores them", owed)
        state.ducked.clear()
        state.capture_muted.clear()
        state.endpoints_muted.clear()
    if not (state.ducked or state.capture_muted or state.endpoints_muted):
        state.retries = 0
    state.tick_at = time.monotonic() + _RETRY_INTERVAL


# ------------------------------------------------------------- public API

def start(level: int) -> None:
    """Snapshot and duck every session except ours. Safe to call twice.
    Returns at once; the work runs on the worker."""
    def run(state: _State) -> None:
        if state.active:
            state.level = level
            return
        state.level = level
        try:
            _duck_sessions(state)
        except Exception as e:
            log.warning("Output isolation could not start: %s", e)
            return
        state.active = True
        state.retries = 0
        state.tick_at = time.monotonic() + _RESCAN_INTERVAL
        log.info("Output isolation on: %d session(s) ducked at level %d", len(state.ducked), level)

    _get_worker().post(run)


def stop() -> None:
    """Restore every ducked session exactly and clear the crash record."""
    ok, err = _get_worker().call(_stop_op)
    if not ok:
        log.warning("Output isolation restore failed: %s", err)


def recover() -> None:
    """Startup crash recovery: if a restore record survived a mid-take crash,
    put every session in it back. Safe to call when nothing was ducked."""

    def run(state: _State) -> None:
        _recover_capture_privacy()
        _settle_owed(state)
        if state.active or not RECORD.exists():
            return
        try:
            rec = json.loads(RECORD.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.exception("Audio restore record unreadable; removing it")
            RECORD.unlink(missing_ok=True)
            return
        wanted = []
        for s in rec.get("sessions", []):
            try:
                wanted.append((str(s.get("key") or ""), int(s["pid"]), float(s["volume"]), bool(s["muted"])))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        if not wanted:
            RECORD.unlink(missing_ok=True)
            return
        live = _enumerate()
        by_key = {key: v for key, _pid, _vol, _m, v in live}
        used: set[int] = set()
        restored = 0
        rest = []
        # Sessions that still exist are matched by their identifier.
        for key, pid, volume, muted in wanted:
            v = by_key.get(key) if key else None
            if v is not None and id(v) not in used:
                used.add(id(v))
                _restore_one(v, volume, muted)
                restored += 1
            else:
                rest.append((pid, volume, muted))
        # Older records (no key) fall back to the pid, in snapshot order, so
        # multi-session processes still restore one-to-one.
        by_pid: dict[int, deque] = {}
        for _key, pid, _vol, _m, v in live:
            if id(v) not in used:
                by_pid.setdefault(pid, deque()).append(v)
        for pid, volume, muted in rest:
            sessions = by_pid.get(pid)
            if not sessions:
                continue  # the process is gone; its sessions died with it
            _restore_one(sessions.popleft(), volume, muted)
            restored += 1
        RECORD.unlink(missing_ok=True)
        log.info("Recovered %d audio session(s) from a previous run's restore record", restored)

    ok, err = _get_worker().call(run)
    if not ok:
        log.warning("Audio restore recovery failed: %s", err)


def _recover_capture_privacy() -> None:
    if not MIC_RECORD.exists():
        return
    try:
        rec = json.loads(MIC_RECORD.read_text(encoding="utf-8"))
        wanted = {str(s["key"]): (float(s["volume"]), bool(s["muted"]))
                  for s in rec.get("sessions", [])}
        live = {key: v for key, _pid, _volume, _muted, v in _enumerate_capture()}
        failures = []
        devices = set(rec.get("endpoints", []))
        for device_id, control, _readers in _enumerate_capture_endpoints():
            if device_id in devices:
                try:
                    control.SetMute(False, None)
                except Exception as e:
                    failures.append(e)
        for key, (volume, muted) in wanted.items():
            control = live.get(key)
            if control is None:
                continue
            try:
                control.SetMasterVolume(volume, None)
                control.SetMute(muted, None)
            except Exception as e:
                failures.append(e)
        if failures:
            raise RuntimeError(f"could not recover {len(failures)} capture session(s)") from failures[0]
        MIC_RECORD.unlink(missing_ok=True)
        log.info("Recovered microphone privacy settings from a previous run")
    except Exception:
        log.exception("Microphone privacy recovery failed; restore record kept at %s", MIC_RECORD)


def start_capture_privacy(own_endpoint: str | None = None) -> None:
    """Mute every other app's microphone session, and every recording device
    except ``own_endpoint`` (the one the take reads), and check it took.
    Raises when a session can't be muted, so the take never opens an
    unprotected mic."""
    ok, err = _get_worker().call(lambda state: _start_capture_privacy(state, own_endpoint))
    if not ok:
        raise RuntimeError(f"microphone privacy could not be enforced: {err}") from err


def capture_is_shared() -> None:
    """The take fell back to shared capture: keep our own device unmuted."""
    ok, err = _get_worker().call(_capture_is_shared)
    if not ok:
        log.warning("Microphone privacy: could not unmute our own device: %s", err)


def capture_privacy_failed() -> bool:
    """Non-blocking signal for the hotkey loop to end an unprotected take."""
    return _capture_failure.is_set()


def stop_capture_privacy() -> None:
    ok, err = _get_worker().call(_stop_capture_privacy)
    if not ok:
        log.error("Microphone privacy restore failed (%s); retrying", err)
