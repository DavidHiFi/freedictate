"""Line icons drawn from inline SVG, coloured per theme, plus the app icon."""
from __future__ import annotations

import struct
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .. import paths

# 24x24 viewBox, stroke icons. {c} is the colour.
_SVG = {
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9.5 9.5h5v5h-5zM9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5"/>',
    "text": '<path d="M4 6h16M4 10h10M4 14h16M4 18h10"/>',
    "palette": '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.7-.8 1.7-1.7 0-.5-.2-.9-.5-1.2a1.6 1.6 0 0 1 1.2-2.7H16a5 5 0 0 0 5-5c0-4.1-4-7.4-9-7.4z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7" r="1"/><circle cx="14.5" cy="7" r="1"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "sliders": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    "home": '<path d="M4 11l8-6 8 6v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "download": '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
    "refresh": '<path d="M20 12a8 8 0 0 1-14.3 5M4 12a8 8 0 0 1 14.3-5M18 3v4h-4M6 21v-4h4"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "pause": '<path d="M9 5v14M15 5v14"/>',
    "play": '<path d="M7 5l12 7-12 7z"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "minimize": '<path d="M5 12h14"/>',
    "maximize": '<rect x="5" y="5" width="14" height="14" rx="1.5"/>',
    "restore": '<rect x="5" y="8" width="11" height="11" rx="1.5"/><path d="M8 5h9.5A1.5 1.5 0 0 1 19 6.5V16"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "gpu": '<rect x="2.5" y="7" width="19" height="10" rx="2"/><circle cx="9" cy="12" r="2.5"/><path d="M15 10.5h3M15 13.5h3M6 17v2.5M10 17v2.5"/>',
}


def _svg(name: str, color: str, width: float = 1.6) -> bytes:
    body = _SVG[name]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


@lru_cache(maxsize=512)
def pixmap(name: str, color: str, size: int, dpr: float = 1.0) -> QPixmap:
    px = int(size * dpr)
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    r = QSvgRenderer(QByteArray(_svg(name, color)))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str, size: int = 16) -> QIcon:
    ic = QIcon()
    for dpr in (1.0, 1.25, 1.5, 2.0):
        ic.addPixmap(pixmap(name, color, size, dpr))
    return ic


def svg_file(name: str, color: str) -> str:
    """Write the icon to the cache and return a stylesheet-friendly path."""
    d = paths.LOGS.parent / "cache"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{name}-{color.lstrip('#')}.svg"
    if not f.exists():
        f.write_bytes(_svg(name, color, 2.0))
    return f.as_posix()


# ------------------------------------------------------------------ app icon

STATE_COLORS = {"ready": "#89b4fa", "listening": "#f38ba8", "transcribing": "#f9e2af",
                "loading": "#7f849c", "paused": "#7f849c", "error": "#f38ba8"}


def app_image(size: int, fill: str = "#89b4fa", ink: str = "#11111b", slash: bool = False,
              ring: str | None = None) -> QImage:
    """The FreeDictate mark: a microphone on a filled circle."""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256.0
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(fill))
    p.drawEllipse(QRectF(8 * s, 8 * s, 240 * s, 240 * s))
    if ring:
        p.setPen(QPen(QColor(ring), 14 * s))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(15 * s, 15 * s, 226 * s, 226 * s))
        p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(ink))
    p.drawRoundedRect(QRectF(98 * s, 46 * s, 60 * s, 108 * s), 30 * s, 30 * s)
    pen = QPen(QColor(ink), 15 * s)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(72 * s, 118 * s)
    path.cubicTo(72 * s, 196 * s, 184 * s, 196 * s, 184 * s, 118 * s)
    p.drawPath(path)
    p.drawLine(QPointF(128 * s, 178 * s), QPointF(128 * s, 206 * s))
    p.drawLine(QPointF(100 * s, 208 * s), QPointF(156 * s, 208 * s))
    if slash:
        pen = QPen(QColor(ink), 18 * s)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(62 * s, 62 * s), QPointF(194 * s, 194 * s))
    p.end()
    return img


def app_icon(state: str = "ready") -> QIcon:
    fill = STATE_COLORS.get(state, STATE_COLORS["ready"])
    ic = QIcon()
    for sz in (16, 20, 24, 32, 40, 48, 64, 256):
        ic.addPixmap(QPixmap.fromImage(app_image(sz, fill, slash=state in ("paused", "error"))))
    return ic


def write_ico(target: Path) -> None:
    """Multi-size .ico for the exe and installer. Qt only writes single-image
    .ico files, so the PNG-compressed entries are packed by hand."""
    target.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for sz in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        app_image(sz).save(buf, "PNG")
        images.append((sz, bytes(buf.data())))
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for sz, data in images:
        entries += struct.pack("<BBBBHHII", sz % 256, sz % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    target.write_bytes(header + entries + blobs)
