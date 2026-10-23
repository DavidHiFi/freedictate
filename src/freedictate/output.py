"""Deliver text to the focused app: clipboard paste, typing, or clipboard only."""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes as wt

from . import hotkeys
from .log import log

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

user32.OpenClipboard.argtypes = [wt.HWND]
user32.GetClipboardData.restype = wt.HANDLE
user32.GetClipboardData.argtypes = [wt.UINT]
user32.SetClipboardData.restype = wt.HANDLE
user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
user32.EnumClipboardFormats.argtypes = [wt.UINT]
user32.EnumClipboardFormats.restype = wt.UINT
user32.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wt.UINT
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
kernel32.GlobalAlloc.restype = wt.HGLOBAL
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalSize.argtypes = [wt.HGLOBAL]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
advapi32.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
# Handle-based formats that are not global memory; Windows re-synthesizes them.
_GDI_FORMATS = {2, 3, 9, 14}
# Ask clipboard managers and Win+V history to skip our temporary text.
_FMT_NO_MONITOR = user32.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing")
_FMT_NO_HISTORY = user32.RegisterClipboardFormatW("CanIncludeInClipboardHistory")
_FMT_NO_CLOUD = user32.RegisterClipboardFormatW("CanUploadToCloudClipboard")


# --------------------------------------------------------------- SendInput

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


KEYUP, UNICODE, EXTENDED = 0x0002, 0x0004, 0x0001
VK_CONTROL, VK_SHIFT, VK_INSERT, VK_RETURN, VK_V = 0x11, 0x10, 0x2D, 0x0D, 0x56


def _key(vk=0, scan=0, flags=0) -> _INPUT:
    i = _INPUT(type=1)
    i.u.ki = _KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


def _send(inputs: list[_INPUT]) -> int:
    arr = (_INPUT * len(inputs))(*inputs)
    return user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))


def _chord(mod: int, vk: int, ext: bool = False) -> None:
    f = EXTENDED if ext else 0
    _send([_key(mod), _key(vk, flags=f), _key(vk, flags=f | KEYUP), _key(mod, flags=KEYUP)])


def press_enter() -> None:
    """Send the Enter key (smart auto-submit)."""
    _send([_key(VK_RETURN), _key(VK_RETURN, flags=KEYUP)])


def type_text(text: str) -> None:
    """Type characters one by one as Unicode input. Slower than pasting, but
    works where paste is blocked and leaves the clipboard alone."""
    batch: list[_INPUT] = []
    for ch in text.replace("\r\n", "\n"):
        if ch == "\n":
            batch += [_key(VK_RETURN), _key(VK_RETURN, flags=KEYUP)]
            continue
        data = ch.encode("utf-16-le")  # characters outside the BMP send two surrogate units
        for i in range(0, len(data), 2):
            code = int.from_bytes(data[i:i + 2], "little")
            batch += [_key(0, code, UNICODE), _key(0, code, UNICODE | KEYUP)]
        if len(batch) >= 64:
            _send(batch)
            batch = []
            time.sleep(0.004)
    if batch:
        _send(batch)


# --------------------------------------------------------------- clipboard

def _open_clipboard(tries: int = 20) -> bool:
    for _ in range(tries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.015)
    return False


def _global_from_bytes(data: bytes):
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, max(1, len(data)))
    if not h:
        return None
    p = kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(h)
    return h


def save_clipboard() -> list[tuple[int, bytes]] | None:
    """Copy every memory-backed format so the clipboard can be put back."""
    if not _open_clipboard():
        return None
    saved = []
    try:
        fmt = 0
        while True:
            fmt = user32.EnumClipboardFormats(fmt)
            if not fmt:
                break
            if fmt in _GDI_FORMATS:
                continue
            h = user32.GetClipboardData(fmt)
            if not h:
                continue
            size = kernel32.GlobalSize(h)
            p = kernel32.GlobalLock(h)
            if not p:
                continue
            try:
                saved.append((fmt, ctypes.string_at(p, size)))
            finally:
                kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()
    return saved


