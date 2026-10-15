"""UI regression tests: the tint slider geometry, the tint with the Windows
title bar, and the History tab's deferred, reuse-based reload."""
import os
import sys
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
# fresh_cfg() saves settings: never let a script that imports this module write
# the real profile (it happened once, through a probe outside pytest).
if not os.environ.get("FREEDICTATE_HOME"):
    raise RuntimeError("Set FREEDICTATE_HOME to a scratch folder before importing the UI tests")

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QSlider, QStyle, QStyleOptionSlider

from freedictate import paths
from freedictate.app import Bus
from freedictate.config import Config
from freedictate.history import History
from freedictate.ui import native, theme
from freedictate.ui import settings as settings_mod
from freedictate.ui.settings import SettingsWindow
from freedictate.ui.window import FluentWindow


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
        assert len(sliders) == 4  # sound volume, processor cores, beam size, tint
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


def test_unloaded_status_title_fits_the_sidebar(qapp, env):
    """The unloaded title sits in the 232 px sidebar; "Unloaded to save VRAM"
    clipped its last word there. Keep it short — the wrapped line under it
    already spells out what happened."""
    app = make_app(fresh_cfg(), env.hist)
    app.engine.model = None
    app.engine.ms = SimpleNamespace(active="", device="cpu", compute="int8",
                                    status="idle", error="", wanted="", progress=(0, 1))
    win = SettingsWindow(app)
    win.show()
    pump(qapp, 6)
    try:
        assert win.status_title.text() == "Unloaded"
        fm = win.status_title.fontMetrics()
        assert fm.horizontalAdvance(win.status_title.text()) <= win.status_title.width()
    finally:
        win.dispose()
        win.close()


def test_tint_stays_usable_with_windows_titlebar(qapp, env):
    cfg = fresh_cfg(titlebar="windows")
    win = open_window(qapp, cfg, env)
    try:
        assert win.tint_row.isEnabled()
        assert win.tint_row.note.text() == ""     # the caption takes the tint since 3.0.3
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


def test_caption_matches_tinted_body_with_windows_titlebar(qapp, env, monkeypatch):
    """The caption gets the tint composed over the material tone measured off
    the caption strip; a tint change recomposes from the cached tone without
    re-measuring, and solid/zero tints keep their exact captions."""
    calls, measured = [], []
    monkeypatch.setattr(native, "set_caption", lambda h, c, t: calls.append(c))
    monkeypatch.setattr(native, "visible_rect", lambda h: (0, 100, 800, 500))
    monkeypatch.setattr(native, "client_origin", lambda h: (0, 131))  # caption is 31px
    monkeypatch.setattr(native, "screen_patch_median", lambda rect: measured.append(rect) or (73, 76, 95))

    win = FluentWindow("caption-test", native_titlebar=True)
    monkeypatch.setattr(native, "point_window", lambda x, y: win.hwnd())
    win.show()
    pump(qapp, 2)
    pal = theme.current()
    try:
        win._backdrop, win._tint = "acrylic", 0.75
        win._apply_caption()
        assert calls[-1] is None, "raw material until the tone is measured"
        win._measure_caption_tone()          # the deferred step, run inline
        assert len(measured) == 1
        m_hex = "#494c5f"                    # the stubbed strip median
        assert calls[-1] == theme.mix(m_hex, pal.bg, 0.75)

        win._tint = 0.30                     # slider drag: no re-measure
        win._apply_caption()
        assert calls[-1] == theme.mix(m_hex, pal.bg, 0.30)
        assert len(measured) == 1

        win._backdrop = "solid"
        win._apply_caption()
        assert calls[-1] == pal.bg
        win._backdrop, win._tint = "acrylic", 0.0
        win._apply_caption()
        assert calls[-1] is None

        # let the deferred measurement timer from the first pass fire safely
        loop = QEventLoop()
        QTimer.singleShot(800, loop.quit)
        loop.exec()
    finally:
        win.deleteLater()
        pump(qapp, 2)


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


