"""UI regression tests: the tint slider geometry, the tint with the Windows
title bar, and the History tab's deferred, reuse-based reload."""
import os
import sys
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import pytest
from PySide6.QtWidgets import QApplication, QSlider, QStyle, QStyleOptionSlider

from freedictate import paths
from freedictate.app import Bus
from freedictate.config import Config
from freedictate.history import History
from freedictate.ui import native, theme
from freedictate.ui import settings as settings_mod
from freedictate.ui.settings import SettingsWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv or ["fd-test"])


@pytest.fixture(scope="module")
def env(qapp):
    paths.ensure()
    pal = theme.set_current("Catppuccin Mocha", "Segoe UI Variable Text")
    qapp.setStyleSheet(theme.stylesheet(pal, True))
    qapp.setFont(theme.font())
    hist = History()
    if hist.count() < 50:
        now = time.time()
        for i in range(50):
            hist.add(f"Regression seed {i}: a sentence long enough to wrap the card label.", 2.5,
                     "large-v3", "chrome.exe", ts=now - i * 900)
    yield SimpleNamespace(hist=hist)
    hist.close()


class FakeEngine:
    state = "ready"
    paused = False
    suspended = False
    model = object()

    class _MS:
        active, device, compute = "large-v3", "cuda", "float16"
        status, error, wanted = "idle", "", "large-v3"
        progress = (0, 1)

    ms = _MS()

    def status_text(self):
        return "Ready"

    def cancel_download(self):
        pass

    def ensure_model(self, force=False):
        pass

    def toggle_pause(self):
        return False


def make_app(cfg, hist):
    eng = FakeEngine()
    eng.recorder = SimpleNamespace(level=0.0, elapsed=lambda: 0.0)
    return SimpleNamespace(
        cfg=cfg, engine=eng, history=hist, bus=Bus(),
        toggle_pause=lambda: None, pick_file=lambda: None,
        notify=lambda *a, **k: None, copy=lambda t: None,
        autostart_state=lambda: (False, False), set_autostart=lambda e, a: "",
        check_updates=lambda manual=True: None, install_update=lambda: None,
        download_gpu=lambda: None, cancel_gpu=lambda: None,
        gpu_busy=False, update_busy=False, update_release=None)


def fresh_cfg(**overrides):
    cfg = Config()
    cfg.update({"first_run_done": True, "window_page": "dictation",
                "theme": "Catppuccin Mocha", "titlebar": "custom",
                "backdrop": "mica_alt", "tint": 65})
    cfg.update(overrides)
    return cfg


def pump(qapp, n=20):
    for _ in range(n):
        qapp.processEvents()


def open_window(qapp, cfg, env):
    win = SettingsWindow(make_app(cfg, env.hist))
    win.show()
    pump(qapp, 6)
    return win


def test_every_slider_fits_its_handle(qapp, env):
    """The 12px handle plus its 4px ring is 20px tall; a shorter slider clips
    the ring at the top and bottom."""
    win = open_window(qapp, fresh_cfg(), env)
    try:
        sliders = win.findChildren(QSlider)
        assert len(sliders) == 3  # sound volume, beam size, tint
        for sl in sliders:
            opt = QStyleOptionSlider()
            sl.initStyleOption(opt)
            handle = sl.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                               QStyle.SubControl.SC_SliderHandle, sl)
            assert handle.height() <= sl.height(), (handle, sl.height())
            assert 0 <= handle.top() and handle.bottom() < sl.height()
    finally:
        win.dispose()
        win.close()


def test_tint_stays_usable_with_windows_titlebar(qapp, env):
    cfg = fresh_cfg(titlebar="windows")
    win = open_window(qapp, cfg, env)
    try:
        assert win.tint_row.isEnabled()
        assert "raw material" in win.tint_row.note.text()
        if not (native.backdrop_supported() and native.transparency_enabled()):
            pytest.skip("no systembackdrop on this machine")
        win.set_look("mica_alt", 0.0, cfg["backdrop_when_inactive"])
        pump(qapp, 6)
        img0 = win.grab().toImage()
        win.set_look("mica_alt", 0.65, cfg["backdrop_when_inactive"])
        pump(qapp, 6)
        img65 = win.grab().toImage()
        x, y = win.width() - 12, win.height() // 2
        assert img0.pixelColor(x, y) != img65.pixelColor(x, y), "tint must paint the body"
    finally:
        win.dispose()
        win.close()


def test_history_reloads_deferred_and_reuses_cards(qapp, env):
    counter = {"n": 0}
    orig = settings_mod.HistoryItem

    class Counting(orig):
        def __init__(self, *a, **k):
            counter["n"] += 1
            super().__init__(*a, **k)

    settings_mod.HistoryItem = Counting
    win = open_window(qapp, fresh_cfg(), env)
    try:
        win.go("history")
        assert counter["n"] == 0, "the tab switch must not build inline"
        pump(qapp)
        built = counter["n"]
        assert 0 < built <= 150
        assert win.hist_box.itemAt(0).widget().body_label.text() == env.hist.search("", limit=1)[0].text

        win.go("dictation")
        pump(qapp, 6)
        win.go("history")
        pump(qapp)
        assert counter["n"] == built, "returning to the tab must not rebuild"

        env.hist.add("Dictated while watching the History page.", 1.0, "large-v3", "notepad.exe")
        win.app.bus.history_changed.emit()
        pump(qapp)
        assert counter["n"] == built + 1, "only the new card may be built, never the whole page"
        assert win.hist_box.itemAt(0).widget().body_label.text() == \
            "Dictated while watching the History page."

        win.go("dictation")
        pump(qapp, 6)
        env.hist.add("Another dictation written on another page.", 1.0, "large-v3", "notepad.exe")
        win.app.bus.history_changed.emit()   # marks the tab stale
        win.go("history")
        pump(qapp)
        assert counter["n"] == built + 2, "returning must rebind, not rebuild"
        assert win.hist_box.itemAt(0).widget().body_label.text() == \
            "Another dictation written on another page."
    finally:
        settings_mod.HistoryItem = orig
        win.dispose()
        win.close()
