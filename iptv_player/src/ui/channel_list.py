"""Channel list/grid widget for displaying IPTV channels."""

from typing import Callable, Optional

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.channel import Channel
from ..core.image_loader import get_image_loader
from .poster_delegate import IMAGE_URL_ROLE, ChannelRowDelegate, PosterCardDelegate
from .theme import Palette


class ChannelListWidget(QWidget):
    """Widget displaying channels in a poster-card grid with group filtering,
    search and a parental-lock gate that all read paths funnel through."""

    # High enough that pagination never kicks in for any real playlist — the
    # grid view only paints visible cards (Qt virtualizes QListView), so a
    # single "page" of a few thousand channels doesn't cost anything at
    # render time. This just bounds the pathological case so a single
    # rebuild in _apply_filters() can't hang the UI outright.
    PAGE_SIZE = 20000
    CARD_SIZE = QSize(168, 132)
    ROW_HEIGHT = 44

    channel_selected = Signal(object)  # Channel
    favorite_toggled = Signal(object, bool)  # Channel, is_favorite
    context_menu_requested = Signal(object, object)  # channel, position
    diagnostic_requested = Signal(object)
    page_or_filter_changed = Signal()
    group_lock_toggle_requested = Signal(str, bool)  # group_name, new_locked_state
    locked_group_access_requested = Signal(str)  # group_name (needs a PIN)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._channels: list = []
        self._filtered_channels: list = []
        self._current_page_channels: list = []
        self._group_filter = ("all", "")
        self._current_page = 0
        self._page_count = 1
        self._category_positions: dict[tuple, tuple[int, object]] = {}
        self._group_items: dict[str, QTreeWidgetItem] = {}
        self._locked_groups: set[str] = set()
        self._session_unlocked: set[str] = set()
        self._progress_provider: Optional[Callable[[Channel], Optional[float]]] = None
        self._setup_ui()
        # Logos load in bursts (a whole page fetching at once); coalesce the
        # resulting repaints instead of doing one full viewport repaint per
        # image, which made scrolling/browsing feel heavy while a page of
        # artwork was still loading in.
        self._image_repaint_timer = QTimer(self)
        self._image_repaint_timer.setSingleShot(True)
        self._image_repaint_timer.setInterval(80)
        self._image_repaint_timer.timeout.connect(self._channel_list.viewport().update)
        get_image_loader().image_ready.connect(self._on_image_ready)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # Search bar
        search_layout = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("🔍 Pesquisar canais...")
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._filter_channels)
        self._search_input.textChanged.connect(self._schedule_filter)
        search_layout.addWidget(self._search_input)
        layout.addLayout(search_layout)

        # Group filter
        category_title = QLabel("CATEGORIAS")
        category_title.setStyleSheet(
            f"color: {Palette.TEXT_SECONDARY}; font-size: 11px; font-weight: 700; "
            "letter-spacing: 1px; padding: 5px 4px 1px 4px;"
        )
        layout.addWidget(category_title)

        self._group_combo = QTreeWidget()
        self._group_combo.setHeaderHidden(True)
        self._group_combo.setRootIsDecorated(False)
        self._group_combo.setIndentation(10)
        self._group_combo.setMinimumHeight(140)
        self._group_combo.setMaximumHeight(260)
        self._group_combo.itemClicked.connect(self._on_group_selected)
        self._group_combo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._group_combo.customContextMenuRequested.connect(self._show_group_context_menu)
        layout.addWidget(self._group_combo)

        # Channel count label + grid/list view toggle
        count_row = QHBoxLayout()
        self._count_label = QLabel("CANAIS · 0")
        self._count_label.setStyleSheet(
            f"color: {Palette.TEXT_SECONDARY}; font-size: 11px; font-weight: 700; "
            "letter-spacing: 1px; padding: 7px 5px 3px 5px;"
        )
        count_row.addWidget(self._count_label, 1)

        view_toggle_style = f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {Palette.BORDER_STRONG};
                color: {Palette.TEXT_MUTED};
                font-size: 12px;
                padding: 2px 0;
            }}
            QPushButton:checked {{
                background: {Palette.ACCENT};
                border-color: {Palette.ACCENT};
                color: {Palette.TEXT_ON_ACCENT};
            }}
            QPushButton:hover:!checked {{
                color: {Palette.TEXT_PRIMARY};
            }}
        """
        self._grid_view_btn = QPushButton("▦")
        self._grid_view_btn.setCheckable(True)
        self._grid_view_btn.setFixedSize(26, 22)
        self._grid_view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._grid_view_btn.setToolTip("Ver em grelha")
        self._grid_view_btn.setStyleSheet(
            view_toggle_style.replace("border: 1px solid", "border-top-left-radius: 5px; border-bottom-left-radius: 5px; border: 1px solid")
        )
        self._list_view_btn = QPushButton("☰")
        self._list_view_btn.setCheckable(True)
        self._list_view_btn.setFixedSize(26, 22)
        self._list_view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._list_view_btn.setToolTip("Ver em lista")
        self._list_view_btn.setStyleSheet(
            view_toggle_style.replace("border: 1px solid", "border-top-right-radius: 5px; border-bottom-right-radius: 5px; border-left: none; border: 1px solid")
        )
        self._view_toggle_group = QButtonGroup(self)
        self._view_toggle_group.setExclusive(True)
        self._view_toggle_group.addButton(self._grid_view_btn, 0)
        self._view_toggle_group.addButton(self._list_view_btn, 1)
        self._view_toggle_group.idClicked.connect(
            lambda idx: self._set_view_mode("list" if idx == 1 else "grid")
        )
        count_row.addWidget(self._grid_view_btn)
        count_row.addWidget(self._list_view_btn)
        layout.addLayout(count_row)

        # Status banner (loading / error) shown above the list when set.
        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            f"color: {Palette.WARNING_AMBER}; font-size: 12px; padding: 8px; "
            f"background: {Palette.BG_ELEVATED}; border-radius: 4px;"
        )
        self._status_label.hide()
        layout.addWidget(self._status_label)

        # Channel poster-card grid (or plain list, per _view_mode)
        self._channel_list = QListWidget()
        self._channel_list.setResizeMode(QListView.ResizeMode.Adjust)
        self._channel_list.setMovement(QListView.Movement.Static)
        self._channel_list.setUniformItemSizes(True)
        self._card_delegate = PosterCardDelegate(
            self._channel_list,
            card_size=self.CARD_SIZE,
            favorite_fn=self._item_is_favorite,
            live_fn=self._item_is_live,
            progress_fn=self._item_progress,
        )
        self._row_delegate = ChannelRowDelegate(
            self._channel_list,
            row_height=self.ROW_HEIGHT,
            favorite_fn=self._item_is_favorite,
            live_fn=self._item_is_live,
            progress_fn=self._item_progress,
        )
        self._view_settings = QSettings("IPTVPlayer", "IPTVPlayer")
        self._view_mode = self._view_settings.value("channel_list/view_mode", "grid")
        if self._view_mode not in ("grid", "list"):
            self._view_mode = "grid"
        (self._grid_view_btn if self._view_mode == "grid" else self._list_view_btn).setChecked(True)
        self._apply_view_mode()
        self._channel_list.setMouseTracking(True)
        self._channel_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._channel_list.customContextMenuRequested.connect(self._show_context_menu)
        self._channel_list.itemActivated.connect(self._on_channel_activated)
        self._channel_list.currentItemChanged.connect(self._on_channel_selected)
        layout.addWidget(self._channel_list)

        pagination = QHBoxLayout()
        self._previous_page_btn = QPushButton("Anterior")
        self._previous_page_btn.clicked.connect(self._previous_page)
        pagination.addWidget(self._previous_page_btn)
        self._page_label = QLabel("Página 1 de 1")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; padding: 4px;")
        pagination.addWidget(self._page_label, 1)
        self._next_page_btn = QPushButton("Seguinte")
        self._next_page_btn.clicked.connect(self._next_page)
        pagination.addWidget(self._next_page_btn)
        layout.addLayout(pagination)

    def set_channels(self, channels: list, groups: Optional[list] = None):
        """Set the channel list and populate UI."""
        self._channels = channels
        self._filtered_channels = list(channels)
        self._current_page = 0
        self._category_positions.clear()

        # Update groups
        self._group_combo.clear()
        all_item = QTreeWidgetItem(["All"])
        all_item.setData(0, Qt.ItemDataRole.UserRole, ("all", ""))
        self._group_combo.addTopLevelItem(all_item)
        favorites_item = QTreeWidgetItem(["Favoritos"])
        favorites_item.setData(0, Qt.ItemDataRole.UserRole, ("favorite", ""))
        self._group_combo.addTopLevelItem(favorites_item)
        self._group_combo.setRootIsDecorated(False)
        if groups is None:
            # dict.fromkeys preserves the category order supplied by the portal.
            groups = list(
                dict.fromkeys(ch.group for ch in channels if ch.group)
            )
        self._group_items.clear()
        for group in groups:
            item = QTreeWidgetItem([self._format_provider_group(group)])
            item.setData(
                0, Qt.ItemDataRole.UserRole, ("group", group)
            )
            self._group_combo.addTopLevelItem(item)
            self._group_items[group] = item

        self._group_filter = ("all", "")
        self._group_combo.setCurrentItem(all_item)
        self._refresh_group_lock_icons()
        self._apply_filters(reset_page=True)

    @staticmethod
    def _format_provider_group(group: str) -> str:
        """Render the provider's box separators in the requested |UK| style."""
        return group.replace("┃", "|").strip()

    def _apply_filters(self, reset_page: bool = False):
        """Filter the complete catalogue and render one bounded page."""
        self._channel_list.clear()
        search_text = self._search_input.text().strip().lower()

        channels = self._channels
        if search_text:
            channels = [
                ch for ch in channels
                if search_text in ch.name.lower() or search_text in ch.group.lower()
            ]

        # Parental gate: applied at the shared filtering point so it protects
        # every access path (All, Favoritos, search, group click) rather than
        # only the group-tree click handler.
        if self._locked_groups:
            channels = [
                ch for ch in channels
                if ch.group not in self._locked_groups or ch.group in self._session_unlocked
            ]

        filter_type, filter_value = self._group_filter
        if filter_type == "country":
            channels = [
                ch for ch in channels if ch.country_code == filter_value
            ]
        elif filter_type == "group":
            channels = [ch for ch in channels if ch.group == filter_value]
        elif filter_type == "favorite":
            channels = [ch for ch in channels if ch.is_favorite]

        self._filtered_channels = channels
        self._page_count = max(
            1, (len(channels) + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        )
        if reset_page:
            self._current_page = 0
        self._current_page = min(self._current_page, self._page_count - 1)
        start = self._current_page * self.PAGE_SIZE
        channels = channels[start : start + self.PAGE_SIZE]
        self._current_page_channels = channels

        for channel in channels:
            # Build display text with optional quality badge
            display_name = channel.name
            if channel.quality:
                display_name = f"{display_name}  [{channel.quality}]"

            item = QListWidgetItem(display_name)
            item.setData(Qt.ItemDataRole.UserRole, channel)
            item.setData(IMAGE_URL_ROLE, channel.logo or channel.tvg_logo)
            item.setToolTip(
                f"{channel.name}\nGrupo: {channel.group}\nOrigem: {channel.source}"
            )

            self._channel_list.addItem(item)

        self._count_label.setText(
            f"CANAIS · {self._channel_list.count()}"
        )

        total = len(self._filtered_channels)
        self._page_label.setText(
            f"Página {self._current_page + 1} de {self._page_count} · {total} itens"
        )
        self._previous_page_btn.setEnabled(self._current_page > 0)
        self._next_page_btn.setEnabled(
            self._current_page + 1 < self._page_count
        )
        self.page_or_filter_changed.emit()

    def _filter_channels(self):
        """Filter channels based on search text."""
        self._apply_filters(reset_page=True)

    def _on_group_selected(self, item: QTreeWidgetItem, column: int):
        """Handle group selection change."""
        target_filter = item.data(0, Qt.ItemDataRole.UserRole) or ("all", "")
        ftype, fvalue = target_filter
        if ftype == "group" and self._is_group_locked(fvalue):
            self.locked_group_access_requested.emit(fvalue)
            self._sync_group_tree_selection()
            return

        self._remember_position()
        self._group_filter = target_filter
        saved_page, channel_key = self._category_positions.get(
            self._group_filter, (0, None)
        )
        self._current_page = saved_page
        self._apply_filters()
        self._restore_channel(channel_key)

    def _sync_group_tree_selection(self):
        """Re-select the tree item matching the active filter (no PIN prompt loop)."""
        ftype, fvalue = self._group_filter
        target_data = (ftype, fvalue)
        for i in range(self._group_combo.topLevelItemCount()):
            item = self._group_combo.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == target_data:
                self._group_combo.setCurrentItem(item)
                return

    def _is_group_locked(self, group: str) -> bool:
        return group in self._locked_groups and group not in self._session_unlocked

    def set_locked_groups(self, names: set):
        """Set the permanent (DB-backed) set of locked group names."""
        self._locked_groups = set(names)
        self._refresh_group_lock_icons()
        self._apply_filters()

    def unlock_group_session(self, group: str):
        """Unlock a group for the remainder of this app session (PIN accepted)."""
        self._session_unlocked.add(group)
        self._refresh_group_lock_icons()
        self._group_filter = ("group", group)
        self._apply_filters(reset_page=True)

    def _refresh_group_lock_icons(self):
        for group, item in self._group_items.items():
            label = self._format_provider_group(group)
            if self._is_group_locked(group):
                item.setText(0, f"🔒 {label}")
            else:
                item.setText(0, label)

    def _show_group_context_menu(self, position):
        item = self._group_combo.itemAt(position)
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole) or ("all", "")
        if data[0] != "group":
            return
        group = data[1]
        menu = QMenu(self)
        if group in self._locked_groups:
            action = menu.addAction("🔓 Desbloquear categoria")
            action.triggered.connect(
                lambda: self.group_lock_toggle_requested.emit(group, False)
            )
        else:
            action = menu.addAction("🔒 Bloquear categoria")
            action.triggered.connect(
                lambda: self.group_lock_toggle_requested.emit(group, True)
            )
        menu.exec(self._group_combo.mapToGlobal(position))

    def _set_view_mode(self, mode: str):
        """Switch between the poster-card grid and a plain channel list."""
        if mode == self._view_mode:
            return
        self._view_mode = mode
        self._apply_view_mode()
        self._view_settings.setValue("channel_list/view_mode", mode)

    def _apply_view_mode(self):
        if self._view_mode == "list":
            self._channel_list.setViewMode(QListView.ViewMode.ListMode)
            self._channel_list.setFlow(QListView.Flow.TopToBottom)
            self._channel_list.setWrapping(False)
            self._channel_list.setGridSize(QSize())
            self._channel_list.setSpacing(1)
            self._channel_list.setItemDelegate(self._row_delegate)
        else:
            self._channel_list.setViewMode(QListView.ViewMode.IconMode)
            self._channel_list.setFlow(QListView.Flow.LeftToRight)
            self._channel_list.setWrapping(True)
            self._channel_list.setGridSize(self.CARD_SIZE)
            self._channel_list.setSpacing(4)
            self._channel_list.setItemDelegate(self._card_delegate)

    def _schedule_filter(self):
        self._search_timer.start()

    def _previous_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._apply_filters()

    def _next_page(self):
        if self._current_page + 1 < self._page_count:
            self._current_page += 1
            self._apply_filters()

    def _on_channel_activated(self, item: QListWidgetItem):
        """Play only on explicit activation (double-click, Enter or Return)."""
        channel = item.data(Qt.ItemDataRole.UserRole)
        if channel:
            self._remember_position()
            self.channel_selected.emit(channel)

    def _on_channel_selected(self, current, previous):
        """Single click only changes selection; it must not start playback."""

    def _show_context_menu(self, position):
        """Show context menu for a channel."""
        item = self._channel_list.itemAt(position)
        if not item:
            return

        channel = item.data(Qt.ItemDataRole.UserRole)
        if not channel:
            return

        menu = QMenu(self)

        play_action = menu.addAction("▶ Reproduzir")
        play_action.triggered.connect(lambda: self.channel_selected.emit(channel))

        fav_text = "⭐ Remover Favorito" if channel.is_favorite else "⭐ Adicionar Favorito"
        fav_action = menu.addAction(fav_text)
        new_fav_state = not channel.is_favorite
        fav_action.triggered.connect(
            lambda: self.favorite_toggled.emit(channel, new_fav_state)
        )

        menu.addSeparator()

        copy_action = menu.addAction("📋 Copiar URL")
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(channel.url))

        menu.addSeparator()
        diagnostic_action = menu.addAction("Diagnosticar disponibilidade")
        diagnostic_action.triggered.connect(
            lambda: self.diagnostic_requested.emit(channel)
        )

        menu.exec(self._channel_list.mapToGlobal(position))

    def toggle_favorite(self, channel_id: int, is_favorite: bool):
        """Toggle favorite state and update UI."""
        for ch in self._channels:
            if ch.database_id == channel_id:
                ch.is_favorite = is_favorite
                break
        self._apply_filters()

    def get_current_channel(self) -> Optional[Channel]:
        """Get the currently selected channel."""
        item = self._channel_list.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def get_current_page_channels(self) -> list:
        """Channels actually rendered on the current page (post-filter)."""
        return list(self._current_page_channels)

    def set_status_message(self, text: str = ""):
        """Show a transient banner (loading/error) above the list, if any."""
        if text:
            self._status_label.setText(text)
            self._status_label.show()
        else:
            self._status_label.clear()
            self._status_label.hide()

    def get_group_filter(self):
        """Return the active (filter_type, value) tuple."""
        return self._group_filter

    def set_group_filter(self, filter_value: tuple):
        """Apply a (filter_type, value) tuple and refresh the tree selection."""
        filter_value = tuple(filter_value) if filter_value else ("all", "")
        self._group_filter = filter_value
        for i in range(self._group_combo.topLevelItemCount()):
            item = self._group_combo.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == filter_value:
                self._group_combo.setCurrentItem(item)
                break
        self._apply_filters(reset_page=True)

    def restore_channel_by_url_or_id(self, url: str, database_id: int) -> bool:
        """Best-effort re-selection of the last played channel on startup."""
        for channel in self._filtered_channels:
            if (database_id and channel.database_id == database_id) or (
                url and channel.url == url
            ):
                return self._restore_channel(self._channel_key(channel))
        return False

    def set_progress_provider(self, provider: Optional[Callable[[Channel], Optional[float]]]):
        """Inject a `(channel) -> 0..1 | None` lookup for the resume-progress bar."""
        self._progress_provider = provider

    def _item_is_favorite(self, index) -> bool:
        channel = index.data(Qt.ItemDataRole.UserRole)
        return bool(getattr(channel, "is_favorite", False))

    def _item_is_live(self, index) -> bool:
        channel = index.data(Qt.ItemDataRole.UserRole)
        return getattr(channel, "stream_type", "") == "live"

    def _item_progress(self, index) -> Optional[float]:
        if not self._progress_provider:
            return None
        channel = index.data(Qt.ItemDataRole.UserRole)
        if channel is None:
            return None
        return self._progress_provider(channel)

    def _on_image_ready(self, url: str, pixmap):
        self._image_repaint_timer.start()

    @staticmethod
    def _channel_key(channel: Optional[Channel]):
        if channel is None:
            return None
        return channel.database_id or channel.url or (channel.name, channel.group)

    def _remember_position(self):
        """Remember the page and selected channel independently per category."""
        self._category_positions[self._group_filter] = (
            self._current_page,
            self._channel_key(self.get_current_channel()),
        )

    def _restore_channel(self, channel_key) -> bool:
        if channel_key is None:
            return False
        for row in range(self._channel_list.count()):
            item = self._channel_list.item(row)
            if self._channel_key(item.data(Qt.ItemDataRole.UserRole)) == channel_key:
                self._channel_list.setCurrentItem(item)
                self._channel_list.scrollToItem(item)
                return True
        return False

    def play_adjacent(self, direction: int) -> Optional[Channel]:
        """Select and emit the previous/next channel across paginated results."""
        if not self._filtered_channels:
            return None
        current_key = self._channel_key(self.get_current_channel())
        index = next(
            (
                idx
                for idx, channel in enumerate(self._filtered_channels)
                if self._channel_key(channel) == current_key
            ),
            -1,
        )
        if index < 0:
            target_index = 0
        else:
            target_index = (index + (1 if direction >= 0 else -1)) % len(
                self._filtered_channels
            )
        target = self._filtered_channels[target_index]
        self._current_page = target_index // self.PAGE_SIZE
        self._apply_filters()
        self._restore_channel(self._channel_key(target))
        self._remember_position()
        self.channel_selected.emit(target)
        return target
