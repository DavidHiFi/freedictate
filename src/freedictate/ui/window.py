"""A top-level window with Windows 11 materials and its own title bar.

The window is a real resizable Win32 window (WS_CAPTION | WS_THICKFRAME). Its
non-client area is folded into the client (WM_NCCALCSIZE returns 0) so the
backdrop covers the title bar and body as one surface, and WM_NCHITTEST hands
the title bar back to Windows as HTCAPTION. Dragging therefore runs the
system move loop, which is what snap, AltSnap-style tools and the
wobbly-windows mod hook into.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from . import icons, native, theme

TITLE_H = 44


class CaptionButton(QPushButton):
    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(46, TITLE_H - 8)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setAccessibleName({"minimize": "Minimize", "maximize": "Maximize", "restore": "Restore",
                                "close": "Close"}[kind])
        self._hover = False

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.setAccessibleName("Restore" if kind == "restore" else "Maximize")
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = theme.current()
        down = self.isDown()
        if self._hover or down:
            if self.kind == "close":
                bg = QColor("#c42b1c") if not down else QColor("#a52618")
            else:
                bg = theme.qc(pal.text, 0.12 if not down else 0.07)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 5, 5)
        color = "#ffffff" if (self.kind == "close" and (self._hover or down)) else pal.text
        if not self.window().isActiveWindow() and not self._hover:
            color = pal.sub
        pm = icons.pixmap(self.kind, color, 14, self.devicePixelRatioF())
        p.drawPixmap(int((self.width() - 14) / 2), int((self.height() - 14) / 2), pm)


class TitleBar(QWidget):
    def __init__(self, window: "FluentWindow", title: str):
        super().__init__(window)
        self.setFixedHeight(TITLE_H)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 4, 4, 4)
        lay.setSpacing(10)
        self.icon = QLabel(self)
        self.icon.setFixedSize(18, 18)
        self.title = QLabel(title, self)
        self.title.setProperty("role", "sub")
        lay.addWidget(self.icon)
        lay.addWidget(self.title)
        lay.addStretch(1)
        self.extra = QHBoxLayout()
        self.extra.setSpacing(6)
        lay.addLayout(self.extra)
        self.btn_min = CaptionButton("minimize", self)
        self.btn_max = CaptionButton("maximize", self)
        self.btn_close = CaptionButton("close", self)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b)
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_max.clicked.connect(window.toggle_maximized)
        self.btn_close.clicked.connect(window.close)

    def refresh(self) -> None:
        self.icon.setPixmap(icons.app_icon("ready").pixmap(QSize(18, 18)))
        for b in (self.btn_min, self.btn_max, self.btn_close):
            b.update()


class FluentWindow(QWidget):
    """Frameless Qt window with real Win32 frame semantics and a DWM backdrop."""
    activeChanged = Signal(bool)

    def __init__(self, title: str):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self._backdrop = "mica_alt"
        self._tint = 0.65
        self._keep_active = False
        self._chrome_applied = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.titlebar = TitleBar(self, title)
        root.addWidget(self.titlebar)
        self.body = QWidget(self)
        root.addWidget(self.body, 1)

    # ------------------------------------------------------------ appearance
    def hwnd(self) -> int:
        return int(self.winId())

    def set_look(self, backdrop: str, tint: float, keep_active: bool) -> None:
        if backdrop != "solid" and not (native.backdrop_supported() and native.transparency_enabled()):
            backdrop = "solid"
        self._backdrop, self._tint, self._keep_active = backdrop, tint, keep_active
        if self._chrome_applied:
            self._apply_dwm()
        self.titlebar.refresh()
        self.update()

    def effective_backdrop(self) -> str:
        return self._backdrop

    def _apply_dwm(self) -> None:
        h = self.hwnd()
        native.set_dark(h, theme.current().dark)
        native.set_corners(h)
        native.set_backdrop(h, self._backdrop)

    def showEvent(self, e):
        super().showEvent(e)
        h = self.hwnd()
        native.add_frame_styles(h)
        self._apply_dwm()
        self._chrome_applied = True

    def paintEvent(self, e):
        p = QPainter(self)
        pal = theme.current()
        alpha = 1.0 if self._backdrop == "solid" else self._tint
        p.fillRect(self.rect(), theme.qc(pal.bg, alpha))

    def changeEvent(self, e):
        if e.type() == QEvent.Type.WindowStateChange:
            self.titlebar.btn_max.set_kind("restore" if self.isMaximized() else "maximize")
        elif e.type() == QEvent.Type.ActivationChange:
            self.titlebar.refresh()
            self.activeChanged.emit(self.isActiveWindow())
        super().changeEvent(e)

    def toggle_maximized(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    # --------------------------------------------------------------- native
    def _hit_widget_is_interactive(self, local: QPoint) -> bool:
        w = self.childAt(local)
        while w is not None and w is not self:
            if isinstance(w, (QAbstractButton, QLineEdit, QComboBox)) or w.property("interactive"):
                return True
            w = w.parentWidget()
        return False

    def nativeEvent(self, event_type, message):
        try:
            msg = wt.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0
        m = msg.message
        if m == native.WM_NCCALCSIZE and msg.wParam:
            if native.is_zoomed(msg.hWnd):
                # A maximized window hangs its frame off-screen; keep the content on it.
                params = native.NCCALCSIZE_PARAMS.from_address(msg.lParam)
                f = native.frame_thickness(msg.hWnd)
                r = params.rgrc[0]
                r.left += f
                r.top += f
                r.right -= f
                r.bottom -= f
            return True, 0
        if m == native.WM_NCHITTEST:
            return True, self._hit_test(msg)
        if m == native.WM_NCACTIVATE and self._keep_active and self._backdrop != "solid":
            # Report "active" to the frame so DWM keeps the material instead of
            # switching to its flat inactive colour. Focus handling is unchanged.
            return True, native.user32.DefWindowProcW(msg.hWnd, m, 1, -1)
        return False, 0

    def _hit_test(self, msg) -> int:
        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        left, top, right, bottom = native.window_rect(msg.hWnd)
        dpr = self.devicePixelRatioF()
        border = round(6 * dpr)
        if not self.isMaximized():
            lft, rgt = x < left + border, x >= right - border
            tp, btm = y < top + border, y >= bottom - border
            if tp and lft:
                return native.HTTOPLEFT
            if tp and rgt:
                return native.HTTOPRIGHT
            if btm and lft:
                return native.HTBOTTOMLEFT
            if btm and rgt:
                return native.HTBOTTOMRIGHT
            if lft:
                return native.HTLEFT
            if rgt:
                return native.HTRIGHT
            if tp:
                return native.HTTOP
            if btm:
                return native.HTBOTTOM
        local = QPoint(round((x - left) / dpr), round((y - top) / dpr))
        if self.isMaximized():
            f = native.frame_thickness(msg.hWnd)
            local -= QPoint(round(f / dpr), round(f / dpr))
        if local.y() < TITLE_H and not self._hit_widget_is_interactive(local):
            return native.HTCAPTION
        return native.HTCLIENT
