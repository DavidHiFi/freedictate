import io
import json
import sqlite3

import numpy as np

from freedictate import history, models, tidy


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_ollama(monkeypatch, answer: str, thinking: bool = False):
    sent = []

    def request(path, body=None, timeout=5.0):
        sent.append((path, body))
        if path == "/api/show":
            return _Resp(json.dumps({"capabilities": ["completion"] + (["thinking"] if thinking else [])}).encode())
        return _Resp(json.dumps({"message": {"content": answer}}).encode())
    monkeypatch.setattr(tidy, "_request", request)
    tidy._thinking.clear()
    return sent


TAKE = "I want, I want you to update the readme and then and then push it to GitHub when the tests pass"


def test_rewrite_returns_clean_text_and_strips_wrappers(monkeypatch):
    _fake_ollama(monkeypatch, "Here is the cleaned text:\n\"I want you to update the readme and then push it "
                              "to GitHub when the tests pass.\"")
    out = tidy.rewrite(TAKE, "m")
    assert out == "I want you to update the readme and then push it to GitHub when the tests pass."


def test_rewrite_rejects_an_answer_instead_of_the_text(monkeypatch):
    _fake_ollama(monkeypatch, "Sure, I can help with that.")
    assert tidy.rewrite(TAKE, "m") is None


def test_a_changed_number_is_rejected(monkeypatch):
    take = "it was using like 10 percent of my CPU and then and then the other one was at 40"
    _fake_ollama(monkeypatch, "It was using about -10 percent of my CPU, and the other one was at 40.")
    assert tidy.rewrite(take, "m") is None


def test_think_is_only_sent_to_reasoning_models(monkeypatch):
    sent = _fake_ollama(monkeypatch, TAKE, thinking=False)
    tidy.rewrite(TAKE, "plain")
    assert "think" not in [b for p, b in sent if p == "/api/chat"][0]
    sent = _fake_ollama(monkeypatch, TAKE, thinking=True)
    tidy.rewrite(TAKE, "reasoner")
    assert [b for p, b in sent if p == "/api/chat"][0]["think"] is False


def test_dashes_bold_and_curly_quotes_are_normalised(monkeypatch):
    _fake_ollama(monkeypatch, "I want you to update the readme — and then push it to GitHub when the "
                              "tests pass. **Don’t** wait.")
    out = tidy.rewrite(TAKE + " don't wait", "m")
    assert out == "I want you to update the readme, and then push it to GitHub when the tests pass. Don't wait."


def test_short_takes_skip_the_model(monkeypatch):
    sent = _fake_ollama(monkeypatch, "x")
    assert tidy.rewrite("yes please", "m") is None
    assert sent == []


def test_history_keeps_the_original_and_migrates_old_databases(tmp_path):
    db = tmp_path / "h.db"
    old = sqlite3.connect(db)
    old.executescript("CREATE TABLE entries (id INTEGER PRIMARY KEY, ts REAL NOT NULL, seconds REAL NOT NULL "
                      "DEFAULT 0, words INTEGER NOT NULL DEFAULT 0, text TEXT NOT NULL, model TEXT NOT NULL "
                      "DEFAULT '', app TEXT NOT NULL DEFAULT '');"
                      "INSERT INTO entries(ts, text) VALUES (1, 'old take');")
    old.close()
    h = history.History(db)
    try:
        h.add("tidy", 2.0, raw="the the tidy")
        entries = {e.text: e for e in h.search()}
        assert entries["old take"].raw == ""
        assert entries["tidy"].raw == "the the tidy"
    finally:
        h.close()


def test_parakeet_is_wired_to_its_own_repo_and_files():
    info = models.BY_NAME["parakeet-tdt-0.6b-v2"]
    assert info.engine == "parakeet" and not info.prompts and info.english_only
    assert models.repo_id(info.name) == "istupakov/parakeet-tdt-0.6b-v2-onnx"
    assert models.repo_id("large-v3") == "Systran/faster-whisper-large-v3"
    assert models.BY_NAME["large-v3"].prompts


def test_parakeet_splits_long_takes_into_chunks():
    m = models.ParakeetModel.__new__(models.ParakeetModel)
    seen = []

    class Rec:
        def recognize(self, chunks, sample_rate):
            seen.append([len(c) for c in chunks])
            return [f"part{i}." for i in range(len(chunks))]
    m._m = Rec()
    short = np.zeros(16000 * 5, dtype=np.float32)
    text = next(m.transcribe(short, vad_filter=False)[0]).text
    assert seen[-1] == [len(short)] and text == "part0."
    # A long take goes through the VAD; silence alone gives nothing to decode.
    long = np.zeros(16000 * 90, dtype=np.float32)
    assert next(m.transcribe(long)[0]).text == ""


def test_both_engines_load_through_models_load(monkeypatch, tmp_path):
    """models.load must reach each engine's real constructor (a dropped import
    once broke every Whisper model while all unit tests passed)."""
    import faster_whisper
    calls = []

    class FakeWhisper:
        def __init__(self, *a, **k):
            calls.append("whisper")

        def transcribe(self, *a, **k):
            return iter([]), None
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisper)
    monkeypatch.setattr(models, "local_path", lambda name: tmp_path)
    monkeypatch.setattr(models, "resolve_device", lambda d, c: ("cpu", "int8"))
    m, dev, ct = models.load("tiny.en", "cpu", "int8")
    assert calls == ["whisper"] and (dev, ct) == ("cpu", "int8")

    class FakeParakeet(models.ParakeetModel):
        def __init__(self, path, cpu_threads=0):
            calls.append("parakeet")
    monkeypatch.setattr(models, "ParakeetModel", FakeParakeet)
    monkeypatch.setattr(FakeParakeet, "transcribe", lambda self, a, **k: (iter([]), None))
    m, dev, ct = models.load("parakeet-tdt-0.6b-v2", "cuda", "auto")
    assert calls[-1] == "parakeet" and (dev, ct) == ("cpu", "int8")
