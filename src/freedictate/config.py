"""Settings: defaults, validation, migration from v1/v2 config.json, atomic save."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable

from . import paths
from .log import log

DEFAULTS: dict[str, Any] = {
    # dictation
    "hotkey": "ctrl+win",
    "hotkey_mode": "hold",          # hold | toggle | both
    "cancel_key": "esc",            # stops a take at any point: recording, or while it is written out
    "model": "small.en",
    "language": "en",               # ISO code, or "auto"
    "input_device": "",             # device name; "" is the system default
    "sounds": True,
    "sound_volume": 50,             # 0-100
    "max_seconds": 600,
    "auto_stop_silence": 0,         # seconds of silence that end a toggle take; 0 is off
    "vocabulary": "",               # names and jargon passed to Whisper as a prompt
    # output
    "output": "paste",              # paste | paste_shift_insert | type | clipboard
    "restore_clipboard": True,
    "trailing_space": True,
    "remove_fillers": True,
    "remove_repeats": True,
    "capitalize": True,
    "end_punctuation": True,
    "voice_commands": True,
    "replacements": [],             # [{"find": str, "replace": str}]
    "auto_submit": False,           # a take ending in "submit" is stripped and Enter is sent
    "ai_tidy": False,               # rewrite each take with a writing model (writer.py)
    "ai_model": "standard",         # light | standard (writer.CATALOG)
    # privacy while dictating (both apply on the next take)
    "mic_privacy_while_dictating": False,   # WASAPI exclusive capture: other apps lose the mic until the take ends
    "isolate_output_while_dictating": False,  # duck or mute every other app's audio until the take ends
    "isolate_output_level": 0,      # 0 mutes other sessions; 1-100 sets their volume to that percent
    # overlay
    "overlay": True,
    "overlay_position": "bottom",   # bottom | top
    "overlay_timer": True,
    "overlay_backdrop": "solid",    # mica_alt | mica | acrylic | blur | solid; the window's tint applies
    # look
    "theme": "Catppuccin Mocha",
    "accent_source": "theme",       # theme | windows
    "font": "Segoe UI Variable Text",
    "backdrop": "mica_alt",         # mica_alt | mica | acrylic | blur | solid
    "tint": 65,                     # 0-100, how much theme colour covers the backdrop
    "backdrop_when_inactive": False,
    "titlebar": "custom",           # custom | windows
    "reduce_motion": False,
    # system
    "run_elevated": False,
    "history_enabled": True,
    "history_days": 0,              # 0 keeps everything
    "check_updates": True,
    "update_prereleases": False,
    "skipped_version": "",
    "last_update_check": 0.0,
    # engine tuning
    "device": "auto",               # auto | cpu | cuda
    "compute_type": "auto",         # auto | int8 | int8_float16 | float16 | float32
    "cpu_threads": 6,               # 0 = every core; 6 keeps the rest of the machine free
    "beam_size": 5,
    "vad": True,
    "min_seconds": 0.4,
    "silence_peak": 0.004,
    "paste_delay_ms": 40,
    "idle_unload": True,            # unload models when not dictating, freeing VRAM/RAM
    "idle_seconds": 0,              # idle seconds before unloading (0 unloads right after each take)
    # bookkeeping
    "first_run_done": False,
    "window_geometry": "",
    "window_page": "dictation",
}

CHOICES: dict[str, tuple] = {
    "hotkey_mode": ("hold", "toggle", "both"),
    "output": ("paste", "paste_shift_insert", "type", "clipboard"),
    "overlay_position": ("bottom", "top"),
    "accent_source": ("theme", "windows"),
    "backdrop": ("mica_alt", "mica", "acrylic", "blur", "solid"),
    "ai_model": ("light", "standard"),
    "overlay_backdrop": ("mica_alt", "mica", "acrylic", "blur", "solid"),
    "titlebar": ("custom", "windows"),
    "device": ("auto", "cpu", "cuda"),
    "compute_type": ("auto", "int8", "int8_float16", "float16", "float32"),
}

RANGES: dict[str, tuple[float, float]] = {
    "sound_volume": (0, 100), "max_seconds": (10, 3600), "auto_stop_silence": (0, 30),
    "tint": (0, 100), "history_days": (0, 3650), "cpu_threads": (0, 64), "beam_size": (1, 10),
    "min_seconds": (0.1, 5), "silence_peak": (0.0, 0.2), "paste_delay_ms": (0, 1000),
    "idle_seconds": (0, 3600), "isolate_output_level": (0, 100),
}

_OLD_BACKDROP = {"Acrylic": "acrylic", "Frosted glass": "acrylic", "Mica": "mica",
                 "Mica Alt": "mica_alt", "Light acrylic": "mica", "Solid": "solid"}


def _coerce(key: str, value: Any) -> Any:
    default = DEFAULTS[key]
    if isinstance(default, bool):
        if isinstance(value, str):     # an imported "false" must not become True
            v = value.strip().lower()
            if v in ("true", "1", "yes", "on"):
                return True
            if v in ("false", "0", "no", "off", ""):
                return False
        return bool(value)
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        try:
            value = type(default)(value)
        except (TypeError, ValueError):
            return default
        if key in RANGES:
            lo, hi = RANGES[key]
            value = type(default)(min(max(value, lo), hi))
        return value
    if isinstance(default, str):
        value = str(value)
        if key in CHOICES and value not in CHOICES[key]:
            return default
        return value
    if isinstance(default, list):
        if key == "replacements" and isinstance(value, list):
            return [{"find": str(r.get("find", "")), "replace": str(r.get("replace", ""))}
                    for r in value if isinstance(r, dict) and str(r.get("find", "")).strip()]
        return list(default)
    return value


def _is_legacy(raw: dict) -> bool:
    return "beeps" in raw or "auto_paste" in raw or "paste_delay" in raw


def migrate_legacy(old: dict) -> dict:
    """Map a v1/v2 config.json onto v3 keys."""
    out: dict[str, Any] = {}
    for key in ("model", "language", "input_device", "hotkey", "remove_fillers", "overlay", "theme", "font"):
        if key in old:
            out[key] = old[key]
    if old.get("device") in ("cpu", "cuda", "auto"):
        out["device"] = old["device"]
    if old.get("compute_type") in ("auto", "int8", "int8_float16", "float16", "float32"):
        out["compute_type"] = old["compute_type"]
    if "beeps" in old:
        out["sounds"] = old["beeps"]
    if "auto_paste" in old:
        out["output"] = "paste" if old["auto_paste"] else "clipboard"
    if "backdrop" in old:
        out["backdrop"] = _OLD_BACKDROP.get(old["backdrop"], "mica_alt")
    if "min_seconds" in old:
        out["min_seconds"] = old["min_seconds"]
    if "silence_peak" in old:
        out["silence_peak"] = old["silence_peak"]
    if "paste_delay" in old:
        try:
            out["paste_delay_ms"] = round(float(old["paste_delay"]) * 1000)
        except (TypeError, ValueError):
            pass
    if "hotkey" in out:
        out["hotkey"] = {"right-ctrl": "rctrl", "right-alt": "ralt"}.get(out["hotkey"], out["hotkey"])
    out["first_run_done"] = True
    return out


class Config:
    """Thread-safe settings with change listeners. Saves on every change."""

    def __init__(self, path: Path | None = None):
        self.path = path or paths.SETTINGS
        self._lock = threading.RLock()
        self._data = dict(DEFAULTS)
        self._listeners: list[Callable[[set[str]], None]] = []
        self.load()

    def load(self) -> None:
        raw: dict = {}
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("settings file is not a JSON object")
                if _is_legacy(raw):
                    raw = migrate_legacy(raw)   # v1/v2 settings keep their meaning
                if "idle_seconds" not in raw and "idle_minutes" in raw:
                    # 3.3 kept minutes; 3.4 speaks seconds, where 0 unloads
                    # right after each take. Keep what the user chose.
                    try:
                        raw["idle_seconds"] = int(float(raw["idle_minutes"]) * 60)
                    except (TypeError, ValueError):
                        pass
            except (OSError, ValueError) as e:
                log.warning("Settings unreadable (%s); keeping a copy and using defaults.", e)
                try:
                    self.path.replace(self.path.with_suffix(".broken.json"))
                except OSError:
                    pass
                raw = {}
        with self._lock:
            self._data = dict(DEFAULTS)
            for k, v in raw.items():
                if k in DEFAULTS:
                    self._data[k] = _coerce(k, v)
            # 3.5.0 made a 6-core cap the default. Anyone who never chose the
            # old "0 = every core" setting gets the cap once; turning the new
            # switch off afterwards is remembered for good.
            if raw and self._data["cpu_threads"] == 0 and "cpu_threads_350_migrated" not in raw:
                self._data["cpu_threads"] = 6
                self._data["cpu_threads_350_migrated"] = True

    def save(self) -> None:
        with self._lock:
            text = json.dumps(self._data, indent=2, ensure_ascii=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A unique temp name: two threads saving at once must not clobber
        # each other's file, and an antivirus lock on the target must not
        # leave junk behind.
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def snapshot(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def update(self, values: dict[str, Any], save: bool = True) -> set[str]:
        changed: set[str] = set()
        with self._lock:
            for k, v in values.items():
                if k not in DEFAULTS:
                    continue
                v = _coerce(k, v)
                if self._data.get(k) != v:
                    self._data[k] = v
                    changed.add(k)
        if changed:
            if save:
                try:
                    self.save()
                except OSError:
                    # A locked or read-only settings file must not stop the
                    # change from taking effect for this session.
                    log.exception("Settings could not be saved to %s", self.path)
        for fn in list(self._listeners):
            try:
                fn(changed)
            except Exception:
                log.exception("Settings listener failed")
        return changed

    def __setitem__(self, key: str, value: Any) -> None:
        self.update({key: value})

    def reset(self, keep: tuple[str, ...] = ("first_run_done", "window_geometry")) -> None:
        values = {k: v for k, v in DEFAULTS.items() if k not in keep}
        self.update(values)

    def on_change(self, fn: Callable[[set[str]], None]) -> None:
        self._listeners.append(fn)

    def export_to(self, target: Path) -> None:
        data = self.snapshot()
        for k in ("window_geometry", "last_update_check", "first_run_done"):
            data.pop(k, None)
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def import_from(self, source: Path) -> set[str]:
        raw = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Not a FreeDictate settings file.")
        if _is_legacy(raw):
            raw = migrate_legacy(raw)
        return self.update({k: v for k, v in raw.items() if k in DEFAULTS})
