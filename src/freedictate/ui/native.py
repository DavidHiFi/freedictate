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


def set_backdrop(hwnd: int, kind: str) -> bool:
    if not backdrop_supported():
        return False
    # Margins stay 0: a -1 "sheet of glass" makes DWM paint a dark caption band
    # over the backdrop while the window is inactive (measured on 26200).
    dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(MARGINS(0, 0, 0, 0)))
    return _attr(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, BACKDROP_VALUES.get(kind, 1)) == 0


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