def restore_clipboard(saved: list[tuple[int, bytes]]) -> None:
    if not _open_clipboard():
        return
    try:
        user32.EmptyClipboard()
        for fmt, data in saved:
            h = _global_from_bytes(data)
            if h:
                user32.SetClipboardData(fmt, h)
    finally:
        user32.CloseClipboard()


def set_clipboard(text: str, transient: bool = False) -> bool:
    if not _open_clipboard():
        log.warning("Clipboard busy; could not set text.")
        return False
    try:
        user32.EmptyClipboard()
        h = _global_from_bytes((text + "\0").encode("utf-16-le"))
        if not h or not user32.SetClipboardData(CF_UNICODETEXT, h):
            return False
        if transient:
            zero = b"\0\0\0\0"
            for fmt in (_FMT_NO_MONITOR,):
                hh = _global_from_bytes(zero)
                if hh:
                    user32.SetClipboardData(fmt, hh)
            for fmt in (_FMT_NO_HISTORY, _FMT_NO_CLOUD):
                hh = _global_from_bytes(zero)
                if hh:
                    user32.SetClipboardData(fmt, hh)
        return True
    finally:
        user32.CloseClipboard()


def get_clipboard_text() -> str:
    if not _open_clipboard():
        return ""
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        p = kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


# ------------------------------------------------------------- target app

def foreground_process() -> tuple[int, str]:
    hwnd = user32.GetForegroundWindow()
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = ""
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = wt.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                name = os.path.basename(buf.value)
        finally:
            kernel32.CloseHandle(h)
    return pid.value, name


def _elevated(pid: int) -> bool | None:
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    try:
        tok = wt.HANDLE()
        if not advapi32.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):  # TOKEN_QUERY
            return True  # access denied to the token: it runs above us
        try:
            val, n = wt.DWORD(), wt.DWORD()
            if advapi32.GetTokenInformation(tok, 20, ctypes.byref(val), 4, ctypes.byref(n)):  # TokenElevation
                return bool(val.value)
            return None
        finally:
            kernel32.CloseHandle(tok)
    finally:
        kernel32.CloseHandle(h)


def self_elevated() -> bool:
    return bool(_elevated(os.getpid()))


def target_blocks_input() -> bool:
    """True when the focused app runs as administrator and we do not, so
    Windows will drop our keystrokes (UIPI)."""
    pid, _ = foreground_process()
    return bool(_elevated(pid)) and not self_elevated()


# ------------------------------------------------------------------ deliver

def wait_for_modifiers_release(timeout: float = 2.0) -> None:
    """Ctrl+V sent while Win is still down becomes Win+Ctrl+V."""
    end = time.monotonic() + timeout
    while time.monotonic() < end and hotkeys.modifiers_down():
        time.sleep(0.01)


def deliver(text: str, method: str, restore: bool, delay_ms: int, submit: bool = False) -> str:
    """Send text to the focused app, then Enter when ``submit``. Returns what
    happened, for logging: 'pasted', 'typed', 'copied', or 'blocked' (admin
    window, text left on the clipboard)."""
    if method == "clipboard":
        set_clipboard(text)
        return "copied"
    wait_for_modifiers_release()
    if target_blocks_input():
        set_clipboard(text)
        return "blocked"
    time.sleep(delay_ms / 1000)
    if method == "type":
        type_text(text)
        if submit:
            press_enter()
        return "typed"
    saved = save_clipboard() if restore else None
    if not set_clipboard(text, transient=restore and saved is not None):
        if saved is not None:
            restore_clipboard(saved)   # don't leave the clipboard emptied by the failed set
        type_text(text)
        if submit:
            press_enter()
        return "typed"
    seq = user32.GetClipboardSequenceNumber()
    if method == "paste_shift_insert":
        _chord(VK_SHIFT, VK_INSERT, ext=True)
    else:
        _chord(VK_CONTROL, VK_V)
    if submit:
        # Queued right behind the paste, while the clipboard still holds the
        # text: after the restore, a slow app could paste and send the old one.
        press_enter()
    if saved is not None:
        # The target reads the clipboard after it handles the keystroke. Give it
        # time, then put the old contents back unless something else copied.
        time.sleep(0.45)
        if user32.GetClipboardSequenceNumber() == seq:
            restore_clipboard(saved)
    return "pasted"
