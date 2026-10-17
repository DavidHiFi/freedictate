"""Hotkey parsing, matching and display.

A hotkey is a ``+``-joined list of key names, e.g. ``ctrl+win`` or ``rctrl`` or
``ctrl+shift+space``. Generic modifier names match either side. Keys are read
by polling ``GetAsyncKeyState``: Windows silently drops a low-level keyboard
hook whose callback stalls, which once left v1 running but deaf. Polling cannot
fail that way.
"""
from __future__ import annotations

import ctypes
import string

# name -> (label, virtual-key codes that count as this key)
KEYS: dict[str, tuple[str, tuple[int, ...]]] = {
    "ctrl": ("Ctrl", (0xA2, 0xA3)), "lctrl": ("Left Ctrl", (0xA2,)), "rctrl": ("Right Ctrl", (0xA3,)),
    "alt": ("Alt", (0xA4, 0xA5)), "lalt": ("Left Alt", (0xA4,)), "ralt": ("Right Alt", (0xA5,)),
    "shift": ("Shift", (0xA0, 0xA1)), "lshift": ("Left Shift", (0xA0,)), "rshift": ("Right Shift", (0xA1,)),
    "win": ("Win", (0x5B, 0x5C)), "lwin": ("Left Win", (0x5B,)), "rwin": ("Right Win", (0x5C,)),
    "space": ("Space", (0x20,)), "tab": ("Tab", (0x09,)), "capslock": ("Caps Lock", (0x14,)),
    "esc": ("Esc", (0x1B,)),
    "enter": ("Enter", (0x0D,)), "backspace": ("Backspace", (0x08,)),
    "insert": ("Insert", (0x2D,)), "delete": ("Delete", (0x2E,)), "home": ("Home", (0x24,)),
    "end": ("End", (0x23,)), "pageup": ("Page Up", (0x21,)), "pagedown": ("Page Down", (0x22,)),
    "up": ("Up", (0x26,)), "down": ("Down", (0x28,)), "left": ("Left", (0x25,)), "right": ("Right", (0x27,)),
    "pause": ("Pause", (0x13,)), "scrolllock": ("Scroll Lock", (0x91,)), "apps": ("Menu", (0x5D,)),
    "backquote": ("`", (0xC0,)), "minus": ("-", (0xBD,)), "equals": ("=", (0xBB,)),
    "lbracket": ("[", (0xDB,)), "rbracket": ("]", (0xDD,)), "backslash": ("\\", (0xDC,)),
    "semicolon": (";", (0xBA,)), "quote": ("'", (0xDE,)), "comma": (",", (0xBC,)),
    "period": (".", (0xBE,)), "slash": ("/", (0xBF,)),
    "mouse3": ("Middle mouse", (0x04,)), "mouse4": ("Mouse back", (0x05,)), "mouse5": ("Mouse forward", (0x06,)),
}
for _i in range(1, 25):
    KEYS[f"f{_i}"] = (f"F{_i}", (0x6F + _i,))
for _c in string.ascii_lowercase:
    KEYS[_c] = (_c.upper(), (ord(_c.upper()),))
for _d in string.digits:
    KEYS[_d] = (_d, (ord(_d),))
for _d in range(10):
    KEYS[f"num{_d}"] = (f"Num {_d}", (0x60 + _d,))

MODIFIERS = {"ctrl", "lctrl", "rctrl", "alt", "lalt", "ralt", "shift", "lshift", "rshift", "win", "lwin", "rwin"}
MODIFIER_VKS = (0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C)
MOUSE = {"mouse3", "mouse4", "mouse5"}
VK_ESCAPE = 0x1B

# Order used when displaying and when recording a combination.
_ORDER = ["ctrl", "lctrl", "rctrl", "win", "lwin", "rwin", "alt", "lalt", "ralt", "shift", "lshift", "rshift"]

PRESETS = ["ctrl+win", "ctrl+alt", "ctrl+shift", "rctrl", "ralt", "capslock", "f9", "mouse4"]

# vk -> most specific name, for recording
_VK_NAME: dict[int, str] = {}
for _name, (_label, _vks) in KEYS.items():
    if len(_vks) == 1 and _vks[0] not in _VK_NAME:
        _VK_NAME[_vks[0]] = _name

