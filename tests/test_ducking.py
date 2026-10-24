"""Output isolation (ducking.py) unit tests: no COM, no Windows audio touched.

The ducking worker is stubbed to run synchronously, and the session
enumerator is faked, so these prove the bookkeeping: what gets ducked,
what gets restored, and what survives a crash in the record file.
"""
import json
import logging
import time

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
    monkeypatch.setattr(ducking, "MIC_RECORD", tmp_path / "mic-privacy-restore.json")
    return w


@pytest.fixture(autouse=True)
def no_capture_endpoints(monkeypatch):
    """Endpoint mute is off the table unless a test hands over endpoints."""
    monkeypatch.setattr(ducking, "_enumerate_capture_endpoints", lambda: [])


def set_sessions(worker, sessions):
    """sessions: list of (pid, [FakeVolume, ...]) — a pid may own several.
    Each FakeVolume is one session; its identity is the session key, the way
    the instance identifier stays fixed across real re-enumerations. Every
    enumeration reads the sessions' current values, like Windows does."""
    flat = []
    for pid, vols in sessions:
        for v in vols:
            flat.append((f"session-{id(v)}|{pid}", pid, v))
    ducking._enumerate = lambda: [(key, pid, v.volume, v.muted, v) for key, pid, v in flat]


def tick(worker):
    """One round of the worker's own mid-take upkeep."""
    ok, err = worker.call(ducking._tick)
    assert ok, err


class CountingVolume(FakeVolume):
    def __init__(self, volume=1.0, muted=False):
        super().__init__(volume, muted)
        self.mute_calls = 0

    def SetMute(self, m, ctx=None):
        self.mute_calls += 1
        super().SetMute(m, ctx)


@pytest.fixture
def live_worker(monkeypatch, tmp_path):
    """The real worker thread, with fake sessions and a fast re-scan."""
    monkeypatch.setattr(ducking, "RECORD", tmp_path / "audio-restore.json")
    monkeypatch.setattr(ducking, "MIC_RECORD", tmp_path / "mic-privacy-restore.json")
    monkeypatch.setattr(ducking, "_RESCAN_INTERVAL", 0.05)
    w = ducking._Worker()
    monkeypatch.setattr(ducking, "_get_worker", lambda: w)
    yield w
    w.post(None)


def test_new_settings_are_validated():
    from freedictate.config import DEFAULTS, Config
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as d:
        c = Config(pathlib.Path(d) / "settings.json")
        assert c["mic_privacy_while_dictating"] is False
        assert c["isolate_output_while_dictating"] is False
        assert c["isolate_output_level"] == 0
        c.update({"isolate_output_level": 500})
        assert c["isolate_output_level"] == 0      # 100 meant "no change": a switched-on setting that did nothing
        c.update({"isolate_output_level": "37"})
        assert c["isolate_output_level"] == 25     # snaps to the nearest step the Settings page offers
        c.update({"isolate_output_level": 50})
        assert c["isolate_output_level"] == 50


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
    tick(worker)
    assert late.muted
    ducking.stop()
    assert late.volume == 0.9 and late.muted is False
    # The late session was in the record too, so a crash would still restore it.


def test_device_change_is_just_another_rescan(worker):
    """Audio can move to a different output device mid-take. The all-endpoint
    rescan ducks the new device's sessions without disturbing the old ones,
    and stop restores everything."""
    a = FakeVolume(0.6, False)
    set_sessions(worker, [(123, [a])])               # endpoint-a only
    ducking.start(0)
    assert a.muted
    b = FakeVolume(0.8, False)
    set_sessions(worker, [(123, [a]), (555, [b])])   # b lives on the new device
    tick(worker)                                # must not crash or restore-clear
    assert a.muted and b.muted
    ducking.stop()
    assert (a.volume, a.muted) == (0.6, False)
    assert (b.volume, b.muted) == (0.8, False)
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
    tick(worker)
    assert second.muted
    rec = json.loads(ducking.RECORD.read_text())
    assert len(rec["sessions"]) == 2 and all(s["key"] for s in rec["sessions"])
    tick(worker)          # a re-enumeration must not overwrite the originals
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


