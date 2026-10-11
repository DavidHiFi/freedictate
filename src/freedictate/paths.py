"""Where FreeDictate keeps its files.

Installed: settings and history in %APPDATA%\\FreeDictate, logs in
%LOCALAPPDATA%\\FreeDictate\\logs. Portable (a ``portable.txt`` file next to the
exe, or ``--portable``): everything in ``data\\`` beside the exe, models included.

Models default to the Hugging Face cache, so a model downloaded by any earlier
FreeDictate version or another faster-whisper app is reused.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
# The folder holding FreeDictate.exe, or the repo root when run from source.
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parents[2]
ASSETS = Path(getattr(sys, "_MEIPASS", APP_DIR)) / "assets"

_portable = (APP_DIR / "portable.txt").exists() or "--portable" in sys.argv


def _known(env: str, fallback: str) -> Path:
    v = os.environ.get(env)
    return Path(v) if v else Path.home() / fallback


if os.environ.get("FREEDICTATE_HOME"):  # tests and side-by-side dev runs; models stay shared
    DATA = Path(os.environ["FREEDICTATE_HOME"])
    LOGS = DATA / "logs"
    MODELS = None
elif _portable:
    DATA = APP_DIR / "data"
    LOGS = DATA / "logs"
    MODELS: Path | None = DATA / "models"
else:
    DATA = _known("APPDATA", "AppData/Roaming") / "FreeDictate"
    LOGS = _known("LOCALAPPDATA", "AppData/Local") / "FreeDictate" / "logs"
    MODELS = None  # Hugging Face default cache

SETTINGS = DATA / "settings.json"
HISTORY_DB = DATA / "history.db"
CUDA_DIR = (DATA if _portable else _known("LOCALAPPDATA", "AppData/Local") / "FreeDictate") / "cuda"


def portable() -> bool:
    return _portable


def ensure() -> None:
    for d in (DATA, LOGS):
        d.mkdir(parents=True, exist_ok=True)
    if MODELS is not None:
        MODELS.mkdir(parents=True, exist_ok=True)


def exe_command() -> list[str]:
    """Command line that starts this FreeDictate (used for autostart and restarts)."""
    if FROZEN:
        return [sys.executable]
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else exe), "-m", "freedictate"]
