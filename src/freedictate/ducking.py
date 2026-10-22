"""Output isolation while dictating.

While a take runs, every render-endpoint audio session except our own is
muted (or ducked to a fixed percent) and restored exactly when it ends.
All Windows Core Audio work happens on one worker thread so every session
control is created and used inside the same COM apartment. Callers never
wait for it: start, rescan and stop are queued in order and return at once,
so the hotkey thread and the microphone open are never delayed.

Crash safety: the pre-take snapshot is written to ``audio-restore.json`` in
the app data folder and removed only after a successful restore. If the app
dies mid-take, the next start re-applies the restore from that file.

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
_RESCAN_INTERVAL = 0.25   # seconds between mid-take session re-scans
_MIDTAKE_REV = 3          # record format: sessions carry their key

_worker: _Worker | None = None
_worker_lock = threading.Lock()
_capture_failure = threading.Event()


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
            fn = self._q.get()
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
        # session key -> (pid, original volume, original mute, control)
        self.ducked: dict[str, tuple[int, float, bool, object]] = {}
        self.endpoint = ""                   # id of the endpoint we ducked
        self.rescan_at = 0.0
        self.capture_active = False
        self.capture_muted: dict[str, tuple[int, float, bool, object]] = {}


# ------------------------------------------------------------------ helpers

def available() -> bool:
    try:
        import pycaw  # noqa: F401
        import comtypes  # noqa: F401
        return True
    except ImportError:
        return False


def _session_key(session, pid: int, ordinal: int) -> str:
    """Stable identity of one audio session across re-enumerations. The
    instance identifier is unique per session and carries the pid; the pid
    plus its enumeration ordinal is the fallback when it can't be read."""
    try:
        ident = session.InstanceIdentifier
        if ident:
            return str(ident)
    except Exception:
        pass
    return f"pid:{pid}#{ordinal}"


def _enumerate():
    """[(key, pid, volume, muted, SimpleAudioVolume)] for every session on the
    default render endpoint. Runs on the worker thread."""
    from pycaw.pycaw import AudioUtilities
    out = []
    per_pid: dict[int, int] = {}
    for s in AudioUtilities.GetAllSessions():
        try:
            pid = int(s.ProcessId)
            n = per_pid[pid] = per_pid.get(pid, -1) + 1
            v = s.SimpleAudioVolume
            out.append((_session_key(s, pid, n), pid, float(v.GetMasterVolume()), bool(v.GetMute()), v))
        except Exception:
            log.debug("Session %s unreadable; skipping", getattr(s, "ProcessId", "?"), exc_info=True)
    return out


def _enumerate_capture():
    """Enumerate sessions on every active capture endpoint.

    Unlike GetAllSessions(), which only returns render sessions, this opens
    IAudioSessionManager2 on each active capture endpoint. Any enumeration or
    session-read failure is fatal: privacy must not claim success partially.
    """
    import comtypes
    from pycaw.constants import DEVICE_STATE, EDataFlow
    from pycaw.pycaw import AudioSession, AudioUtilities, IAudioSessionControl2, IAudioSessionManager2

    out = []
    for device in AudioUtilities.GetAllDevices(EDataFlow.eCapture.value, DEVICE_STATE.ACTIVE.value):
        manager = device._dev.Activate(
            IAudioSessionManager2._iid_, comtypes.CLSCTX_INPROC_SERVER, None
        ).QueryInterface(IAudioSessionManager2)
        sessions = manager.GetSessionEnumerator()
        for index in range(sessions.GetCount()):
            control = sessions.GetSession(index).QueryInterface(IAudioSessionControl2)
            session = AudioSession(control)
            pid = int(session.ProcessId)
            if pid <= 0:
                continue
            volume = session.SimpleAudioVolume
            key = f"{device.id}|{_session_key(session, pid, index)}"
            out.append((key, pid, float(volume.GetMasterVolume()), bool(volume.GetMute()), volume))
    return out


def _endpoint_id() -> str:
    from pycaw.pycaw import AudioUtilities
    try:
        return AudioUtilities.GetSpeakers().id or ""
    except Exception:
        return ""


def _apply_duck(v, level: int) -> None:
    # pycaw 20260927 exposes the raw ISimpleAudioVolume: both setters take
    # an LPCGUID EventContext we do not need (probe-verified WinError-level
    # TypeError without it).
    if level <= 0:
        v.SetMute(True, None)
    else:
        v.SetMasterVolume(level / 100.0, None)


def _restore_one(v, volume: float, muted: bool) -> None:
    try:
        v.SetMasterVolume(volume, None)
        v.SetMute(muted, None)
    except Exception:
        log.debug("Session restore failed", exc_info=True)


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


# ------------------------------------------------------------- public API

def start(level: int) -> None:
    """Snapshot and duck every session except ours. Safe to call twice."""
    def run(state: _State) -> None:
        if state.active:
            state.level = level
            return
        state.endpoint = _endpoint_id()
        mine = os.getpid()
        for key, pid, volume, muted, v in _enumerate():
            if pid == mine or key in state.ducked:
                continue
            state.ducked[key] = (pid, volume, muted, v)
            _apply_duck(v, level)
        state.active = True
        state.level = level
        state.rescan_at = time.monotonic() + _RESCAN_INTERVAL
        _write_record(state)
        log.info("Output isolation on: %d session(s) ducked at level %d", len(state.ducked), level)

    ok, err = _get_worker().call(run)
    if not ok:
        log.warning("Output isolation could not start: %s", err)


