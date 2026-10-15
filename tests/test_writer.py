import sqlite3

import numpy as np

from freedictate import history, models, writer


def _fake_model(monkeypatch, answer: str):
    """Writing model that is ready and answers with ``answer``."""
    sent = []
    monkeypatch.setattr(writer, "ready", lambda name: "")
    monkeypatch.setattr(writer._server, "ensure", lambda name, wait=60.0: True)

    def chat(system, text, timeout):
        sent.append((system, text))
        return answer
    monkeypatch.setattr(writer._server, "chat", chat)
    return sent


TAKE = "I want, I want you to update the readme and then and then push it to GitHub when the tests pass"


def test_rewrite_returns_clean_text_and_strips_wrappers(monkeypatch):
    _fake_model(monkeypatch, "Here is the cleaned text:\n\"I want you to update the readme and then push it "
                             "to GitHub when the tests pass.\"")
    out = writer.rewrite(TAKE, "standard")
    assert out == "I want you to update the readme and then push it to GitHub when the tests pass."


def test_rewrite_rejects_an_answer_instead_of_the_text(monkeypatch):
    _fake_model(monkeypatch, "Sure, I can help with that.")
    assert writer.rewrite(TAKE, "standard") is None


def test_a_changed_number_is_rejected(monkeypatch):
    take = "it was using like 10 percent of my CPU and then and then the other one was at 40"
    _fake_model(monkeypatch, "It was using about -10 percent of my CPU, and the other one was at 40.")
    assert writer.rewrite(take, "standard") is None


def test_vocabulary_reaches_the_prompt(monkeypatch):
    sent = _fake_model(monkeypatch, TAKE)
    writer.rewrite(TAKE, "standard", "TestCord, , MochaCord")
    assert sent[0][0].endswith("Spell these names exactly as written: TestCord, MochaCord.")


def test_dashes_bold_and_curly_quotes_are_normalised(monkeypatch):
    _fake_model(monkeypatch, "I want you to update the readme \u2014 and then push it to GitHub when the "
                             "tests pass. **Don\u2019t** wait.")
    out = writer.rewrite(TAKE + " don't wait", "standard")
    assert out == "I want you to update the readme, and then push it to GitHub when the tests pass. Don't wait."


def test_short_takes_and_unready_models_skip_the_model(monkeypatch):
    sent = _fake_model(monkeypatch, "x")
    assert writer.rewrite("yes please", "standard") is None
    monkeypatch.setattr(writer, "ready", lambda name: "Not downloaded yet.")
    assert writer.rewrite(TAKE, "standard") is None
    assert sent == []


def test_without_a_graphics_card_the_tidy_up_stays_off(monkeypatch):
    monkeypatch.setattr(writer, "engine_installed", lambda: True)
    monkeypatch.setattr(writer, "gpu", lambda: ("", 0))
    assert "graphics card" in writer.ready("standard")
    monkeypatch.setattr(writer, "gpu", lambda: ("NVIDIA GeForce RTX 4070", 12010))
    monkeypatch.setattr(writer, "model_path", lambda name: None)
    assert writer.ready("standard") == "Not downloaded yet."
    assert writer.recommended() == "standard"
    monkeypatch.setattr(writer, "gpu", lambda: ("Small card", 4096))
    assert writer.recommended() == "light"


def test_writing_models_are_pinned():
    for m in writer.CATALOG:
        assert len(m.revision) == 40 and m.file.endswith(".gguf") and m.size_mb > 0
    assert len(writer.ENGINE_SHA256) == 64 and writer.ENGINE_TAG in writer.ENGINE_URL


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


def test_local_path_finds_a_sha_pinned_download(tmp_path, monkeypatch):
    """A download pinned to a commit SHA writes no refs/main entry, so
    snapshot_download can't resolve it on a cache this app filled itself.
    3.4.0 regression: fresh installs said "isn't downloaded" right after a
    completed download (Parakeet), and Whisper models re-downloaded."""
    monkeypatch.setattr(models, "cache_dir", lambda: str(tmp_path))
    snap = tmp_path / "models--istupakov--parakeet-tdt-0.6b-v2-onnx" / "snapshots" / ("0" * 40)
    snap.mkdir(parents=True)
    for f in ("config.json", "vocab.txt", "nemo128.onnx", "encoder-model.int8.onnx",
              "decoder_joint-model.int8.onnx"):
        (snap / f).write_text("x", encoding="utf-8")
    assert models.local_path("parakeet-tdt-0.6b-v2") == snap
    assert models.is_downloaded("parakeet-tdt-0.6b-v2") is True
    # An incomplete download (no main file yet) is still not downloaded.
    (snap / "encoder-model.int8.onnx").unlink()
    assert models.local_path("parakeet-tdt-0.6b-v2") is None
    assert models.is_downloaded("parakeet-tdt-0.6b-v2") is False


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
    assert calls[-1] == "parakeet" and (dev, ct) == ("cpu", "int8")   # Parakeet is CPU by design
