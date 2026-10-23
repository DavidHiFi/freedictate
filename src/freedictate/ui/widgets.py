"""Controls shared by the Settings pages."""
from __future__ import annotations

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget)

from .. import hotkeys
from . import icons, theme

_reduce_motion = False
_KEYBOARD_REASONS = (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                     Qt.FocusReason.ShortcutFocusReason)


class KeyboardFocusMixin:
    """Draw a focus ring only when focus arrived from the keyboard, like Windows does."""
    _kbd_focus = False

    def focusInEvent(self, e):
        self._kbd_focus = e.reason() in _KEYBOARD_REASONS
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        self._kbd_focus = False
        super().focusOutEvent(e)
        self.update()

    def keyPressEvent(self, e):
        self._kbd_focus = True
        super().keyPressEvent(e)
        self.update()


def set_reduce_motion(on: bool) -> None:
    global _reduce_motion
    _reduce_motion = on


def label(text: str, role: str = "", wrap: bool = False, parent=None) -> QLabel:
    lab = QLabel(text, parent)
    if role:
        lab.setProperty("role", role)
    lab.setWordWrap(wrap)
    if wrap:
        lab.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return lab


def button(text: str, kind: str = "", parent=None, icon: str = "") -> QPushButton:
    b = QPushButton(text, parent)
    if kind:
        b.setProperty("kind", kind)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon:
        b.setProperty("icon_name", icon)
        b.setIcon(icons.icon(icon, theme.current().on_accent if kind == "primary" else theme.current().text))
        b.setIconSize(QSize(16, 16))
    return b


def refresh_icons(root: QWidget) -> None:
    """Re-tint button icons after a theme change."""
    pal = theme.current()
    for b in root.findChildren(QPushButton):
        name = b.property("icon_name")
        if name:
            color = pal.on_accent if b.property("kind") == "primary" else pal.text
            b.setIcon(icons.icon(name, color))


# ------------------------------------------------------------------ toggle

class Toggle(KeyboardFocusMixin, QAbstractButton):
    """Windows 11 style on/off switch."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 22)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)
        self._hover = False

    def _animate(self, on: bool) -> None:
        end = 1.0 if on else 0.0
        if _reduce_motion or not self.isVisible():
            self._pos = end
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(end)
        self._anim.start()

    def get_knob(self) -> float:
        return self._pos

    def set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, get_knob, set_knob)

    def setChecked(self, on: bool) -> None:  # noqa: N802 (Qt name)
        super().setChecked(on)
        if not self._anim_running():
            self._pos = 1.0 if on else 0.0
            self.update()

    def _anim_running(self) -> bool:
        return hasattr(self, "_anim") and self._anim.state() == QPropertyAnimation.State.Running

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def sizeHint(self):
        return QSize(44, 22)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = theme.current()
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        on = self.isChecked()
        enabled = self.isEnabled()
        if on:
            fill = QColor(pal.accent) if enabled else theme.qc(pal.accent, 0.4)
            if self._hover and enabled:
                fill = QColor(theme.mix(pal.accent, pal.text, 0.15))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
        else:
            p.setPen(QPen(theme.qc(pal.sub, 0.9 if enabled else 0.4), 1.2))
            p.setBrush(theme.qc(pal.hover, 0.5) if self._hover else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = 12 if (self._hover and enabled) else 10
        x = r.left() + 5 + self._pos * (r.width() - 10 - d) + (0 if d == 12 else 1)
        y = r.center().y() - d / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal.on_accent) if on else theme.qc(pal.sub, 1.0 if enabled else 0.5))
        p.drawEllipse(QRectF(x, y, d, d))
        if self.hasFocus() and self._kbd_focus:
            p.setPen(QPen(QColor(pal.accent), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), r.height() / 2 + 1, r.height() / 2 + 1)

    def hitButton(self, pos):
        return self.rect().contains(pos)


# ------------------------------------------------------------- rows, cards

class Row(QWidget):
    """One setting: title and description on the left, control on the right."""

    def __init__(self, title: str, desc: str = "", control: QWidget | None = None, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(2)
        # Attach the column before filling it, so every label has a parent
        # before its visibility is set. A parentless label shown is a window of
        # its own: one flashed on screen per row (measured 2026-10-24).
        lay.addLayout(text, 1)
        self.title = label(title, "rowtitle")
        text.addWidget(self.title)
        self.desc = label(desc, "sub", wrap=True)
        text.addWidget(self.desc)
        self.desc.setVisible(bool(desc))
        self.note = label("", "warn", wrap=True)
        text.addWidget(self.note)
        self.note.hide()
        self.controls = QHBoxLayout()
        self.controls.setSpacing(8)
        lay.addLayout(self.controls)
        if control is not None:
            self.controls.addWidget(control)
            if isinstance(control, Toggle):
                control.setAccessibleName(title)
                self.title.setBuddy(control)
            elif hasattr(control, "setAccessibleName"):
                control.setAccessibleName(title)

    def set_note(self, text: str, role: str = "warn") -> None:
        self.note.setProperty("role", role)
        self.note.setText(text)
        self.note.setVisible(bool(text))
        self.note.style().unpolish(self.note)
        self.note.style().polish(self.note)


class Card(QFrame):
    """A group of rows separated by hairlines."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self._count = 0

    def add(self, w: QWidget) -> QWidget:
        if self._count:
            line = QFrame(self)
            line.setObjectName("divider")
            wrap = QHBoxLayout()
            wrap.setContentsMargins(16, 0, 16, 0)
            wrap.addWidget(line)
            self.lay.addLayout(wrap)
            w._card_divider = line
        self.lay.addWidget(w)
        self._count += 1
        return w

    @staticmethod
    def show_row(w: QWidget, visible: bool) -> None:
        """Hide a row together with the hairline above it."""
        w.setVisible(visible)
        line = getattr(w, "_card_divider", None)
        if line is not None:
            line.setVisible(visible)