def test_capture_privacy_mutes_other_capture_sessions_and_restores(worker, monkeypatch):
    mine = FakeVolume(0.8, False)
    discord = FakeVolume(0.6, False)
    already_muted = FakeVolume(0.5, True)
    monkeypatch.setattr(ducking, "_enumerate_capture",
                        lambda: [("mine", ducking.os.getpid(), .8, False, mine),
                                 ("discord", 123, .6, False, discord),
                                 ("muted", 456, .5, True, already_muted)])
    ducking.start_capture_privacy()
    assert not mine.muted
    assert discord.muted and already_muted.muted
    ducking.stop_capture_privacy()
    assert (discord.volume, discord.muted) == (.6, False)
    assert (already_muted.volume, already_muted.muted) == (.5, True)


def test_capture_privacy_fails_closed_if_any_foreign_session_cannot_mute(worker, monkeypatch):
    good, bad = FakeVolume(.7, False), FakeVolume(.4, False)
    def fail_mute(muted, ctx=None):
        raise RuntimeError("access denied")
    bad.SetMute = fail_mute
    monkeypatch.setattr(ducking, "_enumerate_capture",
                        lambda: [("good", 123, .7, False, good), ("bad", 456, .4, False, bad)])
    ok, err = worker.call(lambda state: ducking._start_capture_privacy(state))
    assert not ok and isinstance(err, RuntimeError)
    assert not good.muted
    assert not worker.state.capture_active


def test_capture_privacy_rescan_mutes_new_sessions_and_restores_them(worker, monkeypatch):
    first = FakeVolume(.7, False)
    current = [("first", 123, .7, False, first)]
    monkeypatch.setattr(ducking, "_enumerate_capture", lambda: current)
    ducking.start_capture_privacy()
    late = FakeVolume(.4, False)
    current.append(("late", 456, .4, False, late))
    tick(worker)
    assert first.muted and late.muted
    ducking.stop_capture_privacy()
    assert (first.volume, first.muted) == (.7, False)
    assert (late.volume, late.muted) == (.4, False)
    assert not ducking.MIC_RECORD.exists()


def test_failed_capture_privacy_rescan_sets_nonblocking_failure(worker, monkeypatch):
    first = FakeVolume(.7, False)
    current = [("first", 123, .7, False, first)]
    monkeypatch.setattr(ducking, "_enumerate_capture", lambda: current)
    ducking.start_capture_privacy()
    late = FakeVolume(.4, False)
    original_set_mute = late.SetMute
    def reject_mute(muted, ctx=None):
        if muted:
            raise RuntimeError("session refused mute")
        original_set_mute(muted, ctx)
    late.SetMute = reject_mute
    current.append(("late", 456, .4, False, late))
    tick(worker)
    assert ducking.capture_privacy_failed()
    assert not first.muted and not late.muted
    ducking.stop_capture_privacy()


def test_capture_privacy_crash_recovery_restores_saved_sessions(worker, monkeypatch):
    session = FakeVolume(1.0, True)
    monkeypatch.setattr(ducking, "_enumerate_capture",
                        lambda: [("session-key", 123, 1.0, True, session)])
    ducking.MIC_RECORD.write_text(json.dumps({"version": 1, "sessions": [
        {"key": "session-key", "pid": 123, "volume": .35, "muted": False}]}))
    ducking._recover_capture_privacy()
    assert (session.volume, session.muted) == (.35, False)
    assert not ducking.MIC_RECORD.exists()


# ------------------------------------------------- 2026-10-24 audit regressions

def test_rescan_does_not_resend_a_mute_already_in_place(worker):
    """Every re-scan used to call SetMute on every session, so each app got a
    volume-change notice four times a second for the whole take."""
    a = CountingVolume(0.6, False)
    set_sessions(worker, [(123, [a])])
    ducking.start(0)
    for _ in range(3):
        tick(worker)
    assert a.mute_calls == 1
    ducking.stop()
    assert (a.volume, a.muted) == (0.6, False)


def test_dropping_to_a_level_never_makes_a_quieter_app_louder(worker):
    quiet = FakeVolume(0.10, False)
    loud = FakeVolume(0.90, False)
    set_sessions(worker, [(123, [quiet]), (456, [loud])])
    ducking.start(25)
    assert quiet.volume == 0.10
    assert loud.volume == 0.25
    ducking.stop()
    assert (quiet.volume, loud.volume) == (0.10, 0.90)


