"""Series browser: shows list -> season/episode drill-down."""

import re
from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.channel import Channel
from ..core.image_loader import get_image_loader
from .channel_list import ChannelListWidget
from .poster_delegate import IMAGE_URL_ROLE, PosterCardDelegate
from .theme import Palette

_SXXEXX_RE = re.compile(r"(?i)\bS(\d{1,2})\s*E(\d{1,3})\b")
_NXN_RE = re.compile(r"(?i)\b(\d{1,2})x(\d{1,3})\b")


class SeriesBrowserWidget(QWidget):
    """
    Two-level browser for series content:
    - Page 0: list of shows (reuses ChannelListWidget).
    - Page 1: season selector + episode list for the opened show.

    Season/episode data is fetched live by MainWindow (Stalker/Xtream differ
    in how episode URLs are resolved) and handed to this widget via
    set_seasons(); this widget only renders whatever it's given and hands
    back opaque per-episode payloads on selection.
    """

    show_drill_down_requested = Signal(object)  # Channel (the show)
    episode_selected = Signal(object)  # opaque payload from set_seasons()
    favorite_toggled = Signal(object, bool)  # Channel, is_favorite (passthrough)
    diagnostic_requested = Signal(object)
    group_lock_toggle_requested = Signal(str, bool)  # passthrough from shows list
    locked_group_access_requested = Signal(str)  # passthrough from shows list

    EPISODE_CARD_SIZE = QSize(220, 140)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._seasons: list = []
        self._m3u_groups: dict = {}
        self._setup_ui()
        self._image_repaint_timer = QTimer(self)
        self._image_repaint_timer.setSingleShot(True)
        self._image_repaint_timer.setInterval(80)
        self._image_repaint_timer.timeout.connect(self._episode_list.viewport().update)
        get_image_loader().image_ready.connect(self._on_image_ready)

    def _on_image_ready(self, url: str, pixmap):
        self._image_repaint_timer.start()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # Page 0: shows list
        self._shows_list = ChannelListWidget()
        self._shows_list.channel_selected.connect(self._on_show_clicked)
        self._shows_list.favorite_toggled.connect(self.favorite_toggled)
        self._shows_list.diagnostic_requested.connect(self.diagnostic_requested)
        self._shows_list.group_lock_toggle_requested.connect(self.group_lock_toggle_requested)
        self._shows_list.locked_group_access_requested.connect(self.locked_group_access_requested)
        self._stack.addWidget(self._shows_list)

        # Page 1: season/episode browser
        episode_page = QWidget()
        episode_layout = QVBoxLayout(episode_page)
        episode_layout.setContentsMargins(0, 0, 0, 0)
        episode_layout.setSpacing(5)

        header = QHBoxLayout()
        self._back_btn = QPushButton("◀ Voltar")
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.clicked.connect(self.show_shows_list)
        header.addWidget(self._back_btn)

        self._show_title = QLabel("")
        self._show_title.setStyleSheet(
            f"color: {Palette.TEXT_PRIMARY}; font-size: 13px; font-weight: bold; padding-left: 8px;"
        )
        header.addWidget(self._show_title, 1)
        episode_layout.addLayout(header)

        self._season_combo = QComboBox()
        self._season_combo.currentIndexChanged.connect(self._on_season_changed)
        episode_layout.addWidget(self._season_combo)

        self._episode_list = QListWidget()
        self._episode_list.setViewMode(QListView.ViewMode.IconMode)
        self._episode_list.setResizeMode(QListView.ResizeMode.Adjust)
        self._episode_list.setMovement(QListView.Movement.Static)
        self._episode_list.setWrapping(True)
        self._episode_list.setUniformItemSizes(True)
        self._episode_list.setSpacing(4)
        self._episode_list.setGridSize(self.EPISODE_CARD_SIZE)
        self._episode_list.setItemDelegate(
            PosterCardDelegate(self._episode_list, card_size=self.EPISODE_CARD_SIZE)
        )
        self._episode_list.itemDoubleClicked.connect(self._on_episode_clicked)
        episode_layout.addWidget(self._episode_list, 1)

        self._stack.addWidget(episode_page)

    def set_shows(self, shows: list, groups: Optional[list] = None):
        """Populate the shows list (page 0)."""
        self._m3u_groups = {}
        visible = []
        for show in shows:
            parsed = self._parse_m3u_episode(show) if show.source == "m3u" else None
            if not parsed:
                visible.append(show)
                continue
            title, season, episode = parsed
            key = f"{show.group}\N{SYMBOL FOR UNIT SEPARATOR}{title}"
            self._m3u_groups.setdefault(key, []).append((season, episode, show))
        for key, episodes in self._m3u_groups.items():
            first = episodes[0][2]
            title = self._parse_m3u_episode(first)[0]
            visible.append(
                Channel(
                    name=title,
                    url="",
                    group=first.group,
                    logo=first.logo,
                    stream_type="series",
                    source="m3u_group",
                    xtream_id=key,
                )
            )
        self._shows_list.set_channels(visible, groups)

    @staticmethod
    def _parse_m3u_episode(channel):
        name = channel.name
        match = _SXXEXX_RE.search(name)
        if match:
            title = _SXXEXX_RE.sub("", name).strip(" -._|[]()")
            return title or channel.group, int(match.group(1)), int(match.group(2))
        match = _NXN_RE.search(name)
        if match:
            title = _NXN_RE.sub("", name).strip(" -._|[]()")
            return title or channel.group, int(match.group(1)), int(match.group(2))
        return None

    def toggle_favorite(self, channel_id: int, is_favorite: bool):
        """Passthrough to the underlying shows list."""
        self._shows_list.toggle_favorite(channel_id, is_favorite)

    def set_locked_groups(self, names: set):
        self._shows_list.set_locked_groups(names)

    def unlock_group_session(self, group: str):
        self._shows_list.unlock_group_session(group)

    def _on_show_clicked(self, channel):
        if channel.source == "m3u_group":
            self.show_episode_browser(channel.name)
            by_season = {}
            for season, episode, item in self._m3u_groups.get(channel.xtream_id, []):
                by_season.setdefault(season, []).append((episode, item))
            seasons = []
            for season in sorted(by_season):
                episodes = [
                    {
                        "label": item.name,
                        "payload": {"source": "m3u", "channel": item},
                    }
                    for _, item in sorted(by_season[season], key=lambda value: value[0])
                ]
                seasons.append({"name": f"Temporada {season}", "episodes": episodes})
            self.set_seasons(seasons)
            return
        self.show_drill_down_requested.emit(channel)

    def show_episode_browser(self, show_name: str):
        """Switch to the season/episode page for a newly opened show."""
        self._show_title.setText(show_name)
        self._season_combo.clear()
        self._episode_list.clear()
        self._seasons = []
        self._stack.setCurrentIndex(1)

    def show_shows_list(self):
        """Go back to the shows list (page 0)."""
        self._stack.setCurrentIndex(0)

    def set_seasons(self, seasons: list):
        """
        seasons: list of {"name": str, "episodes": [{"label": str, "payload": Any}, ...]}
        """
        self._seasons = seasons
        self._season_combo.blockSignals(True)
        self._season_combo.clear()
        for season in seasons:
            self._season_combo.addItem(season.get("name", "Temporada"))
        self._season_combo.blockSignals(False)
        self._on_season_changed(0 if seasons else -1)

    def _on_season_changed(self, index: int):
        self._episode_list.clear()
        if index < 0 or index >= len(self._seasons):
            return
        for episode in self._seasons[index].get("episodes", []):
            item = QListWidgetItem(episode.get("label", "Episódio"))
            item.setData(Qt.ItemDataRole.UserRole, episode.get("payload"))
            item.setData(IMAGE_URL_ROLE, episode.get("image", ""))
            self._episode_list.addItem(item)

    def _on_episode_clicked(self, item: QListWidgetItem):
        payload = item.data(Qt.ItemDataRole.UserRole)
        if payload is not None:
            self.episode_selected.emit(payload)
