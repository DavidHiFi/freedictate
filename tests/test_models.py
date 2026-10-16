import hashlib
import json

from freedictate import models


def _fake_model(tmp_path, monkeypatch, files: dict[str, bytes]):
    folder = tmp_path / "model"
    folder.mkdir()
    for name, data in files.items():
        (folder / name).write_bytes(data)
    monkeypatch.setattr(models, "local_path", lambda name: folder)
    return folder


def test_manifest_round_trip(tmp_path, monkeypatch):
    _fake_model(tmp_path, monkeypatch, {"model.bin": b"weights", "config.json": b"{}"})
    assert models.write_manifest("small.en") is not None
    assert models.manifest_state("small.en") == ("ok", "")
    assert models.manifest_state("small.en", full=True) == ("ok", "")


def test_manifest_catches_a_changed_file(tmp_path, monkeypatch):
    folder = _fake_model(tmp_path, monkeypatch, {"model.bin": b"weights"})
    models.write_manifest("small.en")
    (folder / "model.bin").write_bytes(b"corrupted")
    state, detail = models.manifest_state("small.en")
    assert state == "broken" and "model.bin" in detail
    state, detail = models.manifest_state("small.en", full=True)
    assert state == "broken" and "model.bin" in detail


def test_manifest_catches_a_size_change_without_hashing(tmp_path, monkeypatch):
    folder = _fake_model(tmp_path, monkeypatch, {"model.bin": b"weights"})
    models.write_manifest("small.en")
    (folder / "model.bin").write_bytes(b"weights plus")
    assert models.manifest_state("small.en")[0] == "broken"


def test_no_manifest_says_none(tmp_path, monkeypatch):
    _fake_model(tmp_path, monkeypatch, {"model.bin": b"weights"})
    assert models.manifest_state("small.en") == ("none", "")


def test_manifest_records_exact_sizes_and_hashes(tmp_path, monkeypatch):
    folder = _fake_model(tmp_path, monkeypatch, {"model.bin": b"weights"})
    models.write_manifest("small.en")
    entries = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["files"]
    assert entries == [{"path": "model.bin", "size": 7,
                        "sha256": hashlib.sha256(b"weights").hexdigest()}]


def test_parakeet_v3_is_a_multilingual_cpu_model():
    info = models.BY_NAME["parakeet-tdt-0.6b-v3"]
    assert info.engine == "parakeet"
    assert not info.english_only
    assert info.repo == "istupakov/parakeet-tdt-0.6b-v3-onnx"
    assert "encoder-model.int8.onnx" in models._FILES["parakeet"]
