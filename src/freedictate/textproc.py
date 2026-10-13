"""Turn Whisper's raw text into what gets pasted."""
from __future__ import annotations

import re

# Hesitation sounds only. Words like "like" or "you know" carry meaning often
# enough that removing them would change what was said.
_FILLER = re.compile(r"(?<![\w'])(?:u+m+|u+h+|e+r+m*|a+h+|h+m+|m+h*m+)(?![\w'])[,.]?\s*", re.IGNORECASE)

# Private marks used while the text is being rebuilt; none survive clean().
_CAP = "\x01"      # the next letter starts a sentence
_NOSPACE_R = "\x04"  # drop the spaces that follow
_NOSPACE_L = "\x05"  # drop the spaces that come before

# Spoken commands. Whisper punctuates around them on its own ("Hello, comma,
# how are you?"); the optional marks on both sides go with the command.
# Each entry: (phrase, symbol, how it joins its neighbours)
#   attach  sticks to the word before, one space after      ,  .  ?
#   open    one space before, none after                    (  "
#   close   none before, one space after                    )  "
#   join    no space on either side                         -  _
#   word    stands alone with a space each side             *  -
#   line    starts a new line or list item
_SPOKEN: list[tuple[str, str, str]] = [
    (r"new paragraph", "\n\n" + _CAP, "line"),
    (r"new line", "\n" + _CAP, "line"),
    (r"(?:dot|bullet) point", "\n- " + _CAP, "line"),
    (r"full stop", "." + _CAP, "attach"),
    (r"question mark", "?" + _CAP, "attach"),
    (r"exclamation (?:mark|point)", "!" + _CAP, "attach"),
    (r"comma", ",", "attach"),
    (r"semi[- ]?colon", ";", "attach"),
    (r"colon", ":", "attach"),
    (r"open (?:bracket|paren(?:thesis)?)", "(", "open"),
    (r"close (?:bracket|paren(?:thesis)?)", ")", "close"),
    (r"open quote", "\"", "open"),
    (r"(?:close|end) quote", "\"", "close"),
    (r"hyphen", "-", "join"),
    (r"underscore", "_", "join"),
    (r"asterisk", "*", "word"),
    (r"dash", "-", "word"),
]
_JOINS = {
    "attach": (_NOSPACE_L, " "),
    "open": (" ", _NOSPACE_R),
    "close": (_NOSPACE_L, " "),
    "join": (_NOSPACE_L, _NOSPACE_R),
    "word": (" ", " "),
    "line": ("", ""),
}
_PUNCT = r"[,.;:!?]?"
# A line break keeps the punctuation the speaker put before it ("Dear John,
# new line"); a spoken mark replaces whatever Whisper guessed there.
_SPOKEN_RE = [(re.compile(rf"[ \t]*{'' if kind == 'line' else _PUNCT + r'[ \t]*'}\b(?:{p})\b{_PUNCT}[ \t]*",
                          re.IGNORECASE),
               _JOINS[kind][0] + rep + _JOINS[kind][1])
              for p, rep, kind in _SPOKEN]
# "literal comma" types the word itself.
_LITERAL = re.compile(r"\bliteral[,.]?\s+(" + "|".join(p for p, _, _ in _SPOKEN) + r")\b", re.IGNORECASE)

# Words people repeat on purpose, or that are correct twice in a row ("they
# had had enough", "what it is is"). Only single-word repeats need this; a
# repeated run of two or more words is always a stumble.
_REPEAT_OK = {
    "had", "that", "is", "do", "really", "very", "so", "much", "many", "way", "far", "long", "more",
    "again", "over", "round", "on", "no", "yes", "yeah", "ha", "haha", "bye", "night", "please", "there",
    "blah", "knock", "tick", "chop", "go", "hey", "hi", "oh", "wow", "woo", "yay", "now", "well", "ok",
    "okay", "boom", "bang", "super", "little", "tiny", "big",
}
_SENTENCE_END = re.compile(r"[.!?]$")