def test_worker_catches_a_session_that_starts_mid_take_on_its_own(live_worker, monkeypatch):
    """Nobody queues re-scans any more: the worker finds new sessions itself."""
    first, late = FakeVolume(0.6, False), FakeVolume(0.9, False)
    current = [("a", 123, first)]
    monkeypatch.setattr(ducking, "_enumerate", lambda: [(k, p, v.volume, v.muted, v) for k, p, v in current])
    ducking.start(0)
    current.append(("b", 555, late))
    deadline = time.monotonic() + 5
    while not late.muted and time.monotonic() < deadline:
        time.sleep(0.02)
    assert late.muted
    ducking.stop()
    assert (first.muted, late.muted) == (False, False)


def test_restore_is_not_held_up_by_slow_scans(live_worker, monkeypatch):
    """The hotkey loop used to queue a full re-scan every 250 ms. A scan took
    100-185 ms, so long takes built a backlog and the restore at the end
    waited behind it until it timed out (log, 2026-10-24 12:29 AM)."""
    a = FakeVolume(0.6, False)

    def slow():
        time.sleep(0.2)
        return [("a", 123, a.volume, a.muted, a)]
    monkeypatch.setattr(ducking, "_enumerate", slow)
    ducking.start(0)
    time.sleep(1.0)
    t = time.monotonic()
    ducking.stop()
    assert time.monotonic() - t < 1.5   # one scan in flight at most; the old backlog took 8 s
    assert (a.volume, a.muted) == (0.6, False)


def test_mic_restore_skips_sessions_whose_app_has_exited(worker, monkeypatch):
    gone = FakeVolume(.6, False)
    monkeypatch.setattr(ducking, "_enumerate_capture", lambda: [("gone", 4242, gone.volume, gone.muted, gone)])
    ducking.start_capture_privacy()

    def expired(*a, **k):
        raise OSError("the session expired with its app")
    gone.SetMute = gone.SetMasterVolume = expired
    monkeypatch.setattr(ducking, "_pid_alive", lambda pid: False)
    ducking.stop_capture_privacy()
    assert not worker.state.capture_muted and not worker.state.capture_active
    assert not ducking.MIC_RECORD.exists()


def test_a_failed_mic_restore_is_retried_until_it_works(worker, monkeypatch, caplog):
    """A restore that failed used to wait for the next app start, so a call
    partner could not hear you until then."""
    caplog.set_level(logging.INFO, logger="freedictate")
    s = FakeVolume(.6, False)
    monkeypatch.setattr(ducking, "_enumerate_capture", lambda: [("s", 4242, s.volume, s.muted, s)])
    monkeypatch.setattr(ducking, "_pid_alive", lambda pid: True)
    ducking.start_capture_privacy()
    real = FakeVolume.SetMute

    def busy(m, ctx=None):
        if not m:
            raise OSError("busy")
        real(s, m)
    s.SetMute = busy
    ducking.stop_capture_privacy()
    assert s.muted and ducking.MIC_RECORD.exists()
    del s.SetMute
    tick(worker)
    assert not s.muted
    assert not ducking.MIC_RECORD.exists()
    assert "Microphone privacy off: 1 capture session(s) restored" in caplog.text


# ------------------------------------- 2026-10-24 endpoint mute (call partner heard you)

def endpoints(monkeypatch, *eps):
    """eps: (endpoint id, FakeVolume standing in for IAudioEndpointVolume, reader names)."""
    monkeypatch.setattr(ducking, "_enumerate_capture_endpoints", lambda: list(eps))


def test_privacy_mutes_every_other_mic_device_and_leaves_ours_alone(worker, monkeypatch):
    """Discord heard the user through a take with only its session muted, so
    privacy also mutes the device itself, the way the Windows mute does."""
    monkeypatch.setattr(ducking, "_enumerate_capture", lambda: [])
    ours, discord, user_muted = FakeVolume(1, False), FakeVolume(1, False), FakeVolume(1, True)
    endpoints(monkeypatch, ("ours", ours, set()), ("discord", discord, {"discord.exe"}),
              ("user-muted", user_muted, set()))
    ducking.start_capture_privacy("ours")
    assert discord.muted and not ours.muted
    rec = json.loads(ducking.MIC_RECORD.read_text())
    assert rec["endpoints"] == ["discord"]
    ducking.stop_capture_privacy()
    assert not discord.muted and not ours.muted
    assert user_muted.muted            # the user's own mute is not ours to undo
    assert not ducking.MIC_RECORD.exists()


