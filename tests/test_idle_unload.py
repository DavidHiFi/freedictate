"""Idle VRAM release: the speech model unloads after a while without dictation."""
import time

from freedictate import models, writer
from freedictate.config import Config
from freedictate.engine import Engine
from freedictate.history import History


class CfgDict(dict):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._listeners = []

    def get(self, k, d=None):
        return super().get(k, d)

    def __getitem__(self, k):
        return super().__getitem__(k)

    def on_change(self, fn):
        self._listeners.append(fn)


def make_engine(tmp_path, monkeypatch, **overrides):
    cfg_data = {"hotkey": "ctrl+win", "hotkey_mode": "hold", "model": "small.en",
                "device": "cpu", "compute_type": "int8", "cpu_threads": 0,
                "language": "en", "beam_size": 1, "vad": False, "vocabulary": "",
                "min_seconds": 0.4, "silence_peak": 0.004, "max_seconds": 600,
                "auto_stop_silence": 0, "input_device": "", "sounds": False,
                "sound_volume": 0, "ai_tidy": False, "ai_model": "light",
                "idle_unload": True, "idle_minutes": 5}
    cfg_data.update(overrides)
    cfg = CfgDict(cfg_data)
    hist = History(tmp_path / "h.db")
    events = []
    eng = Engine(cfg, hist, lambda kind, data: events.append((kind, data)))
    eng.events = events
    # Don't touch real audio/hardware in tests.
    monkeypatch.setattr(eng.recorder, "start", lambda *a, **k: None)
    monkeypatch.setattr(eng.recorder, "stop", lambda: (None, 0.0))
    return eng, hist


def test_idle_unload_defaults_and_coercion(tmp_path):
    c = Config(tmp_path / "s.json")
    assert c["idle_unload"] is True
    assert c["idle_minutes"] == 5
    c.update({"idle_minutes": 500})
    assert c["idle_minutes"] == 120
    c.update({"idle_minutes": 0})
    assert c["idle_minutes"] == 1


def test_unload_frees_model_and_emits(tmp_path, monkeypatch):
    eng, hist = make_engine(tmp_path, monkeypatch)
    try:
        eng.model = object()
        eng.ms.active, eng.ms.device, eng.ms.compute = "small.en", "cpu", "int8"
        eng.ms.status = "idle"
        freed = []
        monkeypatch.setattr(models, "free_memory", lambda: freed.append(True))
        assert eng.unload_model("test") is True
        assert eng.model is None
        assert eng.ms.active == ""
        assert freed == [True]
        assert ("model", {"unloaded": True}) in eng.events
        # Nothing to free twice.
        assert eng.unload_model("test") is False
    finally:
        hist.close()


def test_unload_refuses_while_busy(tmp_path, monkeypatch):
    eng, hist = make_engine(tmp_path, monkeypatch)
    try:
        eng.model = object()
        eng.ms.active = "small.en"
        eng.ms.status = "idle"
        eng.state = "listening"
        assert eng.unload_model() is False
        eng.state = "ready"
        eng.ms.status = "downloading"
        assert eng.unload_model() is False
        eng.ms.status = "idle"
        assert eng.unload_model() is True
    finally:
        hist.close()


def test_unload_waits_out_a_file_decode(tmp_path, monkeypatch):
    """A file transcription holds the decode lock, so an idle check mid-file
    must not pull the model out from under it."""
    eng, hist = make_engine(tmp_path, monkeypatch)
    try:
        eng.model = object()
        eng.ms.active = "small.en"
        eng.ms.status = "idle"
        eng.state = "ready"
        with eng._decode_lock:
            assert eng.unload_model() is False
            assert eng.model is not None
        assert eng.unload_model() is True
    finally:
        hist.close()


def test_usable_when_unloaded_and_status_text_mentions_vram(tmp_path, monkeypatch):
    eng, hist = make_engine(tmp_path, monkeypatch)
    try:
        eng.model = None
        eng.ms.active = ""
        eng.ms.status = "idle"
        eng.state = "ready"
        assert eng._usable() is True
        assert "VRAM" in eng.status_text()
        eng.paused = True
        assert eng._usable() is False
    finally:
        hist.close()


def test_pause_unloads_and_resume_reloads(tmp_path, monkeypatch):
    eng, hist = make_engine(tmp_path, monkeypatch)
    try:
        eng.model = object()
        eng.ms.active = "small.en"
        eng.ms.status = "idle"
        eng.state = "ready"
        eng.toggle_pause()
        assert eng.paused is True
        assert eng.model is None
        calls = []
        monkeypatch.setattr(eng, "ensure_model", lambda force=False: calls.append(force))
        eng.toggle_pause()
        assert eng.paused is False
        assert calls, "resuming should reload the model"
    finally:
        hist.close()


def test_wait_for_model_returns_quickly_when_ready(tmp_path, monkeypatch):
    eng, hist = make_engine(tmp_path, monkeypatch)
    try:
        eng.model = object()
        assert eng._wait_for_model(timeout=1) is True
        eng.model = None
        eng.ms.status = "failed"
        assert eng._wait_for_model(timeout=1) is False
    finally:
        hist.close()


def test_writer_idle_timeout_follows_setting(tmp_path, monkeypatch):
    eng, hist = make_engine(tmp_path, monkeypatch, idle_minutes=2)
    try:
        seen = []
        monkeypatch.setattr(writer, "set_idle_seconds", lambda s: seen.append(s))
        eng._apply_idle_settings()
        assert seen == [120]
        assert eng._idle_seconds() == 120
        assert writer.IDLE_STOP_S == 5 * 60
    finally:
        hist.close()
        try:
            writer.set_idle_seconds(5 * 60)
        except Exception:
            pass
