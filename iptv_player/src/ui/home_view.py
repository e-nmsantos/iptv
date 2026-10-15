"""Início: hero banner plus rows of cards (continue watching, recents, favourites, new)."""

from datetime import datetime
from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.channel import Channel
from ..core.image_loader import get_image_loader
from .theme import Palette

POSTER = QSize(150, 225)
LANDSCAPE = QSize(272, 153)
CHANNEL = QSize(236, 112)


def _format_remaining(ms: int) -> str:
    minutes = max(0, int(ms // 60000))
    if minutes >= 60:
        return f"faltam {minutes // 60} h {minutes % 60:02d} min"
    return f"faltam {minutes} min" if minutes else "quase no fim"


class MediaCard(QWidget):
    """A clickable, keyboard-focusable artwork card painted in one pass."""

    activated = Signal()
    remove_requested = Signal()

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        image_url: str = "",
        size: QSize = POSTER,
        progress: Optional[float] = None,
        badge: str = "",
        fit_image: bool = False,
        removable: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._title = title
        self._subtitle = subtitle
        self._image_url = image_url or ""
        self._art_size = size
        self._progress = progress
        self._badge = badge
        self._fit = fit_image
        self._removable = removable
        self._pixmap: Optional[QPixmap] = None
        self._hover = False
        caption = 0 if size == CHANNEL else 42
        self.setFixedSize(size.width(), size.height() + caption)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(title if not subtitle else f"{title}\n{subtitle}")
        if self._image_url:
            loader = get_image_loader()
            self._pixmap = loader.load(self._image_url, size)
            if self._pixmap is None:
                loader.image_ready.connect(self._on_image_ready)

    def _on_image_ready(self, url: str, pixmap: QPixmap) -> None:
        if url == self._image_url:
            self._pixmap = pixmap
            self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def focusInEvent(self, event):
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.update()
        super().focusOutEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            return
        if self._removable and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove_requested.emit()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("▶ Reproduzir", self.activated.emit)
        if self._removable:
            menu.addAction("✕ Remover de Continuar a ver", self.remove_requested.emit)
        menu.exec(event.globalPos())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        art = QRectF(0, 0, self._art_size.width(), self._art_size.height())
        path = QPainterPath()
        path.addRoundedRect(art.adjusted(1, 1, -1, -1), 12, 12)
        painter.fillPath(path, QColor(Palette.BG_CARD_HOVER if self._hover else Palette.BG_CARD))

        painter.save()
        painter.setClipPath(path)
        if self._pixmap is not None and not self._pixmap.isNull():
            if self._fit:
                target = art.adjusted(18, 14, -18, -14)
                scaled = self._pixmap.scaled(
                    target.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x = target.x() + (target.width() - scaled.width()) / 2
                y = target.y() + (target.height() - scaled.height()) / 2
                painter.drawPixmap(int(x), int(y), scaled)
            else:
                scaled = self._pixmap.scaled(
                    art.size().toSize(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x = (scaled.width() - art.width()) / 2
                y = (scaled.height() - art.height()) / 2
                painter.drawPixmap(art.toRect(), scaled, QRectF(x, y, art.width(), art.height()).toRect())
        else:
            painter.setPen(QColor(Palette.ACCENT))
            font = QFont(self.font())
            font.setPointSize(22)
            font.setBold(True)
            painter.setFont(font)
            # Channel tiles carry their name at the bottom, so keep the monogram clear of it.
            monogram_area = art.adjusted(0, 0, 0, -art.height() * 0.42) if self._art_size == CHANNEL else art
            painter.drawText(monogram_area, Qt.AlignmentFlag.AlignCenter, self._title[:2].upper())

        if self._art_size == CHANNEL:
            shade = QLinearGradient(art.topLeft(), art.bottomLeft())
            shade.setColorAt(0.35, QColor(0, 0, 0, 0))
            shade.setColorAt(1.0, QColor(0, 0, 0, 215))
            painter.fillRect(art, shade)
            painter.setPen(QColor(Palette.TEXT_PRIMARY))
            title_font = QFont(self.font())
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.drawText(
                art.adjusted(12, 0, -12, -26), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                painter.fontMetrics().elidedText(self._title, Qt.TextElideMode.ElideRight, int(art.width() - 24)),
            )
            painter.setPen(QColor(Palette.TEXT_SECONDARY))
            sub_font = QFont(self.font())
            sub_font.setPointSizeF(max(7.0, sub_font.pointSizeF() - 1))
            painter.setFont(sub_font)
            painter.drawText(
                art.adjusted(12, 0, -12, -9), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                painter.fontMetrics().elidedText(self._subtitle, Qt.TextElideMode.ElideRight, int(art.width() - 24)),
            )

        if self._badge:
            badge_font = QFont(self.font())
            badge_font.setPointSizeF(7.5)
            badge_font.setBold(True)
            painter.setFont(badge_font)
            width = painter.fontMetrics().horizontalAdvance(self._badge) + 12
            badge_rect = QRectF(8, 8, width, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(Palette.ACCENT))
            painter.drawRoundedRect(badge_rect, 4, 4)
            painter.setPen(QColor(Palette.TEXT_ON_ACCENT))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, self._badge)

        if self._progress is not None and self._progress > 0:
            bar = QRectF(0, art.height() - 5, art.width(), 5)
            painter.fillRect(bar, QColor(255, 255, 255, 60))
            painter.fillRect(QRectF(0, bar.y(), art.width() * min(1.0, self._progress), 5), QColor(Palette.ACCENT))
        painter.restore()

        if self._hover or self.hasFocus():
            painter.setPen(QColor(Palette.ACCENT if self.hasFocus() else Palette.TEXT_SECONDARY))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        if self._art_size != CHANNEL:
            caption = QRectF(2, art.height() + 6, art.width() - 4, 18)
            painter.setPen(QColor(Palette.TEXT_PRIMARY))
            title_font = QFont(self.font())
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.drawText(
                caption, Qt.AlignmentFlag.AlignLeft,
                painter.fontMetrics().elidedText(self._title, Qt.TextElideMode.ElideRight, int(caption.width())),
            )
            if self._subtitle:
                painter.setPen(QColor(Palette.TEXT_SECONDARY))
                painter.setFont(self.font())
                painter.drawText(
                    caption.translated(0, 18), Qt.AlignmentFlag.AlignLeft,
                    painter.fontMetrics().elidedText(self._subtitle, Qt.TextElideMode.ElideRight, int(caption.width())),
                )


class _HeroBanner(QFrame):
    """Large featured item with blurred-feeling artwork and a primary action."""

    action_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(280)
        self._pixmap: Optional[QPixmap] = None
        self._image_url = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(36, 28, 28, 28)
        text = QVBoxLayout()
        text.setSpacing(6)
        text.addStretch(1)
        self._eyebrow = QLabel()
        self._eyebrow.setStyleSheet(f"color: {Palette.ACCENT}; font-size: 12px; font-weight: 800; background: transparent;")
        text.addWidget(self._eyebrow)
        self._title = QLabel()
        self._title.setWordWrap(True)
        self._title.setStyleSheet(f"color: {Palette.TEXT_PRIMARY}; font-size: 30px; font-weight: 800; background: transparent;")
        text.addWidget(self._title)
        self._subtitle = QLabel()
        self._subtitle.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-size: 14px; background: transparent;")
        text.addWidget(self._subtitle)
        text.addSpacing(12)
        self._button = QPushButton()
        self._button.setObjectName("heroButton")
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._button.clicked.connect(self.action_clicked.emit)
        text.addWidget(self._button)
        text.addStretch(1)
        layout.addLayout(text, 1)
        get_image_loader().image_ready.connect(self._on_image_ready)

    def set_content(self, eyebrow: str, title: str, subtitle: str, action: str, image_url: str) -> None:
        self._eyebrow.setText(eyebrow)
        self._title.setText(title)
        self._subtitle.setText(subtitle)
        self._subtitle.setVisible(bool(subtitle))
        self._button.setText(action)
        self._image_url = image_url or ""
        self._pixmap = get_image_loader().load(self._image_url, QSize(1280, 720)) if self._image_url else None
        self.update()

    def _on_image_ready(self, url: str, pixmap: QPixmap) -> None:
        if url == self._image_url:
            self._pixmap = pixmap
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, 18, 18)
        painter.setClipPath(path)
        painter.fillRect(rect, QColor(Palette.BG_ELEVATED))
        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                rect.size().toSize(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (scaled.width() - rect.width()) / 2
            y = (scaled.height() - rect.height()) / 3
            painter.setOpacity(0.55)
            painter.drawPixmap(rect.toRect(), scaled, QRectF(x, y, rect.width(), rect.height()).toRect())
            painter.setOpacity(1.0)
        shade = QLinearGradient(rect.topLeft(), rect.topRight())
        base = QColor(Palette.BG_BASE)
        shade.setColorAt(0.0, QColor(base.red(), base.green(), base.blue(), 250))
        shade.setColorAt(0.55, QColor(base.red(), base.green(), base.blue(), 200))
        shade.setColorAt(1.0, QColor(base.red(), base.green(), base.blue(), 40))
        painter.fillRect(rect, shade)


class _Row(QWidget):
    """Section title plus a horizontally scrolling strip of cards."""

    def __init__(self, title: str, hint: str = "", action: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        header = QHBoxLayout()
        label = QLabel(title)
        label.setStyleSheet(f"color: {Palette.TEXT_PRIMARY}; font-size: 18px; font-weight: 800;")
        header.addWidget(label)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setStyleSheet(f"color: {Palette.TEXT_MUTED}; font-size: 11px;")
            header.addWidget(hint_label)
        header.addStretch(1)
        self.action_button: Optional[QPushButton] = None
        if action:
            self.action_button = QPushButton(f"{action}  ›")
            self.action_button.setObjectName("linkButton")
            self.action_button.setCursor(Qt.CursorShape.PointingHandCursor)
            header.addWidget(self.action_button)
        layout.addLayout(header)

        self._strip = QWidget()
        self._strip_layout = QHBoxLayout(self._strip)
        self._strip_layout.setContentsMargins(2, 2, 2, 8)
        self._strip_layout.setSpacing(14)
        self._strip_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("homeRowScroll")
        scroll.setWidget(self._strip)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll = scroll
        layout.addWidget(scroll)

    def set_cards(self, cards: list) -> None:
        while self._strip_layout.count() > 1:
            item = self._strip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        height = 0
        for card in cards:
            self._strip_layout.insertWidget(self._strip_layout.count() - 1, card)
            height = max(height, card.height())
        self._scroll.setFixedHeight(height + 30)
        self.setVisible(bool(cards))


class HomeView(QWidget):
    """Landing page shown in place of the player until something is played."""

    play_requested = Signal(object)          # Channel
    resume_requested = Signal(object)        # continue-watching item dict
    remove_requested = Signal(str)           # media_key
    browse_requested = Signal(int)           # content tab index
    back_to_player_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homeView")
        self._hero_target = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("homeScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("homeContent")
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(24, 20, 24, 24)
        self._layout.setSpacing(26)
        scroll.setWidget(content)

        self._now_playing = QFrame()
        self._now_playing.setObjectName("nowPlayingBar")
        bar = QHBoxLayout(self._now_playing)
        bar.setContentsMargins(16, 10, 12, 10)
        self._now_playing_label = QLabel()
        self._now_playing_label.setStyleSheet(f"color: {Palette.TEXT_PRIMARY}; font-weight: 600; background: transparent;")
        bar.addWidget(self._now_playing_label, 1)
        back = QPushButton("Voltar ao player")
        back.setObjectName("primaryButton")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.back_to_player_requested.emit)
        bar.addWidget(back)
        self._now_playing.hide()
        self._layout.addWidget(self._now_playing)

        self._greeting = QLabel()
        self._greeting.setStyleSheet(f"color: {Palette.TEXT_PRIMARY}; font-size: 28px; font-weight: 800;")
        self._layout.addWidget(self._greeting)
        self._hero = _HeroBanner()
        self._hero.action_clicked.connect(self._on_hero_action)
        self._layout.addWidget(self._hero)

        self._continue_row = _Row("Continuar a ver", hint="Botão direito ou Delete para remover")
        self._recent_row = _Row("Vistos recentemente")
        self._favorites_row = _Row("Favoritos")
        self._movies_row = _Row("Filmes adicionados recentemente", action="Ver filmes")
        self._series_row = _Row("Séries adicionadas recentemente", action="Ver séries")
        self._movies_row.action_button.clicked.connect(lambda: self.browse_requested.emit(1))
        self._series_row.action_button.clicked.connect(lambda: self.browse_requested.emit(2))
        for row in (self._continue_row, self._recent_row, self._favorites_row, self._movies_row, self._series_row):
            row.hide()
            self._layout.addWidget(row)

        self._empty = QLabel(
            "Ainda não há nada para mostrar aqui.\n"
            "Escolhe um canal, filme ou série na lista à esquerda — o que vires aparece no Início."
        )
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-size: 14px; padding: 40px;")
        self._layout.addWidget(self._empty)
        self._layout.addStretch(1)
        self._update_greeting()

    # -- data ---------------------------------------------------------
    def set_now_playing(self, title: Optional[str]) -> None:
        self._now_playing_label.setText(f"▶  A reproduzir: {title}" if title else "")
        self._now_playing.setVisible(bool(title))

    def set_content(
        self,
        continue_items: list,
        recent_live: list,
        favorites: list,
        recent_movies: list,
        recent_series: list,
        now_titles: Optional[dict] = None,
    ) -> None:
        """Rebuild every row. ``now_titles`` maps channel name -> current programme title."""
        now_titles = now_titles or {}
        self._update_greeting()
        self._continue_row.set_cards([self._continue_card(item) for item in continue_items])
        self._recent_row.set_cards([self._channel_card(ch, now_titles) for ch in recent_live])
        self._favorites_row.set_cards([
            self._channel_card(ch, now_titles) if ch.stream_type == "live" else self._poster_card(ch)
            for ch in favorites
        ])
        self._movies_row.set_cards([self._poster_card(ch) for ch in recent_movies])
        self._series_row.set_cards([self._poster_card(ch) for ch in recent_series])

        hero_item = next((item for item in continue_items if item.get("artwork")), None)
        if hero_item is not None:
            self._hero_target = ("resume", hero_item)
            up_next = hero_item.get("up_next")
            self._hero.set_content(
                "PRÓXIMO EPISÓDIO" if up_next else "CONTINUAR A VER",
                hero_item["title"],
                hero_item.get("subtitle", ""),
                "▶  Ver episódio" if up_next else
                f"▶  Continuar · {_format_remaining(hero_item['length_ms'] - hero_item['position_ms'])}",
                hero_item["artwork"],
            )
        else:
            featured = next((ch for ch in list(recent_movies) + list(recent_series) if ch.logo), None)
            if featured is not None:
                self._hero_target = ("play", featured)
                is_series = featured.stream_type == "series"
                self._hero.set_content(
                    "NOVA SÉRIE" if is_series else "NOVIDADE",
                    featured.name,
                    featured.group,
                    "▶  Ver episódios" if is_series else "▶  Ver agora",
                    featured.logo,
                )
            else:
                self._hero_target = None
        self._hero.setVisible(self._hero_target is not None)
        self._greeting.setVisible(self._hero_target is None)
        has_any = any([continue_items, recent_live, favorites, recent_movies, recent_series])
        self._empty.setVisible(not has_any)

    # -- builders -----------------------------------------------------
    def _continue_card(self, item: dict) -> MediaCard:
        up_next = item.get("up_next")
        subtitle = item.get("subtitle", "")
        if not up_next and item.get("length_ms"):
            remaining = _format_remaining(item["length_ms"] - item["position_ms"])
            subtitle = f"{subtitle} · {remaining}" if subtitle else remaining
        card = MediaCard(
            item["title"], subtitle, item.get("artwork", ""), LANDSCAPE,
            progress=None if up_next else item.get("fraction"),
            badge="PRÓXIMO EPISÓDIO" if up_next else "",
            removable=True,
        )
        card.activated.connect(lambda i=item: self.resume_requested.emit(i))
        card.remove_requested.connect(lambda key=item["media_key"]: self.remove_requested.emit(key))
        return card

    def _channel_card(self, channel: Channel, now_titles: dict) -> MediaCard:
        card = MediaCard(
            channel.name, now_titles.get(channel.name) or channel.group,
            channel.logo or channel.tvg_logo, CHANNEL, fit_image=True,
        )
        card.activated.connect(lambda ch=channel: self.play_requested.emit(ch))
        return card

    def _poster_card(self, channel: Channel) -> MediaCard:
        card = MediaCard(channel.name, channel.group, channel.logo or channel.tvg_logo, POSTER)
        card.activated.connect(lambda ch=channel: self.play_requested.emit(ch))
        return card

    def _on_hero_action(self) -> None:
        if not self._hero_target:
            return
        kind, target = self._hero_target
        if kind == "resume":
            self.resume_requested.emit(target)
        else:
            self.play_requested.emit(target)

    def _update_greeting(self) -> None:
        hour = datetime.now().hour
        greeting = "Bom dia" if 6 <= hour < 13 else "Boa tarde" if 13 <= hour < 20 else "Boa noite"
        self._greeting.setText(f"{greeting} 👋")
