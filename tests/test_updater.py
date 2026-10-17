import hashlib
import io

import pytest

from freedictate import updater


class _Resp(io.BytesIO):
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _release(assets):
    return updater.Release("3.6.0", "v3.6.0", "", "", "", False, assets)


def _serve(monkeypatch, tmp_path, sums: bytes | None, payload: bytes):
    """Fake the GitHub downloads. Returns the list of URLs fetched."""
    fetched = []

    def fake_get(url, timeout=20):
        fetched.append(url)
        if url == "sums-url":
            return _Resp(sums or b"")
        return _Resp(payload)

    monkeypatch.setattr(updater, "_get", fake_get)
    monkeypatch.setattr(updater.paths, "portable", lambda: True)
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    return fetched


ZIP = "FreeDictate-3.6.0-Portable.zip"


def test_download_refuses_when_the_release_has_no_checksum_file(monkeypatch, tmp_path):
    fetched = _serve(monkeypatch, tmp_path, None, b"zip")
    rel = _release({ZIP: "zip-url"})
    with pytest.raises(RuntimeError, match="no checksum"):
        updater.download(rel)
    assert "zip-url" not in fetched, "the file must not be fetched when it can't be verified"


def test_download_refuses_when_the_checksum_file_omits_the_asset(monkeypatch, tmp_path):
    sums = b"0" * 64 + b"  FreeDictate-3.6.0-Setup.exe\n"
    fetched = _serve(monkeypatch, tmp_path, sums, b"zip")
    rel = _release({ZIP: "zip-url", "SHA256SUMS": "sums-url"})
    with pytest.raises(RuntimeError, match="no checksum"):
        updater.download(rel)
    assert "zip-url" not in fetched


def test_download_keeps_a_file_that_matches_its_checksum(monkeypatch, tmp_path):
    payload = b"portable zip bytes"
    sums = hashlib.sha256(payload).hexdigest().encode() + b"  " + ZIP.encode() + b"\n"
    _serve(monkeypatch, tmp_path, sums, payload)
    rel = _release({ZIP: "zip-url", "SHA256SUMS": "sums-url"})
    path = updater.download(rel)
    assert path.read_bytes() == payload


def test_download_deletes_a_file_that_fails_its_checksum(monkeypatch, tmp_path):
    sums = b"0" * 64 + b"  " + ZIP.encode() + b"\n"
    _serve(monkeypatch, tmp_path, sums, b"tampered bytes")
    rel = _release({ZIP: "zip-url", "SHA256SUMS": "sums-url"})
    with pytest.raises(RuntimeError, match="didn't match"):
        updater.download(rel)
    assert not (tmp_path / "FreeDictate-update" / ZIP).exists()


def test_version_order():
    assert updater.newer("3.0.1", "3.0.0")
    assert updater.newer("v3.1.0", "3.0.9")
    assert not updater.newer("3.0.0", "3.0.0")
    assert updater.newer("3.0.0", "3.0.0-beta.2")
    assert updater.newer("3.0.0-beta.3", "3.0.0-beta.2")
    assert not updater.newer("2.9", "3.0.0")


def test_prerelease_ranking():
    assert updater.newer("3.1.0-rc.1", "3.1.0-beta.2")
    assert not updater.newer("3.1.0-beta.1", "3.1.0-rc.1")
    assert not updater.newer("3.1.0-rc.1", "3.1.0")


def test_asset_choice():
    rel = updater.Release("3.1.0", "v3.1.0", "", "", "", False,
                          {"FreeDictate-3.1.0-Setup.exe": "u1", "FreeDictate-3.1.0-portable.zip": "u2",
                           "SHA256SUMS.txt": "u3"})
    assert updater._asset(rel, portable=False) == ("FreeDictate-3.1.0-Setup.exe", "u1")
    assert updater._asset(rel, portable=True) == ("FreeDictate-3.1.0-portable.zip", "u2")
