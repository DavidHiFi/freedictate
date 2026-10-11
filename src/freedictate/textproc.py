"""Turn Whisper's raw text into what gets pasted."""
from __future__ import annotations

import re

# Hesitation sounds only. Words like "like" or "you know" carry meaning often
# enough that removing them would change what was said.
_FILLER = re.compile(r"(?<![\w'])(?:u+m+|u+h+|e+r+m*|a+h+|h+m+|m+h*m+)(?![\w'])[,.]?\s*", re.IGNORECASE)

# "new line" / "new paragraph" spoken as a phrase. Whisper punctuates after
# them ("... done. New line. Next ..."); that trailing mark goes too, and the
# punctuation before the command stays where the speaker put it.
_COMMANDS = [
    (re.compile(r"\s*\bnew paragraph\b[,.;:!?]?\s*", re.IGNORECASE), "\n\n"),
    (re.compile(r"\s*\bnew line\b[,.;:!?]?\s*", re.IGNORECASE), "\n"),
]


def _cap_sentences(text: str) -> str:
    """Capitalize the first letter of the text and of each line."""
    def up(m: re.Match) -> str:
        return m.group(1) + m.group(2).upper()
    return re.sub(r"(^|\n)(\s*[a-z])", up, text)


def clean(raw: str, *, remove_fillers: bool = True, voice_commands: bool = True,
          capitalize: bool = True, end_punctuation: bool = True,
          replacements: list[dict] | None = None) -> str:
    text = " ".join(raw.split())
    if not text:
        return ""
    if remove_fillers:
        text = _FILLER.sub("", text)
        text = re.sub(r"\s+([,.!?])", r"\1", text)
        text = re.sub(r"^[,.\s]+", "", text)
    for r in replacements or ():
        find = r.get("find", "").strip()
        if find:
            pattern = re.compile(r"(?<!\w)" + re.escape(find) + r"(?!\w)", re.IGNORECASE)
            text = pattern.sub(lambda _m, rep=r.get("replace", ""): rep, text)
    if voice_commands:
        for pattern, rep in _COMMANDS:
            text = pattern.sub(rep, text)
    text = re.sub(r"[ \t]+", " ", text).strip(" ")
    text = text.strip("\n") if text.strip() else ""
    if not text:
        return ""
    if capitalize:
        text = _cap_sentences(text)
    if end_punctuation and text[-1].isalnum():
        text += "."
    return text


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))