_user32 = ctypes.WinDLL("user32") if hasattr(ctypes, "WinDLL") else None


def parse(text: str) -> list[str]:
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+") if p.strip()]
    legacy = {"right-ctrl": "rctrl", "right-alt": "ralt", "control": "ctrl", "windows": "win"}
    parts = [legacy.get(p, p) for p in parts]
    if not parts or any(p not in KEYS for p in parts) or len(set(parts)) != len(parts):
        raise ValueError(f"Unknown hotkey: {text!r}")
    return sort_keys(parts)


def sort_keys(names: list[str]) -> list[str]:
    return sorted(names, key=lambda n: (_ORDER.index(n) if n in _ORDER else 100, n))


def normalize(text: str) -> str:
    return "+".join(parse(text))


def label(text: str) -> str:
    try:
        return " + ".join(KEYS[k][0] for k in parse(text))
    except ValueError:
        return text


def is_valid(text: str) -> bool:
    try:
        parse(text)
        return True
    except ValueError:
        return False


def overlaps(a: str, b: str) -> bool:
    """True when the two shortcuts share a physical key, so holding one holds the other."""
    keys_a = {vk for k in parse(a) for vk in KEYS[k][1]}
    keys_b = {vk for k in parse(b) for vk in KEYS[k][1]}
    return bool(keys_a & keys_b)


def warning(text: str) -> str:
    """A short caution for hotkeys that will also reach the focused app, or ''."""
    keys = parse(text)
    if any(k in MOUSE for k in keys):
        return "The mouse button still does its normal job, like going back in a browser."
    plain = [k for k in keys if k not in MODIFIERS]
    if len(keys) == 1 and plain and plain[0] in string.ascii_lowercase + string.digits + "space":
        return "A single letter, digit or Space would stop you from typing it. Add a modifier."
    return ""


def single_key_is_swallowable(text: str) -> bool:
    """True when RegisterHotKey can stop the key reaching other apps."""
    keys = parse(text)
    plain = [k for k in keys if k not in MODIFIERS]
    return len(plain) == 1 and plain[0] not in MOUSE


def register_args(text: str) -> tuple[int, int] | None:
    """(modifiers, vk) for RegisterHotKey, or None if the hotkey has no plain key."""
    keys = parse(text)
    plain = [k for k in keys if k not in MODIFIERS]
    if len(plain) != 1 or plain[0] in MOUSE:
        return None
    mods = 0x4000  # MOD_NOREPEAT
    for k in keys:
        if k in ("alt", "lalt", "ralt"):
            mods |= 0x1
        elif k in ("ctrl", "lctrl", "rctrl"):
            mods |= 0x2
        elif k in ("shift", "lshift", "rshift"):
            mods |= 0x4
        elif k in ("win", "lwin", "rwin"):
            mods |= 0x8
    return mods, KEYS[plain[0]][1][0]


def key_down(vk: int) -> bool:
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


class Matcher:
    """Answers "is the hotkey held right now?" for one hotkey string."""

    def __init__(self, text: str):
        self.text = normalize(text)
        self.groups = [KEYS[k][1] for k in parse(self.text)]

    def held(self) -> bool:
        return all(any(key_down(vk) for vk in g) for g in self.groups)


def modifiers_down() -> bool:
    return any(key_down(vk) for vk in MODIFIER_VKS)


# Keys considered while recording a new hotkey.
_RECORDABLE = sorted(set(_VK_NAME) - {0x0D})


def keys_down_now() -> list[str]:
    """Names of recordable keys held at this instant (side-specific for modifiers)."""
    return sort_keys([_VK_NAME[vk] for vk in _RECORDABLE if key_down(vk)])


def generalize(names: list[str]) -> list[str]:
    """Left Ctrl + Left Win -> Ctrl + Win, unless only one side makes sense.

    A lone modifier keeps its side (Right Ctrl), because a generic lone Ctrl
    would fire on every Ctrl+C.
    """
    if len(names) == 1:
        return names
    out = []
    for n in names:
        if n in MODIFIERS and n[0] in "lr" and n[1:] in ("ctrl", "alt", "shift", "win"):
            out.append(n[1:])
        else:
            out.append(n)
    return sort_keys(list(dict.fromkeys(out)))
