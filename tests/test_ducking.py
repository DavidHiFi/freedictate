"""Output isolation (ducking.py) unit tests: no COM, no Windows audio touched.

The ducking worker is stubbed to run synchronously, and the session
enumerator is faked, so these prove the bookkeeping: what gets ducked,
what gets restored, and what survives a crash in the record file.
"""
import json

import pytest

from freedictate import ducking


class FakeVolume:
    """Stand-in for pycaw's SimpleAudioVolume."""

    def __init__(self, volume=1.0, muted=False):
        self.volume = volume
        self.muted = muted

    def GetMasterVolume(self):
        return self.volume

    def GetMute(self):
        return self.muted

    def SetMasterVolume(self, v, ctx=None):
        self.volume = min(max(float(v), 0.0), 1.0)

    def SetMute(self, m, ctx=None):
        self.muted = bool(m)


class FakeState(ducking._State):
    pass


class SyncWorker:
    """Runs ducking operations inline, like the real worker thread would."""

    def __init__(self):
        self.state = FakeState()

    def call(self, fn, timeout=None):
        try:
            return True, fn(self.state)
        except Exception as e:
            return False, e

    def post(self, fn):
        fn(self.state)


@pytest.fixture
def worker(monkeypatch, tmp_path):
    w = SyncWorker()
    monkeypatch.setattr(ducking, "_get_worker", lambda: w)
    monkeypatch.setattr(ducking, "RECORD", tmp_path / "audio-restore.json")
    monkeypatch.setattr(ducking, "_endpoint_id", lambda: "endpoint-a")
    return w


def set_sessions(worker, sessions):
    """sessions: list of (pid, [FakeVolume, ...]) — a pid may own several.
    Each FakeVolume is one session; its identity is the session key, the way
    the instance identifier stays fixed across real re-enumerations."""
    flat = []
    for pid, vols in sessions:
        for v in vols:
            flat.append((f"session-{id(v)}|{pid}", pid, v.volume, v.muted, v))
    ducking._enumerate = lambda: flat


def test_new_settings_are_validated():
    from freedictate.config import DEFAULTS, Config
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as d:
        c = Config(pathlib.Path(d) / "settings.json")
        assert c["mic_privacy_while_dictating"] is False
        assert c["isolate_output_while_dictating"] is False
        assert c["isolate_output_level"] == 0
        c.update({"isolate_output_level": 500})
        assert c["isolate_output_level"] == 100
        c.update({"isolate_output_level": "37"})
        assert c["isolate_output_level"] == 37


def test_start_mutes_everything_but_ours_and_writes_a_record(worker):
    ours = FakeVolume(0.8, False)
    set_sessions(worker, [(123, [FakeVolume(0.6, False)]), (0, [FakeVolume(1.0, True)]),
                          (999, [FakeVolume(0.5, False), FakeVolume(0.2, False)]), (ducking.os.getpid(), [ours])])
    ducking.start(0)
    rec = json.loads(worker.state and ducking.RECORD.read_text())
    assert len(rec["sessions"]) == 4            # 123, pid 0, and 999's two sessions
    assert all(s["pid"] != ducking.os.getpid() for s in rec["sessions"])
    assert ours.volume == 0.8 and ours.muted is False   # ours is never touched


def test_stop_restores_exactly_and_clears_the_record(worker):
    a, b1, b2 = FakeVolume(0.6, False), FakeVolume(0.5, False), FakeVolume(0.2, True)
    set_sessions(worker, [(123, [a]), (999, [b1, b2])])
    ducking.start(0)
    assert a.muted and b1.muted and b2.muted
    ducking.stop()
    assert (a.volume, a.muted) == (0.6, False)
    assert (b1.volume, b1.muted) == (0.5, False)
    assert (b2.volume, b2.muted) == (0.2, True)   # a pre-muted session stays pre-muted
    assert not ducking.RECORD.exists()


def test_duck_level_sets_volume_not_mute(worker):
    a = FakeVolume(0.6, False)
    set_sessions(worker, [(123, [a])])
    ducking.start(30)
    assert a.volume == 0.3 and a.muted is False
    ducking.stop()
    assert a.volume == 0.6


def test_rescan_picks_up_a_session_that_started_mid_take(worker):
    set_sessions(worker, [(123, [FakeVolume(0.6, False)])])
    ducking.start(0)
    late = FakeVolume(0.9, False)
    set_sessions(worker, [(123, [FakeVolume(0.6, False)]), (555, [late])])
    ducking.rescan(0)
    assert late.muted
    ducking.stop()
    assert late.volume == 0.9 and late.muted is False
    # The late session was in the record too, so a crash would still restore it.


def test_device_change_re_enumerates(worker):
    a = FakeVolume(0.6, False)
    set_sessions(worker, [(123, [a])])
    ducking.start(0)
    assert a.muted
    ducking._endpoint_id = lambda: "endpoint-b"
    ducking.rescan(0)          # old endpoint's session is unreachable now; must not crash
    ducking.stop()
    assert not ducking.RECORD.exists()


def test_recover_restores_from_a_crash_record(worker):
    a, b = FakeVolume(1.0, False), FakeVolume(1.0, False)
    ducking.RECORD.write_text(json.dumps({"version": 2, "saved": 0.0, "sessions": [
        {"pid": 123, "volume": 0.6, "muted": False},
        {"pid": 999, "volume": 0.5, "muted": True}]}))
    set_sessions(worker, [(123, [a]), (999, [b]), (4242, [FakeVolume(0.4, False)])])
    ducking.recover()
    assert (a.volume, a.muted) == (0.6, False)
    assert (b.volume, b.muted) == (0.5, True)
    assert not ducking.RECORD.exists()


def test_recover_ignores_a_stale_record(worker, tmp_path):
    ducking.RECORD.write_text("{broken")
    set_sessions(worker, [(123, [FakeVolume(0.6, False)])])
    ducking.recover()
    assert not ducking.RECORD.exists()
    ducking.RECORD.write_text(json.dumps({"version": 2, "saved": 0.0, "sessions": []}))
    ducking.recover()
    assert not ducking.RECORD.exists()


def test_rescan_restores_a_new_session_from_an_already_ducked_process(worker):
    """Regression: a second session opened mid-take by a process that was
    already ducked used to be muted but never recorded, so it stayed muted."""
    first = FakeVolume(0.7, False)
    set_sessions(worker, [(321, [first])])
    ducking.start(0)
    assert first.muted
    second = FakeVolume(0.4, False)
    set_sessions(worker, [(321, [first, second])])
    ducking.rescan(0)
    assert second.muted
    rec = json.loads(ducking.RECORD.read_text())
    assert len(rec["sessions"]) == 2 and all(s["key"] for s in rec["sessions"])
    ducking.rescan(0)          # a re-enumeration must not overwrite the originals
    ducking.stop()
    assert (first.volume, first.muted) == (0.7, False)
    assert (second.volume, second.muted) == (0.4, False)


def test_recover_matches_sessions_by_key(worker):
    a, b = FakeVolume(1.0, True), FakeVolume(1.0, True)
    set_sessions(worker, [(77, [a, b])])
    key_b = ducking._enumerate()[1][0]
    ducking.RECORD.write_text(json.dumps({"version": 3, "saved": 0.0, "sessions": [
        {"key": key_b, "pid": 77, "volume": 0.25, "muted": False}]}))
    ducking.recover()
    assert (b.volume, b.muted) == (0.25, False)
    assert (a.volume, a.muted) == (1.0, True)     # the other session is left alone
