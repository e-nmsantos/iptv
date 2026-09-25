"""Main application window for the IPTV Player."""

from typing import Optional

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Slot
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config.settings import Settings

from ..controllers.catalog_controller import CatalogController
from ..controllers.epg_controller import EpgController
from ..controllers.playback_controller import PlaybackController
from ..controllers.playlist_controller import PlaylistController
from ..controllers.task_controller import TaskController
from ..core.channel import Channel
from ..core.content_types import SERIES, VOD, content_type_for_stream
from ..core.database import DatabaseManager
from ..core.parental import PinAttemptLimiter
from ..core.provider_sessions import ProviderSessionManager
from ..core.task_manager import TaskWorker
from ..player.media_player import MediaPlayer
from ..utils.logger import get_logger
from .catalog_mixin import CatalogMixin
from .channel_list import ChannelListWidget
from .dialogs import SettingsDialog
from .epg_grid_widget import EPGGridWidget
from .epg_widget import EPGWidget
from .global_search import GlobalSearchDialog
from .import_flow_mixin import ImportFlowMixin
from .pill_tabs import PillTabBar
from .playback import PlaybackMixin
from .player_widget import PlayerWidget
from .playlist_ops_mixin import PlaylistOpsMixin
from .playlist_widget import PlaylistWidget
from .series_browser import SeriesBrowserWidget
from .session_state import SessionStateMixin
from .theme import Palette
from .toast import Toast
from .tools_mixin import ToolsMixin
from .updates_mixin import UpdatesMixin