def test_silence_row_only_shows_for_press_to_start(qapp, env):
    win = open_window(qapp, fresh_cfg(hotkey_mode="hold"), env)
    try:
        row = win._silence_row
        assert row.isHidden() and row._card_divider.isHidden()
        win.cfg["hotkey_mode"] = "toggle"
        from freedictate.ui.widgets import Card
        Card.show_row(row, True)
        pump(qapp)
        assert not row.isHidden() and not row._card_divider.isHidden()
    finally:
        win.close()
        win.deleteLater()
        pump(qapp)


def test_ai_tidy_offers_the_download_with_the_engine_size(qapp, env, monkeypatch):
    from freedictate import writer
    monkeypatch.setattr(writer, "downloaded", lambda: [])
    monkeypatch.setattr(writer, "engine_installed", lambda: False)
    monkeypatch.setattr(writer, "gpu", lambda: ("", 0))
    monkeypatch.setattr(writer, "recommended", lambda: "standard")
    win = open_window(qapp, fresh_cfg(ai_tidy=True, ai_model="standard", window_page="text"), env)
    try:
        deadline = time.monotonic() + 3
        while win.ai_get.isHidden() and time.monotonic() < deadline:
            pump(qapp)
        assert not win.ai_model_row.isHidden()
        assert not win.ai_get.isHidden() and win.ai_del.isHidden()
        assert "Download 2.5 GB to start" in win.ai_model_row.note.text()   # model plus the 32 MB engine
        assert "recommended" in win.ai_model.currentText()
    finally:
        win.close()
        win.deleteLater()
        pump(qapp)


def test_ai_tidy_says_when_there_is_no_graphics_card(qapp, env, monkeypatch):
    from freedictate import writer
    monkeypatch.setattr(writer, "downloaded", lambda: ["light"])
    monkeypatch.setattr(writer, "engine_installed", lambda: True)
    monkeypatch.setattr(writer, "gpu", lambda: ("", 0))
    monkeypatch.setattr(writer, "recommended", lambda: "standard")
    win = open_window(qapp, fresh_cfg(ai_tidy=True, ai_model="light", window_page="text"), env)
    try:
        deadline = time.monotonic() + 3
        while "graphics card" not in win.ai_model_row.note.text() and time.monotonic() < deadline:
            pump(qapp)
        assert "Needs a graphics card" in win.ai_model_row.note.text()
        assert win.ai_get.isHidden() and not win.ai_del.isHidden()
    finally:
        win.close()
        win.deleteLater()
        pump(qapp)


def test_ai_tidy_off_hides_its_rows(qapp, env):
    win = open_window(qapp, fresh_cfg(ai_tidy=False), env)
    try:
        assert win.ai_model_row.isHidden()
    finally:
        win.close()
        win.deleteLater()
        pump(qapp)


def test_speech_models_are_one_dropdown(qapp, env, monkeypatch):
    from freedictate import models
    monkeypatch.setattr(models, "downloaded", lambda: ["large-v3", "tiny.en"])
    win = open_window(qapp, fresh_cfg(model="large-v3", window_page="models"), env)
    try:
        win._refresh_models()
        assert win.model_combo.count() == len(models.CATALOG)
        assert win.model_combo.value() == "large-v3" and "in use" in win.model_combo.currentText()
        assert win.model_btn.isHidden()                           # the model in use needs no button
        lib = win._lib_rows                                        # the library lists every model
        assert "In use" in lib["large-v3"].note.text()
        assert not lib["large-v3"].controls.itemAt(0).widget().isVisible()
        assert lib["tiny.en"].note.text() == "Downloaded"
        assert lib["tiny.en"].controls.itemAt(0).widget().text() == "Remove"
        assert "Not downloaded" in lib["parakeet-tdt-0.6b-v2"].note.text()
        win.model_combo.setCurrentIndex(win.model_combo.findData("parakeet-tdt-0.6b-v2"))
        pump(qapp)
        assert win.model_btn.text() == "Download" and not win.model_btn.isHidden()
        assert "NVIDIA" in win.model_row.desc.text()
        win.model_combo.setCurrentIndex(win.model_combo.findData("tiny.en"))
        pump(qapp)
        assert win.model_btn.text() == "Use"
    finally:
        win.close()
        win.deleteLater()
        pump(qapp)


