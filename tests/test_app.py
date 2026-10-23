"""App wiring that the first tray click depends on. No tray, engine or window is created."""
from types import SimpleNamespace

from freedictate import system
from freedictate.app import App


def test_startup_state_asks_windows_about_the_task_once(monkeypatch):
    """Each schtasks query takes about 0.5 s (measured 2026-10-24), and opening
    Settings asked twice."""
    calls = []
    monkeypatch.setattr(system, "run_key_enabled", lambda: False)
    monkeypatch.setattr(system, "task_enabled", lambda: calls.append(1) or True)
    assert App.autostart_state(SimpleNamespace()) == (True, True)
    assert len(calls) == 1


def test_settings_are_built_ahead_of_the_first_click():
    """Building the window took about 2 s inside the running app, so the first
    tray click after every start waited for it. It is built hidden at idle."""
    built = []
    app = SimpleNamespace(settings_window=None, _make_settings=lambda: built.append(1))
    App._prebuild_settings(app)
    assert built == [1]
    app.settings_window = object()
    App._prebuild_settings(app)
    assert built == [1]
