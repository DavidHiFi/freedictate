"""Paste order with "submit": no keys are sent, every Windows call is faked."""
from types import SimpleNamespace

from freedictate import output


def test_submit_presses_enter_before_the_old_clipboard_comes_back(monkeypatch):
    """Enter used to follow the clipboard restore, 0.45 s after the paste. An
    app that read the clipboard late pasted the old contents, and Enter sent
    them."""
    order = []
    monkeypatch.setattr(output, "wait_for_modifiers_release", lambda: None)
    monkeypatch.setattr(output, "target_blocks_input", lambda: False)
    monkeypatch.setattr(output, "save_clipboard", lambda: "old")
    monkeypatch.setattr(output, "set_clipboard", lambda text, transient=False: True)
    monkeypatch.setattr(output, "_chord", lambda *a, **k: order.append("paste"))
    monkeypatch.setattr(output, "press_enter", lambda: order.append("enter"))
    monkeypatch.setattr(output, "restore_clipboard", lambda saved: order.append("restore"))
    monkeypatch.setattr(output, "user32", SimpleNamespace(GetClipboardSequenceNumber=lambda: 7))
    monkeypatch.setattr(output.time, "sleep", lambda s: None)
    assert output.deliver("hello", "paste", True, 0, submit=True) == "pasted"
    assert order == ["paste", "enter", "restore"]
