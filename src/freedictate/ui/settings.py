"""The FreeDictate window: settings, models, history, updates.

Every control applies its change immediately, the way Windows Settings does.
There is no Save button to forget.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QCompleter, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, REPO_URL, __version__, audio, hotkeys, models, paths, system, writer
from ..log import log
from . import icons, native, theme
from .widgets import (Banner, Card, Combo, HotkeyEdit, LevelMeter, NavButton, Row, Segmented, Slider, StatusDot,
                      Toggle, button, label, refresh_icons)
from .window import FluentWindow

PAGES = [
    ("dictation", "Dictation", "mic"),
    ("models", "Speech model", "cpu"),
    ("text", "Text and pasting", "text"),
    ("look", "Appearance", "palette"),
    ("history", "History", "clock"),
    ("general", "General", "sliders"),
    ("about", "About", "info"),
]

STATE_COLOR = {"ready": "ok", "listening": "danger", "transcribing": "warn", "loading": "sub", "error": "danger"}


def _mb(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


class Page(QScrollArea):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Always reserve the scrollbar's gutter, so content width doesn't jump between pages.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        inner = QWidget()
        inner.setObjectName("page")
        self.setWidget(inner)
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(28, 8, 28, 28)
        outer.setSpacing(0)
        self.column = QVBoxLayout()
        self.column.setSpacing(6)
        wrap = QHBoxLayout()
        wrap.addLayout(self.column, 1)
        outer.addLayout(wrap)
        outer.addStretch(1)
        t = label(title, "title")
        t.setAccessibleName(title)
        self.column.addWidget(t)
        self.column.addSpacing(10)

    def section(self, title: str, desc: str = "") -> Card:
        self.column.addSpacing(10)
        self.column.addWidget(label(title, "section"))
        if desc:
            self.column.addWidget(label(desc, "sub", wrap=True))
        card = Card()
        self.column.addWidget(card)
        return card

    def add(self, w: QWidget) -> QWidget:
        self.column.addWidget(w)
        return w


class SettingsWindow(FluentWindow):
    closed = Signal()               # the app forgets the window when this fires

    def __init__(self, app):
        super().__init__(APP_NAME, native_titlebar=app.cfg["titlebar"] == "windows")
        self.app, self.cfg, self.engine, self.history = app, app.cfg, app.engine, app.history
        self.setMinimumSize(820, 560)
        self._meter = audio.LevelMeter()
        self._meter_timer = QTimer(self)
        self._meter_timer.setInterval(33)
        self._meter_timer.timeout.connect(self._meter_tick)
        self._history_limit = 150
        self._history_stale = True
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self.reload_history)

        body = QHBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        self.stack = QStackedWidget(self)
        body.addWidget(self.stack, 1)

        self.pages: dict[str, Page] = {}
        builders = {"dictation": self._page_dictation, "models": self._page_models, "text": self._page_text,
                    "look": self._page_look, "history": self._page_history, "general": self._page_general,
                    "about": self._page_about}
        for key, title, _ in PAGES:
            page = Page(title)
            builders[key](page)
            self.pages[key] = page
            self.stack.addWidget(page)

        app.bus.update_status.connect(self._on_update_status)
        app.bus.update_progress.connect(self._on_update_progress)
        app.bus.gpu_progress.connect(self._on_gpu_progress)
        app.bus.gpu_status.connect(self._on_gpu_status)
        app.bus.file_result.connect(self._on_file_result)
        # History writes happen on the transcriber thread; a QTimer from there
        # would never fire, so the app re-emits a queued signal instead.
        app.bus.history_changed.connect(self._history_changed)
        self._disposed = False

        for i, (key, _, _) in enumerate(PAGES[:9], start=1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, activated=lambda k=key: self.go(k))
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)
        QShortcut(QKeySequence("Escape"), self, activated=self._escape)

        self.relook()
        self._restore_geometry()
        self.go(self.cfg["window_page"] if self.cfg["window_page"] in self.pages else "dictation")
        self.refresh_status()

    # ------------------------------------------------------------ framework
    def _build_sidebar(self) -> QWidget:
        side = QWidget(self)
        side.setFixedWidth(232)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 4, 8, 14)
        lay.setSpacing(2)

        status = QFrame(side)
        status.setObjectName("card")
        sl = QVBoxLayout(status)
        sl.setContentsMargins(12, 10, 12, 10)
        sl.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.status_dot = StatusDot(status)
        self.status_title = label("Starting", "rowtitle")
        top.addWidget(self.status_dot)
        top.addWidget(self.status_title, 1)
        sl.addLayout(top)
        self.status_text = label("", "sub", wrap=True)
        sl.addWidget(self.status_text)
        self.status_progress = QProgressBar(status)
        self.status_progress.setTextVisible(False)
        self.status_progress.hide()
        sl.addWidget(self.status_progress)
        self.pause_btn = button("Pause", "flat", status, icon="pause")
        self.pause_btn.clicked.connect(self.app.toggle_pause)
        sl.addWidget(self.pause_btn, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(status)
        lay.addSpacing(10)

        self.nav: dict[str, NavButton] = {}
        for key, title, icon_name in PAGES:
            b = NavButton(key, title, icon_name, side)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            self.nav[key] = b
            lay.addWidget(b)
        lay.addStretch(1)
        ver = label(f"Version {__version__}" + (" (portable)" if paths.portable() else ""), "sub")
        ver.setContentsMargins(12, 0, 0, 0)
        lay.addWidget(ver)
        return side

    def go(self, key: str) -> None:
        if key not in self.pages:
            return
        for k, b in self.nav.items():
            b.setChecked(k == key)
        self.stack.setCurrentWidget(self.pages[key])
        self.cfg.update({"window_page": key})
        if key == "history" and self._history_stale:
            # Paint the page first, then fill it: building the cards inline
            # blocked every switch to the tab for a noticeable beat.
            QTimer.singleShot(0, self.reload_history)
        if key == "models":
            self._refresh_models()
        if key != "dictation":
            self._stop_meter()

    def _escape(self) -> None:
        if self.hotkey_edit._timer.isActive():
            return
        self.close()

    def relook(self) -> None:
        backdrop = self.cfg["backdrop"]
        self.set_look(backdrop, self.cfg["tint"] / 100, self.cfg["backdrop_when_inactive"])
        refresh_icons(self)
        if hasattr(self, "backdrop_note"):
            self._update_backdrop_note()
        self.update()
        for w in self.findChildren(QWidget):
            w.update()

    def _restore_geometry(self) -> None:
        g = self.cfg["window_geometry"]
        if g:
            self.restoreGeometry(QByteArray.fromBase64(g.encode()))
            screen = QApplication.screenAt(self.geometry().center())
            if screen is not None:
                return
        self.resize(960, 700)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center() - self.rect().center())

    def save_geometry(self) -> None:
        self.cfg.update({"window_geometry": bytes(self.saveGeometry().toBase64()).decode()})

    def dispose(self) -> None:
        """Detach from the app before the window is replaced (title bar switch)."""
        self._disposed = True
        bus = self.app.bus
        for sig, slot in ((bus.update_status, self._on_update_status), (bus.update_progress, self._on_update_progress),
                          (bus.gpu_progress, self._on_gpu_progress), (bus.gpu_status, self._on_gpu_status),
                          (bus.file_result, self._on_file_result), (bus.history_changed, self._history_changed)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def closeEvent(self, e):
        self._stop_meter()
        if self.hotkey_edit._timer.isActive():
            self.hotkey_edit.cancel()
        self.save_geometry()
        if not self.cfg["first_run_done"] and not self._disposed:
            self.cfg["first_run_done"] = True
            self.app.notify("FreeDictate keeps running in the tray",
                            f"Hold {hotkeys.label(self.cfg['hotkey'])} anywhere to dictate.")
        # A closed window used to be kept hidden with every page and history
        # card in memory. The app hears this and tears it down instead; the
        # next open builds it fresh.
        self.closed.emit()
        e.accept()

    # ------------------------------------------------------------ status
    def refresh_status(self) -> None:
        e = self.engine
        pal = theme.current()
        state = e.state
        titles = {"ready": "Ready", "listening": "Listening", "transcribing": "Transcribing",
                  "loading": "Getting ready", "error": "Not working"}
        title = "Paused" if e.paused else titles.get(state, state)
        if not e.paused and state == "ready" and getattr(e, "model", None) is None \
                and getattr(getattr(e, "ms", None), "active", "") == "":
            # Short: this sits in the fixed-width sidebar, and "Unloaded to
            # save VRAM" clipped there. The wrapped line below spells it out.
            title = "Unloaded"
        self.status_title.setText(title)
        self.status_dot.set_color(pal.sub if e.paused else getattr(pal, STATE_COLOR.get(state, "sub")))
        ms = e.ms
        lines = []
        if state == "error":
            lines.append(ms.error or "The speech model didn't load. See Speech model.")
        elif getattr(e, "model", None) is None and not ms.active and state == "ready" and not e.paused:
            lines.append("Models are unloaded. Nothing uses graphics memory right now.")
        elif ms.active:
            dev = "GPU" if ms.device == "cuda" else "CPU"
            lines.append(f"{_model_title(ms.active)} on {dev}")
        if ms.status == "downloading":
            done, total = ms.progress
            lines.append(f"Downloading {_model_title(ms.wanted)}: {_mb(done)} of {_mb(total)}")
            self.status_progress.setRange(0, 1000)
            self.status_progress.setValue(int(done * 1000 / total) if total else 0)
            self.status_progress.show()
        elif ms.status == "loading":
            lines.append(f"Loading {_model_title(ms.wanted)}")
            self.status_progress.setRange(0, 0)
            self.status_progress.show()
        else:
            self.status_progress.hide()
        if not e.paused and state in ("ready", "listening", "transcribing"):
            verb = {"hold": "Hold", "toggle": "Press", "both": "Hold or tap"}[self.cfg["hotkey_mode"]]
            lines.append(f"{verb} {hotkeys.label(self.cfg['hotkey'])} to dictate")
        self.status_text.setText("\n".join(lines))
        self.pause_btn.setText("Resume" if e.paused else "Pause")
        self.pause_btn.setProperty("icon_name", "play" if e.paused else "pause")
        self.pause_btn.setIcon(icons.icon("play" if e.paused else "pause", pal.text))
        self.pause_btn.setVisible(state != "loading" or e.model is not None)

    def engine_event(self, kind: str, data: dict) -> None:
        if kind in ("state", "model", "download"):
            self.refresh_status()
        if kind in ("model", "download") and self.stack.currentWidget() is self.pages["models"]:
            self._refresh_models(light=kind == "download")

    # ============================================================ pages
    # ------------------------------------------------------------ dictation
    def _page_dictation(self, page: Page) -> None:
        cfg = self.cfg
        if not cfg["first_run_done"]:
            info = models.BY_NAME[cfg["model"]]
            ban = Banner(f"<b>Welcome to FreeDictate.</b> Click where you want text, hold "
                         f"<b>{hotkeys.label(cfg['hotkey'])}</b>, talk, and let go. The {info.title} speech model "
                         f"({_mb(info.size_mb * 1_000_000)}) downloads once, then everything runs offline on this PC.")
            done = button("Got it", "primary")
            done.clicked.connect(lambda: (cfg.update({"first_run_done": True}), ban.hide()))
            ban.actions.addWidget(done)
            page.add(ban)

        card = page.section("Shortcut")
        self.hotkey_edit = HotkeyEdit(cfg["hotkey"])
        reset = button("Reset", "flat")
        reset.setToolTip("Back to Ctrl + Win")
        row = Row("Dictation shortcut", "Click the box, then press the keys you want. Esc cancels a take while "
                  "you're recording.", self.hotkey_edit)
        row.controls.addWidget(reset)
        card.add(row)
        self.hotkey_row = row

        def set_hotkey(v: str) -> None:
            cfg["hotkey"] = v
            row.set_note(hotkeys.warning(v))
            self.refresh_status()

        def recording(on: bool) -> None:
            self.engine.suspended = on

        self.hotkey_edit.recorded.connect(set_hotkey)
        self.hotkey_edit.recording.connect(recording)
        reset.clicked.connect(lambda: (self.hotkey_edit.set_value("ctrl+win"), set_hotkey("ctrl+win")))
        row.set_note(hotkeys.warning(cfg["hotkey"]))

        mode = Segmented([("hold", "Hold"), ("toggle", "Press to start and stop"), ("both", "Both")], cfg["hotkey_mode"])
        mode_row = Row("How the shortcut works", "", mode)
        descs = {"hold": "Hold the shortcut while you talk. Let go to finish.",
                 "toggle": "Press once to start and again to finish. Good for long dictation.",
                 "both": "Hold to talk, or tap it quickly to keep listening until you tap again."}
        mode_row.desc.setText(descs[cfg["hotkey_mode"]])
        mode_row.desc.show()

        def set_mode(k: str) -> None:
            cfg["hotkey_mode"] = k
            mode_row.desc.setText(descs[k])
            Card.show_row(self._silence_row, k != "hold")
            self.refresh_status()
        mode.changed.connect(set_mode)
        card.add(mode_row)

        card = page.section("Microphone")
        self.mic_combo = Combo([], cfg["input_device"], width=300)
        self.mic_combo.setMaximumWidth(460)
        self.mic_combo.setSizeAdjustPolicy(Combo.SizeAdjustPolicy.AdjustToContents)
        self._fill_mics()
        refresh = button("", "flat", icon="refresh")
        refresh.setToolTip("Look for microphones again")
        refresh.setAccessibleName("Refresh microphones")
        refresh.clicked.connect(lambda: (audio.refresh_devices(), self._fill_mics()))
        mic_row = Row("Microphone", "", self.mic_combo)
        mic_row.controls.addWidget(refresh)
        self.mic_combo.currentIndexChanged.connect(lambda _: self._mic_changed())
        self.mic_combo.currentTextChanged.connect(self.mic_combo.setToolTip)   # long device names get cut off
        card.add(mic_row)
        self.meter = LevelMeter(width=220)
        self.meter_btn = button("Test", "", icon="mic")
        self.meter_btn.clicked.connect(self._toggle_meter)
        test_row = Row("Test your microphone", "Speak normally. The bar should reach about halfway.", self.meter)
        test_row.controls.addWidget(self.meter_btn)
        self.meter_row = test_row
        card.add(test_row)

        card = page.section("Recording")
        lang_items = [(k, v) for k, v in models.LANGUAGES.items()]
        lang = Combo(lang_items, cfg["language"], width=240)
        lang_row = Row("Language", "", lang)
        self._lang_row = lang_row

        def set_lang() -> None:
            cfg["language"] = lang.value()
            self._update_lang_note()
        lang.currentIndexChanged.connect(lambda _: set_lang())
        card.add(lang_row)
        self._update_lang_note()

        vocab = QLineEdit(cfg["vocabulary"])
        vocab.setPlaceholderText("Names, separated by commas")
        vocab.setMinimumWidth(300)
        vocab.editingFinished.connect(lambda: cfg.update({"vocabulary": vocab.text().strip()}))
        self._vocab_row = Row("Words it should know", "Helps with names and terms it would otherwise misspell.", vocab)
        card.add(self._vocab_row)
        self._update_lang_note()

        silence = Combo([("0", "Never"), ("2", "After 2 seconds"), ("3", "After 3 seconds"), ("5", "After 5 seconds"),
                         ("8", "After 8 seconds")], str(cfg["auto_stop_silence"]), width=200)
        silence.currentIndexChanged.connect(lambda _: cfg.update({"auto_stop_silence": int(silence.value())}))
        # Only press-to-start takes can end on silence; a held take ends when
        # the keys come up, so the row is hidden in Hold mode.
        self._silence_row = Row("Stop when you go quiet", "Ends a press-to-start take after a pause.", silence)
        card.add(self._silence_row)
        Card.show_row(self._silence_row, cfg["hotkey_mode"] != "hold")

        longest = Combo([("60", "1 minute"), ("120", "2 minutes"), ("300", "5 minutes"), ("600", "10 minutes"),
                         ("1200", "20 minutes"), ("3600", "1 hour")], str(cfg["max_seconds"]), width=200)
        longest.currentIndexChanged.connect(lambda _: cfg.update({"max_seconds": int(longest.value())}))
        card.add(Row("Longest take", "A take this long finishes by itself.", longest))

        card = page.section("Feedback")
        sounds = Toggle(cfg["sounds"])
        vol = Slider(5, 100, cfg["sound_volume"], "%")
        vol.setEnabled(cfg["sounds"])
        sounds.toggled.connect(lambda on: (cfg.update({"sounds": on}), vol.setEnabled(on)))
        vol.changed.connect(lambda v: (cfg.update({"sound_volume": v}), audio.play("start", v)))
        card.add(Row("Sounds", "A short tone when recording starts and stops, and when the text arrives.", sounds))
        card.add(Row("Sound volume", "", vol))
        bar = Toggle(cfg["overlay"])
        pos = Segmented([("bottom", "Bottom"), ("top", "Top")], cfg["overlay_position"])
        mat = Segmented([("mica_alt", "Mica Alt"), ("mica", "Mica"), ("acrylic", "Acrylic"), ("blur", "Blur"),
                         ("solid", "Solid")], cfg["overlay_backdrop"])
        timer = Toggle(cfg["overlay_timer"])

        def set_bar(on: bool) -> None:
            cfg["overlay"] = on
            pos.setEnabled(on)
            mat.setEnabled(on)
            timer.setEnabled(on)
        bar.toggled.connect(set_bar)
        pos.changed.connect(lambda k: cfg.update({"overlay_position": k}))
        mat.changed.connect(lambda k: cfg.update({"overlay_backdrop": k}))
        timer.toggled.connect(lambda on: cfg.update({"overlay_timer": on}))
        pos.setEnabled(cfg["overlay"])
        mat.setEnabled(cfg["overlay"])
        timer.setEnabled(cfg["overlay"])
        card.add(Row("Recording bar", "A small bar on screen while it listens and transcribes.", bar))
        card.add(Row("Bar position", "", pos))
        mat_row = Row("Bar material", "Uses the window's tint over a picture of what's behind the bar, "
                      "taken as it appears.", mat)
        if not native.backdrop_supported():
            mat_row.set_note("Materials need Windows 11 22H2 or later. The bar stays solid.")
        elif not native.transparency_enabled():
            mat_row.set_note("Transparency effects are off in Windows Settings > Personalization > Colors.")
        card.add(mat_row)
        card.add(Row("Show the timer", "", timer))

    def _update_lang_note(self) -> None:
        info = models.BY_NAME.get(self.cfg["model"])
        if info and info.english_only and self.cfg["language"] != "en":
            self._lang_row.set_note(f"{info.title} only understands English. Pick a multilingual model "
                                    "under Speech model to dictate in other languages.")
        else:
            self._lang_row.set_note("")
        if hasattr(self, "_vocab_row"):
            self._vocab_row.set_note("" if not info or info.prompts else
                                     f"{info.title} doesn't use this list. Add fixes under Replacements "
                                     "on the Text and pasting page instead.")

    def _fill_mics(self) -> None:
        try:
            devs = audio.input_devices()
        except Exception as e:
            log.warning("Listing microphones failed: %s", e)
            devs = []
        default = next((d.label for d in devs if d.default), "")
        items = [("", f"Windows default ({default})" if default else "Windows default")]
        items += [(d.name, d.label) for d in devs]
        cur = self.cfg["input_device"]
        if cur and cur not in [d.name for d in devs]:
            items.append((cur, f"{cur} (not connected)"))
        self.mic_combo.set_items(items, cur)

    def _mic_changed(self) -> None:
        self.cfg["input_device"] = self.mic_combo.value() or ""
        if self._meter.running:
            self._stop_meter()
            self._toggle_meter()

    def _toggle_meter(self) -> None:
        if self._meter.running:
            self._stop_meter()
            return
        try:
            self._meter.start(self.cfg["input_device"])
        except Exception as e:
            self.meter_row.set_note(f"Couldn't open this microphone: {e}", "danger")
            return
        self.meter_row.set_note("")
        self.meter_btn.setText("Stop")
        self._meter_started = time.monotonic()
        self._meter_timer.start()

    def _meter_tick(self) -> None:
        self.meter.set_level(self._meter.level)
        if time.monotonic() - self._meter_started > 15:
            self._stop_meter()

    def _stop_meter(self) -> None:
        if not hasattr(self, "meter_btn"):
            return
        was = self._meter.running
        self._meter.stop()
        self._meter_timer.stop()
        self.meter.set_level(0)
        self.meter_btn.setText("Test")
        if was:
            if self._meter.peak < 0.01:
                self.meter_row.set_note("Heard nothing. Check that this is the right microphone and that it isn't muted.")
            else:
                self.meter_row.set_note("")

    # ------------------------------------------------------------ models
    def _page_models(self, page: Page) -> None:
        card = page.section("Models", "Larger models are more accurate and slower. Each downloads once.")
        self.model_combo = Combo([], self.cfg["model"], width=300)
        self.model_combo.setSizeAdjustPolicy(Combo.SizeAdjustPolicy.AdjustToContents)
        self.model_combo.currentIndexChanged.connect(lambda _: self._refresh_models(light=True))
        self.model_btn = button("Use", "primary")
        self.model_btn.clicked.connect(self._model_btn_clicked)
        self.model_row = Row("Speech model", "", self.model_combo)
        self.model_row.controls.addWidget(self.model_btn)
        card.add(self.model_row)
        self._downloaded_cache: set[str] = set()
        card = page.section("Model library",
                            "Everything FreeDictate can run. Download what you need, remove what you "
                            "don't. Same files, same accuracy — only the chip doing the work changes.")
        self._lib_rows: dict[str, Row] = {}
        for info in models.CATALOG:
            btn = button("")
            btn.clicked.connect(lambda _=False, n=info.name: self._library_clicked(n))
            row = Row(info.title, "", btn)
            card.add(row)
            self._lib_rows[info.name] = row
        self._refresh_library()

        card = page.section("Graphics card", "An NVIDIA graphics card makes the large models many times faster.")
        gpu = models.gpu_name()
        self.gpu_progress = QProgressBar()
        self.gpu_progress.setTextVisible(False)
        self.gpu_progress.setFixedWidth(180)
        self.gpu_progress.hide()
        self.gpu_btn = button("Download GPU support", "primary", icon="download")
        self.gpu_btn.clicked.connect(self._gpu_clicked)
        desc = (f"Found {gpu}. Uses NVIDIA's cuBLAS library ({_mb(models.gpu_download_size())} download)."
                if gpu else "No NVIDIA graphics card found. FreeDictate runs on the processor.")
        self.gpu_row = Row("GPU acceleration", desc, self.gpu_progress)
        self.gpu_row.controls.addWidget(self.gpu_btn)
        self.gpu_row.setEnabled(bool(gpu))
        card.add(self.gpu_row)
        device = Combo([("auto", "Automatic"), ("cuda", "Graphics card"), ("cpu", "Processor")],
                       self.cfg["device"], width=200)
        device.currentIndexChanged.connect(lambda _: self.cfg.update({"device": device.value()}))
        card.add(Row("Run the model on", "Automatic uses the graphics card when GPU support is installed.", device))
        self._refresh_gpu()

        card = page.section("Memory", "FreeDictate holds graphics memory while its models are loaded. "
                            "Unloading gives it back to games and other apps when you're not dictating.")
        idle = Toggle(self.cfg.get("idle_unload", True))
        after = Combo([("0", "Right after each take"), ("30", "30 seconds"), ("60", "1 minute"),
                       ("120", "2 minutes"), ("300", "5 minutes"), ("600", "10 minutes"),
                       ("1800", "30 minutes"), ("3600", "1 hour")],
                      str(int(self.cfg.get("idle_seconds", 0))), width=200)
        after.setEnabled(idle.isChecked())
        idle.toggled.connect(lambda on: (self.cfg.update({"idle_unload": on}), after.setEnabled(on)))
        after.currentIndexChanged.connect(lambda _: self.cfg.update({"idle_seconds": int(after.value())}))
        card.add(Row("Free graphics memory when idle",
                     "Unloads the models so games get the memory back. Right after each take is the "
                     "default: nothing sits in VRAM between takes, and the next take reloads while "
                     "you're already talking. Pausing unloads immediately.",
                     idle))
        self._idle_after_row = Row("Keep models loaded for", "", after)
        card.add(self._idle_after_row)

        card = page.section("Fine tuning", "Defaults suit most people.")
        compute = Combo([("auto", "Automatic"), ("int8", "int8 (smallest, CPU)"), ("int8_float16", "int8 + float16 (GPU)"),
                         ("float16", "float16 (GPU)"), ("float32", "float32 (largest)")], self.cfg["compute_type"], width=220)
        compute.currentIndexChanged.connect(lambda _: self.cfg.update({"compute_type": compute.value()}))
        card.add(Row("Precision", "How the model's numbers are stored. Automatic picks the fastest for your hardware.", compute))
        beam = Slider(1, 10, self.cfg["beam_size"], "", width=160)
        beam.changed.connect(lambda v: self.cfg.update({"beam_size": v}))
        card.add(Row("Search width", "Higher is slightly more accurate and slower. 5 is standard.", beam))
        cores = os.cpu_count() or 8
        limit = Toggle(self.cfg["cpu_threads"] > 0)
        cap = Slider(1, cores, self.cfg["cpu_threads"] or min(6, cores), " cores", width=180)
        cap.changed.connect(lambda v: self.cfg.update({"cpu_threads": v}))
        cap_row = Row("Processor cores", f"This PC reports {cores} threads. "
                      "Dictation waits longer for your words the lower this is.", cap)
        limit.toggled.connect(lambda on: (
            self.cfg.update({"cpu_threads": (self.cfg["cpu_threads"] or min(6, cores)) if on else 0}),
            Card.show_row(cap_row, on)))
        card.add(Row("Limit processor cores",
                     "Caps how many processor cores dictation may use. The lower you set it, the longer "
                     "a take takes — but the fewer CPU spikes and audio crackles. Six cores measured "
                     "just as fast as every core, with the rest of the machine left alone.", limit))
        card.add(cap_row)
        Card.show_row(cap_row, self.cfg["cpu_threads"] > 0)
        vad = Toggle(self.cfg["vad"])
        vad.toggled.connect(lambda on: self.cfg.update({"vad": on}))
        card.add(Row("Skip silent parts", "Cuts pauses before transcribing. Faster, and stops made-up words in silence.", vad))

    def _refresh_models(self, light: bool = False) -> None:
        """Fill both model lists and set the button for the model shown. The
        list shows the chosen model until you pick another to look at."""
        if not light:
            self._downloaded_cache = set(models.downloaded())
        ms, have = self.engine.ms, self._downloaded_cache
        shown = self.model_combo.value() or self.cfg["model"]
        if not light or self.model_combo.count() == 0:
            items = []
            for info in models.CATALOG:
                if info.name == ms.active and self.engine.model is not None:
                    state = "in use"
                elif info.name in have:
                    state = "downloaded"
                else:
                    state = _mb(info.size_mb * 1_000_000)
                items.append((info.name, f"{info.title} ({state})"))
            self.model_combo.set_items(items, shown)
        info = models.BY_NAME.get(shown)
        desc = info.note + (" English only." if info and info.english_only else "") if info else ""
        self.model_row.desc.setText(desc)
        self.model_row.desc.setVisible(bool(desc))
        btn, note = self.model_btn, ""
        using = shown == ms.active and self.engine.model is not None
        if shown == ms.wanted and ms.status == "downloading":
            done, total = ms.progress
            note = f"Downloading {done * 100 // total if total else 0}%"
            btn.setText("Cancel")
            btn.setProperty("kind", "")
        elif shown == self.cfg["model"] and ms.status == "loading":
            note = "Loading"
            btn.setText("Use")
        elif using:
            note = "In use on the graphics card." if ms.device == "cuda" else "In use on the processor."
        else:
            btn.setText("Use" if shown in have else "Download")
            btn.setProperty("kind", "primary")
        btn.setVisible(not using)
        btn.setEnabled(ms.status != "loading")
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        self.model_row.set_note(note, "value")

        self._refresh_library()
        self._update_lang_note()

    def _model_btn_clicked(self) -> None:
        name = self.model_combo.value()
        ms = self.engine.ms
        if ms.status == "downloading" and ms.wanted == name:
            self.engine.cancel_download()
            if ms.active:
                self.cfg["model"] = ms.active
        elif not self.cfg.update({"model": name}):
            # Same model as configured (e.g. retrying after a failed
            # download): cfg.update reported no change, so ask the engine
            # directly or the button would do nothing until a restart.
            self.engine.ensure_model(force=True)
        self._refresh_models()
        self.refresh_status()

    def _refresh_library(self) -> None:
        """Status and action for every model in the catalog: coloured state
        text on the left, the one valid action on the right."""
        ms, have = self.engine.ms, self._downloaded_cache
        for name, row in self._lib_rows.items():
            info = models.BY_NAME[name]
            btn = row.controls.itemAt(0).widget()
            note, role = "", ""
            if name == ms.wanted and ms.status == "downloading":
                done, total = ms.progress
                note, role = f"Downloading {done * 100 // total if total else 0}%…", "warn"
                btn.setText("Cancel")
                btn.setProperty("kind", "")
            elif name == ms.active and self.engine.model is not None:
                note = f"In use · on the {'graphics card' if ms.device == 'cuda' else 'processor'}"
                role = "ok"
                btn.setVisible(False)
            elif name in have:
                note, role = "Downloaded", "ok"
                btn.setText("Remove")
                btn.setProperty("kind", "")
                btn.setVisible(True)
            else:
                note, role = f"Not downloaded · {_mb(info.size_mb * 1_000_000)}", "danger"
                btn.setText("Download")
                btn.setProperty("kind", "primary")
                btn.setVisible(True)
            row.set_note(note, role)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            refresh_icons(row)

    def _library_clicked(self, name: str) -> None:
        ms = self.engine.ms
        if name == ms.wanted and ms.status == "downloading":
            self.engine.cancel_download()
            if ms.active:
                self.cfg["model"] = ms.active
        elif name in self._downloaded_cache:
            info = models.BY_NAME.get(name)
            if info and QMessageBox.question(self, "Remove model", f"Remove {info.title} from this PC? "
                                             "You can download it again later.") != QMessageBox.StandardButton.Yes:
                return
            if not models.delete(name):
                QMessageBox.information(self, "Remove model", f"{info.title} couldn't be removed. "
                                        "It may be in use; restart FreeDictate and try again.")
        else:
            self.cfg.update({"model": name})   # choosing a model downloads it automatically
        self._refresh_models()
        self._refresh_library()
        self.refresh_status()


    def _refresh_gpu(self) -> None:
        if models.gpu_libs_present():
            self.gpu_btn.setText("Remove")
            self.gpu_btn.setProperty("kind", "")
            self.gpu_btn.setProperty("icon_name", "trash")
            on = self.engine.ms.device == "cuda"
            self.gpu_row.set_note("Installed. " + ("The model runs on your graphics card." if on else
                                                    "The model will use it the next time it loads."), "value")
        else:
            self.gpu_btn.setText("Download GPU support")
            self.gpu_btn.setProperty("kind", "primary")
            self.gpu_btn.setProperty("icon_name", "download")
        self.gpu_btn.style().unpolish(self.gpu_btn)
        self.gpu_btn.style().polish(self.gpu_btn)
        refresh_icons(self.gpu_row)

    def _gpu_clicked(self) -> None:
        if self.app.gpu_busy:
            self.app.cancel_gpu()
            return
        if models.gpu_libs_present():
            try:
                models.remove_gpu_libs()
            except OSError:
                # The DLLs are loaded into this process while the model runs
                # on the GPU; Windows won't let go of them until restart.
                self.gpu_row.set_note("FreeDictate is using the graphics card right now. "
                                      "Restart it, then remove GPU support.", "danger")
                return
            self.gpu_row.set_note("Removed. FreeDictate uses the processor after a restart.", "value")
            self._refresh_gpu()
            return
        self.app.download_gpu()

    @Slot(int, int)
    def _on_gpu_progress(self, done: int, total: int) -> None:
        self.gpu_progress.setRange(0, 1000)
        self.gpu_progress.setValue(int(done * 1000 / total) if total else 0)
        self.gpu_row.set_note(f"Downloading {_mb(done)} of {_mb(total)}", "value")

    @Slot(str)
    def _on_gpu_status(self, status: str) -> None:
        busy = status == "downloading"
        self.gpu_progress.setVisible(busy)
        if busy:
            self.gpu_btn.setText("Cancel")
            self.gpu_btn.setProperty("kind", "")
            self.gpu_btn.style().unpolish(self.gpu_btn)
            self.gpu_btn.style().polish(self.gpu_btn)
            return
        self._refresh_gpu()
        if status.startswith("error"):
            self.gpu_row.set_note(f"Download failed: {status[7:]}", "danger")
        elif status == "done":
            self.gpu_row.set_note("Installed. Loading the model on your graphics card.", "value")

    # ------------------------------------------------------------ text
    def _page_text(self, page: Page) -> None:
        cfg = self.cfg
        card = page.section("Output")
        out = Combo([("paste", "Paste it"), ("paste_shift_insert", "Paste with Shift+Insert (terminals)"),
                     ("type", "Type it out"), ("clipboard", "Copy it, I'll paste")], cfg["output"], width=290)
        out_row = Row("How the text arrives", "", out)
        descs = {"paste": "Fast and works in almost every app.",
                 "paste_shift_insert": "For terminals and apps where Ctrl+V does something else.",
                 "type": "Types each character. Slower, but works where pasting is blocked.",
                 "clipboard": "The text goes on the clipboard. Press Ctrl+V where you want it."}
        out_row.desc.setText(descs[cfg["output"]])
        out_row.desc.show()
        restore = Toggle(cfg["restore_clipboard"])

        def set_out() -> None:
            cfg["output"] = out.value()
            out_row.desc.setText(descs[out.value()])
            restore.setEnabled(out.value() in ("paste", "paste_shift_insert"))
        out.currentIndexChanged.connect(lambda _: set_out())
        card.add(out_row)
        restore.toggled.connect(lambda on: cfg.update({"restore_clipboard": on}))
        restore.setEnabled(cfg["output"] in ("paste", "paste_shift_insert"))
        card.add(Row("Keep my clipboard", "Puts back whatever you had copied after pasting. Clipboard managers "
                     "are asked to skip the dictated text.", restore))
        space = Toggle(cfg["trailing_space"])
        space.toggled.connect(lambda on: cfg.update({"trailing_space": on}))
        card.add(Row("Add a space after", "So the next take doesn't run into this one.", space))

        card = page.section("Cleanup")
        for key, title, desc in (
                ("capitalize", "Capital letter at the start", ""),
                ("end_punctuation", "Full stop at the end", "Adds one when the sentence has none."),
                ("remove_fillers", "Remove um and uh", "Drops hesitation sounds. Words like \"like\" stay."),
                ("remove_repeats", "Remove repeated words", "Turns \"the the\" or \"I want, I want to\" into "
                 "one. Words people repeat on purpose, like \"really really\", stay."),
                ("voice_commands", "Spoken punctuation and lists",
                 "Say \"comma\", \"full stop\", \"question mark\", \"colon\", \"hyphen\", \"open bracket\", "
                 "\"open quote\", \"dot point\", \"new line\" or \"new paragraph\". "
                 "Say \"literal\" first to type the word instead.")):
            t = Toggle(cfg[key])
            t.toggled.connect(lambda on, k=key: cfg.update({k: on}))
            card.add(Row(title, desc, t))

        self._page_text_ai(page)

        card = page.section("Replacements", "Fix words it keeps getting wrong. Matches whole words, any case.")
        self.repl_box = QVBoxLayout()
        self.repl_box.setContentsMargins(16, 12, 16, 12)
        self.repl_box.setSpacing(8)
        holder = QWidget()
        holder.setLayout(self.repl_box)
        card.add(holder)
        self._repl_rows: list[tuple[QLineEdit, QLineEdit, QWidget]] = []
        add = button("Add replacement", "", icon="plus")
        add.clicked.connect(lambda: self._add_repl("", "", focus=True))
        self.repl_add = add
        self.repl_box.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        for r in cfg["replacements"]:
            self._add_repl(r["find"], r["replace"])

    def _page_text_ai(self, page: Page) -> None:
        cfg = self.cfg
        card = page.section("AI tidy-up", "A small writing model on this PC rewrites each take after it's "
                            "transcribed. Nothing leaves your PC.")
        on = Toggle(cfg["ai_tidy"])
        card.add(Row("Tidy with AI", "Removes stumbles, false starts and repeats, and punctuates long run-on "
                     "takes. Keeps your words and their order. If the result doesn't match what you said, the "
                     "plain transcript is pasted instead.", on))
        self.ai_model = Combo([], cfg["ai_model"], width=220)
        self.ai_model.setSizeAdjustPolicy(Combo.SizeAdjustPolicy.AdjustToContents)
        self.ai_model.currentIndexChanged.connect(lambda _: self._ai_model_changed())
        self.ai_get = button("Download", "primary", icon="download")
        self.ai_get.clicked.connect(self._ai_get_clicked)
        self.ai_del = button("", "flat", icon="trash")
        self.ai_del.setToolTip("Delete this writing model")
        self.ai_del.setAccessibleName("Delete writing model")
        self.ai_del.clicked.connect(self._ai_delete)
        self.ai_model_row = Row("Writing model", "", self.ai_model)
        self.ai_model_row.controls.addWidget(self.ai_get)
        self.ai_model_row.controls.addWidget(self.ai_del)
        self.ai_get.hide()        # both shown once the check below says what's on disk
        self.ai_del.hide()
        card.add(self.ai_model_row)

        def set_on(enabled: bool) -> None:
            cfg["ai_tidy"] = enabled
            Card.show_row(self.ai_model_row, enabled)
            if enabled:
                self._ai_refresh()
        on.toggled.connect(set_on)
        self._ai_job: dict = {}
        self._ai_cancel = threading.Event()
        self._ai_timer = QTimer(self)
        self._ai_timer.setInterval(250)
        self._ai_timer.timeout.connect(self._ai_tick)
        Card.show_row(self.ai_model_row, cfg["ai_tidy"])
        if cfg["ai_tidy"]:
            QTimer.singleShot(0, self._ai_refresh)

    def _ai_refresh(self) -> None:
        """Fill the writing model list and say what's missing. Checking the
        graphics card starts the engine once, so it runs off the UI thread."""
        if self._ai_job.get("busy") or self._ai_job.get("checking"):
            return
        self._ai_job["checking"] = True

        def work():
            self._ai_job["state"] = (writer.downloaded(), writer.engine_installed(), writer.gpu(),
                                     writer.recommended())
            self._ai_job["checking"] = False
        threading.Thread(target=work, daemon=True, name="writer-check").start()
        self._ai_timer.start()

    def _ai_tick(self) -> None:
        job = self._ai_job
        if job.pop("refresh", False):
            self._ai_refresh()
            return
        if job.get("busy"):
            done, total = job.get("progress", (0, 0))
            what = job.get("what", "")
            self.ai_model_row.set_note(f"Downloading {what} {done * 100 // total if total else 0}%", "value")
            return
        state = job.get("state")
        if state is None:
            return
        self._ai_timer.stop()
        job["state"] = None
        have, engine, (gpu_name, _), rec = state
        want = self.cfg["ai_model"]
        items = []
        for m in writer.CATALOG:
            items.append((m.name, m.title + (" (recommended)" if m.name == rec else "")))
        self.ai_model.set_items(items, want)
        info = writer.BY_NAME[want]
        self.ai_model_row.desc.setText(info.note)
        self.ai_model_row.desc.show()
        ready = want in have and engine
        self.ai_get.setText("Download")
        self.ai_get.setVisible(not ready)
        self.ai_del.setVisible(want in have)
        error = job.pop("error", "")
        if error:
            self.ai_model_row.set_note(f"Download failed: {error}", "danger")
        elif engine and not gpu_name:
            self.ai_model_row.set_note("Needs a graphics card. On the processor alone it takes about 11 seconds "
                                       "per take, so it stays off.", "warn")
        elif not ready:
            size = (0 if want in have else info.size_mb * 1_000_000) + (0 if engine else writer.ENGINE_SIZE)
            self.ai_model_row.set_note(f"Download {_mb(size)} to start. Until then, takes are pasted as "
                                       "transcribed.", "warn")
        else:
            self.ai_model_row.set_note(f"Ready. Runs on {gpu_name}." if gpu_name else "Ready.", "value")

    def _ai_model_changed(self) -> None:
        name = self.ai_model.value()
        if name and name != self.cfg["ai_model"]:
            self.cfg["ai_model"] = name
            self._ai_refresh()

    def _ai_get_clicked(self) -> None:
        job = self._ai_job
        if job.get("busy"):
            self._ai_cancel.set()
            return
        name = self.cfg["ai_model"]
        self._ai_cancel = threading.Event()
        cancel = self._ai_cancel
        job.update(busy=True, progress=(0, 0), what="")
        self.ai_get.setText("Cancel")

        def work():
            try:
                if not writer.engine_installed():
                    job["what"] = "engine"
                    writer.download_engine(lambda d, t: job.__setitem__("progress", (d, t)), cancel)
                job["what"] = writer.BY_NAME[name].title.lower() + " model"
                writer.download_model(name, lambda d, t: job.__setitem__("progress", (d, t)), cancel)
            except InterruptedError:
                pass
            except Exception as e:
                log.exception("Downloading writing model %s failed", name)
                job["error"] = str(e).splitlines()[0][:200] if str(e) else type(e).__name__
            finally:
                job["busy"] = False
                job["refresh"] = True   # picked up on the UI thread by _ai_tick
                if self.cfg["ai_tidy"] and not writer.ready(name):
                    writer.prepare(name)
        threading.Thread(target=work, daemon=True, name="writer-download").start()
        self._ai_timer.start()

    def _ai_delete(self) -> None:
        name = self.cfg["ai_model"]
        title = writer.BY_NAME[name].title
        if QMessageBox.question(self, "Delete writing model", f"Delete the {title} writing model from this PC? "
                                "You can download it again later.") != QMessageBox.StandardButton.Yes:
            return
        writer.delete_model(name)
        self._ai_refresh()

    def _add_repl(self, find: str, rep: str, focus: bool = False) -> None:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        a, b = QLineEdit(find), QLineEdit(rep)
        a.setPlaceholderText("When it writes")
        b.setPlaceholderText("Use this instead")
        a.setAccessibleName("Replace")
        b.setAccessibleName("With")
        arrow = label("→", "sub")
        rm = button("", "flat", icon="x")
        rm.setAccessibleName("Remove replacement")
        lay.addWidget(a, 1)
        lay.addWidget(arrow)
        lay.addWidget(b, 1)
        lay.addWidget(rm)
        self.repl_box.insertWidget(self.repl_box.count() - 1, w)
        entry = (a, b, w)
        self._repl_rows.append(entry)
        a.editingFinished.connect(self._save_repl)
        b.editingFinished.connect(self._save_repl)

        def remove():
            self._repl_rows.remove(entry)
            w.deleteLater()
            self._save_repl()
        rm.clicked.connect(remove)
        if focus:
            a.setFocus()

    def _save_repl(self) -> None:
        self.cfg["replacements"] = [{"find": a.text().strip(), "replace": b.text()}
                                    for a, b, _ in self._repl_rows if a.text().strip()]

    # ------------------------------------------------------------ look
    def _page_look(self, page: Page) -> None:
        cfg = self.cfg
        card = page.section("Colours")
        th = Combo([(n, n) for n in theme.THEME_NAMES], cfg["theme"], width=240)
        th.currentIndexChanged.connect(lambda _: cfg.update({"theme": th.value()}))
        card.add(Row("Theme", "", th))
        acc = Segmented([("theme", "From the theme"), ("windows", "Windows accent")], cfg["accent_source"])
        acc.changed.connect(lambda k: cfg.update({"accent_source": k}))
        card.add(Row("Accent colour", "Buttons, switches and highlights.", acc))
        families = sorted({f for f in QFontDatabase.families() if not f.startswith("@")}, key=str.lower)
        font = QLineEdit(cfg["font"])
        font.setMinimumWidth(240)
        comp = QCompleter(families, font)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        font.setCompleter(comp)
        font_row = Row("Font", "Type to search the fonts on this PC.", font)

        def set_font() -> None:
            name = font.text().strip()
            match = next((f for f in families if f.lower() == name.lower()), None)
            if match:
                font.setText(match)
                font_row.set_note("")
                cfg["font"] = match
            elif name:
                font_row.set_note(f"No font called \"{name}\" on this PC.")
        font.editingFinished.connect(set_font)
        comp.activated.connect(lambda _: set_font())
        card.add(font_row)

        card = page.section("Window material")
        bd = Segmented([("mica_alt", "Mica Alt"), ("mica", "Mica"), ("acrylic", "Acrylic"), ("blur", "Blur"),
                        ("solid", "Solid")],
                       cfg["backdrop"])
        self.backdrop_row = Row("Material", "", bd)
        self.backdrop_note = self.backdrop_row
        tint = Slider(0, 100, cfg["tint"], "%")
        keep = Toggle(cfg["backdrop_when_inactive"])
        bd.changed.connect(lambda k: cfg.update({"backdrop": k}))
        tint.changed.connect(lambda v: cfg.update({"tint": v}))
        keep.toggled.connect(lambda on: cfg.update({"backdrop_when_inactive": on}))
        card.add(self.backdrop_row)
        self.tint_row = Row("Tint", "How much of the theme colour covers the material. Lower lets more through.", tint)
        card.add(self.tint_row)
        self.keep_row = Row("Keep the effect in the background",
                            "Windows normally swaps the material for a flat colour when you switch to another window.",
                            keep)
        card.add(self.keep_row)
        tb = Segmented([("custom", "FreeDictate"), ("windows", "Windows")], cfg["titlebar"])
        tb.changed.connect(lambda k: cfg.update({"titlebar": k}))
        card.add(Row("Title bar", "Windows uses the standard title bar, buttons and menu.", tb))
        self._update_backdrop_note()

        card = page.section("Motion")
        rm = Toggle(cfg["reduce_motion"])
        rm.toggled.connect(lambda on: cfg.update({"reduce_motion": on}))
        card.add(Row("Reduce motion", "Turns off fades and sliding switches.", rm))

    def _update_backdrop_note(self) -> None:
        cfg = self.cfg
        descs = {"mica_alt": "Mica Alt: a deeper tint of your wallpaper. Windows uses it for tabbed apps.",
                 "mica": "Mica: a subtle tint of your wallpaper.",
                 "acrylic": "Acrylic: frosted glass that blurs what's behind the window.",
                 "blur": "Blur: a clear, smooth blur of what's behind the window, without Acrylic's grain.",
                 "solid": "Solid: a plain theme colour."}
        row = self.backdrop_row
        row.desc.setText(descs[cfg["backdrop"]])
        row.desc.show()
        solid = cfg["backdrop"] == "solid"
        if not native.backdrop_supported():
            row.set_note("Materials need Windows 11 22H2 or later. The window stays solid.")
        elif not native.transparency_enabled():
            row.set_note("Transparency effects are off in Windows Settings > Personalization > Colors.")
        else:
            row.set_note("")
        self.tint_row.setEnabled(not solid)
        self.keep_row.setEnabled(not solid)

    # ------------------------------------------------------------ history
    def _page_history(self, page: Page) -> None:
        self.stats = label("", "sub")
        page.add(self.stats)
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search your dictations")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search", theme.current().sub), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        bar.addWidget(self.search, 1)
        f = button("Transcribe a file", "", icon="file")
        f.clicked.connect(self.app.pick_file)
        bar.addWidget(f)
        ex = button("Export", "")
        ex.clicked.connect(self._export_history)
        bar.addWidget(ex)
        clear = button("Clear all", "danger")
        clear.clicked.connect(self._clear_history)
        bar.addWidget(clear)
        holder = QWidget()
        holder.setLayout(bar)
        page.add(holder)

        self.file_banner = Banner("")
        self.file_banner.hide()
        page.add(self.file_banner)

        self.hist_holder = QWidget()
        self.hist_box = QVBoxLayout(self.hist_holder)
        self.hist_box.setContentsMargins(0, 4, 0, 0)
        self.hist_box.setSpacing(6)
        page.add(self.hist_holder)
        self.hist_empty = label("", "sub", wrap=True)
        self.hist_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hist_empty.setContentsMargins(0, 30, 0, 30)
        page.add(self.hist_empty)
        self.more_btn = button("Show more")
        self.more_btn.clicked.connect(self._more_history)
        page.add(self.more_btn)

        card = page.section("Keeping history")
        keep = Toggle(self.cfg["history_enabled"])
        keep.toggled.connect(lambda on: self.cfg.update({"history_enabled": on}))
        card.add(Row("Save my dictations", "Stored only on this PC.", keep))
        days = Combo([("0", "Forever"), ("365", "1 year"), ("90", "90 days"), ("30", "30 days"), ("7", "7 days"),
                      ("1", "1 day")], str(self.cfg["history_days"]), width=180)
        days.currentIndexChanged.connect(lambda _: self.cfg.update({"history_days": int(days.value())}))
        card.add(Row("Delete dictations older than", "", days))

    def _focus_search(self) -> None:
        self.go("history")
        self.search.setFocus()
        self.search.selectAll()

    def _history_changed(self) -> None:
        if self.isVisible() and self.stack.currentWidget() is self.pages["history"]:
            self.reload_history()
        else:
            # Rebuild on the next visit instead of on every write.
            self._history_stale = True

    def _more_history(self) -> None:
        self._history_limit += 150
        self.reload_history()

    def reload_history(self) -> None:
        if not hasattr(self, "hist_box") or getattr(self, "_disposed", False):
            return
        self._history_stale = False
        q = self.search.text()
        st = self.history.stats()
        if st["count"]:
            mins = st["seconds"] / 60
            self.stats.setText(f"{st['count']:,} dictations, {st['words']:,} words, {mins:,.0f} minutes of speech. "
                               f"{st['words_week']:,} words in the last 7 days.")
        else:
            self.stats.setText("")
        self.stats.setVisible(bool(st["count"]))
        entries = self.history.search(q, limit=self._history_limit)
        total = self.history.count(q)
        self.hist_holder.setUpdatesEnabled(False)
        # Rebind the surviving cards to the new entries; tear down only the
        # tail and build only the growth. Deleting and recreating every card
        # restyled ~150 frames per keystroke and per dictation.
        while self.hist_box.count() > len(entries):
            w = self.hist_box.takeAt(self.hist_box.count() - 1).widget()
            if w:
                w.deleteLater()
        for i, e in enumerate(entries):
            item = self.hist_box.itemAt(i).widget() if i < self.hist_box.count() else None
            if item is None:
                self.hist_box.addWidget(HistoryItem(e, self))
            else:
                item.rebind(e)
        self.hist_holder.setUpdatesEnabled(True)
        self.hist_holder.setVisible(bool(entries))
        if not entries:
            if q:
                self.hist_empty.setText(f"Nothing matches \"{q}\".")
            elif not self.cfg["history_enabled"]:
                self.hist_empty.setText("History is off. Turn on \"Save my dictations\" below to keep a record here.")
            else:
                self.hist_empty.setText(f"No dictations yet. Hold {hotkeys.label(self.cfg['hotkey'])} anywhere, "
                                        "talk, and let go. Each one shows up here.")
        self.hist_empty.setVisible(not entries)
        self.more_btn.setVisible(total > len(entries))

    def _export_history(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export history", str(Path.home() / "FreeDictate history.txt"),
                                              "Text files (*.txt)")
        if path:
            n = self.history.export_text(Path(path))
            self.app.notify("History exported", f"{n} dictations saved to {Path(path).name}.")

    def _clear_history(self) -> None:
        if QMessageBox.question(self, "Clear history", "Delete every saved dictation? This can't be undone.") \
                == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self.reload_history()

    def file_started(self, path: str) -> None:
        self.file_banner.setObjectName("banner")
        self.file_banner.text.setText(f"Transcribing <b>{Path(path).name}</b>. Long files take a while.")
        self._clear_banner_actions()
        self.file_banner.show()

    def _clear_banner_actions(self) -> None:
        while self.file_banner.actions.count():
            w = self.file_banner.actions.takeAt(0).widget()
            if w:
                w.deleteLater()

    @Slot(str, str)
    def _on_file_result(self, path: str, text: str) -> None:
        self._clear_banner_actions()
        name = Path(path).name
        if text.startswith("error:"):
            self.file_banner.text.setText(f"<b>{name}</b> couldn't be transcribed: {text[6:].strip()}")
            close = button("", "flat", icon="x")
            close.setAccessibleName("Close")
            close.clicked.connect(self.file_banner.hide)
            self.file_banner.actions.addWidget(close)
            return
        if not text.strip():
            self.file_banner.text.setText(f"No speech found in <b>{name}</b>.")
            return
        words = len(text.split())
        self.file_banner.text.setText(f"<b>{name}</b>: {words:,} words. Copy them, or save them as a text file.")
        copy = button("Copy", "primary", icon="copy")
        copy.clicked.connect(lambda: self.app.copy(text))
        save = button("Save")

        def save_file():
            target, _ = QFileDialog.getSaveFileName(self, "Save transcript", str(Path(path).with_suffix(".txt")),
                                                    "Text files (*.txt)")
            if target:
                Path(target).write_text(text + "\n", encoding="utf-8")
        save.clicked.connect(save_file)
        close = button("", "flat", icon="x")
        close.setAccessibleName("Close")
        close.clicked.connect(self.file_banner.hide)
        for b in (copy, save, close):
            self.file_banner.actions.addWidget(b)

    # ------------------------------------------------------------ general
    def _page_general(self, page: Page) -> None:
        cfg = self.cfg
        card = page.section("Startup")
        enabled, elevated = self.app.autostart_state()
        self.auto = Toggle(enabled)
        self.admin = Toggle(elevated or cfg["run_elevated"])
        auto_row = Row("Start with Windows", "Starts quietly in the tray when you sign in.", self.auto)
        admin_row = Row("Run as administrator",
                        "Lets it paste into apps that run as administrator. Windows blocks that otherwise. "
                        "Asks for permission once.", self.admin)
        self.admin_row = admin_row
        # One persistent button, shown only while a restart is pending. A fresh
        # insert per apply_startup() call stacked copies when both toggles
        # changed in one pass, and left one behind when the toggle went off.
        self.restart_btn = button("Restart now")
        self.restart_btn.clicked.connect(lambda: self.app.restart(elevated=True))
        self.restart_btn.hide()
        admin_row.controls.insertWidget(0, self.restart_btn)

        def apply_startup() -> None:
            err = self.app.set_autostart(self.auto.isChecked(), self.admin.isChecked())
            now_enabled, now_elevated = self.app.autostart_state()
            for t, v in ((self.auto, now_enabled), (self.admin, now_elevated)):
                t.blockSignals(True)
                t.setChecked(v)
                t.blockSignals(False)
            self.restart_btn.setVisible(not err and now_elevated and not system.is_admin())
            if err:
                admin_row.set_note(err, "danger")
            elif now_elevated and not system.is_admin():
                admin_row.set_note("Takes effect when FreeDictate restarts.")
            else:
                admin_row.set_note("")
        self.auto.toggled.connect(lambda _: apply_startup())
        self.admin.toggled.connect(lambda on: (self.auto.setChecked(True) if on and not self.auto.isChecked() else None,
                                               apply_startup()))
        card.add(auto_row)
        card.add(admin_row)
        if system.is_admin():
            admin_row.set_note("Running as administrator now.", "value")

        card = page.section("Updates")
        self.update_banner = Banner("", parent=None)
        self.update_banner.hide()
        page.column.insertWidget(page.column.count() - 1, self.update_banner)
        auto_upd = Toggle(cfg["check_updates"])
        auto_upd.toggled.connect(lambda on: cfg.update({"check_updates": on}))
        card.add(Row("Check for updates automatically", "Once a day, from GitHub. Nothing installs without you.", auto_upd))
        pre = Toggle(cfg["update_prereleases"])
        pre.toggled.connect(lambda on: cfg.update({"update_prereleases": on}))
        card.add(Row("Include test versions", "Get pre-releases early. They may have bugs.", pre))
        self.update_btn = button("Check now", "", icon="refresh")
        self.update_btn.clicked.connect(lambda: self.app.check_updates(manual=True))
        self.update_progress = QProgressBar()
        self.update_progress.setTextVisible(False)
        self.update_progress.setFixedWidth(160)
        self.update_progress.hide()
        last = cfg["last_update_check"]
        when = time.strftime("%d %b %Y, %I:%M %p", time.localtime(last)).lstrip("0") if last else "never"
        self.update_row = Row(f"FreeDictate {__version__}", f"Last checked: {when}.", self.update_progress)
        self.update_row.controls.addWidget(self.update_btn)
        card.add(self.update_row)
        if self.app.update_release:
            self._on_update_status(f"FreeDictate {self.app.update_release.version} is available.", self.app.update_release)

        card = page.section("Your data")
        where = label(str(paths.DATA), "sub")
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        opn = button("Open folder", "", icon="external")
        opn.clicked.connect(lambda: system.open_path(paths.DATA))
        r = Row("Settings and history", "", where)
        r.controls.addWidget(opn)
        card.add(r)
        logs = button("Open logs", "", icon="external")
        logs.clicked.connect(lambda: system.open_path(paths.LOGS))
        card.add(Row("Logs", "What to attach when you report a problem.", logs))
        exp, imp = button("Export"), button("Import")
        exp.clicked.connect(self._export_settings)
        imp.clicked.connect(self._import_settings)
        r = Row("Back up your settings", "Save them to a file, or load them on another PC.", exp)
        r.controls.addWidget(imp)
        card.add(r)
        reset = button("Reset", "danger")
        reset.clicked.connect(self._reset_settings)
        card.add(Row("Reset all settings", "History and downloaded models are kept.", reset))
        old = button("Import from FreeDictate 2…", "", icon="file")
        old.clicked.connect(self._import_v2)
        card.add(Row("Coming from FreeDictate 2?",
                     "Point this at your old FreeDictate folder to bring over its settings and history.", old))

    @Slot(str, object)
    def _on_update_status(self, msg: str, rel) -> None:
        if not msg:
            return
        self.update_row.desc.setText(msg)
        self.update_row.desc.show()
        busy = self.app.update_busy
        self.update_btn.setEnabled(not busy)
        if rel is not None and not busy:
            notes = rel.notes.strip().splitlines()
            summary = " ".join(n.strip("-*# ") for n in notes[:3] if n.strip())[:220]
            self.update_banner.text.setText(f"<b>FreeDictate {rel.version} is ready to install.</b> {summary}"
                                            f" <a href=\"{rel.url}\">Release notes</a>")
            while self.update_banner.actions.count():
                w = self.update_banner.actions.takeAt(0).widget()
                if w:
                    w.deleteLater()
            inst = button("Install and restart", "primary", icon="download")
            inst.clicked.connect(self.app.install_update)
            skip = button("Skip this version", "flat")
            skip.clicked.connect(lambda: (self.cfg.update({"skipped_version": rel.version}), self.update_banner.hide()))
            self.update_banner.actions.addWidget(skip)
            self.update_banner.actions.addWidget(inst)
            self.update_banner.show()
        if not busy:
            self.update_progress.hide()

    @Slot(int, int)
    def _on_update_progress(self, done: int, total: int) -> None:
        self.update_progress.show()
        self.update_progress.setRange(0, 1000 if total else 0)
        if total:
            self.update_progress.setValue(int(done * 1000 / total))

    def _export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export settings", str(Path.home() / "FreeDictate settings.json"),
                                              "Settings (*.json)")
        if path:
            self.cfg.export_to(Path(path))

    def _import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import settings", str(Path.home()), "Settings (*.json)")
        if not path:
            return
        try:
            self.cfg.import_from(Path(path))
        except Exception as e:
            QMessageBox.warning(self, "Import settings", f"That file couldn't be read: {e}")
            return
        self._rebuild()

    def _import_v2(self) -> None:
        """Pull settings and history out of a v1/v2 FreeDictate folder
        (config.json and transcripts.log next to freedictate.py)."""
        folder = QFileDialog.getExistingDirectory(self, "Choose your old FreeDictate folder")
        if not folder:
            return
        old = Path(folder)
        notes = []
        cfg_file = old / "config.json"
        if cfg_file.exists():
            try:
                self.cfg.import_from(cfg_file)
                notes.append("settings imported")
            except Exception as e:
                notes.append(f"settings not readable ({e})")
        log_file = old / "transcripts.log"
        if log_file.exists():
            try:
                n = self.history.import_legacy_log(log_file)
                notes.append(f"{n} dictations added to history")
            except Exception as e:
                notes.append(f"history not readable ({e})")
        if not notes:
            QMessageBox.information(self, "Import from FreeDictate 2",
                                    "No config.json or transcripts.log in that folder.")
            return
        if "settings imported" in notes:
            self._rebuild()
            self.reload_history()
        QMessageBox.information(self, "Import from FreeDictate 2", "; ".join(notes).capitalize() + ".")

    def _reset_settings(self) -> None:
        if QMessageBox.question(self, "Reset settings", "Put every setting back to its default?") \
                == QMessageBox.StandardButton.Yes:
            self.cfg.reset()
            self._rebuild()

    def _rebuild(self) -> None:
        """Rebuild the pages so every control shows the new values."""
        page = self.cfg["window_page"]
        geo = self.saveGeometry()
        self.dispose()          # don't leave bus/history listeners on a dead window
        self.app.settings_window = None
        self.close()
        self.deleteLater()
        self.app.show_settings(page)
        self.app.settings_window.restoreGeometry(geo)

    # ------------------------------------------------------------ about
    def _page_about(self, page: Page) -> None:
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(icons.app_icon("ready").pixmap(QSize(64, 64)))
        head.addWidget(logo)
        txt = QVBoxLayout()
        txt.setSpacing(2)
        name = label(APP_NAME, "name")
        txt.addWidget(name)
        txt.addWidget(label(f"Version {__version__}", "sub"))
        txt.addWidget(label("Speak, and the words appear where you're typing. Offline, private, and free.", "sub", wrap=True))
        head.addLayout(txt, 1)
        holder = QWidget()
        holder.setLayout(head)
        page.add(holder)

        card = page.section("Links")
        for title, desc, url in (
                ("Project page", "Source code, documentation and releases.", REPO_URL),
                ("Report a problem", "Attach the log file from General > Your data.", f"{REPO_URL}/issues/new"),
                ("What's new", "Changes in every version.", f"{REPO_URL}/releases")):
            b = button("Open", "", icon="external")
            b.clicked.connect(lambda _=False, u=url: system.open_path(u))
            card.add(Row(title, desc, b))

        card = page.section("Built with")
        credits = label(
            "Speech recognition by OpenAI Whisper, run through faster-whisper (SYSTRAN) and CTranslate2 (OpenNMT), "
            "and NVIDIA Parakeet through onnx-asr. AI tidy-up by Qwen3 models (Apache 2.0) run with llama.cpp. "
            "Interface built with Qt for Python. Audio through PortAudio and sounddevice. "
            "FreeDictate is open source under the MIT license.", "sub", wrap=True)
        credits.setContentsMargins(16, 12, 16, 12)
        card.add(credits)


class HistoryItem(QFrame):
    def __init__(self, entry, win: SettingsWindow):
        super().__init__()
        self.setObjectName("card")
        self.entry, self.win = entry, win
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 8, 10)
        lay.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(3)
        self.meta_label = label(self._meta_text(entry), "sub")
        text.addWidget(self.meta_label)
        self.body_label = label(self._body_text(entry), wrap=True)
        self.body_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.addWidget(self.body_label)
        lay.addLayout(text, 1)
        copy = button("", "flat", icon="copy")
        copy.setToolTip("Copy")
        copy.setAccessibleName("Copy dictation")
        copy.clicked.connect(self._copy)
        delete = button("", "flat", icon="trash")
        delete.setToolTip("Delete")
        delete.setAccessibleName("Delete dictation")
        delete.clicked.connect(self._delete)
        original = button("", "flat", icon="undo")
        original.setToolTip("Copy what you said, before the AI tidy-up")
        original.setAccessibleName("Copy original dictation")
        original.clicked.connect(self._copy_original)
        lay.addWidget(original, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(copy, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(delete, 0, Qt.AlignmentFlag.AlignTop)
        self.copy_btn = copy
        self.original_btn = original
        original.setVisible(bool(entry.raw) and entry.raw != entry.text)

    @staticmethod
    def _meta_text(entry) -> str:
        when = time.strftime("%a %d %b, %I:%M %p", time.localtime(entry.ts)).replace(" 0", " ")
        meta = [when, f"{entry.seconds:.0f} s"]
        if entry.app:
            meta.append(entry.app.removesuffix(".exe"))
        return "  ·  ".join(meta)

    @staticmethod
    def _body_text(entry) -> str:
        return entry.text if len(entry.text) < 600 else entry.text[:600].rstrip() + "..."

    def rebind(self, entry) -> None:
        """Show another entry in this card. Rebuilding ~150 styled frames on
        every keystroke and every dictation was the History tab's lag."""
        self.entry = entry
        self.meta_label.setText(self._meta_text(entry))
        self.body_label.setText(self._body_text(entry))
        self.original_btn.setVisible(bool(entry.raw) and entry.raw != entry.text)

    def _copy_original(self) -> None:
        self.win.app.copy(self.entry.raw)
        self.original_btn.setIcon(icons.icon("check", theme.current().ok))
        QTimer.singleShot(1200, lambda: self.original_btn.setIcon(icons.icon("undo", theme.current().text)))

    def _copy(self) -> None:
        self.win.app.copy(self.entry.text)
        self.copy_btn.setIcon(icons.icon("check", theme.current().ok))
        QTimer.singleShot(1200, lambda: self.copy_btn.setIcon(icons.icon("copy", theme.current().text)))

    def _delete(self) -> None:
        self.win.history.delete(self.entry.id)


def _model_title(name: str) -> str:
    info = models.BY_NAME.get(name)
    return info.title if info else name
