"""The two "While I dictate" switches reach the config, and the level menu follows them.

Reuses the Settings-window fixtures from test_ui.py. When FD_RENDER_DIR is set,
the section is also saved as a PNG there, so the wording can be looked at.
"""
import os

from test_ui import env, fresh_cfg, open_window, pump, qapp  # noqa: F401  (pytest fixtures)
from PySide6.QtWidgets import QComboBox, QLabel

from freedictate.ui.widgets import Card, Toggle


def _row_control(win, title: str, kind):
    """The control inside the row whose title label reads `title`."""
    label = next(lbl for lbl in win.findChildren(QLabel) if lbl.text() == title)
    node = label.parentWidget()
    while node is not None and not node.findChildren(kind):
        node = node.parentWidget()
    assert node is not None, f"no {kind.__name__} beside {title!r}"
    return node.findChildren(kind)[0]


def test_privacy_switches_write_the_config_and_the_menu_follows(qapp, env):
    # Start from the defaults: an earlier run in the same scratch profile saved these on.
    cfg = fresh_cfg(mic_privacy_while_dictating=False, isolate_output_while_dictating=False, isolate_output_level=0)
    win = open_window(qapp, cfg, env)
    try:
        private = _row_control(win, "Keep my mic private", Toggle)
        mute = _row_control(win, "Turn other apps down", Toggle)
        menu = _row_control(win, "How far down", QComboBox)

        assert win.cfg["mic_privacy_while_dictating"] is False
        private.setChecked(True)
        assert win.cfg["mic_privacy_while_dictating"] is True

        assert win.cfg["isolate_output_while_dictating"] is False
        assert not menu.isEnabled()
        mute.setChecked(True)
        assert win.cfg["isolate_output_while_dictating"] is True
        assert menu.isEnabled()
        assert win.cfg["isolate_output_level"] == 0          # default: mute them

        menu.setCurrentIndex(menu.findText("25% volume"))
        assert win.cfg["isolate_output_level"] == 25
        menu.setCurrentIndex(menu.findText("Mute them"))
        assert win.cfg["isolate_output_level"] == 0

        mute.setChecked(False)
        assert not menu.isEnabled()
    finally:
        win.close()
        win.deleteLater()
        pump(qapp)


def test_privacy_section_renders(qapp, env):
    out_dir = os.environ.get("FD_RENDER_DIR")
    if not out_dir:
        return
    win = open_window(qapp, fresh_cfg(), env)
    try:
        mute_label = next(lbl for lbl in win.findChildren(QLabel) if lbl.text() == "Turn other apps down")
        node = mute_label.parentWidget()
        while node is not None and not isinstance(node, Card):
            node = node.parentWidget()
        assert node is not None, "the privacy rows should sit inside a Card"
        node.resize(node.sizeHint())
        pump(qapp)
        assert node.grab().save(os.path.join(out_dir, "settings-while-i-dictate.png"))
    finally:
        win.close()
        win.deleteLater()
        pump(qapp)
