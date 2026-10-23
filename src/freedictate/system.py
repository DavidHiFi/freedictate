"""Start with Windows, run as administrator, and shell helpers."""
from __future__ import annotations

import ctypes
import os
import subprocess
import winreg
from pathlib import Path

from . import paths
from .log import log

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "FreeDictate"
TASK = "FreeDictate"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _quote(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts)


def launch_command(*extra: str) -> str:
    return _quote(paths.exe_command() + ["--background", *extra])


# ------------------------------------------------------------- Run key

def run_key_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            value, _ = winreg.QueryValueEx(k, RUN_VALUE)
            return bool(value)
    except OSError:
        return False


def set_run_key(enabled: bool) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if enabled:
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_VALUE)
            except FileNotFoundError:
                pass


# ------------------------------------------------------------- task

def _schtasks(*args: str) -> tuple[int, str]:
    r = subprocess.run(["schtasks", *args], capture_output=True, text=True, creationflags=_NO_WINDOW)
    return r.returncode, (r.stdout + r.stderr).strip()


def task_exists() -> bool:
    return _schtasks("/query", "/tn", TASK)[0] == 0


def task_enabled() -> bool:
    # The XML tags aren't translated; the CSV status column ("Disabled") is.
    code, out = _schtasks("/query", "/tn", TASK, "/xml")
    return code == 0 and "<Enabled>false</Enabled>" not in out


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def register_task() -> tuple[bool, str]:
    """Create the logon task that starts FreeDictate elevated. Needs admin."""
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Starts FreeDictate at sign-in with administrator rights, so it can paste into admin windows.</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{os.environ.get("USERDOMAIN", "")}\\{os.environ.get("USERNAME", "")}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{os.environ.get("USERDOMAIN", "")}\\{os.environ.get("USERNAME", "")}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec><Command>{_xml(paths.exe_command()[0])}</Command><Arguments>{_xml(_quote(paths.exe_command()[1:] + ["--background"]))}</Arguments><WorkingDirectory>{_xml(str(paths.APP_DIR))}</WorkingDirectory></Exec></Actions>
</Task>"""
    tmp = paths.DATA / "task.xml"
    tmp.write_text(xml, encoding="utf-16")
    try:
        code, out = _schtasks("/create", "/tn", TASK, "/xml", str(tmp), "/f")
    finally:
        tmp.unlink(missing_ok=True)
    if code == 0:
        set_run_key(False)  # one autostart mechanism, not two
    return code == 0, out


def unregister_task() -> tuple[bool, str]:
    if not task_exists():
        return True, ""
    code, out = _schtasks("/delete", "/tn", TASK, "/f")
    return code == 0, out


def run_task() -> bool:
    return _schtasks("/run", "/tn", TASK)[0] == 0


def _xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def run_elevated(*args: str, wait: bool = True) -> int:
    """Run this FreeDictate with admin rights (UAC prompt where enabled)."""
    cmd = paths.exe_command()
    params = _quote(cmd[1:] + list(args))

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("fMask", ctypes.c_ulong), ("hwnd", ctypes.c_void_p),
                    ("lpVerb", ctypes.c_wchar_p), ("lpFile", ctypes.c_wchar_p), ("lpParameters", ctypes.c_wchar_p),
                    ("lpDirectory", ctypes.c_wchar_p), ("nShow", ctypes.c_int), ("hInstApp", ctypes.c_void_p),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", ctypes.c_wchar_p), ("hkeyClass", ctypes.c_void_p),
                    ("dwHotKey", ctypes.c_ulong), ("hIcon", ctypes.c_void_p), ("hProcess", ctypes.c_void_p)]

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb, info.lpFile, info.lpParameters = "runas", cmd[0], params
    info.lpDirectory, info.nShow = str(paths.APP_DIR), 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return -1  # cancelled at the UAC prompt
    if not wait or not info.hProcess:
        return 0
    ctypes.windll.kernel32.WaitForSingleObject(ctypes.c_void_p(info.hProcess), 60000)
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(ctypes.c_void_p(info.hProcess), ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(info.hProcess))
    return code.value


# ------------------------------------------------------------- autostart

def remove_duplicate_run_key() -> None:
    """The installer used to autostart through a Run key; the task replaced it.
    A copy started by the task deletes any stray key so startup stays single."""
    if task_enabled() and run_key_enabled():
        set_run_key(False)
        log.info("Removed the leftover FreeDictate Run key; the startup task owns autostart")


def autostart_enabled() -> bool:
    return run_key_enabled() or task_enabled()


def set_autostart(enabled: bool, elevated: bool) -> str:
    """Apply the Start with Windows and Run as administrator choices.
    Returns an error message, or '' on success."""
    try:
        if enabled and elevated:
            if not task_enabled():
                if is_admin():
                    ok, out = register_task()
                else:
                    ok = run_elevated("--register-task") == 0
                    out = "Administrator permission was not given."
                if not ok:
                    return out or "Couldn't create the startup task."
            set_run_key(False)
        elif enabled:
            set_run_key(True)
            if task_exists():
                if is_admin():
                    unregister_task()
                else:
                    run_elevated("--unregister-task")
        else:
            set_run_key(False)
            if task_exists():
                if is_admin():
                    unregister_task()
                else:
                    run_elevated("--unregister-task")
    except Exception as e:
        log.exception("Autostart change failed")
        return str(e)
    return ""


def open_path(p: Path | str) -> None:
    try:
        os.startfile(str(p))
    except OSError:
        log.exception("Could not open %s", p)


def reveal(p: Path | str) -> None:
    subprocess.Popen(["explorer", "/select,", str(p)], creationflags=_NO_WINDOW)
