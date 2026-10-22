"""A top-level window with Windows 11 materials and a choice of title bar.

Custom title bar (default): the window is a real resizable Win32 window
(WS_CAPTION | WS_THICKFRAME) whose non-client area is folded into the client
(WM_NCCALCSIZE returns 0), so the backdrop covers the title bar and body as
one surface. WM_NCHITTEST hands the title bar back to Windows as HTCAPTION, so
dragging runs the system move loop that snap, AltSnap-style tools and the
wobbly-windows mod hook into.

Windows title bar: a normal framed window. The frame is extended over the
whole client area and the caption colour is cleared, so the material runs
under the title bar, and the body is left untinted so both match.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from . import icons, native, theme

TITLE_H = 40
CAPTION_W = 46

# A caption title colour set with DWMWA_TEXT_COLOR is drawn verbatim, so DWM
# never dims it on its own (measured: a set #ff0000 stayed #ff0000 on the
# inactive caption). Windows' own inactive caption text is DWM's default blended
# 0.396-0.399 per channel toward the caption colour (measured against DWM's
# inactive default caption on build 26200), so the themed colour is dimmed by
# that much when the Windows title bar is inactive.
INACTIVE_TEXT_MIX = 0.40

# Segoe Fluent Icons (Windows 11) or Segoe MDL2 Assets (Windows 10): the glyphs
# Windows draws on its own caption buttons.
_GLYPHS = {"minimize": "", "maximize": "", "restore": "", "close": ""}
_glyph_font: str | None = None


def _caption_font() -> str:
    global _glyph_font
    if _glyph_font is None:
        fams = set(QFontDatabase.families())
        _glyph_font = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in fams), "")
    return _glyph_font


class CaptionButton(QPushButton):
    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(CAPTION_W, TITLE_H)
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
        pal = theme.current()
        down = self.isDown()
        if self._hover or down:
            if self.kind == "close":
                bg = QColor("#c42b1c") if not down else QColor("#c42b1c").darker(115)
            else:
                bg = theme.qc(pal.text, 0.09 if not down else 0.05)
            # Square and flush, like Windows' own buttons; the window's rounded
            # corner clips the close button's outer corner.
            p.fillRect(self.rect(), bg)
        color = "#ffffff" if (self.kind == "close" and (self._hover or down)) else pal.text
        if not self.window().isActiveWindow() and not self._hover:
            color = pal.sub
        fam = _caption_font()
        if fam:
            f = QFont(fam)
            f.setPixelSize(10)
            # Grey anti-aliasing: ClearType fringes show colour on the red hover.
            f.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias)
            p.setFont(f)
            p.setPen(QColor(color))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _GLYPHS[self.kind])
        else:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pm = icons.pixmap(self.kind, color, 14, self.devicePixelRatioF())
            p.drawPixmap(round((self.width() - 14) / 2), round((self.height() - 14) / 2), pm)


class TitleBar(QWidget):
    def __init__(self, window: "FluentWindow", title: str):
        super().__init__(window)
        self.setFixedHeight(TITLE_H)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 0, 0)
        lay.setSpacing(10)
        self.icon = QLabel(self)
        self.icon.setFixedSize(16, 16)
        self.title = QLabel(title, self)
        self.title.setProperty("role", "sub")
        lay.addWidget(self.icon)
        lay.addWidget(self.title)
        lay.addStretch(1)
        self.extra = QHBoxLayout()
        self.extra.setSpacing(6)
        lay.addLayout(self.extra)
        buttons = QHBoxLayout()
        buttons.setSpacing(0)
        self.btn_min = CaptionButton("minimize", self)
        self.btn_max = CaptionButton("maximize", self)
        self.btn_close = CaptionButton("close", self)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            buttons.addWidget(b)
        lay.addLayout(buttons)
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_max.clicked.connect(window.toggle_maximized)
        self.btn_close.clicked.connect(window.close)

    def refresh(self) -> None:
        self.icon.setPixmap(icons.app_icon("ready").pixmap(QSize(16, 16)))
        for b in (self.btn_min, self.btn_max, self.btn_close):
            b.update()


class FluentWindow(QWidget):
    """Qt window with real Win32 frame semantics and a DWM backdrop."""
    activeChanged = Signal(bool)

    def __init__(self, title: str, native_titlebar: bool = False):
        self._native_tb = native_titlebar
        super().__init__(None, self._flags())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self._backdrop = "mica_alt"
        self._tint = 0.65
        self._keep_active = False
        self._chrome_applied = False
        self._cap_m: tuple[int, int, int] | None = None
        self._cap_m_key: tuple[str, bool] | None = None
        self._cap_measuring = False
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self.titlebar = TitleBar(self, title)
        self.titlebar.setVisible(not native_titlebar)
        self._root.addWidget(self.titlebar)
        self.body = QWidget(self)
        self._root.addWidget(self.body, 1)

    def _flags(self):
        f = Qt.WindowType.Window
        return f if self._native_tb else f | Qt.WindowType.FramelessWindowHint

    # ------------------------------------------------------------ appearance
    def hwnd(self) -> int:
        return int(self.winId())

    def native_titlebar(self) -> bool:
        return self._native_tb

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
        pal = theme.current()
        native.set_dark(h, pal.dark)
        native.set_corners(h)
        native.set_backdrop(h, self._backdrop, extend=self._native_tb)
        self._apply_caption()

    def _apply_caption(self) -> None:
        # Qt paints the Windows caption in the palette's window colour on show
        # and on activation, which hid the material under the title bar
        # (measured: a flat #1e1e2e caption over Mica). This runs after Qt's pass.
        if not self._native_tb or not self.isVisible() or self.isMinimized():
            return
        pal = theme.current()
        h = self.hwnd()
        if self._backdrop == "solid" or self._tint >= 1.0:
            # The body paints pal.bg opaque, so the caption is exactly that.
            native.set_caption(h, pal.bg, self._caption_text(pal, pal.bg))
            return
        if self._tint <= 0.0:
            # The strip shows the raw material; dim the text toward pal.bg as a
            # stand-in for the material tone it sits on.
            native.set_caption(h, None, self._caption_text(pal, pal.bg))
            return
        # A material runs under the caption raw, while the body gets the tint
        # over it — the caption looked lighter than the window (measured: up to
        # 32/255 on acrylic at 75% tint). DWM accepts a caption colour, so feed
        # it the tint composed over the material tone measured off the strip.
        # DWMWA_CAPTION_COLOR does not read back on current builds; the tone
        # comes from a screen grab instead, cached per material and dark mode.
        tone = self._caption_tone(pal)
        native.set_caption(h, tone, self._caption_text(pal, tone or pal.bg))

    def _caption_text(self, pal, color: str) -> str:
        """The caption title colour for the current activation state: pal.text
        focused, DWM's inactive blend of it (toward the caption colour) when
        not. The blend has to be computed here because DWM draws a colour set
        with DWMWA_TEXT_COLOR verbatim."""
        if self.isActiveWindow():
            return pal.text
        return theme.mix(color, pal.text, INACTIVE_TEXT_MIX)

    def _caption_tone(self, pal) -> str | None:
        """Tint composed over the measured material tone, or None until the
        measurement lands (the caption then shows the raw material, as before)."""
        key = (self._backdrop, pal.dark)
        if self._cap_m is not None and self._cap_m_key == key:
            return theme.mix("#{:02x}{:02x}{:02x}".format(*self._cap_m), pal.bg, self._tint)
        self._cap_m, self._cap_m_key = None, key
        self._schedule_caption_measure()
        return None

    def _schedule_caption_measure(self) -> None:
        if self._cap_measuring:
            return
        self._cap_measuring = True
        native.set_caption(self.hwnd(), None, self._caption_text(theme.current(), theme.current().bg))  # raw material in the strip
        # A DWM backdrop switch animates for a few hundred ms; measure after it.
        QTimer.singleShot(600, self._measure_caption_tone)

    def _measure_caption_tone(self) -> None:
        self._cap_measuring = False
        if not self._native_tb or not self.isVisible() or self.isMinimized():
            return
        rect = self._caption_strip_rect()
        if rect is None:
            return
        x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        if native.point_window(x, y) != self.hwnd():
            return  # covered by another window: retry on the next activation change
        m = native.screen_patch_median(rect)
        if m is None:
            return
        self._cap_m = m
        self._apply_caption()

    def _caption_strip_rect(self) -> tuple[int, int, int, int] | None:
        """Caption band clear of the icon, the title text and the buttons."""
        vl, vt, vr, _vb = native.visible_rect(self.hwnd())
        cap_h = native.client_origin(self.hwnd())[1] - vt
        if cap_h <= 4:
            return None
        dpr = self.devicePixelRatioF()
        x0, x1 = vl + round(150 * dpr), vr - round(170 * dpr)
        if x1 - x0 < round(60 * dpr):
            return None  # too narrow for a band that avoids the chrome
        return x0, vt + 2, x1, vt + cap_h - 2

    def showEvent(self, e):
        super().showEvent(e)
        if not self._chrome_applied:
            h = self.hwnd()
            if not self._native_tb:
                native.add_frame_styles(h)
            self._apply_dwm()
            self._chrome_applied = True
        self._sync_margins()
        QTimer.singleShot(0, self._record_normal)
        QTimer.singleShot(0, self._apply_caption)

    def paintEvent(self, e):
        p = QPainter(self)
        pal = theme.current()
        # Solid covers the material completely; a material takes the tint over
        # it. The Windows title bar can't take the tint: it keeps the raw
        # material, drawn by DWM outside this client area.
        alpha = 1.0 if self._backdrop == "solid" else self._tint
        # One step above zero keeps the window clickable: a layered window's
        # fully transparent pixels pass clicks to the window behind.
        p.fillRect(self.rect(), theme.qc(pal.bg, max(alpha, 1 / 255)))

    def _sync_margins(self) -> None:
        # A maximized window hangs its resize frame off the screen. With the
        # custom title bar that frame is client area, so pad it out of view.
        m = 0
        if not self._native_tb and self.isMaximized():
            m = round(native.frame_thickness(self.hwnd()) / self.devicePixelRatioF())
        self._root.setContentsMargins(m, m, m, m)

    # Qt rewrites the restore position when it maximizes or minimizes a window,
    # in screen coordinates where Windows expects work-area coordinates. With a
    # taskbar or app bar at the top, every maximize and restore moved the window
    # down by the bar's height (measured: 50 px per cycle; Tk windows don't
    # drift). The last normal placement is recorded and put back.
    def _record_normal(self) -> None:
        if self.isVisible():
            rect = native.normal_rect(self.hwnd())
            if rect:
                self._normal_rect = rect

    def _restore_normal(self) -> None:
        rect = getattr(self, "_normal_rect", None)
        if rect and (self.isMaximized() or self.isMinimized()):
            native.set_normal_rect(self.hwnd(), rect)

    def moveEvent(self, e):
        super().moveEvent(e)
        self._record_normal()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._record_normal()

    def changeEvent(self, e):
        if e.type() == QEvent.Type.WindowStateChange:
            self.titlebar.btn_max.set_kind("restore" if self.isMaximized() else "maximize")
            self._sync_margins()
            if self.isMaximized() or self.isMinimized():
                QTimer.singleShot(0, self._restore_normal)
        elif e.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            QTimer.singleShot(0, self._apply_caption)
        elif e.type() == QEvent.Type.ActivationChange:
            QTimer.singleShot(0, self._apply_caption)
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
        if m == native.WM_NCACTIVATE and self._keep_active and self._backdrop != "solid" and not self._native_tb:
            # Report "active" to the frame so DWM keeps the material instead of
            # switching to its flat inactive colour. Focus handling is unchanged.
            # Frameless windows only: with the Windows title bar the real state
            # has to reach DefWindowProc so DWM dims its own caption buttons,
            # and the re-asserted caption colour (see _apply_caption) keeps the
            # material tone instead.
            return True, native.user32.DefWindowProcW(msg.hWnd, m, 1, -1)
        if self._native_tb:
            return False, 0
        if m == native.WM_NCCALCSIZE and msg.wParam:
            # Client area = window rect, maximized too. Insetting the client
            # while maximized broke the layered window: Qt counted the inset as
            # a frame, its UpdateLayeredWindow push failed, and the old small
            # image stayed on a full-screen window (measured). _sync_margins
            # pads the off-screen overhang instead.
            return True, 0
        if m == native.WM_NCHITTEST:
            return True, self._hit_test(msg)
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
        local = QPoint(int((x - left) / dpr), int((y - top) / dpr))
        if local.y() <= self.titlebar.geometry().bottom() and not self._hit_widget_is_interactive(local):
            return native.HTCAPTION
        return native.HTCLIENT