def test_privacy_never_mutes_a_device_an_audio_router_is_reading(worker, monkeypatch):
    """Voicemeeter or a mixer may read the hardware mic and feed our virtual
    input; muting the hardware would silence the take itself."""
    monkeypatch.setattr(ducking, "_enumerate_capture", lambda: [])
    hw = FakeVolume(1, False)
    endpoints(monkeypatch, ("hw", hw, {"voicemeeter8x64.exe", "discord.exe"}))
    ducking.start_capture_privacy("virtual")
    assert not hw.muted
    ducking.stop_capture_privacy()


def test_privacy_mutes_a_device_that_appears_mid_take(worker, monkeypatch):
    monkeypatch.setattr(ducking, "_enumerate_capture", lambda: [])
    headset = FakeVolume(1, False)
    current = []
    monkeypatch.setattr(ducking, "_enumerate_capture_endpoints", lambda: list(current))
    ducking.start_capture_privacy("ours")
    current.append(("headset", headset, set()))
    tick(worker)
    assert headset.muted
    ducking.stop_capture_privacy()
    assert not headset.muted


def test_privacy_skips_every_device_when_ours_is_unknown(worker, monkeypatch):
    """Without knowing which device the take records from, endpoint mute
    could silence the take; session mute still runs."""
    monkeypatch.setattr(ducking, "_enumerate_capture", lambda: [])
    a = FakeVolume(1, False)
    endpoints(monkeypatch, ("a", a, set()))
    ducking.start_capture_privacy(None)
    assert not a.muted
    ducking.stop_capture_privacy()


def test_privacy_unmutes_our_own_device_if_a_crash_left_it_muted(worker, monkeypatch):
    monkeypatch.setattr(ducking, "_enumerate_capture", lambda: [])
    ours = FakeVolume(1, True)
    endpoints(monkeypatch, ("ours", ours, set()))
    ducking.MIC_RECORD.write_text(json.dumps({"version": 1, "sessions": [], "endpoints": ["ours"]}))
    ducking._recover_capture_privacy()
    assert not ours.muted
    assert not ducking.MIC_RECORD.exists()


def test_session_mute_is_reasserted_when_an_app_unmutes_itself(worker, monkeypatch):
    s = FakeVolume(.6, False)
    monkeypatch.setattr(ducking, "_enumerate_capture", lambda: [("s", 123, s.volume, s.muted, s)])
    ducking.start_capture_privacy()
    s.muted = False                    # the app turned its own mute off
    tick(worker)
    assert s.muted
    ducking.stop_capture_privacy()
    assert not s.muted


class LinkedMute:
    """Devices that share one mute switch, like VB-Audio's VAIO devices."""

    def __init__(self):
        self.muted = False

    def device(self):
        group = self

        class Device(FakeVolume):
            def GetMute(self):
                return group.muted

            def SetMute(self, m, ctx=None):
                group.muted = bool(m)
        return Device()


def test_devices_sharing_a_mute_switch_are_all_put_back(worker, monkeypatch):
    """Muting VAIO 2 muted VAIO 1 too (measured 2026-10-24 8:12 AM)."""
    monkeypatch.setattr(ducking, "_enumerate_capture", lambda: [])
    vaio = LinkedMute()
    ours, discord, visualizer = vaio.device(), vaio.device(), vaio.device()
    endpoints(monkeypatch, ("visualizer", visualizer, set()), ("ours", ours, set()),
              ("discord", discord, {"discord.exe"}))
    ducking.start_capture_privacy("ours")
    assert vaio.muted
    assert set(json.loads(ducking.MIC_RECORD.read_text())["endpoints"]) == {"visualizer", "ours", "discord"}
    tick(worker)
    ducking.stop_capture_privacy()
    assert not vaio.muted
    assert not ducking.MIC_RECORD.exists()


def test_a_shared_take_keeps_its_own_device_unmuted(worker, monkeypatch):
    monkeypatch.setattr(ducking, "_enumerate_capture", lambda: [])
    vaio = LinkedMute()
    endpoints(monkeypatch, ("ours", vaio.device(), set()), ("discord", vaio.device(), set()))
    ducking.start_capture_privacy("ours")
    ducking.capture_is_shared()
    assert not vaio.muted
    tick(worker)                       # the re-scan must not mute it again
    assert not vaio.muted
    ducking.stop_capture_privacy()
    assert not vaio.muted