def test_slider_values_can_be_typed(qapp, env):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from freedictate.ui.widgets import Slider
    sl = Slider(0, 100, 65, "%")
    got = []
    sl.changed.connect(got.append)
    sl.show()
    pump(qapp)
    box = sl.v
    assert box.text() == "65%"
    box.setFocus()
    box.selectAll()
    QTest.keyClicks(box, "87%")
    QTest.keyClick(box, Qt.Key.Key_Return)
    pump(qapp)
    assert sl.value() == 87 and box.text() == "87%" and got[-1] == 87
    box.setFocus()
    box.selectAll()
    QTest.keyClicks(box, "250")                       # out of range: clamped
    QTest.keyClick(box, Qt.Key.Key_Return)
    pump(qapp)
    assert sl.value() == 100 and box.text() == "100%"
    box.setFocus()
    box.selectAll()
    QTest.keyClicks(box, "abc")                       # nonsense: the value stays
    QTest.keyClick(box, Qt.Key.Key_Return)
    pump(qapp)
    assert sl.value() == 100 and box.text() == "100%"
    box.setFocus()
    box.selectAll()
    QTest.keyClicks(box, "12")
    QTest.keyClick(box, Qt.Key.Key_Escape)            # Esc cancels
    pump(qapp)
    assert sl.value() == 100 and box.text() == "100%"
    sl.s.setValue(40)                                 # dragging updates the box
    assert box.text() == "40%"
    sl.close()


def test_blur_is_a_material_choice(qapp, env):
    from freedictate.config import CHOICES
    assert "blur" in CHOICES["backdrop"]
    cfg = fresh_cfg(backdrop="blur")
    assert cfg["backdrop"] == "blur"
    win = open_window(qapp, cfg, env)
    try:
        assert win.backdrop_row.desc.text().startswith("Blur:")
        assert win.effective_backdrop() in ("blur", "solid")   # offscreen tests have no real HWND to blur
    finally:
        win.dispose()
        win.close()


def test_bar_material_offers_the_window_choices(qapp, env):
    from freedictate.config import CHOICES
    assert CHOICES["overlay_backdrop"] == CHOICES["backdrop"]
    assert fresh_cfg()["overlay_backdrop"] == "solid"


def test_bar_material_maps_to_what_windows_can_draw(qapp, env, monkeypatch):
    """A bar that never takes focus gets no system Mica or Acrylic (measured flat),
    so the bar paints its own material: frosted for Blur and Acrylic, tinted for Mica."""
    from freedictate.ui import overlay
    monkeypatch.setattr(native, "backdrop_supported", lambda: True)
    monkeypatch.setattr(native, "transparency_enabled", lambda: True)
    cfg = fresh_cfg()
    expected = {"solid": "solid", "mica": "tinted", "mica_alt": "tinted", "acrylic": "frosted", "blur": "frosted"}
    for choice, kind in expected.items():
        cfg["overlay_backdrop"] = choice
        assert overlay.bar_kind(cfg) == kind, choice
    monkeypatch.setattr(native, "transparency_enabled", lambda: False)
    cfg["overlay_backdrop"] = "blur"
    assert overlay.bar_kind(cfg) == "solid"


def test_transcribing_dots_sit_on_the_bar_midline(qapp, env):
    """The old "..." was text on the baseline and read low; the dots are shapes now."""
    from freedictate.ui.overlay import H, W, Overlay
    engine = FakeEngine()
    engine.recorder = SimpleNamespace(level=0.0, elapsed=lambda: 0.0)
    bar = Overlay(engine, fresh_cfg(overlay_timer=True, overlay_backdrop="solid"))
    try:
        bar.mode = "transcribing"
        img = bar.grab().toImage()
        base = img.pixelColor(W - 40, 2).getRgb()[:3]
        rows = [y for y in range(6, H - 6) for x in range(W - 27, W - 13)
                if sum(abs(a - b) for a, b in zip(img.pixelColor(x, y).getRgb()[:3], base)) > 60]
        assert rows, "the dots must be drawn"
        assert abs(sum(rows) / len(rows) - (H - 1) / 2) < 0.5
    finally:
        bar.deleteLater()
        pump(qapp)
