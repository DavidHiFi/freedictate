"""Window material under the Windows title bar: keep-effect and Blur margins."""
import ctypes
from ctypes import wintypes as wt
from types import SimpleNamespace

import pytest

from freedictate.ui import native
from freedictate.ui.window import FluentWindow
from test_ui import env, qapp  # noqa: F401  (pytest fixtures)


def _supported():
    return native.backdrop_supported() and native.transparency_enabled()


def test_keep_effect_answers_active_with_the_windows_title_bar(qapp, env, monkeypatch):
    if not _supported():
        pytest.skip("no systembackdrop on this machine")
    calls = []
    monkeypatch.setattr(native.user32, "DefWindowProcW", lambda h, m, w, l: calls.append((m, w, l)) or 0)
    win = FluentWindow("FreeDictate test", native_titlebar=True)
    try:
        win.set_look("acrylic", 0.5, True)
        msg = wt.MSG(hWnd=win.hwnd(), message=native.WM_NCACTIVATE)
        handled, _ = win.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))
        assert handled
        assert calls == [(native.WM_NCACTIVATE, 1, -1)]
    finally:
        win.close()
        win.deleteLater()


def test_blur_under_the_windows_title_bar_tints_through_dwm(monkeypatch):
    margins, accents, bb = [], [], []
    real_margins = native.MARGINS
    monkeypatch.setattr(native, "MARGINS", lambda *m: (margins.append(m), real_margins(*m))[1])
    monkeypatch.setattr(native, "backdrop_supported", lambda: True)
    monkeypatch.setattr(native, "_attr", lambda h, a, v: 0)
    monkeypatch.setattr(native, "_set_accent", lambda h, s, g=0: accents.append((s, g)) or True)
    monkeypatch.setattr(native, "_blur_behind", lambda h, on: bb.append(on))
    monkeypatch.setattr(native, "dwmapi", SimpleNamespace(DwmExtendFrameIntoClientArea=lambda h, p: 0))
    native.set_backdrop(1, "blur", extend=True, tint=0x7F2E1E1E)
    native.set_backdrop(1, "acrylic", extend=True)
    native.set_backdrop(1, "blur")
    assert margins == [(-1,) * 4, (-1,) * 4, (0,) * 4]
    assert bb == [True, False]
    assert accents == [(native._ACCENT_ACRYLIC, 0x7F2E1E1E), (native._ACCENT_DISABLED, 0), (native._ACCENT_BLURBEHIND, 0)]


def test_blur_window_paints_no_tint_of_its_own_under_the_windows_title_bar(qapp, env, monkeypatch):
    if not _supported():
        pytest.skip("no systembackdrop on this machine")
    for native_tb, want in ((True, True), (False, False)):
        win = FluentWindow("FreeDictate test", native_titlebar=native_tb)
        try:
            win.set_look("blur", 0.5, True)
            assert win._dwm_tints() is want
        finally:
            win.close()
            win.deleteLater()


def test_pending_window_timers_skip_a_deleted_window(qapp, env):
    import shiboken6
    from PySide6.QtCore import QEventLoop, QTimer
    calls = []
    win = FluentWindow("FreeDictate test", native_titlebar=True)
    win._soon(0, lambda: calls.append("ran"))
    shiboken6.delete(win)
    loop = QEventLoop()
    QTimer.singleShot(50, loop.quit)
    loop.exec()
    assert calls == []
