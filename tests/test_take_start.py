"""The order things happen when a take starts, with mic privacy on.

Other apps' microphones must be silenced before ours opens: Discord heard the
first half second of every take while the old order (duck output, open the
mic, then mute other mics) ran (measured 2026-10-24)."""
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
    monkeypatch.setattr(ducking, "start_capture_privacy", lambda: order.append("mute other mics"))
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


def test_mic_never_opens_when_privacy_cannot_be_turned_on(started, monkeypatch):
    eng, order = started

    def refuse():
        order.append("mute other mics")
        raise RuntimeError("a capture session refused mute")
    monkeypatch.setattr(ducking, "start_capture_privacy", refuse)
    assert not eng._begin()
    assert "open our mic" not in order and "quiet other apps" not in order
    assert order[-1] == "unmute other mics"
    assert any(kind == "error" for kind, _ in eng.events)
