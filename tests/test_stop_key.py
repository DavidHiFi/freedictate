"""The stop key (Esc by default) drops a take at any point: while recording,
while it waits for the model, or while it is being transcribed or tidied."""
import numpy as np

from freedictate import hotkeys, output
from freedictate.config import Config
from freedictate.engine import Engine, Take
from freedictate.history import History


class CfgDict(dict):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._listeners = []

    def on_change(self, fn):
        self._listeners.append(fn)


def make_engine(tmp_path, monkeypatch, **overrides):
    cfg_data = {"hotkey": "ctrl+win", "hotkey_mode": "hold", "cancel_key": "esc", "model": "small.en",
                "device": "cpu", "compute_type": "int8", "cpu_threads": 0, "language": "en",
                "beam_size": 1, "vad": False, "vocabulary": "", "min_seconds": 0.4,
                "silence_peak": 0.004, "max_seconds": 600, "auto_stop_silence": 0, "input_device": "",
                "sounds": False, "sound_volume": 0, "ai_tidy": False, "ai_model": "light",
                "idle_unload": True, "idle_seconds": 0}
    cfg_data.update(overrides)
    cfg = CfgDict(cfg_data)
    hist = History(tmp_path / "h.db")
    events = []
    eng = Engine(cfg, hist, lambda kind, data: events.append((kind, data)))
    eng.events = events
    monkeypatch.setattr(eng.recorder, "start", lambda *a, **k: None)
    monkeypatch.setattr(eng.recorder, "stop", lambda: (None, 0.0))
    return eng, hist


def test_stop_key_defaults_and_coercion(tmp_path, monkeypatch):
    assert Config(tmp_path / "s.json")["cancel_key"] == "esc"
    eng, hist = make_engine(tmp_path, monkeypatch)
    try:
        assert eng._cancel_matcher.groups == [(0x1B,)]
        eng.cfg["cancel_key"] = "f8"
        eng._config_changed({"cancel_key"})
        assert eng._cancel_matcher.groups == [(0x77,)]
        eng.cfg["cancel_key"] = "not a key"
        eng._config_changed({"cancel_key"})
        assert eng._cancel_matcher.groups == [(0x1B,)], "an unknown key falls back to Esc"
    finally:
        hist.close()


def test_stop_key_while_transcribing_drops_the_take(tmp_path, monkeypatch):
    eng, hist = make_engine(tmp_path, monkeypatch)
    try:
        eng.model = object()
        eng.state = "transcribing"
        eng._take_seq = 2
        eng._cancel_queued()
        assert eng._cancelled_upto == 2
        assert eng.state == "ready"
        assert ("cancelled", {}) in eng.events

        ran = []
        monkeypatch.setattr(eng, "_decode", lambda data: ran.append(True) or "never")
        eng._do_take(Take(np.ones(16_000) * 0.5, 1.0, seq=2))
        assert ran == [], "a cancelled take must not reach the decoder"
    finally:
        hist.close()


def test_stop_key_ignored_when_nothing_is_being_transcribed(tmp_path, monkeypatch):
    eng, hist = make_engine(tmp_path, monkeypatch)
    try:
        eng.state = "ready"
        eng._take_seq = 5
        eng._cancel_queued()
        assert eng._cancelled_upto == 0
        assert ("cancelled", {}) not in eng.events
    finally:
        hist.close()


def test_take_queued_after_the_stop_key_still_runs(tmp_path, monkeypatch):
    eng, hist = make_engine(tmp_path, monkeypatch)
    try:
        eng.state = "transcribing"
        eng._take_seq = 2
        eng._cancel_queued()
        assert not eng._cancelled(Take(None, 0.0, seq=3))
        assert eng._cancelled(Take(None, 0.0, seq=2))
        assert not eng._cancelled(Take(None, 0.0, seq=0)), "file transcriptions are never dropped"
    finally:
        hist.close()


def test_stop_key_during_decode_drops_text_before_tidy_and_paste(tmp_path, monkeypatch):
    eng, hist = make_engine(tmp_path, monkeypatch)
    try:
        eng.model = object()
        eng._take_seq = 1
        take = Take(np.ones(16_000) * 0.5, 1.0, seq=1)

        def decode_then_stop(data):
            eng._cancelled_upto = 1          # the stop key arrives while the model runs
            return "hello there"

        monkeypatch.setattr(eng, "_decode", decode_then_stop)
        monkeypatch.setattr(eng, "_tidy", lambda text: (_ for _ in ()).throw(AssertionError("tidy ran")))
        pasted = []
        monkeypatch.setattr(output, "deliver", lambda *a, **k: pasted.append(a) or "pasted")
        eng._do_take(take)
        assert pasted == []
        assert not [e for e in eng.events if e[0] in ("result", "nothing")]
    finally:
        hist.close()


def test_stop_key_while_recording_also_drops_queued_takes(tmp_path, monkeypatch):
    eng, hist = make_engine(tmp_path, monkeypatch)
    try:
        eng.state = "listening"
        eng._take_seq = 4
        eng._end(True)
        assert eng._cancelled_upto == 4
        assert ("cancelled", {}) in eng.events
    finally:
        hist.close()


def test_wait_for_model_gives_up_when_the_take_is_cancelled(tmp_path, monkeypatch):
    eng, hist = make_engine(tmp_path, monkeypatch)
    try:
        eng.model = None
        eng.ms.status = "loading"
        assert eng._wait_for_model(timeout=5, abort=lambda: True) is False
    finally:
        hist.close()


def test_hotkey_overlap_is_refused_both_ways():
    assert hotkeys.overlaps("ctrl+win", "lctrl")
    assert hotkeys.overlaps("esc", "esc")
    assert not hotkeys.overlaps("ctrl+win", "esc")
    assert hotkeys.label("esc") == "Esc"
