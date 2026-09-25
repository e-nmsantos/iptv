"""Card-style item delegate for channel/VOD/series/episode grids."""

import hashlib
from typing import Callable, Optional

from PySide6.QtCore import QModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..core.image_loader import get_image_loader
from .theme import Palette

IMAGE_URL_ROLE = Qt.ItemDataRole.UserRole + 1

_MONOGRAM_COLORS = [
    "#8e44ad", "#2980b9", "#16a085", "#c0392b", "#d35400",
    "#2c3e50", "#27ae60", "#7f8c8d", "#e67e22", "#2471a3",
]


class PosterCardDelegate(QStyledItemDelegate):
    """Paints a rounded poster/logo card with title + optional badges.

    Generic over the item's underlying payload: `favorite_fn`, `live_fn` and
    `progress_fn` are given the QModelIndex and may return None/False when
    not applicable (e.g. episode items have no favorite state).
    """

    def __init__(
        self,
        parent=None,
        *,
        card_size: Optional[QSize] = None,
        poster_ratio: float = 0.62,
        favorite_fn: Optional[Callable[[QModelIndex], bool]] = None,
        live_fn: Optional[Callable[[QModelIndex], bool]] = None,
        progress_fn: Optional[Callable[[QModelIndex], Optional[float]]] = None,
        playing_fn: Optional[Callable[[QModelIndex], bool]] = None,
    ):
        super().__init__(parent)
        self._card_size = card_size or QSize(160, 130)
        self._poster_ratio = poster_ratio
        self._favorite_fn = favorite_fn
        self._live_fn = live_fn
        self._progress_fn = progress_fn
        self._playing_fn = playing_fn

        # Built once (not per paint() call) since font construction/metrics
        # aren't free and paint() runs for every visible card on every
        # repaint (scroll, hover, image-load) — this was a real source of
        # sluggishness with a full page of cards on screen.
        self._monogram_font = QFont()
        self._monogram_font.setPointSize(20)
        self._monogram_font.setBold(True)
        self._title_font = QFont()
        self._title_font.setPointSize(9)
        self._badge_font = QFont()
        self._badge_font.setPointSize(7)
        self._badge_font.setBold(True)
        self._star_font = QFont()
        self._star_font.setPointSize(9)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return self._card_size

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        card_rect = QRectF(option.rect).adjusted(4, 4, -4, -4)
        radius = Palette.RADIUS_CARD
        path = QPainterPath()
        path.addRoundedRect(card_rect, radius, radius)
        painter.setClipPath(path)

        is_playing = bool(self._playing_fn and self._playing_fn(index))
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hover = bool(option.state & QStyle.StateFlag.State_MouseOver)

        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        image_url = index.data(IMAGE_URL_ROLE) or ""

        poster_h = card_rect.height() * self._poster_ratio
        poster_rect = QRectF(card_rect.left(), card_rect.top(), card_rect.width(), poster_h)

        pixmap = None
        if image_url:
            size = QSize(int(poster_rect.width() * 2), int(poster_rect.height() * 2))
            pixmap = get_image_loader().load(image_url, size)

        if pixmap is not None and not pixmap.isNull():
            pw, ph = pixmap.width(), pixmap.height()
            rw, rh = poster_rect.width(), poster_rect.height()
            if pw > 0 and ph > 0 and rw > 0 and rh > 0:
                scale = max(rw / pw, rh / ph)
                sw = rw / scale
                sh = rh / scale
                sx = (pw - sw) / 2
                sy = (ph - sh) / 2
                painter.drawPixmap(poster_rect, pixmap, QRectF(sx, sy, sw, sh))
            else:
                painter.drawPixmap(poster_rect.toRect(), pixmap)
        else:
            painter.fillRect(poster_rect, QColor(_monogram_color(title)))
            painter.setPen(QColor(Palette.TEXT_ON_ACCENT))
            painter.setFont(self._monogram_font)
            painter.drawText(poster_rect, Qt.AlignmentFlag.AlignCenter, _monogram(title))

        # Body (below poster) background.
        body_rect = QRectF(
            card_rect.left(), poster_rect.bottom(), card_rect.width(),
            card_rect.height() - poster_h,
        )
        body_color = QColor(Palette.BG_CARD_HOVER if (is_selected or is_hover or is_playing) else Palette.BG_CARD)
        painter.fillRect(body_rect, body_color)

        # Title legibility gradient over the bottom of the poster.
        gradient = QLinearGradient(poster_rect.topLeft(), poster_rect.bottomLeft())
        gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 140))
        painter.fillRect(poster_rect, QBrush(gradient))

        # Badges.
        if is_playing:
            _draw_badge(painter, poster_rect, "▶ A REPRODUZIR", Palette.SUCCESS_GREEN, self._badge_font, left=True)
        elif self._live_fn and self._live_fn(index):
            _draw_badge(painter, poster_rect, "AO VIVO", Palette.LIVE_BADGE, self._badge_font, left=True)
        if self._favorite_fn and self._favorite_fn(index):
            _draw_star(painter, poster_rect, self._star_font)

        progress = self._progress_fn(index) if self._progress_fn else None
        if progress is not None and progress > 0:
            _draw_progress_bar(painter, poster_rect, progress)

        # Title text in the body.
        painter.setPen(QColor(Palette.TEXT_PRIMARY))
        painter.setFont(self._title_font)
        text_rect = body_rect.adjusted(6, 2, -6, -2)
        metrics = painter.fontMetrics()
        elided = metrics.elidedText(title, Qt.TextElideMode.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

        if is_playing:
            pen = QPen(QColor(Palette.SUCCESS_GREEN))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(card_rect.adjusted(1, 1, -1, -1), radius, radius)
        elif is_selected:
            pen = QPen(QColor(Palette.ACCENT))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(card_rect.adjusted(1, 1, -1, -1), radius, radius)

        painter.restore()


class ChannelRowDelegate(QStyledItemDelegate):
    """Paints a compact single-line row (thumbnail + title + badges).

    Alternative to `PosterCardDelegate` for a dense "list view" of the same
    channel/VOD/series items, analogous to how categories are shown as a
    plain list rather than a grid.
    """

    def __init__(
        self,
        parent=None,
        *,
        row_height: int = 44,
        favorite_fn: Optional[Callable[[QModelIndex], bool]] = None,
        live_fn: Optional[Callable[[QModelIndex], bool]] = None,
        progress_fn: Optional[Callable[[QModelIndex], Optional[float]]] = None,
        playing_fn: Optional[Callable[[QModelIndex], bool]] = None,
    ):
        super().__init__(parent)
        self._row_height = row_height
        self._favorite_fn = favorite_fn
        self._live_fn = live_fn
        self._progress_fn = progress_fn
        self._playing_fn = playing_fn

        self._title_font = QFont()
        self._title_font.setPointSize(10)
        self._monogram_font = QFont()
        self._monogram_font.setPointSize(11)
        self._monogram_font.setBold(True)
        self._badge_font = QFont()
        self._badge_font.setPointSize(7)
        self._badge_font.setBold(True)
        self._star_font = QFont()
        self._star_font.setPointSize(10)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(0, self._row_height)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        row_rect = QRectF(option.rect).adjusted(4, 2, -4, -2)
        is_playing = bool(self._playing_fn and self._playing_fn(index))
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hover = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if is_selected or is_hover or is_playing:
            bg_path = QPainterPath()
            bg_path.addRoundedRect(row_rect, 6, 6)
            painter.fillPath(bg_path, QColor(Palette.BG_CARD_HOVER))

        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        image_url = index.data(IMAGE_URL_ROLE) or ""

        thumb_size = row_rect.height() - 8
        thumb_rect = QRectF(
            row_rect.left() + 6,
            row_rect.top() + (row_rect.height() - thumb_size) / 2,
            thumb_size,
            thumb_size,
        )

        painter.save()
        thumb_path = QPainterPath()
        thumb_path.addRoundedRect(thumb_rect, 4, 4)
        painter.setClipPath(thumb_path)

        pixmap = None
        if image_url:
            size = QSize(int(thumb_size * 2), int(thumb_size * 2))
            pixmap = get_image_loader().load(image_url, size)

        if pixmap is not None and not pixmap.isNull():
            pw, ph = pixmap.width(), pixmap.height()
            tw = thumb_rect.width()
            th = thumb_rect.height()
            if pw > 0 and ph > 0 and tw > 0 and th > 0:
                scale = max(tw / pw, th / ph)
                sw = tw / scale
                sh = th / scale
                sx = (pw - sw) / 2
                sy = (ph - sh) / 2
                painter.drawPixmap(thumb_rect, pixmap, QRectF(sx, sy, sw, sh))
            else:
                painter.drawPixmap(thumb_rect.toRect(), pixmap)
        else:
            painter.fillRect(thumb_rect, QColor(_monogram_color(title)))
            painter.setPen(QColor(Palette.TEXT_ON_ACCENT))
            painter.setFont(self._monogram_font)
            painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter, _monogram(title))
        painter.restore()

        is_favorite = bool(self._favorite_fn and self._favorite_fn(index))
        is_live = bool(self._live_fn and self._live_fn(index))

        right_edge = row_rect.right() - 8
        if is_favorite:
            star_rect = QRectF(
                right_edge - 18, row_rect.top() + (row_rect.height() - 18) / 2, 18, 18
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(Palette.FAVORITE_GOLD))
            painter.drawEllipse(star_rect)
            painter.setPen(QColor(Palette.BG_BASE))
            painter.setFont(self._star_font)
            painter.drawText(star_rect, Qt.AlignmentFlag.AlignCenter, "★")
            right_edge -= 24

        if is_playing:
            painter.setFont(self._badge_font)
            metrics = painter.fontMetrics()
            text = "▶ A REPRODUZIR"
            badge_w = metrics.horizontalAdvance(text) + 10
            badge_rect = QRectF(
                right_edge - badge_w,
                row_rect.top() + (row_rect.height() - metrics.height() - 4) / 2,
                badge_w,
                metrics.height() + 4,
            )
            badge_path = QPainterPath()
            badge_path.addRoundedRect(badge_rect, 3, 3)
            painter.fillPath(badge_path, QColor(Palette.SUCCESS_GREEN))
            painter.setPen(QColor(Palette.TEXT_ON_ACCENT))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)
            right_edge -= badge_w + 8
        elif is_live:
            painter.setFont(self._badge_font)
            metrics = painter.fontMetrics()
            text = "AO VIVO"
            badge_w = metrics.horizontalAdvance(text) + 10
            badge_rect = QRectF(
                right_edge - badge_w,
                row_rect.top() + (row_rect.height() - metrics.height() - 4) / 2,
                badge_w,
                metrics.height() + 4,
            )
            badge_path = QPainterPath()
            badge_path.addRoundedRect(badge_rect, 3, 3)
            painter.fillPath(badge_path, QColor(Palette.LIVE_BADGE))
            painter.setPen(QColor(Palette.TEXT_ON_ACCENT))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)
            right_edge -= badge_w + 8

        text_rect = QRectF(
            thumb_rect.right() + 10, row_rect.top(), right_edge - (thumb_rect.right() + 10), row_rect.height()
        )
        painter.setPen(QColor(Palette.TEXT_PRIMARY))
        painter.setFont(self._title_font)
        metrics = painter.fontMetrics()
        elided = metrics.elidedText(title, Qt.TextElideMode.ElideRight, max(0, int(text_rect.width())))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

        if is_playing:
            pen = QPen(QColor(Palette.SUCCESS_GREEN))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(row_rect.adjusted(1, 1, -1, -1), 6, 6)
        elif is_selected:
            pen = QPen(QColor(Palette.ACCENT))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(row_rect.adjusted(1, 1, -1, -1), 6, 6)
            painter.drawRoundedRect(row_rect.adjusted(1, 1, -1, -1), 6, 6)

        progress = self._progress_fn(index) if self._progress_fn else None
        if progress is not None and progress > 0:
            bar_rect = QRectF(row_rect.left(), row_rect.bottom() - 2, row_rect.width(), 2)
            painter.fillRect(bar_rect, QColor(0, 0, 0, 80))
            filled = QRectF(
                bar_rect.left(), bar_rect.top(), bar_rect.width() * max(0.0, min(1.0, progress)), 2
            )
            painter.fillRect(filled, QColor(Palette.ACCENT))

        painter.restore()


