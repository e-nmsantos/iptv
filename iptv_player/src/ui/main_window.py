"""Main application window for the IPTV Player."""

from dataclasses import replace as dc_replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Slot
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from config import APP_VERSION
from config.settings import Settings

from ..controllers.catalog_controller import CatalogController
from ..controllers.epg_controller import EpgController
from ..controllers.playback_controller import PlaybackController
from ..controllers.playlist_controller import PlaylistController
from ..controllers.task_controller import TaskController
from ..core.backup import create_backup, read_backup
from ..core.channel import Channel
from ..core.database import DatabaseManager
from ..core.device_sync import export_device_state, import_device_state
from ..core.parental import PinAttemptLimiter
from ..core.provider_sessions import ProviderSessionManager
from ..core.task_manager import TaskWorker, report_progress
from ..core.update_manager import fetch_manifest, is_newer_version
from ..parsers.m3u_parser import M3UParser
from ..parsers.stalker_parser import StalkerParser
from ..parsers.xtream_parser import XtreamParser
from ..player.media_player import MediaPlayer
from ..utils.logger import get_logger
from .channel_list import ChannelListWidget
from .dialogs import ParentalPinDialog, PlaylistDialog, SettingsDialog, StalkerDialog, XtreamDialog
from .epg_grid_widget import EPGGridWidget
from .epg_widget import EPGWidget
from .global_search import GlobalSearchDialog
from .pill_tabs import PillTabBar
from .playback import PlaybackMixin
from .player_widget import PlayerWidget
from .playlist_widget import PlaylistWidget
from .series_browser import SeriesBrowserWidget
from .session_state import SessionStateMixin
from .theme import Palette
from .toast import Toast


