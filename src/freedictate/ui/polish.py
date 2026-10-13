"""App-wide touches applied through one event filter.

- Menus and dropdown lists get rounded corners, dark-mode frames and an acrylic
  backdrop, like Windows 11's own flyouts. The system Acrylic goes black on a
  menu that is not the focused window (the tray menu), so it is drawn as an
  accent instead, which Windows keeps drawing.
- Buttons and combo boxes show a focus border only when focus came from the
  keyboard.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QComboBox, QMenu, QPushButton, QWidget

from . import native, theme

_KEYBOARD = (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)


def _is_popup(w: QWidget) -> bool:
    return isinstance(w, QMenu) or type(w).__name__ == "QComboBoxPrivateContainer"


class Polisher(QObject):
    def __init__(self, translucent: bool):
        super().__init__()
        self.translucent = translucent

    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.Type.Polish and isinstance(obj, QWidget) and _is_popup(obj):
            if self.translucent and not obj.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
                obj.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            obj.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        elif t == QEvent.Type.Show and isinstance(obj, QWidget) and _is_popup(obj) and obj.isWindow():
            h = int(obj.winId())
            native.set_dark(h, theme.current().dark)
            native.set_corners(h, small=True)
            if self.translucent:
                native.set_accent_acrylic(h)
        elif t in (QEvent.Type.FocusIn, QEvent.Type.FocusOut) and isinstance(obj, (QPushButton, QComboBox)):
            kbd = t == QEvent.Type.FocusIn and e.reason() in _KEYBOARD
            if bool(obj.property("kbd")) != kbd:
                obj.setProperty("kbd", kbd)
                obj.style().unpolish(obj)
                obj.style().polish(obj)
        return False
