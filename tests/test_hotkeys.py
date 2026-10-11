import pytest

from freedictate import hotkeys


def test_parse_normalizes_order_and_legacy_names():
    assert hotkeys.normalize("win+ctrl") == "ctrl+win"
    assert hotkeys.normalize("right-ctrl") == "rctrl"
    assert hotkeys.normalize("Shift + Ctrl + F12") == "ctrl+shift+f12"


@pytest.mark.parametrize("bad", ["", "ctrl+ctrl", "ctrl+nope", "+"])
def test_invalid(bad):
    assert not hotkeys.is_valid(bad)


def test_labels():
    assert hotkeys.label("ctrl+win") == "Ctrl + Win"
    assert hotkeys.label("mouse4") == "Mouse back"


def test_warnings():
    assert hotkeys.warning("ctrl+win") == ""
    assert "mouse" in hotkeys.warning("mouse4").lower()
    assert hotkeys.warning("a")


def test_generalize_keeps_a_lone_side_specific_modifier():
    assert hotkeys.generalize(["rctrl"]) == ["rctrl"]
    assert hotkeys.generalize(["lctrl", "lwin"]) == ["ctrl", "win"]
    assert hotkeys.generalize(["lctrl", "lshift", "f12"]) == ["ctrl", "shift", "f12"]


def test_register_args():
    assert hotkeys.register_args("ctrl+win") is None
    mods, vk = hotkeys.register_args("ctrl+shift+f12")
    assert vk == 0x7B and mods & 0x2 and mods & 0x4


def test_matcher_groups():
    m = hotkeys.Matcher("ctrl+win")
    assert m.groups == [(0xA2, 0xA3), (0x5B, 0x5C)]
