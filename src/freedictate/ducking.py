"""Output isolation while dictating.

While a take runs, every render-endpoint audio session except our own is
muted (or ducked to a fixed percent) and restored exactly when it ends.
All Windows Core Audio work happens on one worker thread so every session
control is created and used inside the same COM apartment.

Crash safety: the pre-take snapshot is written to ``audio-restore.json`` in
the app data folder and removed only after a successful restore. If the app
dies mid-take, the next start re-applies the restore from that file.

Restore is keyed per session through a pid -> deque of records: a process
can own several sessions (Flow.Launcher held two), and a per-pid dict would
leave the extras muted. The endpoint master volume is never touched.
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
_RESCAN_INTERVAL = 0.25   # seconds between mid-take session re-scans
_MIDTAKE_REV = 2          # record format

_worker: _Worker | None = None
_worker_lock = threading.Lock()


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
        self.ducked: dict[int, deque] = {}   # pid -> deque[(volume, muted, control)]
        self.endpoint = ""                   # id of the endpoint we ducked
        self.rescan_at = 0.0


# ------------------------------------------------------------------ helpers

def available() -> bool:
    try:
        import pycaw  # noqa: F401
        import comtypes  # noqa: F401
        return True
    except ImportError:
        return False


def _enumerate():
    """[(pid, volume, muted, SimpleAudioVolume)] for every session on the
    default render endpoint. Runs on the worker thread."""
    from pycaw.pycaw import AudioUtilities
    out = []
    for s in AudioUtilities.GetAllSessions():
        try:
            v = s.SimpleAudioVolume
            out.append((s.ProcessId, float(v.GetMasterVolume()), bool(v.GetMute()), v))
        except Exception:
            log.debug("Session %s unreadable; skipping", getattr(s, "ProcessId", "?"), exc_info=True)
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
    sessions = []
    for pid, records in state.ducked.items():
        for volume, muted, _v in records:
            sessions.append({"pid": pid, "volume": volume, "muted": muted})
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
        for pid, volume, muted, v in _enumerate():
            if pid == mine:
                continue
            state.ducked.setdefault(pid, deque()).append((volume, muted, v))
            _apply_duck(v, level)
        state.active = True
        state.level = level
        state.rescan_at = time.monotonic() + _RESCAN_INTERVAL
        _write_record(state)
        log.info("Output isolation on: %d session(s) ducked at level %d",
                 sum(len(r) for r in state.ducked.values()), level)

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
            for records in state.ducked.values():
                for volume, muted, v in records:
                    _restore_one(v, volume, muted)
            state.ducked.clear()
            state.endpoint = endpoint
        for pid, volume, muted, v in _enumerate():
            if pid == mine:
                continue
            if pid not in state.ducked:
                state.ducked[pid] = deque()
                state.ducked[pid].append((volume, muted, v))
                _apply_duck(v, state.level)
                _write_record(state)
            else:
                # Re-assert in case the app raised itself while we held it.
                _apply_duck(v, state.level)

    _get_worker().post(run)


def stop() -> None:
    """Restore every ducked session exactly and clear the crash record."""

    def run(state: _State) -> None:
        if not state.active:
            return
        restored = 0
        for records in state.ducked.values():
            for volume, muted, v in records:
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

    ok, err = _get_worker().call(run)
    if not ok:
        log.warning("Output isolation restore failed: %s", err)


def recover() -> None:
    """Startup crash recovery: if a restore record survived a mid-take crash,
    put every session in it back. Safe to call when nothing was ducked."""

    def run(state: _State) -> None:
        if state.active or not RECORD.exists():
            return
        try:
            rec = json.loads(RECORD.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.exception("Audio restore record unreadable; removing it")
            RECORD.unlink(missing_ok=True)
            return
        by_pid: dict[int, deque] = {}
        for s in rec.get("sessions", []):
            try:
                by_pid.setdefault(int(s["pid"]), deque()).append((float(s["volume"]), bool(s["muted"])))
            except (KeyError, TypeError, ValueError):
                continue
        if not by_pid:
            RECORD.unlink(missing_ok=True)
            return
        # Match records to live sessions per pid, in the order they were
        # snapshotted, so multi-session processes restore one-to-one.
        live: dict[int, deque] = {}
        for pid, volume, muted, v in _enumerate():
            live.setdefault(pid, deque()).append((volume, muted, v))
        restored = 0
        for pid, values in by_pid.items():
            sessions = live.get(pid)
            if not sessions:
                continue  # the process is gone; its sessions died with it
            for volume, muted in values:
                if not sessions:
                    break
                _orig_volume, _orig_muted, v = sessions.popleft()
                _restore_one(v, volume, muted)
                restored += 1
        RECORD.unlink(missing_ok=True)
        log.info("Recovered %d audio session(s) from a previous run's restore record", restored)

    ok, err = _get_worker().call(run)
    if not ok:
        log.warning("Audio restore recovery failed: %s", err)