class Banner(QFrame):
    def __init__(self, text: str, warn: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("bannerWarn" if warn else "banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 10, 10)
        lay.setSpacing(10)
        self.text = label(text, wrap=True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setOpenExternalLinks(True)
        lay.addWidget(self.text, 1)
        self.actions = QHBoxLayout()
        lay.addLayout(self.actions)


# ------------------------------------------------------------- segmented

class Segmented(QWidget):
    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], value: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for i, (key, text) in enumerate(options):
            b = QPushButton(text, self)
            b.setCheckable(True)
            b.setProperty("kind", "segment")
            b.setProperty("first", i == 0)
            b.setProperty("last", i == len(options) - 1)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        self.set_value(value)

    def set_value(self, value: str) -> None:
        if value in self.buttons:
            self.buttons[value].setChecked(True)

    def value(self) -> str:
        return next((k for k, b in self.buttons.items() if b.isChecked()), "")


# ------------------------------------------------------------- combo

class Combo(QComboBox):
    """Combo box that ignores the mouse wheel unless it has focus, so scrolling
    a page never changes a setting by accident."""

    def __init__(self, items: list[tuple[str, str]], value: str, parent=None, width: int = 240):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(width)
        self.setMaxVisibleItems(14)
        self.set_items(items, value)

    def set_items(self, items: list[tuple[str, str]], value: str) -> None:
        self.blockSignals(True)
        self.clear()
        for key, text in items:
            self.addItem(text, key)
        idx = self.findData(value)
        if idx < 0 and value not in ("", None):
            # Keep an unknown saved value visible and current instead of
            # silently showing (and later saving) the first item's value.
            self.addItem(str(value), value)
            idx = self.count() - 1
        self.setCurrentIndex(max(0, idx))
        self.blockSignals(False)

    def value(self) -> str:
        return self.currentData()

    def wheelEvent(self, e):
        if self.hasFocus() and self.view().isVisible():
            super().wheelEvent(e)
        else:
            e.ignore()


class ValueBox(QLineEdit):
    """The number beside a slider, typeable: click it, type 87 or 87%, press
    Enter (or click away). Esc puts the slider's value back. Same behaviour as
    WinLaunch Enhanced's settings."""
    committed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("valueBox")
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setFixedWidth(64)
        self.setMaxLength(6)
        self._shown = ""
        self.editingFinished.connect(lambda: self.committed.emit(self.text()))

    def show_value(self, text: str) -> None:
        self._shown = text
        if not self.hasFocus():
            self.setText(text)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        QTimer.singleShot(0, self.selectAll)   # a click would otherwise drop the selection

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.setText(self._shown)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.setText(self._shown)
            self.clearFocus()
            return
        super().keyPressEvent(e)
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clearFocus()


class Slider(QWidget):
    changed = Signal(int)

    def __init__(self, lo: int, hi: int, value: int, suffix: str = "", parent=None, width: int = 200):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.s = QSlider(Qt.Orientation.Horizontal, self)
        self.s.setRange(lo, hi)
        self.s.setValue(value)
        self.s.setFixedWidth(width)
        self.s.setCursor(Qt.CursorShape.PointingHandCursor)
        self.suffix = suffix
        self.v = ValueBox(self)
        self.v.show_value(f"{value}{suffix}")
        lay.addWidget(self.s)
        lay.addWidget(self.v)
        self.s.valueChanged.connect(lambda x: self.v.show_value(f"{x}{self.suffix}"))
        self.s.sliderReleased.connect(lambda: self.changed.emit(self.s.value()))
        self.s.valueChanged.connect(self._maybe_emit)
        self.v.committed.connect(self._typed)

    def _typed(self, text: str) -> None:
        digits = text.strip().rstrip("%").strip().replace(",", ".")
        try:
            v = round(float(digits))
        except ValueError:
            self.v.show_value(f"{self.s.value()}{self.suffix}")
            return
        v = min(max(v, self.s.minimum()), self.s.maximum())
        if v == self.s.value():
            self.v.show_value(f"{v}{self.suffix}")
        self.s.setValue(v)        # emits changed through valueChanged

    def _maybe_emit(self, x: int) -> None:
        if not self.s.isSliderDown():
            self.changed.emit(x)

    def setAccessibleName(self, name: str) -> None:
        super().setAccessibleName(name)
        self.s.setAccessibleName(name)
        self.v.setAccessibleName(f"{name} value")

    def value(self) -> int:
        return self.s.value()


# ------------------------------------------------------------- level meter

class LevelMeter(QWidget):
    def __init__(self, parent=None, width: int = 200):
        super().__init__(parent)
        self.setFixedSize(width, 8)
        self._level = 0.0
        self._peak = 0.0
        self.setAccessibleName("Microphone level")

    def set_level(self, rms: float) -> None:
        v = min(1.0, (rms * 12) ** 0.6)
        self._level = v if v > self._level else self._level * 0.82 + v * 0.18
        self._peak = max(self._peak * 0.97, self._level)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = theme.current()
        r = QRectF(0, 1, self.width(), self.height() - 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.qc(pal.line, 1.0))
        p.drawRoundedRect(r, 3, 3)
        if self._level > 0.005:
            w = max(6.0, r.width() * self._level)
            p.setBrush(QColor(pal.ok if self._level < 0.85 else pal.warn))
            p.drawRoundedRect(QRectF(r.left(), r.top(), w, r.height()), 3, 3)
        if self._peak > 0.02:
            x = r.left() + r.width() * self._peak
            p.setBrush(theme.qc(pal.text, 0.6))
            p.drawRect(QRectF(min(x, r.right() - 2), r.top(), 2, r.height()))


# ------------------------------------------------------------- hotkey edit

class HotkeyEdit(QPushButton):
    """Shows the current shortcut. Click, then press the new combination.
    Keys are read with GetAsyncKeyState, so Win and mouse side buttons work."""
    recorded = Signal(str)
    recording = Signal(bool)

    def __init__(self, value: str, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.value = value
        self._timer = QTimer(self)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._poll)
        self._held: list[str] = []
        self._best: list[str] = []
        self._armed = False
        self.clicked.connect(self.start)
        self._show()

    def _show(self) -> None:
        self.setText(hotkeys.label(self.value))
        f = self.font()
        f.setWeight(QFont.Weight.DemiBold)
        self.setFont(f)

    def start(self) -> None:
        if self._timer.isActive():
            return
        self._held, self._best, self._armed = [], [], False
        self.setText("Press your shortcut")
        self.setProperty("kind", "primary")
        self.style().unpolish(self)
        self.style().polish(self)
        self.recording.emit(True)
        self._timer.start()

    def cancel(self) -> None:
        self._finish(None)

    def _poll(self) -> None:
        if hotkeys.key_down(hotkeys.VK_ESCAPE):
            self._finish(None)
            return
        down = [k for k in hotkeys.keys_down_now() if k != "mouse3" or self._armed]
        # The click that started recording is still held at first; wait for a clean slate.
        if not self._armed:
            if not down and not hotkeys.key_down(0x01):
                self._armed = True
            return
        if down:
            if len(down) >= len(self._best):
                self._best = down
            self.setText(hotkeys.label("+".join(hotkeys.generalize(self._best))))
        elif self._best:
            self._finish("+".join(hotkeys.generalize(self._best)))

    def _finish(self, combo: str | None) -> None:
        self._timer.stop()
        self.setProperty("kind", "")
        self.style().unpolish(self)
        self.style().polish(self)
        if combo and hotkeys.is_valid(combo):
            self.value = hotkeys.normalize(combo)
            self._show()
            self.recording.emit(False)
            self.recorded.emit(self.value)
        else:
            self._show()
            self.recording.emit(False)

    def set_value(self, value: str) -> None:
        self.value = value
        self._show()


# ------------------------------------------------------------- nav

class NavButton(KeyboardFocusMixin, QAbstractButton):
    def __init__(self, key: str, text: str, icon_name: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setText(text)
        self.icon_name = icon_name
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(text)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def sizeHint(self):
        return QSize(180, 38)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = theme.current()
        r = QRectF(self.rect()).adjusted(0, 2, 0, -2)
        if self.isChecked() or self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.qc(pal.text, 0.09 if self.isChecked() else 0.05))
            p.drawRoundedRect(r, 6, 6)
        if self.isChecked():
            # The selection marker: Windows 11 navigation uses an accent pill on the left edge.
            p.setBrush(QColor(pal.accent))
            p.drawRoundedRect(QRectF(r.left(), r.center().y() - 8, 3, 16), 1.5, 1.5)
        if self.hasFocus() and self._kbd_focus:
            p.setPen(QPen(QColor(pal.accent), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 6, 6)
        color = pal.text
        pm = icons.pixmap(self.icon_name, color, 18, self.devicePixelRatioF())
        p.drawPixmap(14, int(r.center().y() - 9), pm)
        p.setPen(QColor(color))
        f = theme.font(10.5, QFont.Weight.DemiBold if self.isChecked() else QFont.Weight.Normal)
        p.setFont(f)
        p.drawText(QRectF(44, r.top(), r.width() - 48, r.height()),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())


class StatusDot(QWidget):
    """Marks the engine's real state: ready, listening, transcribing, paused, error."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self.color = "#7f849c"

    def set_color(self, c: str) -> None:
        self.color = c
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.color))
        p.drawEllipse(QRectF(1, 1, 8, 8))
