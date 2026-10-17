import json

from freedictate.config import DEFAULTS, Config, migrate_legacy


def test_defaults_and_coercion(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"tint": 500, "backdrop": "rainbow", "sounds": 0, "beam_size": "3",
                             "unknown": 1, "replacements": [{"find": " x ", "replace": "y"}, {"find": ""}]}))
    c = Config(p)
    assert c["tint"] == 100
    assert c["backdrop"] == DEFAULTS["backdrop"]
    assert c["sounds"] is False
    assert c["beam_size"] == 3
    assert c["replacements"] == [{"find": " x ", "replace": "y"}]
    assert c.get("unknown") is None


def test_update_saves_and_notifies(tmp_path):
    p = tmp_path / "settings.json"
    c = Config(p)
    seen = []
    c.on_change(seen.append)
    assert c.update({"theme": "Nord", "tint": 65}) == {"theme"}  # tint was already 65
    assert seen == [{"theme"}]
    assert json.loads(p.read_text())["theme"] == "Nord"


def test_broken_file_is_kept_aside(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{not json")
    c = Config(p)
    assert c["theme"] == DEFAULTS["theme"]
    assert (tmp_path / "settings.broken.json").exists()


def test_legacy_migration():
    old = {"model": "large-v3-turbo", "beeps": False, "auto_paste": False, "backdrop": "Acrylic",
           "hotkey": "right-ctrl", "font": "FiraCode Nerd Font", "paste_delay": 0.15}
    m = migrate_legacy(old)
    assert m == {"model": "large-v3-turbo", "hotkey": "rctrl", "font": "FiraCode Nerd Font", "sounds": False,
                 "output": "clipboard", "backdrop": "acrylic", "paste_delay_ms": 150, "first_run_done": True}


def test_non_object_settings_file_is_quarantined(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("[1, 2, 3]")
    c = Config(p)
    assert c["theme"] == DEFAULTS["theme"]
    assert (tmp_path / "settings.broken.json").exists()


def test_legacy_settings_file_migrates_on_load(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"beeps": False, "auto_paste": False, "paste_delay": 0.3}))
    c = Config(p)
    assert c["sounds"] is False
    assert c["output"] == "clipboard"
    assert c["paste_delay_ms"] == 300


def test_existing_zero_thread_setting_gets_the_3_5_0_cap_once(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"cpu_threads": 0}))
    c = Config(p)
    assert c["cpu_threads"] == 6   # the cap applies once, even for an existing 0
    c.update({"cpu_threads": 0})   # turning it off afterwards is remembered
    assert Config(p)["cpu_threads"] == 0
    p.write_text(json.dumps({"cpu_threads": 9}))   # an explicit value is kept as-is
    assert Config(p)["cpu_threads"] == 9


def test_export_import_roundtrip(tmp_path):
    a = Config(tmp_path / "a.json")
    a.update({"theme": "Dracula", "hotkey": "rctrl"})
    a.export_to(tmp_path / "export.json")
    b = Config(tmp_path / "b.json")
    assert b.import_from(tmp_path / "export.json") == {"theme", "hotkey"}
    assert b["theme"] == "Dracula"


def test_export_import_restores_every_exported_setting(tmp_path):
    a = Config(tmp_path / "a.json")
    a.update({"theme": "Dracula", "hotkey": "rctrl", "cpu_threads": 9, "beam_size": 7, "tint": 40,
              "replacements": [{"find": "teh", "replace": "the"}]})
    a.export_to(tmp_path / "export.json")
    exported = json.loads((tmp_path / "export.json").read_text(encoding="utf-8"))
    assert "window_geometry" not in exported and "first_run_done" not in exported
    b = Config(tmp_path / "b.json")
    b.import_from(tmp_path / "export.json")
    for key, value in exported.items():
        if key in DEFAULTS:
            assert b[key] == value, key
