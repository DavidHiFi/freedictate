"""Win32 and DWM calls used by the window chrome, the overlay and popups."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wt.UINT]
user32.GetDpiForWindow.argtypes = [wt.HWND]
user32.IsZoomed.argtypes = [wt.HWND]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.MonitorFromWindow.restype = wt.HMONITOR
user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
user32.GetForegroundWindow.restype = wt.HWND
dwmapi.DwmSetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
dwmapi.DwmExtendFrameIntoClientArea.argtypes = [wt.HWND, ctypes.c_void_p]
dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
user32.SetWindowPlacement.argtypes = [wt.HWND, ctypes.c_void_p]
user32.GetWindowPlacement.argtypes = [wt.HWND, ctypes.c_void_p]
user32.IsIconic.argtypes = [wt.HWND]
user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.c_void_p]
user32.WindowFromPoint.restype = wt.HWND
user32.WindowFromPoint.argtypes = [wt.POINT]
user32.ClientToScreen.restype = wt.BOOL
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
user32.GetDC.restype = wt.HDC
user32.GetDC.argtypes = [wt.HWND]
user32.ReleaseDC.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]

gdi32 = ctypes.WinDLL("gdi32")
SRCCOPY = 0x00CC0020
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
gdi32.DeleteObject.restype = wt.BOOL
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.restype = wt.BOOL
gdi32.DeleteDC.argtypes = [wt.HDC]

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CAPTION, WS_THICKFRAME, WS_SYSMENU = 0x00C00000, 0x00040000, 0x00080000
WS_MINIMIZEBOX, WS_MAXIMIZEBOX, WS_POPUP = 0x00020000, 0x00010000, 0x80000000
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TRANSPARENT, WS_EX_LAYERED, WS_EX_TOPMOST = \
    0x80, 0x08000000, 0x20, 0x80000, 0x8
SWP_FRAMECHANGED = 0x0020
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10

WM_NCCALCSIZE, WM_NCHITTEST, WM_NCACTIVATE = 0x0083, 0x0084, 0x0086
WM_SETTINGCHANGE, WM_DWMCOLORIZATIONCOLORCHANGED = 0x001A, 0x0320
HTCLIENT, HTCAPTION = 1, 2
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT, HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 10, 11, 12, 13, 14, 15, 16, 17

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR = 35, 36
DWMWA_COLOR_NONE = 0xFFFFFFFE
DWMWA_SYSTEMBACKDROP_TYPE = 38
BACKDROP_VALUES = {"solid": 1, "mica": 2, "acrylic": 3, "mica_alt": 4}
BUILD = sys.getwindowsversion().build


def backdrop_supported() -> bool:
    """DWMWA_SYSTEMBACKDROP_TYPE arrived in Windows 11 22H2 (build 22621)."""
    return BUILD >= 22621


def transparency_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "EnableTransparency")[0])
    except OSError:
        return True


class MARGINS(ctypes.Structure):
    _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]


class NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wt.RECT * 3), ("lppos", ctypes.c_void_p)]


def _attr(hwnd: int, attr: int, value: int) -> int:
    v = ctypes.c_int(value)
    return dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4)


def set_dark(hwnd: int, dark: bool) -> None:
    _attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)


def set_corners(hwnd: int, small: bool = False) -> None:
    _attr(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, 3 if small else 2)


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int), ("gradient", wt.DWORD), ("animation", ctypes.c_int)]


class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [("attribute", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]


user32.SetWindowCompositionAttribute.argtypes = [wt.HWND, ctypes.POINTER(_WINCOMPATTRDATA)]
_WCA_ACCENT_POLICY, _ACCENT_DISABLED, _ACCENT_BLURBEHIND, _ACCENT_ACRYLIC = 19, 0, 3, 4


def _set_accent(hwnd: int, state: int, gradient: int = 0) -> bool:
    """Accent policies from Windows 10, still drawn by Windows 11: blur (no noise
    or tint of its own) and acrylic (blur with grain; ``gradient`` is its tint)."""
    policy = _ACCENT_POLICY(state, 0, gradient, 0)
    data = _WINCOMPATTRDATA(_WCA_ACCENT_POLICY, ctypes.cast(ctypes.byref(policy), ctypes.c_void_p),
                            ctypes.sizeof(policy))
    return bool(user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data)))


def set_backdrop(hwnd: int, kind: str, extend: bool = False) -> bool:
    """Apply a system backdrop. ``extend`` is for windows that keep the Windows
    title bar: the frame is extended over the client so the material runs
    from the caption into the body."""
    if not backdrop_supported():
        return False
    # Frameless windows keep margins at 0: a -1 "sheet of glass" makes DWM paint
    # a dark caption band over the backdrop while the window is inactive
    # (measured on 26200).
    m = -1 if extend and kind != "solid" else 0
    dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(MARGINS(m, m, m, m)))
    if kind == "blur":
        # Blur is an accent, not a system backdrop; the two would stack.
        _attr(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, 1)
        return _set_accent(hwnd, _ACCENT_BLURBEHIND)
    _set_accent(hwnd, _ACCENT_DISABLED)
    return _attr(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, BACKDROP_VALUES.get(kind, 1)) == 0


def set_accent_acrylic(hwnd: int) -> bool:
    """Acrylic drawn as an accent. The system Acrylic backdrop goes black on a menu
    that is not the focused window (the tray menu); the accent keeps drawing. The
    gradient is almost clear, so the window's own tint sets the colour."""
    if not backdrop_supported():
        return False
    _attr(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, 1)
    return _set_accent(hwnd, _ACCENT_ACRYLIC, 0x01000000)


def _bgr(hex_color: str) -> int:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return (b << 16) | (g << 8) | r