class MainWindow(PlaybackMixin, SessionStateMixin, QMainWindow):
    """Main application window orchestrating all components."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("IPTV Player")
        self.setMinimumSize(1200, 750)
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

        # Saved layout margins for exiting fullscreen
        self._normal_layout_margins = (5, 5, 5, 5)
        self._is_fullscreen = False

        # Logger
        self._logger = get_logger()

        # Non-intrusive toast notifications + auto-zap guard.
        self._toast = Toast(self)
        self._auto_next_pending = False
        self._pin_attempts = PinAttemptLimiter()

        # Setup UI (global theme/QSS is applied once at the QApplication level
        # in main.py; this window only builds widgets/menus).
        self._setup_menu_bar()
        self._setup_ui()
        self._setup_status_bar()
        self._setup_shortcuts()
        self._connect_signals()
        self._load_playlists()

    def _setup_menu_bar(self):
        """Set up the application menu bar."""
        menubar = self.menuBar()

        style = self.style()
        self._action_import_m3u = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "Importar M3U / M3U8...",
            self,
        )
        self._action_import_m3u.setShortcut(QKeySequence("Ctrl+M"))
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

        view_menu = menubar.addMenu("Ver")
        view_menu.addAction(self._action_global_search)
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
        self._toolbar.addAction(self._action_import_m3u)
        self._toolbar.addAction(self._action_import_xtream)
        self._toolbar.addAction(self._action_import_stalker)
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

        self._content_tabs = PillTabBar(["Live", "Vod", "Series"])
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

        # Player
        self._player_widget = PlayerWidget(self._media_player, self._settings)
        right_layout.addWidget(self._player_widget, 3)

        # Bottom tabs (EPG)
        self._bottom_tabs = QTabWidget()

        self._epg_widget = EPGWidget()
        self._bottom_tabs.addTab(self._epg_widget, "📅 EPG")

        self._epg_grid_widget = EPGGridWidget()
        self._epg_grid_widget.set_programs_provider(self._epg_programs_for_channel)
        self._bottom_tabs.addTab(self._epg_grid_widget, "🗓 Guia")

        empty_tab = QWidget()
        info_layout = QVBoxLayout(empty_tab)
        info_layout.setContentsMargins(8, 8, 8, 8)
        info_title = QLabel("REPRODUZIDOS RECENTEMENTE")
        info_title.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-weight: 700;")
        info_layout.addWidget(info_title)
        self._history_list = QListWidget()
        self._history_list.setAlternatingRowColors(True)
        info_layout.addWidget(self._history_list)
        self._bottom_tabs.addTab(empty_tab, "📋 Info")

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
        self._bottom_tabs.addTab(resume_tab, "▶ Continuar")

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
        if channel.stream_type in ("vod", "movie"):
            target_tab = 1
        elif channel.stream_type == "series":
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
    def _copy_device_sync(self):
        """Copy credential-free favorites/resume state for the TV pairing page."""
        if not self._current_playlist_id:
            QMessageBox.information(
                self, "Sincronizar TV", "Seleciona primeiro uma playlist."
            )
            return
        payload = export_device_state(self._db, self._current_playlist_id)
        QApplication.clipboard().setText(payload)
        QMessageBox.information(
            self,
            "Sincronizar TV",
            "Os favoritos e pontos de retoma foram copiados. Abre o QR code da TV "
            "no navegador e cola os dados na secção Sincronização. Não são incluídos "
            "URLs nem credenciais.",
        )

    @Slot()
    def _import_device_sync(self):
        """Merge credential-free favorites/resume copied from the TV."""
        if not self._current_playlist_id:
            QMessageBox.information(
                self, "Sincronizar TV", "Seleciona primeiro uma playlist."
            )
            return
        payload, accepted = QInputDialog.getMultiLineText(
            self,
            "Sincronizar TV",
            "Cola o estado copiado da página de emparelhamento da TV:",
        )
        if not accepted or not payload.strip():
            return
        try:
            result = import_device_state(
                self._db, self._current_playlist_id, payload.strip()
            )
        except (ValueError, TypeError, KeyError) as error:
            QMessageBox.warning(self, "Sincronizar TV", str(error))
            return
        self._distribute_channels(
            self._db.get_channels(self._current_playlist_id)
        )
        QMessageBox.information(
            self,
            "Sincronizar TV",
            f"Importados {result['favorites']} favoritos e "
            f"{result['progress']} pontos de retoma.",
        )

    @Slot()
    def _export_backup(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar backup cifrado",
            f"IPTVPlayer-backup-{datetime.now():%Y%m%d}.iptvbackup",
            "Backup IPTV Player (*.iptvbackup)",
        )
        if not path:
            return
        password, accepted = QInputDialog.getText(
            self,
            "Proteger backup",
            "Palavra-passe (mínimo 8 caracteres):",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return
        confirmation, accepted = QInputDialog.getText(
            self,
            "Confirmar palavra-passe",
            "Repete a palavra-passe:",
            QLineEdit.EchoMode.Password,
        )
        if not accepted or confirmation != password:
            QMessageBox.warning(self, "Backup", "As palavras-passe não coincidem.")
            return

        def export():
            create_backup(Path(path), self._db.export_backup_data(), password)
            return path

        self._run_background(
            export,
            lambda saved: QMessageBox.information(
                self, "Backup", f"Backup criado em:\n{saved}"
            ),
            status_message="A criar backup cifrado...",
        )

    @Slot()
    def _import_backup(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Importar backup cifrado",
            "",
            "Backup IPTV Player (*.iptvbackup)",
        )
        if not path:
            return
        password, accepted = QInputDialog.getText(
            self,
            "Abrir backup",
            "Palavra-passe do backup:",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return

        def restore():
            data = read_backup(Path(path), password)
            return self._db.import_backup_data(data)

        def restored(playlist_ids):
            self._load_playlists()
            QMessageBox.information(
                self,
                "Backup",
                f"{len(playlist_ids)} playlist(s) importada(s). Os dados existentes foram preservados.",
            )

        self._run_background(
            restore,
            restored,
            status_message="A importar backup cifrado...",
        )

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

        # Vod list (movies need lazy resolve for Stalker before playback)
        self._vod_list.channel_selected.connect(self._on_vod_selected)
        self._vod_list.favorite_toggled.connect(self._on_favorite_toggled)
        self._vod_list.diagnostic_requested.connect(self._diagnose_channel)

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
        self._media_player.time_changed.connect(self._track_playback_time)
        self._media_player.length_changed.connect(self._track_playback_length)
        self._media_player.media_ended.connect(self._on_media_ended)
        self._media_player.error_occurred.connect(self._on_media_error)

    def _load_playlists(self):
        """Load saved playlists from database."""
        try:
            playlists = self._playlist_controller.list()
            self._playlist_widget.set_playlists(playlists)
            self._restore_session_state(playlists)
        except Exception as e:
            self._logger.error(f"Failed to load playlists: {e}")

    @Slot()
    def _import_m3u(self):
        """Open M3U import dialog and parse playlist."""
        dialog = PlaylistDialog(self)
        if dialog.exec() != PlaylistDialog.DialogCode.Accepted:
            return

        source = dialog.playlist_path or dialog.playlist_url
        if not source:
            QMessageBox.warning(self, "Aviso", "Seleciona um ficheiro ou URL.")
            return

        name = dialog.playlist_name
        epg_source = dialog.epg_source
        if not name:
            QMessageBox.warning(
                self, "Aviso", "Indica um nome para a playlist."
            )
            return

        def import_func():
            parser = M3UParser(
                timeout=self._settings.get("network_timeout_seconds", 30),
                user_agent=self._settings.get("user_agent", ""),
            )
            playlist = parser.parse(source, name)
            if epg_source:
                if epg_source.startswith(("http://", "https://")):
                    playlist.epg_url = epg_source
                else:
                    playlist.epg_source = epg_source
            return playlist

        self._run_import(import_func, "A importar playlist M3U...")

    @Slot()
    def _import_xtream(self):
        """Open Xtream login dialog and fetch channels."""
        dialog = XtreamDialog(self)
        if dialog.exec() != XtreamDialog.DialogCode.Accepted:
            return

        server = dialog.server_url
        username = dialog.username
        password = dialog.password
        name = dialog.playlist_name

        if not all([name, server, username, password]):
            QMessageBox.warning(self, "Aviso", "Preenche todos os campos.")
            return

        def import_func():
            with XtreamParser(
                server,
                username,
                password,
                timeout=self._settings.get("network_timeout_seconds", 30),
            ) as parser:
                parser.authenticate()
                playlist = parser.get_full_playlist(
                    should_cancel=lambda: QThread.currentThread().isInterruptionRequested(),
                    include_vod=False,
                    include_series=False,
                )
            playlist.name = name
            return playlist

        self._run_import(import_func, "A ligar ao servidor Xtream...")

    @Slot()
    def _import_stalker(self):
        """Open Stalker login dialog and fetch channels."""
        dialog = StalkerDialog(self)
        if dialog.exec() != StalkerDialog.DialogCode.Accepted:
            return

        portal = dialog.portal_url
        mac = dialog.mac_address
        name = dialog.playlist_name

        if not all([name, portal, mac]):
            QMessageBox.warning(self, "Aviso", "Preenche todos os campos.")
            return

        def import_func():
            with StalkerParser(
                portal,
                mac,
                timeout=self._settings.get("network_timeout_seconds", 30),
            ) as parser:
                parser.authenticate()
                playlist = parser.get_full_playlist(
                    should_cancel=lambda: QThread.currentThread().isInterruptionRequested(),
                )
            playlist.name = name
            return playlist

        self._run_import(import_func, "A ligar ao portal Stalker...")

    def _run_import(self, import_func, status_message: str):
        """Run import in a worker thread."""
        if self._closing:
            return
        if getattr(self, "_worker", None) and self._worker.isRunning():
            self.statusBar().showMessage("Já existe uma importação em curso.")
            return
        self.statusBar().showMessage(status_message)

        def limited_import_func():
            if QThread.currentThread().isInterruptionRequested():
                return None
            return self._task_controller.execute(import_func)

        self._worker = TaskWorker(limited_import_func)
        self._task_controller.add(self._worker)
        self._worker.succeeded.connect(self._on_import_finished)
        self._worker.failed.connect(self._on_import_error)
        self._worker.cancelled.connect(self._on_task_cancelled)
        self._worker.progress.connect(self._on_task_progress)
        self._worker.finished.connect(
            lambda worker=self._worker: self._on_worker_finished(worker)
        )
        self._worker.start()
        self._sync_task_widgets()

    def _run_background(
        self,
        func,
        on_success,
        on_error=None,
        status_message: str = "",
        context_playlist_id: Optional[int] = None,
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
            return self._task_controller.execute(func)

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
            on_success(result)

        def _on_fail(message):
            if self._closing:
                return
            if (
                context_playlist_id is not None
                and self._current_playlist_id != context_playlist_id
            ):
                return
            if on_error:
                on_error(message)
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

    def _distribute_channels(self, channels: list):
        """Split channels by stream_type across the Live/Vod/Series pages."""
        live = [c for c in channels if c.stream_type == "live"]
        vod = [c for c in channels if c.stream_type in ("vod", "movie")]
        series = [c for c in channels if c.stream_type == "series"]
        self._live_list.set_channels(live)
        self._vod_list.set_channels(vod)
        self._series_browser.set_shows(series)
        self._refresh_locked_groups()

    @Slot(int)
    def _on_content_tab_changed(self, index: int):
        self._content_stack.setCurrentIndex(index)
        self._ensure_catalog_for_tab(index)

    @Slot()
    def _refresh_current_catalog(self):
        if not self._current_playlist_id:
            self.statusBar().showMessage("Seleciona primeiro uma playlist.")
            return
        index = self._content_stack.currentIndex()
        self._ensure_catalog_for_tab(index, force=True)

    def _ensure_catalog_for_tab(self, index: int, force: bool = False):
        """Load VOD/series only when its tab is first opened or refreshed."""
        playlist_id = self._current_playlist_id
        content_type = {0: "live", 1: "vod", 2: "series"}.get(index)
        if not playlist_id or not content_type:
            return

        playlist = self._db.get_playlist(playlist_id)
        source_type = playlist.get("source_type") if playlist else ""
        if not playlist or (
            source_type not in ("stalker", "xtream")
            and source_type not in ("m3u", "m3u_plus")
        ):
            return
        key = (playlist_id, content_type)
        if key in self._catalog_loading:
            self.statusBar().showMessage(
                f"O catálogo {content_type.upper()} já está a carregar..."
            )
            return

        state = self._db.get_catalog_state(playlist_id, content_type)
        if state and state.get("status") == "ready" and not force:
            return

        self._catalog_loading.add(key)
        previous_count = state.get("item_count", 0) if state else 0
        self._db.set_catalog_state(
            playlist_id, content_type, "loading", previous_count
        )
        target_widget = {0: self._live_list, 1: self._vod_list}.get(index)
        if target_widget is not None:
            target_widget.set_status_message(
                f"A carregar catálogo {content_type.upper()}..."
            )
        def fetch_and_store():
            def should_cancel():
                return QThread.currentThread().isInterruptionRequested()

            return self._catalog_controller.refresh(
                playlist_id,
                content_type,
                should_cancel=should_cancel,
                progress=report_progress,
            )

        def on_success(channels):
            self._catalog_loading.discard(key)
            if channels is None:
                return
            if self._current_playlist_id == playlist_id:
                if target_widget is not None:
                    target_widget.set_status_message("")
                self._distribute_channels(channels)
                accepted_types = (
                    ("vod", "movie")
                    if content_type == "vod"
                    else (content_type,)
                )
                item_count = sum(
                    1 for channel in channels
                    if channel.stream_type in accepted_types
                )
                self.statusBar().showMessage(
                    f"Catálogo {content_type.upper()} atualizado: "
                    f"{item_count} itens."
                )

        def on_error(message):
            self._catalog_loading.discard(key)
            self._db.set_catalog_state(
                playlist_id, content_type, "error", previous_count, message
            )
            if self._current_playlist_id == playlist_id:
                if target_widget is not None:
                    target_widget.set_status_message(
                        f"Falha ao carregar: {message}"
                    )
                self.statusBar().showMessage(
                    f"Falha ao carregar {content_type.upper()}: {message}"
                )

        self._run_background(
            fetch_and_store,
            on_success,
            on_error,
            status_message=f"A carregar catálogo {content_type.upper()}...",
        )

    def _epg_channel_maps(self, channels: list):
        """Return canonical EPG IDs and display names for live channels."""
        return self._epg_controller.channel_maps(channels)

    def _show_epg_programs(self, programs: list, channels: list, playlist_id: Optional[int] = None):
        """Group normalized programs and hand them to the EPG widget.

        Also seeds the guide-grid's in-memory cache from the same grouped
        data (when `playlist_id` is given) so the grid never needs its own
        per-channel DB round-trips — see `_epg_programs_for_channel`.
        """
        grouped = {}
        for program in programs:
            grouped.setdefault(program.channel_id, []).append(program)
        _, channel_names = self._epg_channel_maps(channels)
        self._epg_widget.set_epg_data(grouped, channel_names)
        if playlist_id is not None:
            self._epg_grid_cache = grouped
            self._epg_grid_cache_playlist_id = playlist_id

    def _load_playlist_epg(
        self, playlist_id: int, channels: list, force: bool = False
    ):
        """Show cached EPG and refresh a configured XMLTV source when stale."""
        cached = self._epg_controller.cached(playlist_id)
        self._show_epg_programs(cached, channels, playlist_id)

        playlist = self._db.get_playlist(playlist_id)
        if not playlist:
            return
        source = playlist.get("epg_url") or playlist.get("epg_source")
        if not source or playlist.get("source_type") not in ("m3u", "m3u_plus"):
            return
        if playlist_id in self._epg_loading_playlists:
            return

        if not self._epg_controller.should_refresh(playlist_id, cached, force):
            return

        self._epg_loading_playlists.add(playlist_id)

        def fetch_and_cache():
            return self._epg_controller.refresh_xmltv(
                playlist_id, source, channels
            )

        def on_success(programs):
            self._epg_loading_playlists.discard(playlist_id)
            if self._current_playlist_id == playlist_id:
                self._show_epg_programs(programs, channels, playlist_id)
                self.statusBar().showMessage(
                    f"EPG atualizado: {len(programs)} programas."
                )

        def on_error(message):
            self._epg_loading_playlists.discard(playlist_id)
            self._logger.warning(f"Failed to update XMLTV EPG: {message}")
            if self._current_playlist_id == playlist_id:
                self.statusBar().showMessage(f"Não foi possível atualizar o EPG: {message}")

        self._run_background(
            fetch_and_cache,
            on_success,
            on_error,
            status_message="A atualizar o guia EPG...",
        )

    @Slot()
    def _refresh_current_epg(self):
        """Force a refresh of the current playlist's configured XMLTV source."""
        if not self._current_playlist_id:
            self.statusBar().showMessage("Seleciona primeiro uma playlist.")
            return
        playlist = self._db.get_playlist(self._current_playlist_id)
        if playlist and playlist.get("source_type") in ("xtream", "stalker"):
            self.statusBar().showMessage(
                "Nesta playlist, o EPG é atualizado ao selecionar cada canal."
            )
            return
        if not playlist or not (
            playlist.get("epg_url") or playlist.get("epg_source")
        ):
            self.statusBar().showMessage(
                "Esta playlist não tem uma fonte XMLTV configurada."
            )
            return
        channels = self._db.get_channels(self._current_playlist_id)
        self._load_playlist_epg(self._current_playlist_id, channels, force=True)

    def _load_channel_epg(self, channel: Channel):
        """Display cached EPG and lazily refresh Xtream EPG for one channel."""
        playlist_id = self._current_playlist_id
        channel_id = channel.epg_channel_id or channel.tvg_id or channel.xtream_id
        if not playlist_id or not channel_id:
            return

        cached = self._epg_controller.cached(playlist_id, channel_id)
        if cached:
            self._epg_widget.add_channel_programs(
                channel_id, cached, channel.name
            )
        self._epg_widget.select_channel(channel_id)

        if channel.source not in ("xtream", "stalker"):
            return
        now = datetime.now(cached[0].start.tzinfo if cached else None)
        if cached and max(program.stop for program in cached) > now + timedelta(hours=2):
            return

        key = (playlist_id, channel.database_id)
        if key in self._epg_loading_channels:
            return
        self._epg_loading_channels.add(key)

        def fetch_and_cache():
            if channel.source == "xtream":
                programs = self._call_xtream(
                    playlist_id,
                    lambda parser: parser.get_epg_programs(
                        channel.xtream_id, channel_id=channel_id
                    ),
                )
            else:
                programs = self._call_stalker(
                    playlist_id,
                    lambda parser: parser.get_epg_programs(channel_id),
                )
            self._db.replace_channel_epg(playlist_id, channel_id, programs)
            return programs

        def on_success(programs):
            self._epg_loading_channels.discard(key)
            if self._current_playlist_id == playlist_id:
                self._epg_widget.add_channel_programs(
                    channel_id, programs, channel.name
                )
                self._epg_widget.select_channel(channel_id)

        def on_error(message):
            self._epg_loading_channels.discard(key)
            self._logger.warning(f"Failed to update Xtream EPG: {message}")

        self._run_background(fetch_and_cache, on_success, on_error)

    def _on_live_page_changed(self):
        """Keep the EPG guide grid in sync with the Live list — but only do
        any work when the Guia tab is actually visible. This signal fires on
        every search keystroke/category click/page turn, so skipping it here
        when the tab isn't shown avoids unnecessary EPG cache/fetch work on
        every filter change."""
        if self._bottom_tabs.currentWidget() is not self._epg_grid_widget:
            return
        self._refresh_epg_grid()

    @Slot(int)
    def _on_bottom_tab_changed(self, index: int):
        if self._bottom_tabs.widget(index) is self._epg_grid_widget:
            self._refresh_epg_grid()

    def _refresh_epg_grid(self):
        playlist_id = self._current_playlist_id
        if playlist_id and self._epg_grid_cache_playlist_id != playlist_id:
            self._epg_grid_cache = {}
            programs = self._db.get_playlist_epg(playlist_id)
            for program in programs:
                self._epg_grid_cache.setdefault(program.channel_id, []).append(program)
            self._epg_grid_cache_playlist_id = playlist_id
        self._epg_grid_widget.set_channels(self._live_list.get_current_page_channels())

    def _epg_programs_for_channel(self, channel: Channel) -> list:
        """In-memory cache lookup used by the guide grid; never hits the DB."""
        if self._epg_grid_cache_playlist_id != self._current_playlist_id:
            return []
        channel_id = channel.epg_channel_id or channel.tvg_id or channel.xtream_id
        return self._epg_grid_cache.get(channel_id, [])

    def _ensure_epg_for_channels(self, channels: list):
        """Lazily fetch EPG for exactly the channels currently shown in the
        guide grid, one at a time, reusing the same fetch+cache flow as
        `_load_channel_epg` — never a bulk fetch for the whole catalog."""
        playlist_id = self._current_playlist_id
        if not playlist_id:
            return

        to_fetch = []
        for channel in channels:
            if channel.source not in ("xtream", "stalker"):
                continue
            channel_id = channel.epg_channel_id or channel.tvg_id or channel.xtream_id
            if not channel_id:
                continue
            key = (playlist_id, channel.database_id)
            if key in self._epg_loading_channels:
                continue
            cached = self._epg_grid_cache.get(channel_id, [])
            now = datetime.now(cached[0].start.tzinfo if cached else None)
            if cached and max(program.stop for program in cached) > now + timedelta(hours=2):
                continue
            to_fetch.append((channel, channel_id))

        def fetch_next(index: int = 0):
            if index >= len(to_fetch) or self._current_playlist_id != playlist_id:
                return
            channel, channel_id = to_fetch[index]
            key = (playlist_id, channel.database_id)
            self._epg_loading_channels.add(key)

            def fetch_and_cache():
                if channel.source == "xtream":
                    programs = self._call_xtream(
                        playlist_id,
                        lambda parser: parser.get_epg_programs(
                            channel.xtream_id, channel_id=channel_id
                        ),
                    )
                else:
                    programs = self._call_stalker(
                        playlist_id,
                        lambda parser: parser.get_epg_programs(channel_id),
                    )
                self._db.replace_channel_epg(playlist_id, channel_id, programs)
                return programs

            def on_success(programs):
                self._epg_loading_channels.discard(key)
                if self._current_playlist_id == playlist_id:
                    if self._epg_grid_cache_playlist_id == playlist_id:
                        self._epg_grid_cache[channel_id] = programs
                    self._epg_grid_widget.refresh()
                QTimer.singleShot(400, lambda: fetch_next(index + 1))

            def on_error(message):
                self._epg_loading_channels.discard(key)
                self._logger.warning(f"Failed to update guide EPG: {message}")
                QTimer.singleShot(400, lambda: fetch_next(index + 1))

            self._run_background(fetch_and_cache, on_success, on_error)

        fetch_next()

    @Slot(object, object)
    def _play_catchup(self, channel: Channel, program):
        """Play a past programme via Xtream timeshift (catch-up)."""
        if channel.source != "xtream" or not channel.has_archive:
            return
        playlist_id = self._current_playlist_id
        if not playlist_id:
            return

        def build_url():
            return self._call_xtream(
                playlist_id,
                lambda parser: parser.build_timeshift_url(
                    channel.xtream_id,
                    program.start,
                    max(1, program.duration_minutes),
                ),
            )

        def on_built(timeshift_url):
            self._play_channel(
                dc_replace(
                    channel,
                    url=timeshift_url,
                    name=f"{channel.name} · {program.title}",
                )
            )

        def on_failed(message):
            self._logger.warning(
                f"Failed to build catch-up URL for {channel.name}: {message}"
            )

        # Build the timeshift URL on a worker thread: authenticate() on a
        # cold Xtream session performs blocking HTTP and would freeze the UI.
        self._run_background(
            build_url,
            on_built,
            on_error=on_failed,
            status_message=f"A obter catch-up: {channel.name}...",
            context_playlist_id=playlist_id,
        )

    @Slot(str, bool)
    def _on_group_lock_toggle_requested(self, group: str, new_locked_state: bool):
        """Persist a category lock/unlock and refresh all three catalog widgets."""
        if not self._current_playlist_id:
            return
        if new_locked_state:
            self._db.lock_group(self._current_playlist_id, group)
        else:
            self._db.unlock_group(self._current_playlist_id, group)
        self._refresh_locked_groups()

    def _refresh_locked_groups(self):
        if not self._current_playlist_id:
            return
        locked = self._db.get_locked_groups(self._current_playlist_id)
        for widget in (self._live_list, self._vod_list, self._series_browser):
            widget.set_locked_groups(locked)

    def _on_locked_group_access_requested(self, widget, group: str):
        """Prompt for the parental PIN and unlock the category for this session."""
        if not self._settings.get("parental_lock_enabled", False):
            widget.unlock_group_session(group)
            return
        pin_hash = self._settings.get("parental_pin_hash", "")
        pin_salt = self._settings.get("parental_pin_salt", "")
        if not pin_hash:
            widget.unlock_group_session(group)
            return
        if not self._pin_attempts.is_allowed():
            QMessageBox.warning(
                self,
                "PIN temporariamente bloqueado",
                f"Aguarda {self._pin_attempts.remaining_seconds} segundos antes de tentar novamente.",
            )
            return
        dialog = ParentalPinDialog(self, title=f"PIN para desbloquear '{group}'")
        if dialog.exec() != ParentalPinDialog.DialogCode.Accepted:
            return
        from ..core.parental import verify_pin

        if verify_pin(dialog.pin, pin_salt, pin_hash):
            self._pin_attempts.reset()
            widget.unlock_group_session(group)
        else:
            self._pin_attempts.register_failure()
            QMessageBox.warning(self, "PIN incorreto", "O PIN introduzido está incorreto.")

    def _call_stalker(self, playlist_id: int, callback):
        return self._provider_sessions.call_stalker(playlist_id, callback)

    def _call_xtream(self, playlist_id: int, callback):
        return self._provider_sessions.call_xtream(playlist_id, callback)

    def _discard_provider_sessions(self, playlist_id: Optional[int] = None):
        self._provider_sessions.discard(playlist_id)

    @Slot(object)
    def _on_import_finished(self, playlist):
        """Handle successful playlist import."""
        if playlist is None:
            self.statusBar().showMessage("Importação cancelada.")
            return
        self.statusBar().showMessage(f"Playlist importada: {playlist.name}")

        try:
            playlist_id, channels = self._playlist_controller.import_playlist(playlist)
            self._load_playlists()
            self._playlist_widget.select_playlist(playlist_id)

            # Select the imported playlist
            self._current_playlist_id = playlist_id

            self._distribute_channels(channels)
            self._load_playlist_epg(playlist_id, channels)

            QMessageBox.information(
                self,
                "Importado com sucesso",
                f"Playlist '{playlist.name}' importada!\n"
                f"{len(channels)} itens carregados."
            )
        except Exception as e:
            self._logger.error(f"Failed to save playlist: {e}")
            QMessageBox.critical(self, "Erro", f"Falha ao guardar playlist: {e}")

    @Slot(str)
    def _on_import_error(self, error_message: str):
        """Handle import errors."""
        self.statusBar().showMessage("Erro na importação")
        QMessageBox.critical(self, "Erro de Importação", error_message)

    @Slot(int)
    def _on_playlist_selected(self, playlist_id: int):
        """Handle playlist selection."""
        self._current_playlist_id = playlist_id
        self._refresh_history()
        self._refresh_resume()
        try:
            playlist_details, channels = self._playlist_controller.open(playlist_id)
            if playlist_details and playlist_details.get("source_type") in (
                "m3u",
                "m3u_plus",
            ):
                repaired = False
                for channel in channels:
                    inferred_type = M3UParser.infer_stream_type(
                        channel.url, channel.group, channel.name
                    )
                    if inferred_type != channel.stream_type:
                        channel.stream_type = inferred_type
                        repaired = True
                if repaired:
                    self._db.update_channel_stream_types(playlist_id, channels)
            if (
                playlist_details
                and playlist_details.get("source_type") == "stalker"
                and any(not channel.user_agent or not channel.referer for channel in channels)
            ):
                with StalkerParser(
                    playlist_details["server_url"],
                    playlist_details["mac_address"],
                    timeout=self._settings.get("network_timeout_seconds", 30),
                ) as parser:
                    playback_headers = parser.playback_headers()
                    user_agent = playback_headers.get("User-Agent", "")
                    referer = playback_headers.get("Referer", "")
                self._db.update_stalker_headers(
                    playlist_id, user_agent, referer
                )
                for channel in channels:
                    if channel.source == "stalker":
                        channel.user_agent = user_agent
                        channel.referer = referer
            self._distribute_channels(channels)
            self._load_playlist_epg(playlist_id, channels)
            self._ensure_catalog_for_tab(self._content_stack.currentIndex())
            self._refresh_stalker_metadata_if_needed(
                playlist_id, playlist_details, channels
            )

            playlists = self._playlist_controller.list()
            pl_name = next(
                (p["name"] for p in playlists if p["id"] == playlist_id),
                "Playlist"
            )
            self.statusBar().showMessage(f"Playlist: {pl_name} | {len(channels)} itens")
        except Exception as e:
            self._logger.error(f"Failed to load channels: {e}")

    def _refresh_stalker_metadata_if_needed(
        self, playlist_id: int, playlist: Optional[dict], channels: list
    ):
        """Repair country/category metadata in already-saved Stalker playlists."""
        if (
            not playlist
            or playlist.get("source_type") != "stalker"
            or any(channel.country_code for channel in channels)
            or playlist_id in self._stalker_metadata_loading
        ):
            return

        self._stalker_metadata_loading.add(playlist_id)

        def fetch_and_update():
            with StalkerParser(
                playlist["server_url"],
                playlist["mac_address"],
                timeout=self._settings.get("network_timeout_seconds", 30),
            ) as parser:
                refreshed = parser.get_full_playlist().channels
            self._db.update_stalker_channel_metadata(playlist_id, refreshed)
            return self._db.get_channels(playlist_id)

        def on_success(refreshed):
            self._stalker_metadata_loading.discard(playlist_id)
            if self._current_playlist_id == playlist_id:
                self._distribute_channels(refreshed)
                self.statusBar().showMessage(
                    "Canais organizados pelas categorias originais do portal."
                )

        def on_error(message):
            self._stalker_metadata_loading.discard(playlist_id)
            self._logger.warning(
                f"Failed to refresh Stalker category metadata: {message}"
            )

        self._run_background(
            fetch_and_update,
            on_success,
            on_error,
            status_message="A organizar canais por região e categoria...",
        )

    @Slot(int)
    def _on_playlist_deleted(self, playlist_id: int):
        """Handle playlist deletion."""
        try:
            self._playlist_controller.delete(playlist_id)
            self._load_playlists()
            self._distribute_channels([])
            self._epg_widget.clear()
            self._discard_provider_sessions(playlist_id)
            if self._current_playlist_id == playlist_id:
                self._current_playlist_id = None
            self._catalog_loading = {
                key for key in self._catalog_loading if key[0] != playlist_id
            }
            self.statusBar().showMessage("Playlist eliminada.")
        except Exception as e:
            self._logger.error(f"Failed to delete playlist: {e}")
            QMessageBox.critical(self, "Erro", f"Falha ao eliminar playlist: {e}")

    @Slot(int, str)
    def _on_playlist_renamed(self, playlist_id: int, new_name: str):
        """Persist a user-selected playlist name and refresh the sidebar."""
        try:
            self._playlist_controller.rename(playlist_id, new_name)
            self._load_playlists()
            self._playlist_widget.select_playlist(playlist_id)
            self.statusBar().showMessage(
                f"Playlist alterada para: {new_name}"
            )
        except Exception as exc:
            self._logger.error(f"Failed to rename playlist: {exc}")
            QMessageBox.critical(
                self, "Erro", f"Não foi possível alterar o nome: {exc}"
            )

    @Slot(int)
    def _edit_playlist_connection(self, playlist_id: int):
        details = self._db.get_playlist(playlist_id)
        if not details:
            return
        source_type = details["source_type"]
        if source_type in ("m3u", "m3u_plus"):
            dialog = PlaylistDialog(self, details)
        elif source_type == "xtream":
            dialog = XtreamDialog(self, details)
        elif source_type == "stalker":
            dialog = StalkerDialog(self, details)
        else:
            QMessageBox.warning(self, "Ligação", "Tipo de playlist não suportado.")
            return
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        if source_type in ("m3u", "m3u_plus"):
            connection_input = {
                "name": dialog.playlist_name,
                "url": dialog.playlist_url,
                "file_path": dialog.playlist_path,
                "epg": dialog.epg_source,
            }
        elif source_type == "xtream":
            connection_input = {
                "name": dialog.playlist_name,
                "server_url": dialog.server_url,
                "username": dialog.username,
                "password": dialog.password,
            }
        else:
            connection_input = {
                "name": dialog.playlist_name,
                "server_url": dialog.portal_url,
                "mac_address": dialog.mac_address,
            }

        def test_connection():
            if source_type in ("m3u", "m3u_plus"):
                source = connection_input["file_path"] or connection_input["url"]
                if not source:
                    raise ValueError("Indica uma URL ou ficheiro M3U.")
                parsed = M3UParser(
                    timeout=self._settings.get("network_timeout_seconds", 30),
                    user_agent=self._settings.get("user_agent", ""),
                ).parse(source, connection_input["name"])
                epg = connection_input["epg"]
                epg_is_url = epg.startswith(("http://", "https://"))
                return {
                    "name": connection_input["name"],
                    "url": connection_input["url"],
                    "file_path": connection_input["file_path"],
                    "epg_url": epg if epg_is_url else "",
                    "epg_source": "" if epg_is_url else epg,
                }, parsed.channels
            if source_type == "xtream":
                with XtreamParser(
                    connection_input["server_url"],
                    connection_input["username"],
                    connection_input["password"],
                    timeout=self._settings.get("network_timeout_seconds", 30),
                ) as parser:
                    parser.authenticate()
                return {
                    "name": connection_input["name"],
                    "server_url": connection_input["server_url"],
                    "username": connection_input["username"],
                    "password": connection_input["password"],
                }, None
            with StalkerParser(
                connection_input["server_url"],
                connection_input["mac_address"],
                timeout=self._settings.get("network_timeout_seconds", 30),
            ) as parser:
                parser.authenticate()
            return {
                "name": connection_input["name"],
                "server_url": connection_input["server_url"],
                "mac_address": connection_input["mac_address"],
            }, None

        def on_success(result):
            values, parsed_channels = result
            self._playlist_controller.update_connection(playlist_id, values)
            if parsed_channels is not None:
                for content_type, stream_types in (
                    ("live", ("live",)),
                    ("vod", ("vod", "movie")),
                    ("series", ("series",)),
                ):
                    self._db.replace_catalog(
                        playlist_id,
                        content_type,
                        [
                            channel
                            for channel in parsed_channels
                            if channel.stream_type in stream_types
                        ],
                    )
            self._discard_provider_sessions(playlist_id)
            self._load_playlists()
            self._playlist_widget.select_playlist(playlist_id)
            self._on_playlist_selected(playlist_id)
            self.statusBar().showMessage("Ligação testada e guardada.")

        self._run_background(
            test_connection,
            on_success,
            status_message="A testar ligação antes de guardar...",
            context_playlist_id=playlist_id,
        )

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
    def _check_for_updates(self):
        """Check the configured manifest for a newer release."""
        url = (self._settings.get("update_manifest_url") or "").strip()
        if not url:
            QMessageBox.information(
                self,
                "Atualizações",
                "Não foi configurado um repositório de atualizações.\n"
                "Define o URL do manifesto em Definições → Rede → "
                "URL do manifesto de atualizações.",
            )
            return

        def fetch():
            return fetch_manifest(url, timeout=15)

        def show(info):
            if is_newer_version(info.version, APP_VERSION):
                QMessageBox.information(
                    self,
                    "Atualização disponível",
                    f"Está disponível a versão {info.version}\n"
                    f"(atual: {APP_VERSION}).",
                )
            else:
                QMessageBox.information(
                    self,
                    "Atualizações",
                    f"Estás a usar a versão mais recente ({APP_VERSION}).",
                )

        def fail(message):
            QMessageBox.warning(
                self, "Atualizações", f"Não foi possível verificar: {message}"
            )

        self._run_background(
            fetch, show, fail, status_message="A verificar atualizações..."
        )

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
