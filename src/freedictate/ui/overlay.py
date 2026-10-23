"""The recording pill: shows that FreeDictate is listening or transcribing.

It never takes focus and lets clicks through, so the paste lands where you
were typing. It appears on the monitor of the focused window.
"""
from __future__ import annotations

import collections
import math
import time

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import native, theme

W, H = 212, 42
BARS = 17


def bar_kind(cfg) -> str:
    """How the bar draws its material. Windows' own blur, acrylic and Mica leave square
    corners or go flat on a bar that never takes focus (measured), so the bar paints the
    material itself from a picture of what is behind it: blurred for Blur and Acrylic,
    sharp and tinted for Mica."""
    choice = cfg["overlay_backdrop"]
    if choice == "solid" or not (native.backdrop_supported() and native.transparency_enabled()):
        return "solid"
    return "tinted" if choice in ("mica", "mica_alt") else "frosted"


class Overlay(QWidget):
    def __init__(self, engine, cfg):
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput
                 | Qt.WindowType.NoDropShadowWindowHint)
        super().__init__(None, flags)
        self.engine, self.cfg = engine, cfg
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(W, H)
        self.history = collections.deque([0.0] * (BARS // 2 + 1), maxlen=BARS // 2 + 1)
        self.phase = 0.0
        self.mode = "hidden"       # hidden | listening | transcribing | message
        self.message = ""
        self.message_until = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.fade = QPropertyAnimation(self, b"windowOpacity", self)
        self.fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade.finished.connect(self._fade_done)
        self._hiding = False
        self.kind = bar_kind(cfg)
        self._behind = None

    # ------------------------------------------------------------ control
    def apply_look(self) -> None:
        self.kind = bar_kind(self.cfg)
        self._behind = None
        self.update()

    def _snapshot(self) -> None:
        """Take the picture the material is drawn from. Taken once as the bar appears,
        so the bar itself never ends up in it."""
        self._behind = None
        if self.kind == "solid":
            return
        g = self.geometry()
        screen = QGuiApplication.screenAt(g.center()) or QGuiApplication.primaryScreen()
        # grabWindow(0, ...) counts from this monitor's corner, not the desktop's.
        at = g.topLeft() - screen.geometry().topLeft()
        shot = screen.grabWindow(0, at.x(), at.y(), g.width(), g.height()).toImage()
        if self.kind == "frosted":
            shot = shot.scaled(W // 6, H // 6, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        self._behind = shot.scaled(W, H, Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)

    def on_state(self, state: str) -> None:
        if not self.cfg["overlay"]:
            if self.isVisible():
                self._hide()
            return
        if state == "listening":
            self.history.extend([0.0] * self.history.maxlen)
            self._show("listening")
        elif state == "transcribing":
            self._show("transcribing")
        elif self.mode in ("listening", "transcribing"):
            self._hide()

    def flash(self, text: str, seconds: float = 1.6) -> None:
        if not self.cfg["overlay"]:
            return
        self.message = text
        self.message_until = time.monotonic() + seconds
        self._show("message")

    def _place(self) -> None:
        l, t, r, b = native.foreground_work_area()
        cx, cy = (l + r) // 2, (t + b) // 2
        screen = None
        for s in QGuiApplication.screens():
            g, dpr = s.geometry(), s.devicePixelRatio()
            if g.x() <= cx < g.x() + g.width() * dpr and g.y() <= cy < g.y() + g.height() * dpr:
                screen = s
                break
        screen = screen or QGuiApplication.primaryScreen()
        g, dpr = screen.geometry(), screen.devicePixelRatio()

        def logical(px, py):
            return QPoint(round(g.x() + (px - g.x()) / dpr), round(g.y() + (py - g.y()) / dpr))

        top_left, bottom_right = logical(l, t), logical(r, b)
        x = (top_left.x() + bottom_right.x() - W) // 2
        margin = 26
        y = top_left.y() + margin if self.cfg["overlay_position"] == "top" else bottom_right.y() - H - margin
        self.move(x, y)

    def _show(self, mode: str) -> None:
        was_hidden = not self.isVisible() or self._hiding
        self.mode = mode
        self._hiding = False
        if was_hidden:
            self._place()
            if not self.isVisible():
                self._snapshot()
            self.setWindowOpacity(0.0)
            self.show()
            native.make_overlay(int(self.winId()))
            self._fade_to(1.0, 110)
        if not self.timer.isActive():
            self.timer.start()
        self.update()

    def _hide(self) -> None:
        if not self.isVisible() or self._hiding:
            return
        self._hiding = True
        self._fade_to(0.0, 160)

    def _fade_to(self, target: float, ms: int) -> None:
        self.fade.stop()
        if self.cfg["reduce_motion"]:
            self.setWindowOpacity(target)
            self._fade_done()
            return
        self.fade.setDuration(ms)
        self.fade.setStartValue(self.windowOpacity())
        self.fade.setEndValue(target)
        self.fade.start()

    def _fade_done(self) -> None:
        if self._hiding:
            self.hide()
            self.timer.stop()
            self.mode = "hidden"
            self._hiding = False

    def _tick(self) -> None:
        if self.mode == "listening":
            lvl = self.engine.recorder.level
            self.history.appendleft(min(1.0, (lvl * 16) ** 0.65))
        elif self.mode == "transcribing":
            self.phase += 0.11
        elif self.mode == "message" and time.monotonic() > self.message_until:
            self._hide()
        self.update()

    # ------------------------------------------------------------ paint
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = theme.current()
        r = QRectF(0.5, 0.5, W - 1, H - 1)
        path = QPainterPath()
        path.addRoundedRect(r, H / 2, H / 2)
        if self._behind is not None:
            p.save()
            p.setClipPath(path)
            p.drawImage(QRectF(0, 0, W, H), self._behind)
            p.restore()
        p.fillPath(path, theme.qc(pal.bg, 0.94 if self.kind == "solid" else self.cfg["tint"] / 100))
        p.setPen(QPen(theme.qc(pal.line, 1.0), 1))
        p.drawPath(path)

        if self.mode == "message":
            p.setPen(QColor(pal.text))
            p.setFont(theme.font(9.5, QFont.Weight.DemiBold))
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), self.message)
            return

        listening = self.mode == "listening"
        color = QColor(pal.danger if listening else pal.warn)
        # left: a recording dot while listening (the real mic state)
        if listening:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(QRectF(16, H / 2 - 4, 8, 8))
        bars_left, bars_right = 34, W - (58 if self.cfg["overlay_timer"] else 34)
        gap = (bars_right - bars_left) / (BARS - 1)
        mid, reach = H / 2, (H - 16) / 2
        n = BARS // 2
        pen = QPen(QColor(pal.accent if listening else pal.warn), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for i in range(BARS):
            d = abs(i - n)
            if listening:
                v = self.history[d] * (1 - d / (n + 3))
            else:
                v = 0.2 + 0.16 * math.sin(self.phase - d * 0.6)
            half = max(1.5, v * reach)
            x = bars_left + i * gap
            p.drawLine(QRectF(x, mid - half, 0, 2 * half).topLeft(), QRectF(x, mid - half, 0, 2 * half).bottomLeft())
        if self.cfg["overlay_timer"] and listening:
            secs = int(self.engine.recorder.elapsed())
            p.setPen(QColor(pal.sub))
            p.setFont(theme.font(9, QFont.Weight.Medium))
            text = f"{secs // 60}:{secs % 60:02d}"
            p.drawText(QRectF(W - 54, 0, 40, H), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), text)
        elif self.cfg["overlay_timer"]:
            # Drawn as shapes: "..." as text sits on the baseline and reads low.
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal.sub))
            for i in range(3):
                p.drawEllipse(QPointF(W - 16 - 5 * (2 - i), H / 2), 1.6, 1.6)