def _norm(token: str) -> str:
    return re.sub(r"[^\w']", "", token).lower()


def remove_repeats(text: str) -> str:
    """Collapse a word or phrase said twice in a row ("the the", "I want, I
    want to", "open up my game open up my game"). The second copy stays
    because it carries the punctuation that leads into the rest of the
    sentence. Never reaches across a sentence end or a line break."""
    out_lines = []
    for line in text.split("\n"):
        tokens = line.split(" ")
        i = 0
        while i < len(tokens):
            norm = [_norm(t) for t in tokens]
            for n in range(min(6, (len(tokens) - i) // 2), 0, -1):
                a, b = norm[i:i + n], norm[i + n:i + 2 * n]
                if a != b or not all(a):
                    continue
                if n == 1 and (a[0] in _REPEAT_OK or a[0].isdigit()):
                    continue
                if _SENTENCE_END.search(tokens[i + n - 1]):
                    continue
                first, second = tokens[i], tokens[i + n]
                if first[:1].isupper() and second[:1].islower():
                    tokens[i + n] = second[0].upper() + second[1:]
                del tokens[i:i + n]
                break
            else:
                i += 1
        out_lines.append(" ".join(tokens))
    return "\n".join(out_lines)


def _spoken(text: str) -> str:
    kept: list[str] = []

    def shield(m: re.Match) -> str:
        kept.append(m.group(1))
        return f"\x03{len(kept) - 1}\x03"
    text = _LITERAL.sub(shield, text)
    for pattern, sub in _SPOKEN_RE:
        text = pattern.sub(lambda _m, s=sub: s, text)
    text = re.sub(r"[ \t]*" + _NOSPACE_L, "", text)
    text = re.sub(_NOSPACE_R + r"[ \t]*", "", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n" + _CAP + r"?\n- ", "\n- ", text)              # "new line, dot point"
    text = re.sub(r"\n- " + _CAP + r"?(?=\n|$)", "\n", text)        # an empty list item
    return re.sub(r"\x03(\d+)\x03", lambda m: kept[int(m.group(1))], text)


def apply_replacements(text: str, replacements: list[dict] | None) -> str:
    for r in replacements or ():
        find = r.get("find", "").strip()
        if find:
            pattern = re.compile(r"(?<!\w)" + re.escape(find) + r"(?!\w)", re.IGNORECASE)
            text = pattern.sub(lambda _m, rep=r.get("replace", ""): rep, text)
    return text


def _cap_lines(text: str) -> str:
    """Capitalize the first letter of the text and of each line or list item."""
    return re.sub(r"(^|\n)((?:[-*] |\d+\. )?\s*[a-z])", lambda m: m.group(1) + m.group(2).upper(), text)


def clean(raw: str, *, remove_fillers: bool = True, voice_commands: bool = True,
          capitalize: bool = True, end_punctuation: bool = True, repeats: bool = False,
          replacements: list[dict] | None = None) -> str:
    text = " ".join(raw.split())
    if not text:
        return ""
    if remove_fillers:
        text = _FILLER.sub("", text)
        text = re.sub(r"\s+([,.!?])", r"\1", text)
        text = re.sub(r"^[,.\s]+", "", text)
    if repeats:
        text = remove_repeats(text)
    text = apply_replacements(text, replacements)
    if voice_commands:
        text = _spoken(text)
    if capitalize:
        text = re.sub(_CAP + r"([\s\"(]*)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    text = text.replace(_CAP, "")
    text = re.sub(r"[ \t]+", " ", text).strip(" \n")
    if not text:
        return ""
    if capitalize:
        text = _cap_lines(text)
    last_line = text.rsplit("\n", 1)[-1]
    if end_punctuation and text[-1].isalnum() and not re.match(r"[-*] |\d+\. ", last_line):
        text += "."
    return text


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))
