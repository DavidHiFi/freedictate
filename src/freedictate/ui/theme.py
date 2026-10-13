"""Palettes and the app stylesheet.

Each palette defines roles, not raw colours for widgets: bg (window), surface
(cards), field (inputs), hover, press, line (dividers and borders), text, sub
(secondary text), accent, on_accent, warn, danger, ok, and dark (whether
Windows draws dark chrome). Widgets read roles from ``current()``.
"""
from __future__ import annotations

import winreg
from dataclasses import dataclass, replace

from PySide6.QtGui import QColor, QFont, QFontDatabase


@dataclass(frozen=True)
class Palette:
    name: str
    dark: bool
    bg: str
    surface: str
    field: str
    hover: str
    press: str
    line: str
    text: str
    sub: str
    accent: str
    on_accent: str
    warn: str
    danger: str
    ok: str


PALETTES: dict[str, Palette] = {p.name: p for p in [
    # Base window, Mantle cards, Crust fields; Surface0/1 only for hover, press and
    # hairlines. Surface0 cards read grey against Base (same fix as WinLaunch 2.3.0).
    Palette("Catppuccin Mocha", True, "#1e1e2e", "#181825", "#11111b", "#313244", "#45475a", "#313244",
            "#cdd6f4", "#bac2de", "#89b4fa", "#11111b", "#f9e2af", "#f38ba8", "#a6e3a1"),
    Palette("Catppuccin Macchiato", True, "#24273a", "#363a4f", "#494d64", "#5b6078", "#6e738d", "#494d64",
            "#cad3f5", "#a5adcb", "#8aadf4", "#181926", "#eed49f", "#ed8796", "#a6da95"),
    Palette("Catppuccin Frappe", True, "#303446", "#414559", "#51576d", "#626880", "#737994", "#51576d",
            "#c6d0f5", "#a5adce", "#8caaee", "#232634", "#e5c890", "#e78284", "#a6d189"),
    Palette("Catppuccin Latte", False, "#eff1f5", "#e6e9ef", "#ccd0da", "#bcc0cc", "#acb0be", "#ccd0da",
            "#4c4f69", "#5c5f77", "#1e66f5", "#ffffff", "#df8e1d", "#d20f39", "#40a02b"),
    Palette("Tokyo Night", True, "#1a1b26", "#24283b", "#2f3549", "#3b4261", "#545c7e", "#3b4261",
            "#c0caf5", "#a9b1d6", "#7aa2f7", "#16161e", "#e0af68", "#f7768e", "#9ece6a"),
    Palette("Nord", True, "#2e3440", "#3b4252", "#434c5e", "#4c566a", "#616e88", "#4c566a",
            "#eceff4", "#d8dee9", "#88c0d0", "#2e3440", "#ebcb8b", "#bf616a", "#a3be8c"),
    Palette("Rose Pine", True, "#191724", "#1f1d2e", "#26233a", "#403d52", "#524f67", "#403d52",
            "#e0def4", "#908caa", "#c4a7e7", "#191724", "#f6c177", "#eb6f92", "#9ccfd8"),
    Palette("Dracula", True, "#282a36", "#343746", "#414458", "#4d5066", "#6272a4", "#44475a",
            "#f8f8f2", "#bfc3d9", "#bd93f9", "#1e1f29", "#f1fa8c", "#ff5555", "#50fa7b"),
    Palette("Graphite", True, "#1c1c1c", "#2b2b2b", "#363636", "#404040", "#4d4d4d", "#3a3a3a",
            "#f3f3f3", "#c5c5c5", "#60cdff", "#000000", "#fce100", "#ff99a4", "#6ccb5f"),
    Palette("Paper", False, "#f3f3f3", "#fbfbfb", "#ffffff", "#ebebeb", "#dedede", "#e0e0e0",
            "#1b1b1b", "#5d5d5d", "#005fb8", "#ffffff", "#9d5d00", "#c42b1c", "#0f7b0f"),
]}
SYSTEM = "Match Windows"
DEFAULT_THEME = "Catppuccin Mocha"
THEME_NAMES = [SYSTEM, *PALETTES]

FONT_FALLBACKS = ("Segoe UI Variable Text", "Segoe UI")

_current: Palette = PALETTES[DEFAULT_THEME]
_font_family = "Segoe UI"


def windows_dark() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return True