def rescan(level: int) -> None:
    """Re-apply the duck to sessions that appeared mid-take, and follow a
    change of the default output device. Non-blocking."""

    def run(state: _State) -> None:
        if not state.active:
            return
        state.level = level
        mine = os.getpid()
        endpoint = _endpoint_id()
        if endpoint and endpoint != state.endpoint:
            # The old endpoint's sessions are gone; put back whatever still
            # answers, then duck the new endpoint's sessions.
            log.info("Output device changed mid-take; re-enumerating sessions")
            for _pid, volume, muted, v in state.ducked.values():
                _restore_one(v, volume, muted)
            state.ducked.clear()
            state.endpoint = endpoint
        added = False
        for key, pid, volume, muted, v in _enumerate():
            if pid == mine:
                continue
            if key not in state.ducked:
                # New to this take, including a second session from a
                # process that is already ducked: record it before touching it.
                state.ducked[key] = (pid, volume, muted, v)
                added = True
            # Ducks the new ones and re-asserts the rest, in case an app
            # raised itself while we held it.
            _apply_duck(v, state.level)
        if added:
            _write_record(state)

    _get_worker().post(run)


def _stop_op(state: _State) -> None:
    if not state.active:
        return
    restored = 0
    for _pid, volume, muted, v in state.ducked.values():
        _restore_one(v, volume, muted)
        restored += 1
    state.ducked.clear()
    state.active = False
    state.endpoint = ""
    try:
        RECORD.unlink(missing_ok=True)
    except OSError:
        log.exception("Could not remove the audio restore record %s", RECORD)
    log.info("Output isolation off: %d session(s) restored", restored)


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


def _write_mic_record(state: _State) -> None:
    sessions = [{"key": key, "pid": pid, "volume": volume, "muted": muted}
                for key, (pid, volume, muted, _v) in state.capture_muted.items()]
    try:
        paths.DATA.mkdir(parents=True, exist_ok=True)
        tmp = MIC_RECORD.with_suffix(f".json.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"version": 1, "sessions": sessions}, indent=1), encoding="utf-8")
        os.replace(tmp, MIC_RECORD)
    except OSError:
        log.exception("Could not write the microphone privacy restore record to %s", MIC_RECORD)
        raise


def _start_capture_privacy(state: _State) -> None:
    if state.capture_active:
        return
    _capture_failure.clear()
    mine = os.getpid()
    try:
        for key, pid, volume, muted, control in _enumerate_capture():
            if pid == mine or key in state.capture_muted:
                continue
            state.capture_muted[key] = (pid, volume, muted, control)
            _write_mic_record(state)
            control.SetMute(True, None)
            if not bool(control.GetMute()):
                raise RuntimeError(f"capture session {pid} did not accept mute")
        state.capture_active = True
        log.info("Microphone privacy on: %d capture session(s) muted", len(state.capture_muted))
    except Exception:
        try:
            _stop_capture_privacy(state)
        finally:
            _capture_failure.set()
        raise


def _rescan_capture_privacy(state: _State) -> None:
    if not state.capture_active:
        return
    mine = os.getpid()
    for key, pid, volume, muted, control in _enumerate_capture():
        if pid == mine:
            continue
        if key not in state.capture_muted:
            state.capture_muted[key] = (pid, volume, muted, control)
            _write_mic_record(state)
        control.SetMute(True, None)
        if not bool(control.GetMute()):
            raise RuntimeError(f"capture session {pid} did not accept mute")


def _stop_capture_privacy(state: _State) -> None:
    failures = []
    for key, (_pid, volume, muted, control) in list(state.capture_muted.items()):
        try:
            control.SetMasterVolume(volume, None)
            control.SetMute(muted, None)
            if abs(float(control.GetMasterVolume()) - volume) > 0.001 or bool(control.GetMute()) != muted:
                raise RuntimeError(f"capture session {key} did not restore original settings")
        except Exception as e:
            failures.append(e)
    if failures:
        _write_mic_record(state)
        raise RuntimeError(f"could not restore {len(failures)} capture session(s)") from failures[0]
    state.capture_muted.clear()
    state.capture_active = False
    MIC_RECORD.unlink(missing_ok=True)


def start_capture_privacy() -> None:
    ok, err = _get_worker().call(_start_capture_privacy)
    if not ok:
        raise RuntimeError(f"microphone privacy could not be enforced: {err}") from err


def rescan_capture_privacy() -> None:
    def run(state: _State) -> None:
        try:
            _rescan_capture_privacy(state)
        except Exception:
            log.exception("Microphone privacy was lost during a take; restoring sessions")
            _capture_failure.set()
            _stop_capture_privacy(state)
    _get_worker().post(run)


def capture_privacy_failed() -> bool:
    """Non-blocking signal for the hotkey loop to end an unprotected take."""
    return _capture_failure.is_set()


def stop_capture_privacy() -> None:
    ok, err = _get_worker().call(_stop_capture_privacy)
    if not ok:
        log.error("Microphone privacy restore failed: %s", err)
