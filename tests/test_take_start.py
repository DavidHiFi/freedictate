"""The order things happen when a take starts, with mic privacy on.

Other apps' microphones must be silenced before ours opens: Discord heard the
first half second of every take while the old order (duck output, open the
mic, then mute other mics) ran (measured 2026-10-24)."""
import time

import pytest

from freedictate import ducking, output
from test_stop_key import make_engine


@pytest.fixture
def started(tmp_path, monkeypatch):
    eng, hist = make_engine(tmp_path, monkeypatch, mic_privacy_while_dictating=True,
                            isolate_output_while_dictating=True, isolate_output_level=0)
    eng.model = object()
    order = []
    monkeypatch.setattr(output, "foreground_process", lambda: (0, "notepad.exe"))
    monkeypatch.setattr(ducking, "start_capture_privacy", lambda own=None: order.append("mute other mics"))
    monkeypatch.setattr(ducking, "stop_capture_privacy", lambda: order.append("unmute other mics"))
    monkeypatch.setattr(ducking, "start", lambda level: order.append("quiet other apps"))
    monkeypatch.setattr(ducking, "stop", lambda: order.append("restore other apps"))
    monkeypatch.setattr(eng.recorder, "start", lambda *a, **k: order.append("open our mic"))
    yield eng, order
    hist.close()


def test_other_mics_go_quiet_before_ours_opens(started):
    eng, order = started
    assert eng._begin()
    assert order == ["mute other mics", "open our mic", "quiet other apps"]


def test_a_take_still_records_when_privacy_cannot_be_turned_on(started, monkeypatch, caplog):
    """Privacy is best effort. A refusal must not stop the take: the user asked
    to dictate, and a friend's PC lost every take to this before 3.7.4."""
    eng, order = started

    def refuse(own=None):
        order.append("mute other mics")
        raise RuntimeError("the audio service went away")
    monkeypatch.setattr(ducking, "start_capture_privacy", refuse)
    assert eng._begin()
    assert order == ["mute other mics", "unmute other mics", "open our mic", "quiet other apps"]
    assert "could not be turned on" in caplog.text
    assert not any(kind == "error" for kind, _ in eng.events)


def test_writing_model_warms_up_while_you_talk(tmp_path, monkeypatch):
    """With "free memory right after each take" the writing model started from
    cold after every take: about 7 s before the text arrived (log, 2026-10-24).
    It now starts with the take and is let go when the take is done."""
    import numpy as np
    from freedictate import writer
    eng, hist = make_engine(tmp_path, monkeypatch, ai_tidy=True, ai_model="standard",
                            mic_privacy_while_dictating=False, isolate_output_while_dictating=False,
                            isolate_output_level=0)
    calls = []
    monkeypatch.setattr(writer, "hold", lambda name: calls.append(("hold", name)))
    monkeypatch.setattr(writer, "release", lambda: calls.append(("release",)))
    monkeypatch.setattr(writer, "stop", lambda: None)
    monkeypatch.setattr(output, "foreground_process", lambda: (0, "notepad.exe"))
    eng.model = object()
    try:
        assert eng._begin()
        assert calls == [("hold", "standard")]
        eng._end(cancelled=True)                       # Esc: nothing to tidy
        assert calls[-1] == ("release",)
        calls.clear()
        assert eng._begin()
        monkeypatch.setattr(eng.recorder, "stop", lambda: (np.zeros(16000, dtype=np.float32), 1.0))
        eng._end(cancelled=False)                      # queued: the transcriber lets go
        assert calls == [("hold", "standard")]
        eng._jobs.put(None)
        eng._transcribe_loop()                         # silence: dropped, still let go
        assert calls == [("hold", "standard"), ("release",)]
    finally:
        hist.close()


def test_a_stuck_transcription_is_reported(tmp_path, monkeypatch):
    """At 1:00 AM on 2026-10-24 a decode never returned, and every later take
    queued silently behind it until the app restarted."""
    import threading
    import numpy as np
    from freedictate import engine as engine_mod
    eng, hist = make_engine(tmp_path, monkeypatch)
    monkeypatch.setattr(engine_mod, "STUCK_AFTER", 0.2)
    gate = threading.Event()

    class Hung:
        def transcribe(self, *a, **k):
            gate.wait(5)
            return iter(()), None
    eng.model = Hung()
    eng.ms.active = "small.en"
    try:
        t = threading.Thread(target=eng._decode, args=(np.zeros(1600, dtype=np.float32),))
        t.start()
        deadline = time.monotonic() + 3
        while not any(k == "error" for k, _ in eng.events) and time.monotonic() < deadline:
            time.sleep(0.02)
        gate.set()
        t.join(5)
        errors = [d for k, d in eng.events if k == "error"]
        assert errors and errors[0]["title"] == "Transcription is stuck"
    finally:
        gate.set()
        hist.close()