def windows_accent() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as k:
            v = winreg.QueryValueEx(k, "AccentColor")[0]  # 0xAABBGGRR
        return f"#{v & 0xff:02x}{(v >> 8) & 0xff:02x}{(v >> 16) & 0xff:02x}"
    except OSError:
        return None


def resolve(name: str) -> Palette:
    if name == SYSTEM:
        return PALETTES["Graphite"] if windows_dark() else PALETTES["Paper"]
    return PALETTES.get(name, PALETTES[DEFAULT_THEME])


def set_current(name: str, font: str) -> Palette:
    global _current, _font_family
    _current = resolve(name)
    families = set(QFontDatabase.families())
    _font_family = next((f for f in (font, *FONT_FALLBACKS) if f in families), "Segoe UI")
    return _current


def current() -> Palette:
    return _current


def font_family() -> str:
    return _font_family


def font(size: float = 10.5, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(_font_family)
    f.setPointSizeF(size)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def qc(hex_color: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(alpha)
    return c


def mix(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t), round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha:.3f})"


def stylesheet(p: Palette, translucent: bool) -> str:
    """Qt stylesheet for every standard widget. Surfaces are slightly
    see-through when a backdrop is on, so the material reads through cards."""
    a = 0.55 if translucent else 1.0
    surface = rgba(p.surface, a)
    field = rgba(p.field, 0.75 if translucent else 1.0)
    hover = rgba(p.hover, 0.8 if translucent else 1.0)
    fam = _font_family
    return f"""
* {{ font-family: "{fam}"; font-size: 10.5pt; color: {p.text}; outline: 0; }}
QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 20pt; font-weight: 600; }}
QLabel[role="section"] {{ font-size: 11pt; font-weight: 600; padding-top: 6px; }}
QLabel[role="name"] {{ font-size: 14pt; font-weight: 600; }}
QLabel[role="rowtitle"] {{ font-size: 10.5pt; }}
QLabel[role="sub"] {{ color: {p.sub}; font-size: 9.5pt; }}
QLabel[role="warn"] {{ color: {p.warn}; font-size: 9.5pt; }}
QLabel[role="danger"] {{ color: {p.danger}; font-size: 9.5pt; }}
QLabel[role="value"] {{ color: {p.sub}; }}
QLabel a {{ color: {p.accent}; }}
QLabel:disabled, QLabel[role="rowtitle"]:disabled, QLabel[role="sub"]:disabled, QLabel[role="value"]:disabled {{
    color: {rgba(p.text, 0.4)}; }}

QFrame#card {{ background: {surface}; border-radius: 8px; }}
QFrame#divider {{ background: {rgba(p.line, 0.6)}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#banner {{ background: {rgba(p.accent, 0.16)}; border: 1px solid {rgba(p.accent, 0.45)}; border-radius: 8px; }}
QFrame#bannerWarn {{ background: {rgba(p.warn, 0.14)}; border: 1px solid {rgba(p.warn, 0.45)}; border-radius: 8px; }}

QPushButton {{ background: {field}; border: 1px solid {rgba(p.line, 0.9)}; border-radius: 6px;
              padding: 6px 14px; min-height: 20px; }}
QPushButton:hover {{ background: {hover}; }}
QPushButton:pressed {{ background: {rgba(p.press, 0.9)}; }}
QPushButton:disabled {{ color: {rgba(p.text, 0.4)}; background: {rgba(p.field, 0.4)}; }}
QPushButton:focus[kbd="true"] {{ border: 1px solid {p.accent}; }}
QPushButton[kind="primary"] {{ background: {p.accent}; color: {p.on_accent}; border: 1px solid {p.accent}; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: {mix(p.accent, p.text, 0.18)}; }}
QPushButton[kind="primary"]:pressed {{ background: {mix(p.accent, p.bg, 0.2)}; }}
QPushButton[kind="primary"]:disabled {{ background: {rgba(p.accent, 0.35)}; color: {rgba(p.on_accent, 0.6)}; }}
QPushButton[kind="danger"]:hover {{ background: {rgba(p.danger, 0.22)}; border-color: {p.danger}; }}
QPushButton[kind="flat"] {{ background: transparent; border: 1px solid transparent; padding: 6px 8px; }}
QPushButton[kind="flat"]:hover {{ background: {rgba(p.hover, 0.6)}; }}
QPushButton[kind="link"] {{ background: transparent; border: none; color: {p.accent}; padding: 2px 0; text-align: left; }}
QPushButton[kind="link"]:hover {{ text-decoration: underline; }}
QPushButton[kind="segment"] {{ border-radius: 0; padding: 6px 12px; margin: 0; }}
QPushButton[kind="segment"][first="true"] {{ border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
QPushButton[kind="segment"][last="true"] {{ border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
QPushButton[kind="segment"]:checked {{ background: {p.accent}; color: {p.on_accent}; border-color: {p.accent}; }}

QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {field}; border: 1px solid {rgba(p.line, 0.9)}; border-bottom: 1px solid {rgba(p.sub, 0.6)};
    border-radius: 6px; padding: 5px 9px; selection-background-color: {p.accent}; selection-color: {p.on_accent}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-bottom: 2px solid {p.accent}; }}
QLineEdit#valueBox {{ border: 1px solid transparent; border-bottom: 1px solid transparent; background: {rgba(p.field, 0.55)};
    padding: 3px 8px; color: {p.sub}; }}
QLineEdit#valueBox:hover {{ background: {hover}; color: {p.text}; }}
QLineEdit#valueBox:focus {{ background: {field}; color: {p.text}; border-bottom: 2px solid {p.accent}; }}
QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled {{ color: {rgba(p.text, 0.4)}; background: {rgba(p.field, 0.4)}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}

QComboBox {{ background: {field}; border: 1px solid {rgba(p.line, 0.9)}; border-radius: 6px; padding: 5px 30px 5px 10px; min-height: 20px; }}
QComboBox:hover {{ background: {hover}; }}
QComboBox:disabled {{ color: {rgba(p.text, 0.4)}; background: {rgba(p.field, 0.4)}; }}
QComboBox:focus[kbd="true"] {{ border: 1px solid {p.accent}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url(:/fd/chevron-down.svg); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {rgba(p.surface, 0.55 if translucent else 0.98)}; border: none;
    padding: 4px; selection-background-color: {rgba(p.accent, 0.25)}; selection-color: {p.text}; }}
QComboBoxPrivateContainer {{ background: transparent; border: none; }}
QComboBox QAbstractItemView::item {{ min-height: 30px; padding: 0 8px; border-radius: 4px; }}
QComboBox QAbstractItemView::item:hover {{ background: {rgba(p.hover, 0.7)}; }}

/* The handle is 12px + a 4px ring = 20px tall; without a matching widget
   height Qt sizes the slider to 15px and clips the ring at top and bottom. */
QSlider:horizontal {{ min-height: 20px; }}
QSlider::groove:horizontal {{ height: 4px; background: {rgba(p.line, 1.0)}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {p.accent}; border: 4px solid {mix(p.surface, p.bg, 0.3)}; width: 12px; height: 12px;
    margin: -8px 0; border-radius: 10px; }}
QSlider::handle:horizontal:hover {{ border-width: 3px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {rgba(p.sub, 0.35)}; border-radius: 3px; min-height: 30px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: {rgba(p.sub, 0.6)}; margin: 0; }}
QScrollBar:vertical:disabled, QScrollBar::handle:vertical:disabled {{ background: transparent; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
QScrollBar:horizontal {{ height: 0; }}

QListView, QTableWidget {{ background: transparent; border: none; }}
QTableWidget {{ gridline-color: transparent; }}
QHeaderView::section {{ background: transparent; border: none; color: {p.sub}; padding: 4px 6px; font-size: 9.5pt; }}

QMenu {{ background: {rgba(p.surface, 0.55 if translucent else 0.98)}; border: none; padding: 4px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {rgba(p.hover, 0.85)}; }}
QMenu::item:disabled {{ color: {p.sub}; }}
QMenu::separator {{ height: 1px; background: {rgba(p.line, 0.8)}; margin: 4px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}

QToolTip {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line}; border-radius: 6px; padding: 5px 8px; }}
QProgressBar {{ background: {rgba(p.line, 0.9)}; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 2px; }}
"""


def override_accent(accent: str | None) -> Palette:
    """Swap the current palette's accent (e.g. for the Windows accent colour)."""
    global _current
    if accent:
        c = QColor(accent)
        lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
        _current = replace(_current, accent=accent, on_accent="#000000" if lum > 0.45 else "#ffffff")
    return _current
