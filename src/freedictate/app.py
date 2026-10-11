"""The running app: tray icon, windows, engine wiring, updates, single instance."""
from __future__ import annotations

import os
import sys
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from . import APP_NAME, __version__, models, paths, system, updater
from .config import Config
from .engine import Engine
from .history import History
from .log import log
from .ui import icons, native, theme, widgets

SERVER_NAME = f"FreeDictate-{os.environ.get('USERNAME', 'user')}"


class Bus(QObject):
    """Carries engine events from worker threads to the GUI thread."""
    event = Signal(str, dict)
    update_status = Signal(str, object)        # message, Release | None
    update_progress = Signal(int, int)
    gpu_progress = Signal(int, int)
    gpu_status = Signal(str)                   # "", "downloading", "done", "error: ..."
    file_result = Signal(str, str)             # path, text or "error: ..."
    history_changed = Signal()                 # a dictation was added on a worker thread
    notify = Signal(str, str, bool)            # title, text, error
    quit_requested = Signal()                  # worker threads ask the GUI thread to quit


class App(QObject):
    def __init__(self, qapp: QApplication, background: bool):
        super().__init__()
        self.qapp = qapp
        self.cfg = Config()
        self.history = History()
        self.bus = Bus()
        self.engine = Engine(self.cfg, self.history, lambda kind, data: self.bus.event.emit(kind, data))
        self.settings_window = None
        self.update_release: updater.Release | None = None
        self.update_busy = False
        self.gpu_busy = False
        self._gpu_cancel = threading.Event()
        self._last_error_note = 0.0

        self.apply_look()
        from .ui.overlay import Overlay
        self.overlay = Overlay(self.engine, self.cfg)
        self._build_tray()
        self.bus.event.connect(self._on_engine_event)
        self.bus.notify.connect(self.notify)
        self.bus.quit_requested.connect(self.quit)
        self.cfg.on_change(self._on_config_change)
        models.enable_gpu_libs()
        self.engine.start()
        self.history.prune(self.cfg["history_days"])

        self._schedule_update_check()
        if not self.cfg["first_run_done"]:
            QTimer.singleShot(300, lambda: self.show_settings("dictation"))
        elif not background:
            QTimer.singleShot(150, self.show_settings)
        log.info("FreeDictate %s started (pid %s, %s)", __version__, os.getpid(),
                 "portable" if paths.portable() else "installed")

    # ---------------------------------------------------------------- look
    def apply_look(self) -> None:
        pal = theme.set_current(self.cfg["theme"], self.cfg["font"])
        if self.cfg["accent_source"] == "windows":
            pal = theme.override_accent(theme.windows_accent())
        translucent = self.cfg["backdrop"] != "solid" and native.backdrop_supported() and native.transparency_enabled()
        if not hasattr(self, "_polisher"):
            from .ui.polish import Polisher
            self._polisher = Polisher(translucent)
            self.qapp.installEventFilter(self._polisher)
        self._polisher.translucent = translucent
        css = theme.stylesheet(pal, translucent)
        css = css.replace("url(:/fd/chevron-down.svg)", f"url({icons.svg_file('chevron-down', pal.sub)})")
        self.qapp.setStyleSheet(css)
        self.qapp.setFont(theme.font())
        widgets.set_reduce_motion(self.cfg["reduce_motion"])
        if self.settings_window is not None:
            self.settings_window.relook()
        if hasattr(self, "tray"):
            self._refresh_tray()

    def _on_config_change(self, keys: set[str]) -> None:
        if keys & {"theme", "font", "backdrop", "tint", "backdrop_when_inactive", "reduce_motion", "accent_source"}:
            self.apply_look()
        if "titlebar" in keys:
            # Framed and frameless are different native windows; build a new one.
            QTimer.singleShot(0, self._rebuild_settings)
        if "history_days" in keys:
            self.history.prune(self.cfg["history_days"])
        if keys & {"hotkey", "hotkey_mode"}:
            self._refresh_tray()

    # ---------------------------------------------------------------- tray
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(icons.app_icon("loading"), self)
        self.tray.setToolTip(APP_NAME)
        self.menu = QMenu()
        self.menu.aboutToShow.connect(self._fill_menu)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.messageClicked.connect(lambda: self.show_settings())
        self.tray.show()

    def _fill_menu(self) -> None:
        m = self.menu
        m.clear()
        status = m.addAction(self.engine.status_text())
        status.setEnabled(False)
        m.addSeparator()
        pause = m.addAction("Pause dictation")
        pause.setCheckable(True)
        pause.setChecked(self.engine.paused)
        pause.triggered.connect(self.toggle_pause)
        recent = m.addMenu("Recent")
        entries = self.history.recent(8)
        if not entries:
            a = recent.addAction("Nothing yet. Your dictations appear here.")
            a.setEnabled(False)
        for e in entries:
            text = e.text.replace("\n", " ")
            short = text if len(text) <= 60 else text[:57].rstrip() + "..."
            a = recent.addAction(f"{time.strftime('%H:%M', time.localtime(e.ts))}   {short}")
            a.setToolTip("Click to copy")
            a.triggered.connect(lambda _=False, t=e.text: self.copy(t))
        recent.addSeparator()
        recent.addAction("Show all history").triggered.connect(lambda: self.show_settings("history"))
        m.addAction("Transcribe a file...").triggered.connect(self.pick_file)
        m.addSeparator()
        m.addAction("Settings").triggered.connect(lambda: self.show_settings())
        if self.update_release:
            m.addAction(f"Install update {self.update_release.version}").triggered.connect(
                lambda: self.show_settings("general"))
        m.addSeparator()
        m.addAction("Quit FreeDictate").triggered.connect(self.quit)

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_settings()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.toggle_pause()

    def _refresh_tray(self) -> None:
        e = self.engine
        state = "paused" if e.paused and e.state == "ready" else e.state
        self.tray.setIcon(icons.app_icon(state))
        self.tray.setToolTip(f"{APP_NAME}: {e.status_text()}")

    def notify(self, title: str, text: str, error: bool = False) -> None:
        if error:
            if time.monotonic() - self._last_error_note < 5:
                return
            self._last_error_note = time.monotonic()
        icon = QSystemTrayIcon.MessageIcon.Warning if error else QSystemTrayIcon.MessageIcon.Information
        self.tray.showMessage(title, text, icon, 6000)

    # -------------------------------------------------------------- engine
    @Slot(str, dict)
    def _on_engine_event(self, kind: str, data: dict) -> None:
        if kind == "state":
            self.overlay.on_state(self.engine.state)
            self._refresh_tray()
        elif kind in ("model", "download"):
            self._refresh_tray()
        elif kind == "error":
            log.warning("%s: %s", data.get("title"), data.get("text"))
            self.notify(data.get("title", APP_NAME), data.get("text", ""), error=True)
        elif kind == "notice":
            self.notify(data.get("title", APP_NAME), data.get("text", ""))
        elif kind == "nothing":
            self.overlay.flash("Didn't hear anything" if data.get("reason") == "silence" else "Didn't catch that")
        elif kind == "result":
            if data.get("outcome") == "copied":
                self.overlay.flash("Copied to clipboard")
            elif data.get("outcome") == "blocked":
                self.overlay.flash("Admin window: on clipboard", 2.4)
            self.bus.history_changed.emit()   # history.add ran on the transcriber thread
        if self.settings_window is not None:
            self.settings_window.engine_event(kind, data)

    def toggle_pause(self) -> None:
        self.engine.toggle_pause()
        self._refresh_tray()

    def copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    # ------------------------------------------------------------- windows
    def show_settings(self, page: str | None = None) -> None:
        if self.settings_window is None:
            from .ui.settings import SettingsWindow
            self.settings_window = SettingsWindow(self)
        w = self.settings_window
        if page:
            w.go(page)
        if w.isMinimized():
            w.showNormal()
        w.show()
        w.raise_()
        w.activateWindow()
        # Windows refuses focus to a background process unless it was the last input target.
        native.user32.SetForegroundWindow(int(w.winId()))

    def _rebuild_settings(self) -> None:
        old = self.settings_window
        if old is None:
            return
        visible = old.isVisible() and not old.isMinimized()
        maximized = old.isMaximized()
        bounds = native.visible_rect(old.hwnd())
        page = self.cfg["window_page"]
        scroll = old.stack.currentWidget().verticalScrollBar().value()
        old.dispose()
        old.close()
        old.deleteLater()
        self.settings_window = None
        if visible:
            self.show_settings(page)
            new = self.settings_window
            if maximized:
                new.showMaximized()
            else:
                # Keep the window's visible edges where they were; only the
                # title bar inside them changes.
                native.set_visible_rect(new.hwnd(), bounds)
            bar = new.stack.currentWidget().verticalScrollBar()
            QTimer.singleShot(0, lambda: bar.setValue(scroll))

    def pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            None, "Transcribe an audio or video file", os.path.expanduser("~"),
            "Audio and video (*.wav *.mp3 *.m4a *.flac *.ogg *.opus *.webm *.mp4 *.mkv *.mov *.aac *.wma);;All files (*)")
        if path:
            self.transcribe_file(path)

    def transcribe_file(self, path: str) -> None:
        if self.engine.model is None:
            self.notify("The speech model isn't ready yet", "Try again when the tray icon turns blue.", error=True)
            return
        self.show_settings("history")
        self.settings_window.file_started(path)

        self.engine.transcribe_file(path, lambda text: self.bus.file_result.emit(path, text))

    # ------------------------------------------------------------- updates
    def _schedule_update_check(self) -> None:
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(6 * 3600 * 1000)
        self._update_timer.timeout.connect(lambda: self.check_updates(manual=False))
        self._update_timer.start()
        if self.cfg["check_updates"] and time.time() - self.cfg["last_update_check"] > 20 * 3600:
            QTimer.singleShot(15000, lambda: self.check_updates(manual=False))

    def check_updates(self, manual: bool = True) -> None:
        if not manual and not self.cfg["check_updates"]:
            return
        if self.update_busy:
            return
        self.update_busy = True
        self.bus.update_status.emit("Checking for updates...", None)

        def work():
            try:
                rel = updater.check(self.cfg["update_prereleases"])
                self.cfg["last_update_check"] = time.time()
                if rel is None:
                    msg = f"You're up to date. FreeDictate {__version__} is the latest version."
                elif not manual and rel.version == self.cfg["skipped_version"]:
                    msg, rel = f"You're on {__version__}.", None
                else:
                    msg = f"FreeDictate {rel.version} is available."
                self.update_release = rel
            except Exception as e:
                log.warning("Update check failed: %s", e)
                msg = ("Couldn't reach GitHub to check for updates. Check your connection "
                       "and try again." if manual else "")
                rel = None
            # Free the button before the GUI thread sees the result, not after.
            self.update_busy = False
            self.bus.update_status.emit(msg, rel)
            if rel and not manual:
                self.bus.notify.emit(
                    "An update is ready",
                    f"FreeDictate {rel.version} is available. Open Settings to install it.", False)

        threading.Thread(target=work, daemon=True, name="update-check").start()

    def install_update(self) -> None:
        rel = self.update_release
        if rel is None or self.update_busy:
            return
        self.update_busy = True

        def work():
            try:
                self.bus.update_status.emit(f"Downloading FreeDictate {rel.version}...", rel)
                f = updater.download(rel, lambda d, t: self.bus.update_progress.emit(d, t))
                self.bus.update_status.emit("Installing. FreeDictate restarts by itself.", rel)
                updater.install(f)
                self.bus.quit_requested.emit()
            except Exception as e:
                log.exception("Update failed")
                self.update_busy = False   # before the GUI sees the failure
                self.bus.update_status.emit(f"The update didn't install: {e}", rel)

        threading.Thread(target=work, daemon=True, name="update-install").start()

    # ----------------------------------------------------------------- GPU
    def download_gpu(self) -> None:
        if self.gpu_busy:
            return
        self.gpu_busy = True
        self._gpu_cancel = threading.Event()
        self.bus.gpu_status.emit("downloading")

        def work():
            try:
                models.download_gpu_libs(lambda d, t: self.bus.gpu_progress.emit(d, t), self._gpu_cancel)
                models.enable_gpu_libs()
                self.bus.gpu_status.emit("done")
                if self.cfg["device"] in ("auto", "cuda"):
                    self.engine.ensure_model(force=True)
            except InterruptedError:
                self.bus.gpu_status.emit("")
            except Exception as e:
                log.exception("GPU support download failed")
                self.bus.gpu_status.emit(f"error: {e}")
            finally:
                self.gpu_busy = False

        threading.Thread(target=work, daemon=True, name="gpu-download").start()

    def cancel_gpu(self) -> None:
        self._gpu_cancel.set()

    # ------------------------------------------------------------- startup
    def autostart_state(self) -> tuple[bool, bool]:
        return system.run_key_enabled() or system.task_enabled(), system.task_enabled()

    def set_autostart(self, enabled: bool, elevated: bool) -> str:
        err = system.set_autostart(enabled, elevated)
        if not err:
            self.cfg["run_elevated"] = elevated
        return err

    def restart(self, elevated: bool = False) -> None:
        import subprocess
        if elevated and system.task_enabled() and system.run_task():
            QTimer.singleShot(0, self.quit)
            return
        subprocess.Popen(paths.exe_command() + ["--background", "--wait-for-exit", str(os.getpid())],
                         close_fds=True, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        QTimer.singleShot(0, self.quit)

    def quit(self) -> None:
        log.info("Quit")
        self.engine.shutdown()
        if self.settings_window is not None:
            self.settings_window.save_geometry()
        self.tray.hide()
        self.history.close()
        self.qapp.quit()


# ----------------------------------------------------------------- startup

def _signal_running(message: str) -> bool:
    """True when a copy is already running and got the message.

    A copy running as administrator owns its pipe with a High integrity label;
    a normal launch can't connect to it (SocketAccessError) but must not start
    a second copy over it either."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(400):
        sock.write(message.encode())
        sock.waitForBytesWritten(400)
        sock.disconnectFromServer()
        return True
    return sock.error() == QLocalSocket.LocalSocketError.SocketAccessError


def _wait_for_exit(pid: int) -> None:
    import ctypes
    h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if h:
        ctypes.windll.kernel32.WaitForSingleObject(h, 15000)
        ctypes.windll.kernel32.CloseHandle(h)


def run(argv: list[str]) -> int:
    if "--quit" in argv:
        # Used by the installer and uninstaller to close a running copy cleanly.
        from PySide6.QtCore import QCoreApplication
        _core = QCoreApplication(sys.argv[:1])
        _signal_running("quit")
        return 0
    background = "--background" in argv
    page = next((a.split("=", 1)[1] for a in argv if a.startswith("--page=")), None)
    if "--wait-for-exit" in argv:
        try:
            _wait_for_exit(int(argv[argv.index("--wait-for-exit") + 1]))
        except (IndexError, ValueError):
            pass

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv[:1])
    qapp.setApplicationName(APP_NAME)
    qapp.setApplicationVersion(__version__)
    qapp.setOrganizationName("DavidHiFi")
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setWindowIcon(icons.app_icon("ready"))

    if _signal_running("background" if background else f"show:{page or ''}"):
        return 0
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(SERVER_NAME):
        log.warning("Single-instance server failed: %s", server.errorString())

    app = App(qapp, background)

    def on_connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return

        def read():
            msg = bytes(sock.readAll()).decode(errors="replace")
            if msg.startswith("show"):
                app.show_settings(msg.partition(":")[2] or None)
            elif msg == "quit":
                app.quit()
        sock.readyRead.connect(read)

    server.newConnection.connect(on_connection)
    if page:
        app.show_settings(page)
    code = qapp.exec()
    server.close()
    return code
