"""Command line entry point.

  FreeDictate                    start (or show the window if already running)
  FreeDictate --background       start in the tray without opening the window
  FreeDictate --page=history     open a page
  FreeDictate --portable         keep data next to the exe for this run
  FreeDictate --preload [model]  download a model and exit
  FreeDictate --make-icon PATH   write the .ico used by the build
  FreeDictate --register-task    (admin) create the elevated startup task
  FreeDictate --unregister-task  (admin) remove it
  FreeDictate --self-test FILE   check the bundled libraries work; writes the result to FILE
  FreeDictate --quit             close a running copy (installer, uninstaller)
  FreeDictate --debug            verbose log
"""
from __future__ import annotations

import os
import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # A windowed exe has no console: libraries that print progress would crash.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    import ctypes
    from . import APP_ID, log as logmod
    try:  # taskbar groups our windows as FreeDictate, matching the shortcut's ID
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    logmod.setup(debug="--debug" in argv)

    if "--register-task" in argv or "--unregister-task" in argv:
        from . import system
        ok, out = system.register_task() if "--register-task" in argv else system.unregister_task()
        if not ok:
            logmod.log.error("Task change failed: %s", out)
        return 0 if ok else 1
    if "--make-icon" in argv:
        from pathlib import Path
        from PySide6.QtGui import QGuiApplication
        from .ui import icons
        _app = QGuiApplication(sys.argv[:1])
        icons.write_ico(Path(argv[argv.index("--make-icon") + 1]))
        return 0
    if "--self-test" in argv:
        return _self_test(argv[argv.index("--self-test") + 1])
    if "--preload" in argv:
        from . import models
        i = argv.index("--preload")
        name = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else "small.en"
        if not models.is_downloaded(name):
            models.download(name, lambda d, t: print(f"\r{d * 100 // max(t, 1)}%", end=""))
        models.load(name, "auto", "auto")
        print(f"\n{name} ready")
        return 0

    from .app import run
    try:
        return run(argv)
    except Exception:
        logmod.log.critical("Crashed", exc_info=True)
        raise


def _self_test(target: str) -> int:
    """Exercise every native dependency the frozen build needs."""
    import traceback
    lines, ok = [], True

    def step(name, fn):
        nonlocal ok
        try:
            lines.append(f"ok   {name}: {fn()}")
        except Exception:
            ok = False
            lines.append(f"FAIL {name}: {traceback.format_exc().strip().splitlines()[-1]}")

    import numpy as np
    step("numpy", lambda: np.__version__)
    step("ctranslate2", lambda: __import__("ctranslate2").__version__)
    step("tokenizers", lambda: __import__("tokenizers").__version__)

    def vad():
        from faster_whisper.vad import get_speech_timestamps
        return f"{len(get_speech_timestamps(np.zeros(16000, dtype=np.float32)))} segments in silence"
    step("silero vad (onnxruntime)", vad)
    step("av (file decoding)", lambda: __import__("av").__version__)
    step("sounddevice", lambda: f"{len(__import__('sounddevice').query_devices())} audio devices")

    def qt():
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtSvg import QSvgRenderer  # noqa: F401
        from PySide6.QtNetwork import QLocalServer  # noqa: F401
        app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
        return f"Qt {__import__('PySide6').__version__}, platform {app.platformName()}"
    step("Qt", qt)

    def model():
        from . import models
        have = models.downloaded()
        if not have:
            return "no model downloaded; skipped"
        m, dev, ct = models.load(have[0], "cpu", "int8")
        return f"{have[0]} decoded on {dev}"
    step("speech model", model)
    from pathlib import Path
    verdict = "PASS" if ok else "FAIL"
    Path(target).write_text("\n".join([verdict, *lines]) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
