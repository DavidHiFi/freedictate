"""Render README previews from the real app window, on screen, with its material.

    set FREEDICTATE_HOME=C:\\some\\scratch\\dir
    python scripts\\screenshots.py docs\\images [--theme "Catppuccin Mocha"] [--backdrop acrylic]

Runs a full FreeDictate instance against a scratch data folder (so your own
settings and history are untouched), opens each page and grabs the composited
screen under the window, which is the only way to capture the Windows
backdrop. It also captures the recording bar and the tray menu.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

if not os.environ.get("FREEDICTATE_HOME"):
    sys.exit("Set FREEDICTATE_HOME to a scratch folder first; this must not touch your real settings.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--theme", default="Catppuccin Mocha")
    ap.add_argument("--backdrop", default="mica_alt")
    ap.add_argument("--pages", default="dictation,models,text,look,history,general,about")
    ap.add_argument("--prefix", default="")
    ap.add_argument("--size", default="1000x720")
    ap.add_argument("--overlay", action="store_true")
    ap.add_argument("--menus", action="store_true", help="also capture the tray menu and a dropdown")
    ap.add_argument("--quit", action="store_true", default=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from freedictate import log as logmod
    logmod.setup()
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication
    from freedictate.app import App
    from freedictate.ui import icons

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv[:1])
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setWindowIcon(icons.app_icon("ready"))
    app = App(qapp, background=True)
    app.cfg.update({"theme": args.theme, "backdrop": args.backdrop, "first_run_done": True,
                    "window_geometry": ""})
    w_, h_ = (int(x) for x in args.size.split("x"))
    user32 = ctypes.windll.user32

    def grab(widget, name: str, pad: int = 24) -> None:
        from PySide6.QtGui import QGuiApplication
        g = widget.frameGeometry()
        screen = QGuiApplication.screenAt(g.center()) or QGuiApplication.primaryScreen()
        sg = screen.geometry()
        pm = screen.grabWindow(0, g.x() - sg.x() - pad, g.y() - sg.y() - pad, g.width() + 2 * pad, g.height() + 2 * pad)
        pm.save(str(out / f"{args.prefix}{name}.png"))
        print("wrote", out / f"{args.prefix}{name}.png")

    def foreground(win) -> None:
        user32.keybd_event(0x12, 0, 0, 0)       # a synthetic Alt lifts the foreground lock
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(int(win.winId()))

    steps = []

    def start():
        app.show_settings()
        w = app.settings_window
        w.resize(w_, h_)
        scr = qapp.primaryScreen().availableGeometry()
        w.move(scr.center() - w.rect().center())
        foreground(w)
        QTimer.singleShot(900, lambda: run_steps(w))

    def run_steps(w):
        pages = args.pages.split(",") if args.pages else []
        for p in pages:
            steps.append(("page", p))
        if args.overlay:
            steps.append(("overlay", None))
        if args.menus:
            steps.extend([("menu", None), ("combo", None)])
        next_step(w)

    def next_step(w):
        if not steps:
            if args.quit:
                app.quit()
            return
        kind, val = steps.pop(0)
        if kind == "page":
            w.go(val)
            foreground(w)
            QTimer.singleShot(700, lambda: (grab(w, val), next_step(w)))
        elif kind == "overlay":
            app.engine.recorder.started = time.monotonic() - 7
            app.overlay.cfg.update({"overlay": True})
            app.overlay.history.extend([0.6, 0.9, 0.5, 0.8, 0.4, 0.7, 0.3, 0.5, 0.2])
            app.overlay._show("listening")
            app.overlay.timer.stop()
            QTimer.singleShot(500, lambda: (grab(app.overlay, "overlay", pad=16), app.overlay.hide(), next_step(w)))
        elif kind == "menu":
            from PySide6.QtCore import QPoint
            app._fill_menu()
            g = w.frameGeometry()
            app.menu.popup(QPoint(g.right() - 40, g.top() + 120))

            def shot():
                grab(app.menu, "tray-menu", pad=20)
                app.menu.hide()
                next_step(w)
            QTimer.singleShot(700, shot)
        elif kind == "combo":
            from freedictate.ui.widgets import Combo
            w.go("look")
            foreground(w)
            combo = w.pages["look"].findChildren(Combo)[0]

            def shot():
                popup = combo.view().window()
                g1, g2 = w.frameGeometry(), popup.frameGeometry()
                grab(w, "dropdown", pad=0)
                combo.hidePopup()
                next_step(w)
            QTimer.singleShot(400, combo.showPopup)
            QTimer.singleShot(1100, shot)

    QTimer.singleShot(2500, start)
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