def set_caption(hwnd: int, color: str | None, text: str) -> None:
    """Windows title bar colours: ``color`` None lets the material show through."""
    _attr(hwnd, DWMWA_CAPTION_COLOR, DWMWA_COLOR_NONE if color is None else _bgr(color))
    _attr(hwnd, DWMWA_TEXT_COLOR, _bgr(text))


def add_frame_styles(hwnd: int) -> None:
    """Give a Qt frameless window a real resizable frame, so Windows treats it
    as a normal window: snap, minimize animation, Alt-drag tools, and the
    wobbly-windows mod (which skips windows without WS_THICKFRAME)."""
    style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
    want = (style & ~WS_POPUP) | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
    if want != style:
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, want)
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_FRAMECHANGED | SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)


def make_overlay(hwnd: int) -> None:
    """No focus, no taskbar button, clicks pass through."""
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT | WS_EX_TOPMOST)


def frame_thickness(hwnd: int) -> int:
    dpi = user32.GetDpiForWindow(hwnd) or 96
    return user32.GetSystemMetricsForDpi(32, dpi) + user32.GetSystemMetricsForDpi(92, dpi)  # SM_CXFRAME + SM_CXPADDEDBORDER


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", wt.UINT), ("flags", wt.UINT), ("show", wt.UINT), ("min_pos", wt.POINT),
                ("max_pos", wt.POINT), ("normal", wt.RECT)]


def _placement(hwnd: int) -> _WINDOWPLACEMENT:
    p = _WINDOWPLACEMENT()
    p.length = ctypes.sizeof(p)
    user32.GetWindowPlacement(hwnd, ctypes.byref(p))
    return p


def normal_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """The window's current rect in the work-area coordinates WINDOWPLACEMENT
    uses, or None while it is maximized or minimized."""
    if user32.IsZoomed(hwnd) or user32.IsIconic(hwnd):
        return None
    left, top, right, bottom = window_rect(hwnd)
    mon = user32.MonitorFromWindow(hwnd, 2)
    mi = _MONITORINFO()
    mi.cb = ctypes.sizeof(mi)
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    dx, dy = mi.work.left - mi.mon.left, mi.work.top - mi.mon.top
    return left - dx, top - dy, right - dx, bottom - dy


def set_normal_rect(hwnd: int, rect: tuple[int, int, int, int]) -> None:
    p = _placement(hwnd)
    if (p.normal.left, p.normal.top, p.normal.right, p.normal.bottom) != rect:
        p.normal = wt.RECT(*rect)
        user32.SetWindowPlacement(hwnd, ctypes.byref(p))


def visible_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Window bounds without the invisible resize borders a framed window has."""
    r = wt.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:  # EXTENDED_FRAME_BOUNDS
        return window_rect(hwnd)
    return r.left, r.top, r.right, r.bottom


def set_visible_rect(hwnd: int, rect: tuple[int, int, int, int]) -> None:
    """Place a window so its visible bounds are ``rect``."""
    wl, wtop, wr, wb = window_rect(hwnd)
    vl, vt, vr, vb = visible_rect(hwnd)
    left, top = rect[0] - (vl - wl), rect[1] - (vt - wtop)
    width = rect[2] - rect[0] + (vl - wl) + (wr - vr)
    height = rect[3] - rect[1] + (vt - wtop) + (wb - vb)
    user32.SetWindowPos(hwnd, None, left, top, width, height, SWP_NOZORDER | SWP_NOACTIVATE)


def is_zoomed(hwnd: int) -> bool:
    return bool(user32.IsZoomed(hwnd))


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("mon", wt.RECT), ("work", wt.RECT), ("flags", wt.DWORD)]


def foreground_work_area() -> tuple[int, int, int, int]:
    """Physical work area of the monitor holding the focused window (where you type)."""
    mon = user32.MonitorFromWindow(user32.GetForegroundWindow(), 2)
    mi = _MONITORINFO()
    mi.cb = ctypes.sizeof(mi)
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    return mi.work.left, mi.work.top, mi.work.right, mi.work.bottom


class _BMIH(ctypes.Structure):
    _fields_ = [("sz", wt.DWORD), ("w", ctypes.c_long), ("h", ctypes.c_long),
                ("planes", wt.WORD), ("bits", wt.WORD), ("comp", wt.DWORD),
                ("szimg", wt.DWORD), ("xppm", ctypes.c_long), ("yppm", ctypes.c_long),
                ("used", wt.DWORD), ("imp", wt.DWORD)]


def point_window(x: int, y: int) -> int:
    """Handle of the top-level window under a physical screen point."""
    return user32.WindowFromPoint(wt.POINT(int(x), int(y))) or 0


def client_origin(hwnd: int) -> tuple[int, int]:
    """Screen position of the client area's top-left, physical pixels."""
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def screen_patch_median(rect: tuple[int, int, int, int]) -> tuple[int, int, int] | None:
    """Median RGB of a physical-pixel screen rectangle, None on failure.

    Reads what DWM actually composited there — the only way to see the tone a
    system backdrop was given."""
    l, t, r, b = (int(v) for v in rect)
    w, h = r - l, b - t
    if w <= 0 or h <= 0:
        return None
    hdc = user32.GetDC(None)
    if not hdc:
        return None
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, l, t, SRCCOPY)
    bi = _BMIH(ctypes.sizeof(_BMIH), w, -h, 1, 32, 0)
    buf = (ctypes.c_ubyte * (w * h * 4))()
    ok = gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(None, hdc)
    if not ok:
        return None
    chans = ([], [], [])
    for i in range(0, len(buf), 4):
        for c in range(3):
            chans[c].append(buf[i + 2 - c])  # scanlines are BGRA
    return tuple(sorted(ch)[len(ch) // 2] for ch in chans)
