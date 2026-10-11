# PyInstaller spec for FreeDictate. Build with scripts\build.ps1.
# One folder (not one file): starts faster, and antivirus tools flag
# self-extracting one-file Python apps far more often.
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
VERSION = re.search(r'__version__ = "([^"]+)"', (SRC / "freedictate" / "__init__.py").read_text()).group(1)

datas = [(str(ROOT / "assets"), "assets")]
datas += collect_data_files("faster_whisper")          # Silero VAD model
binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("onnxruntime")
# onnxruntime imports MSVCP140_1.dll, which PyInstaller only bundles inside
# PySide6\. Put the VC++ runtime extras next to python313.dll so a PC without
# the Visual C++ redistributable still loads them (measured with pefile).
import PySide6  # noqa: E402
_qt = Path(PySide6.__file__).parent
binaries += [(str(_qt / n), ".") for n in ("MSVCP140_1.dll", "MSVCP140_2.dll") if (_qt / n).exists()]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["freedictate.app", "freedictate.ui.settings", "freedictate.ui.overlay", "freedictate.ui.polish"],
    excludes=["tkinter", "unittest", "pydoc", "pytest", "IPython", "matplotlib", "PIL", "pynput", "pystray",
              "pyperclip", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL", "PySide6.QtPdf"],
    noarchive=False,
)


def keep(entry):
    """Drop Qt parts the app never loads: UI translations and unused plugins."""
    name = entry[0].replace("\\", "/")
    if "PySide6/translations/" in name:
        return False
    if "PySide6/plugins/" in name:
        return any(f"/plugins/{d}/" in name for d in ("platforms", "styles", "imageformats", "iconengines"))
    return True


a.binaries = [b for b in a.binaries if keep(b)]
a.datas = [d for d in a.datas if keep(d)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FreeDictate",
    icon=str(ROOT / "assets" / "freedictate.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="FreeDictate", upx=False)
