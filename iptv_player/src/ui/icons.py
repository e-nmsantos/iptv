"""Monochrome line icons drawn from inline SVG and tinted to the theme.

Emoji glyphs render differently on every platform/font and can't follow the
palette, so toolbar and player controls use these instead. Every icon is a
24×24 stroke drawing using ``currentColor``; ``icon()`` recolours it.
"""

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import Palette

_STROKE = (
    'fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round"'
)

_PATHS: dict[str, str] = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h5v-6h4v6h5V9.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8"/><path d="M4 3v5h5"/>'
               '<path d="M4 13a8 8 0 0 0 14.5 4.5L20 16"/><path d="M20 21v-5h-5"/>',
    "guide": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M9 9v11M15 9v11"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "settings": '<circle cx="12" cy="12" r="3"/>'
                '<path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3'
                'M4.9 19.1 7 17M17 7l2.1-2.1"/>',
    "play": '<path d="M7 4.5v15l12-7.5z" fill="currentColor"/>',
    "pause": '<path d="M7 4h3.5v16H7zM13.5 4H17v16h-3.5z" fill="currentColor"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor"/>',
    "previous": '<path d="M18 5v14L8 12z" fill="currentColor"/><path d="M6 5v14"/>',
    "next": '<path d="M6 5v14l10-7z" fill="currentColor"/><path d="M18 5v14"/>',
    "rewind": '<path d="M11 6v12l-8-6zM21 6v12l-8-6z" fill="currentColor"/>',
    "forward": '<path d="M3 6v12l8-6zM13 6v12l8-6z" fill="currentColor"/>',
    "volume": '<path d="M4 9v6h4l5 4V5L8 9z" fill="currentColor"/><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/>',
    "audio": '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    "subtitles": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 12h4M13 12h4M7 15.5h7"/>',
    "more": '<circle cx="5" cy="12" r="1.6" fill="currentColor"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/>'
            '<circle cx="19" cy="12" r="1.6" fill="currentColor"/>',
    "fullscreen": '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
    "record": '<circle cx="12" cy="12" r="6" fill="currentColor"/>',
    "live": '<circle cx="12" cy="12" r="3" fill="currentColor"/><path d="M7.5 7.5a6.4 6.4 0 0 0 0 9M16.5 7.5a6.4 6.4 0 0 1 0 9"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "cast": '<path d="M3 8V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-6"/>'
            '<path d="M3 12a8 8 0 0 1 8 8M3 16a4 4 0 0 1 4 4"/><circle cx="3.5" cy="20" r="0.8" fill="currentColor"/>',
}


def svg_markup(name: str, color: str) -> bytes:
    body = _PATHS[name]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {_STROKE} color="{color}">'
        f"{body}</svg>"
    ).replace("currentColor", color).encode("utf-8")


def _render(name: str, color: str, size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_markup(name, color)))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


@lru_cache(maxsize=128)
def icon(name: str, color: str = Palette.TEXT_PRIMARY, active_color: str = "") -> QIcon:
    """Theme-tinted icon; ``active_color`` is used for the checked/hover state."""
    result = QIcon()
    for size in (16, 20, 24, 32, 48):
        result.addPixmap(_render(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
        result.addPixmap(_render(name, Palette.TEXT_MUTED, size), QIcon.Mode.Disabled, QIcon.State.Off)
        if active_color:
            result.addPixmap(_render(name, active_color, size), QIcon.Mode.Normal, QIcon.State.On)
            result.addPixmap(_render(name, active_color, size), QIcon.Mode.Active, QIcon.State.Off)
    return result


ICON_SIZE = QSize(18, 18)

APP_ICON_PATH = Path(__file__).resolve().parent / "assets" / "app_icon.svg"


def app_icon() -> QIcon:
    """The application logo (window, taskbar and tray)."""
    if APP_ICON_PATH.exists():
        return QIcon(str(APP_ICON_PATH))
    return QIcon()