class MainWindow(CatalogMixin, ImportFlowMixin, PlaylistOpsMixin, UpdatesMixin, ToolsMixin, PlaybackMixin, SessionStateMixin, QMainWindow):
    """Main application window orchestrating all components."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("IPTV Player")
        self.setMinimumSize(980, 600)
        self.setWindowIcon(QIcon())

        # Core components
        self._settings = Settings()
        self._db = DatabaseManager()
        self._media_player = MediaPlayer(
            vlc_path=self._settings.get("vlc_path", ""),
            buffer_size_ms=self._settings.get("buffer_size_ms", 5000),
        )
        self._media_player.set_volume(self._settings.get("volume", 80))
        self._current_playlist_id: Optional[int] = None
        self._current_playback_channel: Optional[Channel] = None
        self._playback_position_ms = 0
        self._playback_length_ms = 0
        self._last_progress_save_ms = 0

        self._provider_sessions = ProviderSessionManager(
            self._db,
            lambda: self._settings.get("network_timeout_seconds", 30),
            # Evaluated per request on the calling thread, so cancelling an
            # import aborts the in-flight Xtream/Stalker call instead of
            # waiting for the whole catalogue to be downloaded.
            lambda: QThread.currentThread().isInterruptionRequested(),
        )
        self._catalog_controller = CatalogController(
            self._db, self._provider_sessions, self._settings
        )
        self._playlist_controller = PlaylistController(self._db)
        self._epg_controller = EpgController(self._db, self._settings)
        self._playback_controller = PlaybackController(self._db)
        self._task_controller = TaskController(
            self._settings.get("max_connections", 5)
        )
        self._bg_workers = self._task_controller.workers
        self._closing = False
        self._epg_loading_playlists: set = set()
        self._epg_loading_channels: set = set()
        self._stalker_metadata_loading: set = set()
        self._catalog_loading: set = set()
        # In-memory guide-grid cache (channel_id -> programs), seeded from
        # the same bulk EPG query used by the single-channel EPG tab so the
        # grid never issues its own per-channel DB round-trips.
        self._epg_grid_cache: dict = {}
        self._epg_grid_cache_playlist_id: Optional[int] = None
        # In-memory channel cache by playlist ID (playlist_id -> {"live": [...], "vod": [...], "series": [...]})
        # enables instantaneous (< 5ms) playlist switching in the same session.
        self._playlist_channel_cache: dict[int, dict[str, list]] = {}
        # The saved session is restored exactly once per run; later playlist
        # reloads (after an import, edit or delete) must not switch the user
        # back to whatever playlist was selected last time.
        self._session_restored = False

        # Saved layout margins for exiting fullscreen
        self._normal_layout_margins = (5, 5, 5, 5)
        self._is_fullscreen = False

        # Logger
        self._logger = get_logger()

        # Non-intrusive toast notifications + auto-zap guard.
        self._toast = Toast(self)
        self._auto_next_pending = False
        # Channels already tried as a backup stream, so a failing channel does
        # not ping-pong between the original and its mirror forever.
        self._fallback_attempted: set = set()
        self._fallback_in_progress = False
        self._pin_attempts = PinAttemptLimiter()

        # Setup UI (global theme/QSS is applied once at the QApplication level
        # in main.py; this window only builds widgets/menus).
        self._setup_menu_bar()
        self._setup_ui()
        self._setup_status_bar()
        self._setup_shortcuts()
        self._connect_signals()
        self._load_playlists()
        if not self._settings.get("first_run_done", False):
            QTimer.singleShot(0, self._show_first_run_welcome)
        if self._settings.get("auto_check_updates", True):
            QTimer.singleShot(2500, self._auto_check_updates)

    def _setup_menu_bar(self):
        """Set up the application menu bar."""
        menubar = self.menuBar()

        style = self.style()
        self._action_import_m3u = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "Importar M3U / M3U8...",
            self,
        )
        self._action_import_m3u.setShortcut(QKeySequence("Ctrl+N"))
        self._action_import_m3u.triggered.connect(self._import_m3u)

        self._action_import_xtream = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon),
            "Adicionar Xtream Codes...",
            self,
        )
        self._action_import_xtream.setShortcut(QKeySequence("Ctrl+X"))
        self._action_import_xtream.triggered.connect(self._import_xtream)

        self._action_import_stalker = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon),
            "Adicionar Stalker Portal...",
            self,
        )
        self._action_import_stalker.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._action_import_stalker.triggered.connect(self._import_stalker)

        self._action_refresh_epg = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
            "Atualizar EPG",
            self,
        )
        self._action_refresh_epg.setShortcut(QKeySequence("F5"))
        self._action_refresh_epg.triggered.connect(self._refresh_current_epg)

        self._action_refresh_catalog = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
            "Atualizar catálogo atual",
            self,
        )
        self._action_refresh_catalog.setShortcut(QKeySequence("F6"))
        self._action_refresh_catalog.triggered.connect(
            self._refresh_current_catalog
        )

        self._action_settings = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
            "Definições...",
            self,
        )
        self._action_settings.setShortcut(QKeySequence("Ctrl+,"))
        self._action_settings.triggered.connect(self._show_settings)

        self._action_export_backup = QAction("Exportar backup cifrado...", self)
        self._action_export_backup.triggered.connect(self._export_backup)
        self._action_import_backup = QAction("Importar backup cifrado...", self)
        self._action_import_backup.triggered.connect(self._import_backup)
        self._action_copy_device_sync = QAction(
            "Copiar favoritos e retoma para a TV", self
        )
        self._action_copy_device_sync.triggered.connect(self._copy_device_sync)
        self._action_import_device_sync = QAction(
            "Importar favoritos e retoma da TV...", self
        )
        self._action_import_device_sync.triggered.connect(self._import_device_sync)

        self._action_global_search = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView),
            "Pesquisa global...",
            self,
        )
        self._action_global_search.setShortcut(QKeySequence("Ctrl+K"))
        self._action_global_search.triggered.connect(self._show_global_search)

        playlist_menu = menubar.addMenu("Playlists")
        playlist_menu.addAction(self._action_import_m3u)
        playlist_menu.addAction(self._action_import_xtream)
        playlist_menu.addAction(self._action_import_stalker)
        playlist_menu.addSeparator()
        rename_playlist_action = QAction("Alterar nome da playlist...", self)
        rename_playlist_action.setShortcut(QKeySequence("F2"))
        rename_playlist_action.triggered.connect(self._rename_current_playlist)
        playlist_menu.addAction(rename_playlist_action)
        playlist_menu.addAction(self._action_refresh_catalog)
        playlist_menu.addSeparator()
        playlist_menu.addAction(self._action_copy_device_sync)
        playlist_menu.addAction(self._action_import_device_sync)

        playback_menu = menubar.addMenu("Reprodução")
        play_pause = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay),
            "Reproduzir / Pausar",
            self,
        )
        play_pause.setShortcut(QKeySequence("Ctrl+Space"))
        play_pause.triggered.connect(self._toggle_playback)
        playback_menu.addAction(play_pause)
        stop_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaStop),
            "Parar",
            self,
        )
        stop_action.setShortcut(QKeySequence("Ctrl+S"))
        stop_action.triggered.connect(self._media_player.stop)
        playback_menu.addAction(stop_action)
        playback_menu.addSeparator()
        fullscreen_action = QAction("Ecrã inteiro", self)
        fullscreen_action.setShortcut(QKeySequence("F11"))
        fullscreen_action.triggered.connect(self._toggle_window_fullscreen)
        playback_menu.addAction(fullscreen_action)
        playback_menu.addSeparator()
        cast_action = QAction("Transmitir para TV / Chromecast...", self)
        cast_action.setShortcut(QKeySequence("Ctrl+T"))
        cast_action.triggered.connect(self._show_cast_dialog)
        playback_menu.addAction(cast_action)

        view_menu = menubar.addMenu("Ver")
        view_menu.addAction(self._action_global_search)
        view_menu.addSeparator()
        mosaico_action = QAction("Modo Mosaico (Multi-View 2x2)...", self)
        mosaico_action.setShortcut(QKeySequence("Ctrl+M"))
        mosaico_action.triggered.connect(self._show_multi_view)
        view_menu.addAction(mosaico_action)
        view_menu.addSeparator()
        sidebar_action = QAction("Mostrar / ocultar painel lateral", self)
        sidebar_action.setShortcut(QKeySequence("Ctrl+B"))
        sidebar_action.triggered.connect(self._toggle_sidebar)
        view_menu.addAction(sidebar_action)
        epg_panel_action = QAction("Mostrar / ocultar painel EPG", self)
        epg_panel_action.setShortcut(QKeySequence("Ctrl+G"))
        epg_panel_action.triggered.connect(self._toggle_epg_panel)
        view_menu.addAction(epg_panel_action)

        epg_menu = menubar.addMenu("Guia EPG")
        epg_menu.addAction(self._action_refresh_epg)

        file_menu = menubar.addMenu("Ficheiro")
        file_menu.addAction(self._action_export_backup)
        file_menu.addAction(self._action_import_backup)
        file_menu.addSeparator()
        dl_mgr_action = QAction("Gestor de Transferências...", self)
        dl_mgr_action.setShortcut(QKeySequence("Ctrl+J"))
        dl_mgr_action.triggered.connect(self._show_download_manager)
        file_menu.addAction(dl_mgr_action)
        file_menu.addSeparator()
        file_menu.addAction(self._action_settings)
        file_menu.addSeparator()
        exit_action = QAction("Sair", self)
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = menubar.addMenu("Ajuda")
        check_updates_action = QAction("Verificar atualizações...", self)
        check_updates_action.triggered.connect(self._check_for_updates)
        help_menu.addAction(check_updates_action)
        diagnostics_action = QAction("Guardar relatório de diagnóstico...", self)
        diagnostics_action.triggered.connect(self._export_diagnostics_report)
        help_menu.addAction(diagnostics_action)
        about_action = QAction("Sobre o IPTV Player", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        # Keep Python references: some PySide6 builds can otherwise release
        # submenu wrappers even though their actions remain on the menu bar.
        self._main_menus = [
            playlist_menu,
            playback_menu,
            view_menu,
            epg_menu,
            file_menu,
            help_menu,
        ]

        self._toolbar = QToolBar("Ações principais", self)
        self._toolbar.setObjectName("mainToolbar")
        self._toolbar.setMovable(False)
        self._toolbar.setFloatable(False)
        self._toolbar.setIconSize(QSize(20, 20))
        self._toolbar.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._toolbar.setStyleSheet(f"""
            QToolBar {{
                background: {Palette.BG_PANEL};
                border: none;
                border-bottom: 1px solid {Palette.BORDER};
                spacing: 6px;
                padding: 6px 10px;
            }}
            QToolButton {{
                color: {Palette.TEXT_PRIMARY};
                background: {Palette.BG_ELEVATED};
                border: 1px solid {Palette.BORDER_STRONG};
                border-radius: {Palette.RADIUS_MD}px;
                padding: 7px 11px;
                font-size: 12px;
                font-weight: 600;
            }}
            QToolButton:hover {{
                background: {Palette.BG_CARD_HOVER};
                border-color: {Palette.BORDER_STRONG};
            }}
            QToolButton:pressed {{ background: {Palette.ACCENT}; }}
        """)
        add_playlist_btn = QToolButton(self._toolbar)
        add_playlist_btn.setText("➕ Adicionar lista")
        add_playlist_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        add_menu = QMenu(self)
        add_menu.addAction(self._action_import_m3u)
        add_menu.addAction(self._action_import_xtream)
        add_menu.addAction(self._action_import_stalker)
        add_playlist_btn.setMenu(add_menu)
        self._toolbar.addWidget(add_playlist_btn)
        self._toolbar.addSeparator()
        self._toolbar.addAction(self._action_refresh_epg)
        self._toolbar.addAction(self._action_refresh_catalog)
        self._toolbar.addAction(self._action_global_search)
        self._toolbar.addAction(self._action_settings)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._toolbar)

    def _setup_ui(self):
        """Set up the main UI layout."""
        central = QWidget()
        self.setCentralWidget(central)
        self._main_layout = QVBoxLayout(central)
        self._main_layout.setContentsMargins(*self._normal_layout_margins)
        self._main_layout.setSpacing(5)
        main_layout = self._main_layout

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel - Playlist + Channels
        self._left_panel = QSplitter(Qt.Orientation.Vertical)
        left_panel = self._left_panel
        # Adiciona uma alça visível para criar uma separação clara entre as secções.
        # Isto resolve o problema de os widgets parecerem "uns em cima dos outros".
        left_panel.setStyleSheet(f"""
            QSplitter::handle:vertical {{
                height: 1px;
                background-color: {Palette.BORDER};
                margin: 4px 0;
            }}
            QSplitter::handle:vertical:hover {{
                background-color: {Palette.ACCENT};
            }}
        """)

        # Container para a lista de playlists, para garantir margens consistentes.
        playlist_container = QWidget()
        playlist_layout = QVBoxLayout(playlist_container)
        playlist_layout.setContentsMargins(5, 5, 5, 0)
        playlist_layout.setSpacing(0)
        self._playlist_widget = PlaylistWidget()
        left_panel.addWidget(self._playlist_widget)
        playlist_layout.addWidget(self._playlist_widget)
        left_panel.addWidget(playlist_container)

        # Content type pill tabs (Live / Vod / Series) + stacked content pages
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        # Adiciona margens para dar espaço à volta da lista de canais e separadores.
        content_layout.setContentsMargins(5, 0, 5, 5)
        content_layout.setSpacing(5)

        self._content_tabs = PillTabBar(["Em direto", "Filmes", "Séries"])
        content_layout.addWidget(self._content_tabs)

        self._content_stack = QStackedWidget()
        self._live_list = ChannelListWidget()
        self._vod_list = ChannelListWidget()
        self._series_browser = SeriesBrowserWidget()
        self._content_stack.addWidget(self._live_list)
        self._content_stack.addWidget(self._vod_list)
        self._content_stack.addWidget(self._series_browser)
        content_layout.addWidget(self._content_stack, 1)
        self._live_list.set_progress_provider(self._progress_fraction_for)
        self._vod_list.set_progress_provider(self._progress_fraction_for)

        left_panel.addWidget(content_container)
        left_panel.setSizes([200, 400])

        splitter.addWidget(left_panel)

        # Right panel - Player + EPG tabs
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)

        # Player (parented to right_panel to avoid unparented top-level window warning)
        self._player_widget = PlayerWidget(self._media_player, self._settings, parent=right_panel)
        right_layout.addWidget(self._player_widget, 3)

        # Bottom tabs (EPG)
        self._bottom_tabs = QTabWidget()

        self._epg_widget = EPGWidget()
        self._bottom_tabs.addTab(self._epg_widget, "📺 Programa do canal")

        self._epg_grid_widget = EPGGridWidget()
        self._epg_grid_widget.set_programs_provider(self._epg_programs_for_channel)
        self._bottom_tabs.addTab(self._epg_grid_widget, "🗓 Guia completo")

        empty_tab = QWidget()
        info_layout = QVBoxLayout(empty_tab)
        info_layout.setContentsMargins(8, 8, 8, 8)
        info_title = QLabel("REPRODUZIDOS RECENTEMENTE")
        info_title.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-weight: 700;")
        info_layout.addWidget(info_title)
        self._history_list = QListWidget()
        self._history_list.setAlternatingRowColors(True)
        info_layout.addWidget(self._history_list)
        self._bottom_tabs.addTab(empty_tab, "🕒 Recentes")

        resume_tab = QWidget()
        resume_layout = QVBoxLayout(resume_tab)
        resume_layout.setContentsMargins(8, 8, 8, 8)
        resume_title = QLabel("▶ CONTINUAR A VER")
        resume_title.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-weight: 700;")
        resume_layout.addWidget(resume_title)
        self._resume_list = QListWidget()
        self._resume_list.setAlternatingRowColors(True)
        self._resume_list.itemDoubleClicked.connect(self._on_resume_item_activated)
        resume_layout.addWidget(self._resume_list)
        self._bottom_tabs.addTab(resume_tab, "▶ Continuar a ver")

        right_layout.addWidget(self._bottom_tabs, 1)

        splitter.addWidget(right_panel)
        splitter.setSizes([350, 850])

        main_layout.addWidget(splitter)

    def _setup_status_bar(self):
        """Set up the status bar."""
        status = QStatusBar()
        self.setStatusBar(status)
        self._task_progress = QProgressBar()
        self._task_progress.setRange(0, 0)
        self._task_progress.setFixedWidth(110)
        self._task_progress.setTextVisible(False)
        self._task_progress.hide()
        status.addPermanentWidget(self._task_progress)
        self._cancel_tasks_btn = QPushButton("Cancelar")
        self._cancel_tasks_btn.setToolTip("Cancelar operações de rede em curso")
        self._cancel_tasks_btn.clicked.connect(self._cancel_running_tasks)
        self._cancel_tasks_btn.hide()
        status.addPermanentWidget(self._cancel_tasks_btn)
        status.showMessage("Pronto. Importa uma playlist para começar.")

    def _sync_task_widgets(self):
        running = bool(self._task_controller.running())
        self._task_progress.setVisible(running)
        self._cancel_tasks_btn.setVisible(running)

    @Slot()
    def _cancel_running_tasks(self):
        running = self._task_controller.running()
        self._task_controller.cancel_all()
        if running:
            self._cancel_tasks_btn.setEnabled(False)
            self.statusBar().showMessage("A cancelar operações em curso...")

    def _setup_shortcuts(self):
        """Set up global keyboard shortcuts."""
        esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        esc_shortcut.activated.connect(self._on_escape_pressed)

        previous_shortcut = QShortcut(QKeySequence(Qt.Key.Key_PageUp), self)
        previous_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        previous_shortcut.activated.connect(
            lambda: self._live_list.play_adjacent(-1)
        )
        next_shortcut = QShortcut(QKeySequence(Qt.Key.Key_PageDown), self)
        next_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        next_shortcut.activated.connect(
            lambda: self._live_list.play_adjacent(1)
        )

        # Volume / mute shortcuts.
        vol_up = QShortcut(QKeySequence("+"), self)
        vol_up.setContext(Qt.ShortcutContext.WindowShortcut)
        vol_up.activated.connect(self._increase_volume)
        vol_up_alt = QShortcut(QKeySequence("="), self)
        vol_up_alt.setContext(Qt.ShortcutContext.WindowShortcut)
        vol_up_alt.activated.connect(self._increase_volume)
        vol_down = QShortcut(QKeySequence("-"), self)
        vol_down.setContext(Qt.ShortcutContext.WindowShortcut)
        vol_down.activated.connect(self._decrease_volume)
        mute = QShortcut(QKeySequence("M"), self)
        mute.setContext(Qt.ShortcutContext.WindowShortcut)
        mute.activated.connect(self._toggle_mute)
        recall = QShortcut(QKeySequence("R"), self)
        recall.setContext(Qt.ShortcutContext.WindowShortcut)
        recall.activated.connect(self._recall_previous_channel)

        # Subtitle sync shortcuts (G/H, [/])
        sub_earlier = QShortcut(QKeySequence("G"), self)
        sub_earlier.setContext(Qt.ShortcutContext.WindowShortcut)
        sub_earlier.activated.connect(lambda: self._adjust_subtitle_delay(-50))
        sub_later = QShortcut(QKeySequence("H"), self)
        sub_later.setContext(Qt.ShortcutContext.WindowShortcut)
        sub_later.activated.connect(lambda: self._adjust_subtitle_delay(50))

        sub_earlier_alt = QShortcut(QKeySequence("["), self)
        sub_earlier_alt.setContext(Qt.ShortcutContext.WindowShortcut)
        sub_earlier_alt.activated.connect(lambda: self._adjust_subtitle_delay(-250))
        sub_later_alt = QShortcut(QKeySequence("]"), self)
        sub_later_alt.setContext(Qt.ShortcutContext.WindowShortcut)
        sub_later_alt.activated.connect(lambda: self._adjust_subtitle_delay(250))

    def _adjust_subtitle_delay(self, delta_ms: int):
        """Adjust subtitle synchronization delay and show toast."""
        current = self._media_player.get_subtitle_delay()
        new_val = max(-10000, min(10000, current + delta_ms))
        self._media_player.set_subtitle_delay(new_val)
        sec = new_val / 1000.0
        self._toast.show_message(f"⏱ Sincronização de Legendas: {new_val:+d} ms ({sec:+.2f} s)")

    @Slot()
    def _recall_previous_channel(self):
        """Switch back to the previously played channel."""
        prev = self._playback_controller.get_recall_channel()
        if prev:
            self._on_channel_selected(prev)
            self._toast.show_message(f"↩ A voltar para: {prev.name}")

    @Slot()
    def _on_escape_pressed(self):
        """Exit fullscreen when Esc is pressed, if currently fullscreen."""
        if self._is_fullscreen:
            self._exit_fullscreen()

    @Slot()
    def _toggle_playback(self):
        if self._media_player.is_playing:
            self._media_player.pause()
        else:
            self._media_player.play()

    def _rename_current_playlist(self):
        """Open the rename prompt for the selected item in the sidebar."""
        self._playlist_widget.rename_selected_playlist()

    @Slot()
    def _show_global_search(self):
        dialog = GlobalSearchDialog(self._db.search_all_channels, self)
        if dialog.exec() != dialog.DialogCode.Accepted or not dialog.selected_result:
            return
        result = dialog.selected_result
        playlist_id = result["playlist_id"]
        channel = result["channel"]
        if self._current_playlist_id != playlist_id:
            self._playlist_widget.select_playlist(playlist_id)
            self._on_playlist_selected(playlist_id)
        target_tab = 0
        result_type = content_type_for_stream(channel.stream_type)
        if result_type == VOD:
            target_tab = 1
        elif result_type == SERIES:
            target_tab = 2
        self._content_tabs.set_current_index(target_tab)
        self._on_content_tab_changed(target_tab)
        if target_tab == 0:
            self._on_channel_selected(channel)
        elif target_tab == 1:
            self._on_vod_selected(channel)
        else:
            self._on_series_show_opened(channel)

    @Slot()
    def _toggle_window_fullscreen(self):
        if self._is_fullscreen:
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    @Slot()
    def _toggle_sidebar(self):
        self._left_panel.setVisible(not self._left_panel.isVisible())

    @Slot()
    def _toggle_epg_panel(self):
        self._bottom_tabs.setVisible(not self._bottom_tabs.isVisible())

    @Slot()
    def _show_multi_view(self):
        from .multi_view_dialog import MultiViewDialog
        channels = []
        if self._current_playlist_id:
            try:
                channels = self._db.get_channels_by_type(self._current_playlist_id, "live")
            except Exception:
                channels = []
        dialog = MultiViewDialog(
            channels=channels,
            initial_channel=getattr(self, "_current_playback_channel", None),
            parent=self,
        )
        dialog.exec()

    @Slot()
    def _show_download_manager(self):
        from .download_manager_dialog import DownloadManagerDialog
        dialog = DownloadManagerDialog(media_player=self._media_player, parent=self)
        dialog.exec()

    @Slot()
    def _show_cast_dialog(self):
        from .cast_dialog import CastDialog
        curr_channel = getattr(self, "_current_playback_channel", None)
        url = curr_channel.url if curr_channel else ""
        title = curr_channel.name if curr_channel else ""
        headers = {}
        is_live = True
        if curr_channel:
            headers = dict(curr_channel.custom_headers or {})
            if curr_channel.user_agent:
                headers["User-Agent"] = curr_channel.user_agent
            if curr_channel.referer:
                headers["Referer"] = curr_channel.referer
            is_live = curr_channel.stream_type == "live"

        dialog = CastDialog(
            current_url=url,
            current_title=title,
            headers=headers,
            is_live=is_live,
            media_player=self._media_player,
            parent=self,
        )
        dialog.exec()

    @Slot()
    def _show_about(self):
        QMessageBox.about(
            self,
            "Sobre o IPTV Player",
            "<h3>IPTV Player</h3>"
            "<p>Player para M3U, Xtream Codes e Stalker Portal.</p>"
            "<p><b>Atalhos principais</b><br>"
            "F11 — Ecrã inteiro<br>"
            "Ctrl+B — Painel lateral<br>"
            "Ctrl+G — Guia EPG<br>"
            "F5 — Atualizar EPG<br>"
            "+ / - — Volume&nbsp;&nbsp;·&nbsp;&nbsp;M — Mudo<br>"
            "PageUp / PageDown — canal anterior / seguinte</p>",
        )

    @Slot(bool)
    def _on_fullscreen_toggled(self, is_fullscreen: bool):
        """Handle fullscreen toggle requested by the player widget."""
        if is_fullscreen:
            self._enter_fullscreen()
        else:
            self._exit_fullscreen()

    def _enter_fullscreen(self):
        """Hide all app chrome so only the video (with its overlay controls) is visible."""
        self._is_fullscreen = True
        self.menuBar().hide()
        self._toolbar.hide()
        self._left_panel.hide()
        self._bottom_tabs.hide()
        self.statusBar().hide()
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self.showFullScreen()

    def _exit_fullscreen(self):
        """Restore all app chrome and leave fullscreen."""
        self._is_fullscreen = False
        self.showNormal()
        self.menuBar().show()
        self._toolbar.show()
        self._left_panel.show()
        self._bottom_tabs.show()
        self.statusBar().show()
        self._main_layout.setContentsMargins(*self._normal_layout_margins)
        self._player_widget.set_fullscreen_state(False)

    def _connect_signals(self):
        """Connect widget signals to handlers."""
        # Playlist
        self._playlist_widget.playlist_selected.connect(self._on_playlist_selected)
        self._playlist_widget.playlist_deleted.connect(self._on_playlist_deleted)
        self._playlist_widget.playlist_renamed.connect(self._on_playlist_renamed)
        self._playlist_widget.playlist_edit_requested.connect(
            self._edit_playlist_connection
        )
        self._playlist_widget.import_m3u_requested.connect(self._import_m3u)
        self._playlist_widget.import_xtream_requested.connect(self._import_xtream)
        self._playlist_widget.import_stalker_requested.connect(self._import_stalker)

        # Content type tabs
        self._content_tabs.tab_changed.connect(self._on_content_tab_changed)

        # Live channel list
        self._live_list.channel_selected.connect(self._on_channel_selected)
        self._live_list.favorite_toggled.connect(self._on_favorite_toggled)
        self._live_list.diagnostic_requested.connect(self._diagnose_channel)
        self._live_list.page_or_filter_changed.connect(self._on_live_page_changed)
        self._live_list.set_url_provider(self._resolve_channel_url)

        # Vod list (movies need lazy resolve for Stalker before playback)
        self._vod_list.channel_selected.connect(self._on_vod_selected)
        self._vod_list.favorite_toggled.connect(self._on_favorite_toggled)
        self._vod_list.diagnostic_requested.connect(self._diagnose_channel)
        self._vod_list.set_url_provider(self._resolve_channel_url)

        # Series browser (shows -> seasons/episodes drill-down)
        self._series_browser.show_drill_down_requested.connect(self._on_series_show_opened)
        self._series_browser.episode_selected.connect(self._on_series_episode_selected)
        self._series_browser.favorite_toggled.connect(self._on_favorite_toggled)
        self._series_browser.diagnostic_requested.connect(self._diagnose_channel)

        # Parental lock: group-tree lock toggles + PIN-gated access, shared
        # across all three catalog widgets (Live/VOD/Series shows).
        for widget in (self._live_list, self._vod_list, self._series_browser):
            widget.group_lock_toggle_requested.connect(self._on_group_lock_toggle_requested)
            widget.locked_group_access_requested.connect(
                lambda group, w=widget: self._on_locked_group_access_requested(w, group)
            )

        # Multi-channel EPG guide grid
        self._epg_grid_widget.channels_needed.connect(self._ensure_epg_for_channels)
        self._epg_grid_widget.replay_requested.connect(self._play_catchup)
        self._bottom_tabs.currentChanged.connect(self._on_bottom_tab_changed)

        # Player
        self._player_widget.fullscreen_toggled.connect(self._on_fullscreen_toggled)
        self._player_widget.previous_channel_requested.connect(
            lambda: self._live_list.play_adjacent(-1)
        )
        self._player_widget.next_channel_requested.connect(
            lambda: self._live_list.play_adjacent(1)
        )
        self._player_widget.retry_requested.connect(self._retry_current_channel)
        self._media_player.time_changed.connect(self._track_playback_time)
        self._media_player.length_changed.connect(self._track_playback_length)
        self._media_player.media_ended.connect(self._on_media_ended)
        self._media_player.error_occurred.connect(self._on_media_error)

    def _load_playlists(self):
        """Load saved playlists from database."""
        try:
            playlists = self._playlist_controller.list()
            self._playlist_names = {p["id"]: p.get("name", "Playlist") for p in playlists}
            self._playlist_widget.set_playlists(playlists)
            # Restore the previous session once, on the first load after
            # startup only. Deferring it keeps startup from being blocked by a
            # large catalog, but re-running it after an import would silently
            # switch back to the previously selected playlist.
            if not self._session_restored:
                self._session_restored = True
                QTimer.singleShot(0, lambda: self._restore_session_state(playlists))
        except Exception as e:
            self._logger.error(f"Failed to load playlists: {e}")

    def _run_background(
        self,
        func,
        on_success,
        on_error=None,
        status_message: str = "",
        context_playlist_id: Optional[int] = None,
        use_semaphore: bool = True,
    ):
        """
        Run a one-off background call (resolve a stream URL, list seasons,
        etc.) without freezing the whole window like _run_import does —
        these are short, single calls triggered by a click while the user
        may still want to use fullscreen/Esc or browse other tabs.
        """
        if self._closing:
            return
        if status_message:
            self.statusBar().showMessage(status_message)

        def limited_func():
            if QThread.currentThread().isInterruptionRequested():
                return None
            if use_semaphore:
                return self._task_controller.execute(func)
            return func()

        worker = TaskWorker(limited_func)
        self._task_controller.add(worker)

        def _on_ok(result):
            if self._closing:
                return
            if (
                context_playlist_id is not None
                and self._current_playlist_id != context_playlist_id
            ):
                return
            try:
                on_success(result)
            except Exception:
                self._logger.exception("Erro no callback de sucesso em background")

        def _on_fail(message):
            if self._closing:
                return
            if (
                context_playlist_id is not None
                and self._current_playlist_id != context_playlist_id
            ):
                return
            if on_error:
                try:
                    on_error(message)
                except Exception:
                    self._logger.exception("Erro no callback de erro em background")
            else:
                self.statusBar().showMessage("Erro")
                QMessageBox.warning(self, "Erro", message)

        worker.succeeded.connect(_on_ok)
        worker.failed.connect(_on_fail)
        worker.cancelled.connect(self._on_task_cancelled)
        worker.progress.connect(self._on_task_progress)
        worker.finished.connect(
            lambda worker=worker: self._on_worker_finished(worker)
        )
        worker.start()
        self._sync_task_widgets()

    def _on_worker_finished(self, worker: TaskWorker):
        """Retain QThreads until Qt confirms that their event has finished."""
        self._task_controller.remove(worker)
        if getattr(self, "_worker", None) is worker:
            self._worker = None
        worker.deleteLater()
        self._cancel_tasks_btn.setEnabled(True)
        self._sync_task_widgets()
        if self._closing and not self._task_controller.running():
            QTimer.singleShot(0, self.close)

    @Slot(str)
    def _on_task_progress(self, message: str):
        if not self._closing:
            self.statusBar().showMessage(message)

    @Slot()
    def _on_task_cancelled(self):
        """Release all operation guards after the user cancels active workers."""
        self._catalog_loading.clear()
        self._epg_loading_playlists.clear()
        self._epg_loading_channels.clear()
        self._stalker_metadata_loading.clear()
        if not self._closing:
            self.statusBar().showMessage("Operação cancelada.")

    def _call_stalker(self, playlist_id: int, callback):
        return self._provider_sessions.call_stalker(playlist_id, callback)

    def _call_xtream(self, playlist_id: int, callback):
        return self._provider_sessions.call_xtream(playlist_id, callback)

    def _discard_provider_sessions(self, playlist_id: Optional[int] = None):
        self._provider_sessions.discard(playlist_id)

    @Slot()
    def _show_settings(self):
        """Show settings dialog."""
        old_vlc_path = self._settings.get("vlc_path", "")
        old_buffer = self._settings.get("buffer_size_ms", 5000)
        dialog = SettingsDialog(self._settings, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return

        self._task_controller.configure(
            self._settings.get("max_connections", 5)
        )
        new_vlc_path = self._settings.get("vlc_path", "")
        new_buffer = self._settings.get("buffer_size_ms", 5000)
        try:
            if new_vlc_path != old_vlc_path or new_buffer != old_buffer:
                self._media_player.reinitialize(new_vlc_path, new_buffer)
                self._media_player.set_video_widget(
                    self._player_widget.get_video_widget()
                )
            else:
                self._media_player.set_buffer_size(new_buffer)
            self.statusBar().showMessage("Definições aplicadas.")
        except Exception as exc:
            self._logger.error(f"Failed to apply player settings: {exc}")
            QMessageBox.critical(
                self,
                "Erro",
                f"Não foi possível aplicar as definições do VLC: {exc}",
            )

    @Slot()
    def resizeEvent(self, event):
        """Keep the toast anchored when the window is resized."""
        super().resizeEvent(event)
        if hasattr(self, "_toast"):
            self._toast.parent_resized()

    def closeEvent(self, event):
        """Handle window close - cleanup."""
        self._persist_playback_progress()
        running_workers = self._task_controller.running()
        if running_workers:
            self._closing = True
            self._task_controller.cancel_all()
            self.setEnabled(False)
            self.statusBar().showMessage(
                "A terminar operações de rede antes de fechar..."
            )
            event.ignore()
            return

        self._save_session_state()
        self._discard_provider_sessions()
        self._player_widget.close_pip()
        self._media_player.cleanup()
        event.accept()