def _monogram(title: str) -> str:
    for ch in title:
        if ch.isalnum():
            return ch.upper()
    return "?"


def _monogram_color(title: str) -> str:
    digest = hashlib.sha1(title.encode("utf-8", errors="ignore")).digest()
    return _MONOGRAM_COLORS[digest[0] % len(_MONOGRAM_COLORS)]


def _draw_badge(painter: QPainter, poster_rect: QRectF, text: str, color: str, font: QFont, left: bool = True):
    painter.setFont(font)
    metrics = painter.fontMetrics()
    padding = 5
    text_w = metrics.horizontalAdvance(text)
    badge_rect = QRectF(0, 0, text_w + padding * 2, metrics.height() + 4)
    badge_rect.moveTop(poster_rect.top() + 5)
    badge_rect.moveLeft(poster_rect.left() + 5 if left else poster_rect.right() - badge_rect.width() - 5)
    path = QPainterPath()
    path.addRoundedRect(badge_rect, 3, 3)
    painter.fillPath(path, QColor(color))
    painter.setPen(QColor(Palette.TEXT_ON_ACCENT))
    painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)


def _draw_star(painter: QPainter, poster_rect: QRectF, font: QFont):
    size = 16
    rect = QRectF(poster_rect.right() - size - 5, poster_rect.top() + 5, size, size)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(Palette.FAVORITE_GOLD))
    painter.drawEllipse(rect)
    painter.setPen(QColor(Palette.BG_BASE))
    painter.setFont(font)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "★")


def _draw_progress_bar(painter: QPainter, poster_rect: QRectF, progress: float):
    height = 3
    rect = QRectF(poster_rect.left(), poster_rect.bottom() - height, poster_rect.width(), height)
    painter.fillRect(rect, QColor(0, 0, 0, 120))
    filled = QRectF(rect.left(), rect.top(), rect.width() * max(0.0, min(1.0, progress)), height)
    painter.fillRect(filled, QColor(Palette.ACCENT))
