"""Live check: does the window move with a title-bar drag and with Alt+drag, and
does the wobbly-windows mod deform it mid-drag? Uses real input (SendInput).

    set FREEDICTATE_HOME=C:/scratch & python tests/manual/drag_check.py out_dir
"""
import ctypes, subprocess, sys, time, os
import functools
print = functools.partial(print, flush=True)
from ctypes import wintypes as wt
from pathlib import Path

u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
for name, args in {"GetWindowRect": [wt.HWND, ctypes.POINTER(wt.RECT)], "GetWindowLongW": [wt.HWND, ctypes.c_int],
                   "SetForegroundWindow": [wt.HWND], "GetWindow": [wt.HWND, wt.UINT],
                   "GetWindowThreadProcessId": [wt.HWND, ctypes.POINTER(wt.DWORD)],
                   "IsWindowVisible": [wt.HWND], "GetWindowTextW": [wt.HWND, wt.LPWSTR, ctypes.c_int],
                   "GetClassNameW": [wt.HWND, wt.LPWSTR, ctypes.c_int]}.items():
    getattr(u, name).argtypes = args
u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
root = Path(__file__).resolve().parents[2]
target = sys.argv[2] if len(sys.argv) > 2 else ""
proc = subprocess.Popen([sys.executable, "-m", "freedictate", "--page=look"], cwd=root / "src") if not target else None

def find():
    """The visible FreeDictate main window. Qt creates hidden top-levels with the
    same title for combo popups, and venv python.exe is a launcher whose pid
    differs from the app's, so match on class, title, visibility and size."""
    best, area = None, 0
    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hh, _):
        title = ctypes.create_unicode_buffer(64); cls = ctypes.create_unicode_buffer(64)
        u.GetWindowTextW(hh, title, 64); u.GetClassNameW(hh, cls, 64)
        if (title.value == (target or "FreeDictate")) and (target or cls.value.startswith("Qt")) and u.IsWindowVisible(hh):
            r = wt.RECT(); u.GetWindowRect(hh, ctypes.byref(r))
            nonlocal best, area
            a = (r.right - r.left) * (r.bottom - r.top)
            if a > area:
                best, area = hh, a
        return True
    u.EnumWindows(cb, 0)
    return best if area > 400 * 300 else None

h = None
for _ in range(60):
    time.sleep(0.5); h = find()
    if h: break
assert h, "window not found"
time.sleep(3)
h = find()
print("hwnd", h)
def rect():
    r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r)); return r.left, r.top, r.right, r.bottom
style = u.GetWindowLongW(h, -16) & 0xffffffff; ex = u.GetWindowLongW(h, -20) & 0xffffffff
print(f"style={style:#x} thickframe={bool(style & 0x40000)} caption={bool(style & 0xC00000)} ex={ex:#x} owner={u.GetWindow(h, 4)}")

class MI(ctypes.Structure):
    _fields_=[("dx",wt.LONG),("dy",wt.LONG),("data",wt.DWORD),("flags",wt.DWORD),("time",wt.DWORD),("extra",ctypes.c_size_t)]
class KI(ctypes.Structure):
    _fields_=[("vk",wt.WORD),("scan",wt.WORD),("flags",wt.DWORD),("time",wt.DWORD),("extra",ctypes.c_size_t)]
class U(ctypes.Union): _fields_=[("mi",MI),("ki",KI)]
class INP(ctypes.Structure): _fields_=[("type",wt.DWORD),("u",U)]
def send(*ins):
    arr=(INP*len(ins))(*ins); u.SendInput(len(ins),arr,ctypes.sizeof(INP))
def mouse(flags): i=INP(type=0); i.u.mi=MI(0,0,0,flags,0,0); return i
def key(vk, up=False): i=INP(type=1); i.u.ki=KI(vk,0,2 if up else 0,0,0); return i
from PySide6.QtGui import QGuiApplication
_qapp = QGuiApplication(sys.argv[:1])


def grab(name):
    """Capture the whole primary screen in-process (~20 ms), so the drag keeps
    moving and a wobble has no time to settle."""
    QGuiApplication.primaryScreen().grabWindow(0).save(str(out / name))

old = wt.POINT(); u.GetCursorPos(ctypes.byref(old))
u.keybd_event(0x12,0,0,0); u.keybd_event(0x12,0,2,0); u.SetForegroundWindow(h); time.sleep(0.4)

def drag(x, y, dx, dy, alt=False, shot=None):
    u.SetCursorPos(x, y); time.sleep(0.15)
    if alt: send(key(0x12)); time.sleep(0.05)
    send(mouse(0x2)); time.sleep(0.12)
    steps = 24
    for i in range(1, steps + 1):
        u.SetCursorPos(x + dx * i // steps, y + dy * i // steps); time.sleep(0.016)
        if shot and i == steps // 2:
            grab(shot)
    time.sleep(0.05)
    send(mouse(0x4)); time.sleep(0.05)
    if alt: send(key(0x12, True))
    time.sleep(0.8)

l, t, r, b = rect(); print("start", (l, t, r, b))
drag(l + 400, t + 20, 300, 150, shot=f"mid-title-drag{target}.png")
l2, t2, r2, b2 = rect(); print("title drag moved", (l2 - l, t2 - t), "cursor (300, 150)")
drag(l2 + 300, t2 + 250, -300, -150, alt=True, shot=f"mid-alt-drag{target}.png")
l3, t3, _, _ = rect(); print("alt drag moved", (l3 - l2, t3 - t2), "cursor (-300, -150)")
u.SetCursorPos(old.x, old.y)
pid = wt.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
if proc:
    subprocess.run(["taskkill", "/PID", str(pid.value), "/F"], capture_output=True)
    proc.terminate()
