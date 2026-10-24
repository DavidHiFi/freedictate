"""The speech stack must be the pinned build, with the calls faster-whisper makes."""
import re
from pathlib import Path

import pytest
import tokenizers

from freedictate import models

REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"


def test_tokenizers_is_the_version_requirements_pins():
    pin = re.search(r"(?m)^tokenizers==(\S+)", REQUIREMENTS.read_text(encoding="utf-8")).group(1)
    assert tokenizers.__version__ == pin


def test_the_tokenizer_faster_whisper_uses_reads_every_special_token():
    assert models.check_tokenizer() == "7 special tokens read"


def test_a_tokenizers_without_token_to_id_fails_the_check(monkeypatch):
    """2026-10-24: tokenizers without token_to_id loaded, then failed every take."""
    class NoTokenToId:
        def __init__(self, model):
            pass
    monkeypatch.setattr(tokenizers, "Tokenizer", NoTokenToId)
    with pytest.raises(AttributeError, match="token_to_id"):
        models.check_tokenizer()
