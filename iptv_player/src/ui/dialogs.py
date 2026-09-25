"""Dialog windows for the IPTV Player application."""

from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .theme import Palette


class PlaylistDialog(QDialog):
    """Dialog for importing M3U playlists from URL or file."""

    def __init__(self, parent=None, values: dict = None):
        super().__init__(parent)
        self._values = values or {}
        self.setWindowTitle("Importar Playlist M3U")
        self.setMinimumWidth(500)
        self._playlist_path = ""
        self._playlist_url = ""
        self._setup_ui()
        self._name_input.setText(self._values.get("name", ""))
        self._url_input.setText(self._values.get("url", ""))
        self._epg_input.setText(
            self._values.get("epg_url") or self._values.get("epg_source", "")
        )
        self._playlist_path = self._values.get("file_path", "")
        if self._playlist_path:
            self._file_path_label.setText(self._playlist_path)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("Importar Playlist M3U / M3U8")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        # URL import
        url_group = QGroupBox("A partir de URL")
        url_layout = QHBoxLayout(url_group)
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://exemplo.com/playlist.m3u")
        url_layout.addWidget(self._url_input)
        layout.addWidget(url_group)

        # File import
        file_group = QGroupBox("A partir de ficheiro")
        file_layout = QHBoxLayout(file_group)
        self._file_path_label = QLabel("Nenhum ficheiro selecionado")
        self._file_path_label.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        self._browse_btn = QPushButton("Procurar...")
        self._browse_btn.clicked.connect(self._browse_file)
        file_layout.addWidget(self._file_path_label, 1)
        file_layout.addWidget(self._browse_btn)
        layout.addWidget(file_group)

        # Playlist name
        name_layout = QFormLayout()
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Ex.: TV de Casa")
        name_layout.addRow("Nome da playlist:", self._name_input)

        epg_layout = QHBoxLayout()
        self._epg_input = QLineEdit()
        self._epg_input.setPlaceholderText(
            "Opcional: URL ou ficheiro XMLTV / XMLTV.GZ"
        )
        epg_browse = QPushButton("...")
        epg_browse.setMaximumWidth(35)
        epg_browse.clicked.connect(self._browse_epg)
        epg_layout.addWidget(self._epg_input)
        epg_layout.addWidget(epg_browse)
        name_layout.addRow("Fonte EPG:", epg_layout)
        layout.addLayout(name_layout)

        layout.addStretch()

        # Buttons
        buttons = QDialogButtonBox()
        self._import_btn = buttons.addButton("Importar", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self):
        if not self.playlist_path and not self.playlist_url:
            QMessageBox.warning(
                self, "Aviso", "Por favor, indica um URL ou seleciona um ficheiro."
            )
            self._url_input.setFocus()
            return
        if not self.playlist_name:
            QMessageBox.warning(
                self, "Aviso", "Por favor, indica um nome para a playlist."
            )
            self._name_input.setFocus()
            return
        self.accept()

    def _browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar Playlist", "",
            "Ficheiros M3U (*.m3u *.m3u8);;Todos os ficheiros (*.*)"
        )
        if file_path:
            self._playlist_path = file_path
            self._file_path_label.setText(file_path)
            self._file_path_label.setStyleSheet(f"color: {Palette.TEXT_PRIMARY};")
            if not self._name_input.text():
                from pathlib import Path
                self._name_input.setText(Path(file_path).stem)

    def _browse_epg(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar fonte EPG",
            "",
            "XMLTV (*.xml *.xml.gz *.gz);;Todos os ficheiros (*.*)",
        )
        if file_path:
            self._epg_input.setText(file_path)

    @property
    def playlist_path(self) -> str:
        return self._playlist_path

    @property
    def playlist_url(self) -> str:
        return self._url_input.text().strip()

    @property
    def playlist_name(self) -> str:
        return self._name_input.text().strip()

    @property
    def epg_source(self) -> str:
        return self._epg_input.text().strip()


class XtreamDialog(QDialog):
    """Dialog for Xtream Codes API login."""

    def __init__(self, parent=None, values: dict = None):
        super().__init__(parent)
        self._values = values or {}
        self.setWindowTitle("Xtream Codes - Login")
        self.setMinimumWidth(450)
        self._setup_ui()
        self._name_input.setText(self._values.get("name", ""))
        self._server_input.setText(self._values.get("server_url", ""))
        self._username_input.setText(self._values.get("username", ""))
        self._password_input.setText(self._values.get("password", ""))

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("Xtream Codes API")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        subtitle = QLabel("Introduz os dados do servidor Xtream")
        subtitle.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; margin-bottom: 10px;")
        layout.addWidget(subtitle)

        form = QFormLayout()
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Ex.: TV Principal")
        form.addRow("Nome da playlist:", self._name_input)

        self._server_input = QLineEdit()
        self._server_input.setPlaceholderText("http://seu-servidor.com:8080")
        form.addRow("Servidor:", self._server_input)

        self._username_input = QLineEdit()
        self._username_input.setPlaceholderText("username")
        form.addRow("Utilizador:", self._username_input)

        self._password_input = QLineEdit()
        self._password_input.setPlaceholderText("password")
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Palavra-passe:", self._password_input)

        layout.addLayout(form)
        layout.addStretch()

        buttons = QDialogButtonBox()
        self._login_btn = buttons.addButton("Ligar", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def server_url(self) -> str:
        return self._server_input.text().strip()

    @property
    def username(self) -> str:
        return self._username_input.text().strip()

    @property
    def password(self) -> str:
        return self._password_input.text().strip()

    @property
    def playlist_name(self) -> str:
        return self._name_input.text().strip()

    def _validate_and_accept(self):
        if not self.playlist_name:
            QMessageBox.warning(
                self, "Aviso", "Por favor, indica um nome para a playlist."
            )
            self._name_input.setFocus()
            return
        if not self.server_url:
            QMessageBox.warning(
                self, "Aviso", "Por favor, indica o endereço do servidor Xtream."
            )
            self._server_input.setFocus()
            return
        if not self.username:
            QMessageBox.warning(
                self, "Aviso", "Por favor, indica o nome de utilizador."
            )
            self._username_input.setFocus()
            return
        if not self.password:
            QMessageBox.warning(
                self, "Aviso", "Por favor, indica a palavra-passe."
            )
            self._password_input.setFocus()
            return
        self._accept_if_transport_confirmed()

    def _accept_if_transport_confirmed(self):
        if self.server_url.lower().startswith("http://"):
            answer = QMessageBox.warning(
                self,
                "Ligação sem proteção",
                "Este servidor usa HTTP. O utilizador e a palavra-passe podem ser "
                "intercetados na rede. Usa HTTPS sempre que o fornecedor o permita.\n\n"
                "Queres continuar mesmo assim?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()


class StalkerDialog(QDialog):
    """Dialog for Stalker Portal (MAC) login."""

    def __init__(self, parent=None, values: dict = None):
        super().__init__(parent)
        self._values = values or {}
        self.setWindowTitle("Stalker Portal - Login")
        self.setMinimumWidth(450)
        self._setup_ui()
        self._name_input.setText(self._values.get("name", ""))
        self._portal_input.setText(self._values.get("server_url", ""))
        self._mac_input.setText(self._values.get("mac_address", ""))

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("Stalker Portal (MAC)")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        subtitle = QLabel("Introduz o URL do portal e o endereço MAC")
        subtitle.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; margin-bottom: 10px;")
        layout.addWidget(subtitle)

        form = QFormLayout()
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Ex.: Portal de Casa")
        form.addRow("Nome da playlist:", self._name_input)

        self._portal_input = QLineEdit()
        self._portal_input.setPlaceholderText("http://portal.exemplo.com")
        form.addRow("Portal URL:", self._portal_input)

        self._mac_input = QLineEdit()
        self._mac_input.setPlaceholderText("00:1A:79:XX:XX:XX")
        form.addRow("Endereço MAC:", self._mac_input)

        layout.addLayout(form)

        info = QLabel("Formato MAC: 00:1A:79:XX:XX:XX (12 dígitos hexadecimais)")
        info.setStyleSheet(f"color: {Palette.TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(info)

        layout.addStretch()

        buttons = QDialogButtonBox()
        self._login_btn = buttons.addButton("Ligar", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def portal_url(self) -> str:
        return self._portal_input.text().strip()

    @property
    def mac_address(self) -> str:
        return self._mac_input.text().strip()

    @property
    def playlist_name(self) -> str:
        return self._name_input.text().strip()

    def _validate_and_accept(self):
        if not self.playlist_name:
            QMessageBox.warning(
                self, "Aviso", "Por favor, indica um nome para a playlist."
            )
            self._name_input.setFocus()
            return
        if not self.portal_url:
            QMessageBox.warning(
                self, "Aviso", "Por favor, indica o URL do portal Stalker."
            )
            self._portal_input.setFocus()
            return
        if not self.mac_address:
            QMessageBox.warning(
                self, "Aviso", "Por favor, indica o endereço MAC."
            )
            self._mac_input.setFocus()
            return
        self._accept_if_transport_confirmed()

    def _accept_if_transport_confirmed(self):
        # Stalker addresses without an explicit scheme are normalized to HTTP.
        if self.portal_url and not self.portal_url.lower().startswith("https://"):
            answer = QMessageBox.warning(
                self,
                "Ligação sem proteção",
                "Este portal usa HTTP. O endereço MAC e os dados da sessão podem ser "
                "intercetados na rede. Usa HTTPS sempre que o portal o permita.\n\n"
                "Queres continuar mesmo assim?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()


class SettingsDialog(QDialog):
    """Application settings dialog."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Definições")
        self.setMinimumWidth(500)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # Player tab
        player_tab = QWidget()
        player_layout = QFormLayout(player_tab)
        
        self._vlc_path = QLineEdit()
        self._vlc_path.setText(self._settings.get("vlc_path", ""))
        vlc_browse = QPushButton("...")
        vlc_browse.setMaximumWidth(30)
        vlc_browse.clicked.connect(self._browse_vlc)
        vlc_layout = QHBoxLayout()
        vlc_layout.addWidget(self._vlc_path)
        vlc_layout.addWidget(vlc_browse)
        player_layout.addRow("VLC Path:", vlc_layout)

        self._buffer_size = QSpinBox()
        self._buffer_size.setRange(300, 10000)
        self._buffer_size.setValue(self._settings.get("buffer_size_ms", 5000))
        self._buffer_size.setSuffix(" ms")
        player_layout.addRow("Buffer:", self._buffer_size)

        self._max_conn = QSpinBox()
        self._max_conn.setRange(1, 20)
        self._max_conn.setValue(self._settings.get("max_connections", 5))
        player_layout.addRow("Max Ligações:", self._max_conn)

        self._recording_folder = QLineEdit()
        self._recording_folder.setText(self._settings.get("recording_folder", ""))
        recording_browse = QPushButton("...")
        recording_browse.setMaximumWidth(30)
        recording_browse.clicked.connect(self._browse_recording_folder)
        recording_layout = QHBoxLayout()
        recording_layout.addWidget(self._recording_folder)
        recording_layout.addWidget(recording_browse)
        player_layout.addRow("Pasta de gravações:", recording_layout)

        self._stream_overlay = QCheckBox("Mostrar estatísticas da stream sobre o vídeo")
        self._stream_overlay.setChecked(self._settings.get("stream_overlay_enabled", False))
        player_layout.addRow(self._stream_overlay)

        self._auto_next = QCheckBox("Passar automaticamente para o próximo canal quando a stream falha")
        self._auto_next.setChecked(self._settings.get("auto_next_enabled", True))
        player_layout.addRow(self._auto_next)

        tabs.addTab(player_tab, "Player")

        # Network tab
        network_tab = QWidget()
        network_layout = QFormLayout(network_tab)

        self._timeout = QSpinBox()
        self._timeout.setRange(5, 120)
        self._timeout.setValue(self._settings.get("network_timeout_seconds", 30))
        self._timeout.setSuffix(" s")
        network_layout.addRow("Timeout:", self._timeout)

        self._user_agent = QLineEdit()
        self._user_agent.setText(self._settings.get("user_agent", ""))
        network_layout.addRow("User-Agent:", self._user_agent)

        self._update_url = QLineEdit()
        self._update_url.setText(self._settings.get("update_manifest_url", ""))
        self._update_url.setPlaceholderText("https://exemplo.com/manifest.json")
        network_layout.addRow("URL do manifesto de atualizações:", self._update_url)

        tabs.addTab(network_tab, "Rede")

        # EPG tab
        epg_tab = QWidget()
        epg_layout = QFormLayout(epg_tab)

        self._auto_epg = QCheckBox("Atualizar EPG automaticamente")
        self._auto_epg.setChecked(self._settings.get("epg_auto_update", True))
        epg_layout.addRow(self._auto_epg)

        self._epg_interval = QSpinBox()
        self._epg_interval.setRange(1, 168)
        self._epg_interval.setValue(self._settings.get("epg_update_interval_hours", 24))
        self._epg_interval.setSuffix(" horas")
        epg_layout.addRow("Intervalo EPG:", self._epg_interval)

        tabs.addTab(epg_tab, "EPG")

        # Parental tab
        parental_tab = QWidget()
        parental_layout = QVBoxLayout(parental_tab)

        self._parental_enabled = QCheckBox("Ativar controlo parental")
        self._parental_enabled.setChecked(self._settings.get("parental_lock_enabled", False))
        parental_layout.addWidget(self._parental_enabled)

        parental_info = QLabel(
            "Bloqueia categorias específicas com um PIN. Bloqueia/desbloqueia\n"
            "categorias a partir do menu de contexto na árvore de categorias."
        )
        parental_info.setStyleSheet(f"color: {Palette.TEXT_MUTED}; font-size: 11px;")
        parental_layout.addWidget(parental_info)

        self._pin_btn = QPushButton("Definir / alterar PIN")
        self._pin_btn.clicked.connect(self._change_pin)
        parental_layout.addWidget(self._pin_btn)
        parental_layout.addStretch()

        tabs.addTab(parental_tab, "Parental")

        layout.addWidget(tabs)

        # Buttons
        buttons = QDialogButtonBox()
        buttons.addButton(QDialogButtonBox.StandardButton.Ok)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_vlc(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar VLC", "", "vlc.exe;;*"
        )
        if path:
            self._vlc_path.setText(path)

    def _browse_recording_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Pasta de gravações", self._recording_folder.text())
        if path:
            self._recording_folder.setText(path)

    def _change_pin(self):
        from ..core.parental import generate_salt, hash_pin

        dialog = ParentalPinDialog(self, title="Definir novo PIN")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        pin = dialog.pin
        if not pin:
            return
        salt = generate_salt()
        self._settings.set_many(
            {
                "parental_pin_salt": salt,
                "parental_pin_hash": hash_pin(pin, salt),
            }
        )

    def _save_and_accept(self):
        self._settings.set_many(
            {
                "vlc_path": self._vlc_path.text(),
                "buffer_size_ms": self._buffer_size.value(),
                "max_connections": self._max_conn.value(),
                "network_timeout_seconds": self._timeout.value(),
                "user_agent": self._user_agent.text(),
                "epg_auto_update": self._auto_epg.isChecked(),
                "epg_update_interval_hours": self._epg_interval.value(),
                "recording_folder": self._recording_folder.text(),
                "stream_overlay_enabled": self._stream_overlay.isChecked(),
                "auto_next_enabled": self._auto_next.isChecked(),
                "update_manifest_url": self._update_url.text().strip(),
                "parental_lock_enabled": self._parental_enabled.isChecked(),
            }
        )
        self.accept()


class ParentalPinDialog(QDialog):
    """Single PIN-entry prompt, reused both to set/change and to unlock."""

    def __init__(self, parent=None, title: str = "Introduzir PIN"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(300)
        self._pin = ""

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title))

        self._pin_input = QLineEdit()
        self._pin_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._pin_input.setMaxLength(12)
        self._pin_input.setPlaceholderText("PIN")
        layout.addWidget(self._pin_input)

        buttons = QDialogButtonBox()
        buttons.addButton(QDialogButtonBox.StandardButton.Ok)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_pin)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_pin(self):
        self._pin = self._pin_input.text().strip()
        self.accept()

    @property
    def pin(self) -> str:
        return self._pin


class LoadingDialog(QDialog):
    """Loading dialog with progress bar for async operations."""

    def __init__(self, title: str = "A carregar...", message: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(350)
        self.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.setModal(True)

        layout = QVBoxLayout(self)
        if message:
            layout.addWidget(QLabel(message))
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        layout.addWidget(self.progress_bar)
        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self._cancel_btn)

    def set_progress(self, value: int, maximum: int = 100):
        """Set determinate progress."""
        self.progress_bar.setRange(0, maximum)
        self.progress_bar.setValue(value)


class SubtitleSearchWorker(QThread):
    """Background worker thread to search subtitles without freezing the UI."""
    finished_search = Signal(list)

    def __init__(
        self,
        finder,
        query: str = "",
        languages: str = "pt,pob,en",
        year: Optional[int] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        imdb_id: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.finder = finder
        self.query = query
        self.languages = languages
        self.year = year
        self.season = season
        self.episode = episode
        self.imdb_id = imdb_id

    def run(self):
        try:
            results = self.finder.search_subtitles(
                query=self.query,
                languages=self.languages,
                year=self.year,
                season_number=self.season,
                episode_number=self.episode,
                imdb_id=self.imdb_id,
            )
        except Exception:
            results = []
        self.finished_search.emit(results)


class SubtitleDownloadWorker(QThread):
    """Background worker thread to download a subtitle file."""
    finished_download = Signal(object)

    def __init__(self, finder, subtitle_data, parent=None):
        super().__init__(parent)
        self.finder = finder
        self.subtitle_data = subtitle_data

    def run(self):
        try:
            saved_path = self.finder.download_subtitle_file(self.subtitle_data)
        except Exception:
            saved_path = None
        self.finished_download.emit(saved_path)


class SubtitleSearchDialog(QDialog):
    """Dialog to search, preview, and download online subtitles from OpenSubtitles instantly."""

    def __init__(self, initial_query: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Procurar Legendas Online (OpenSubtitles)")
        self.resize(620, 520)
        self.selected_file_path: Optional[str] = None
        self._finder = None
        self._search_worker: Optional[SubtitleSearchWorker] = None
        self._dl_worker: Optional[SubtitleDownloadWorker] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header info
        header = QLabel("Pesquisa e transferência de legendas para Filmes, Séries e Canais")
        header.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(header)

        # Tabs for Search Modes
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabBar::tab {
                padding: 6px 14px;
                font-size: 11px;
                font-weight: bold;
            }
        """)

        # Tab 1: Movie / General
        tab_movie = QWidget()
        form_movie = QFormLayout(tab_movie)
        self._movie_title = QLineEdit()
        self._movie_title.setPlaceholderText("Título do filme (ex: Gladiator II)")
        self._movie_title.returnPressed.connect(self._start_search)
        self._movie_year = QLineEdit()
        self._movie_year.setPlaceholderText("Ano opcional (ex: 2024)")
        self._movie_year.returnPressed.connect(self._start_search)
        form_movie.addRow("Título:", self._movie_title)
        form_movie.addRow("Ano:", self._movie_year)
        self._tabs.addTab(tab_movie, "🎬 Filme / Geral")

        # Tab 2: Series / TV Show
        tab_series = QWidget()
        form_series = QFormLayout(tab_series)
        self._series_title = QLineEdit()
        self._series_title.setPlaceholderText("Nome da série (ex: Breaking Bad)")
        self._series_title.returnPressed.connect(self._start_search)
        se_row = QHBoxLayout()
        self._season_spin = QSpinBox()
        self._season_spin.setRange(1, 99)
        self._season_spin.setValue(1)
        self._season_spin.setPrefix("T ")
        self._episode_spin = QSpinBox()
        self._episode_spin.setRange(1, 999)
        self._episode_spin.setValue(1)
        self._episode_spin.setPrefix("Ep ")
        se_row.addWidget(self._season_spin)
        se_row.addWidget(self._episode_spin)
        form_series.addRow("Série:", self._series_title)
        form_series.addRow("Temporada/Ep:", se_row)
        self._tabs.addTab(tab_series, "📺 Série")

        # Tab 3: IMDb ID
        tab_imdb = QWidget()
        form_imdb = QFormLayout(tab_imdb)
        self._imdb_input = QLineEdit()
        self._imdb_input.setPlaceholderText("Código IMDb (ex: tt0133093)")
        self._imdb_input.returnPressed.connect(self._start_search)
        form_imdb.addRow("IMDb ID:", self._imdb_input)
        self._tabs.addTab(tab_imdb, "🆔 IMDb ID")

        layout.addWidget(self._tabs)

        # Languages filter row
        lang_group = QGroupBox("Idiomas de Legendas")
        lang_layout = QHBoxLayout(lang_group)
        self._cb_pt = QCheckBox("Português (PT)")
        self._cb_pt.setChecked(True)
        self._cb_br = QCheckBox("Português (BR)")
        self._cb_br.setChecked(True)
        self._cb_en = QCheckBox("Inglês (EN)")
        self._cb_en.setChecked(True)
        self._cb_es = QCheckBox("Espanhol (ES)")
        self._cb_es.setChecked(False)

        lang_layout.addWidget(self._cb_pt)
        lang_layout.addWidget(self._cb_br)
        lang_layout.addWidget(self._cb_en)
        lang_layout.addWidget(self._cb_es)
        lang_layout.addStretch()

        # Search action button in language row
        self._search_btn = QPushButton("🔍 Procurar")
        self._search_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Palette.ACCENT};
                color: #FFFFFF;
                font-weight: bold;
                padding: 6px 16px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: #0070E0;
            }}
        """)
        self._search_btn.clicked.connect(self._start_search)
        lang_layout.addWidget(self._search_btn)

        layout.addWidget(lang_group)

        # Progress bar (indeterminate while searching)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.hide()
        layout.addWidget(self._progress)

        # Results list
        self._results_list = QListWidget()
        self._results_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {Palette.BG_CARD};
                border: 1px solid {Palette.BORDER};
                border-radius: 4px;
            }}
            QListWidget::item {{
                padding: 6px 8px;
                border-bottom: 1px solid {Palette.BORDER};
            }}
            QListWidget::item:selected {{
                background-color: {Palette.ACCENT};
                color: #FFFFFF;
            }}
        """)
        self._results_list.itemDoubleClicked.connect(self._download_and_apply)
        layout.addWidget(self._results_list, 1)

        # Bottom buttons
        btn_box = QHBoxLayout()
        self._status_label = QLabel("Ajusta o título/ano e clica em Procurar.")
        self._status_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-size: 11px;")
        btn_box.addWidget(self._status_label, 1)

        self._apply_btn = QPushButton("Descarregar e Aplicar")
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._download_and_apply)
        btn_box.addWidget(self._apply_btn)

        local_btn = QPushButton("📂 Ficheiro Local...")
        local_btn.setToolTip("Carregar um ficheiro .srt / .vtt guardado no computador")
        local_btn.clicked.connect(self._pick_local_file)
        btn_box.addWidget(local_btn)

        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(self.reject)
        btn_box.addWidget(close_btn)

        layout.addLayout(btn_box)

        self._results_list.itemSelectionChanged.connect(
            lambda: self._apply_btn.setEnabled(self._results_list.currentItem() is not None)
        )

        # Pre-fill query
        self._prefill_query(initial_query)

    def _prefill_query(self, query: str):
        if not query:
            return
        import re

        from ..core.channel_cleaner import ChannelCleaner
        from ..core.metadata_enricher import MetadataEnricher

        cleaned = ChannelCleaner.clean_name(query)
        # Check if it looks like a series (e.g. S01E02 or 1x02)
        s_match = re.search(r"(?i)\bS(\d{1,2})\s*E(\d{1,3})\b", cleaned) or re.search(r"(?i)\b(\d{1,2})x(\d{1,3})\b", cleaned)
        if s_match:
            series_title = re.sub(r"(?i)\bS\d{1,2}\s*E\d{1,3}\b|\b\d{1,2}x\d{1,3}\b", "", cleaned).strip(" -._|[]()")
            self._series_title.setText(series_title)
            self._season_spin.setValue(int(s_match.group(1)))
            self._episode_spin.setValue(int(s_match.group(2)))
            self._tabs.setCurrentIndex(1)
        else:
            title, year = MetadataEnricher.extract_title_and_year(cleaned)
            self._movie_title.setText(title)
            if year:
                self._movie_year.setText(str(year))
            self._tabs.setCurrentIndex(0)

    def _selected_languages(self) -> str:
        langs = []
        if self._cb_pt.isChecked():
            langs.append("pt")
        if self._cb_br.isChecked():
            langs.append("pob")
        if self._cb_en.isChecked():
            langs.append("en")
        if self._cb_es.isChecked():
            langs.append("es")
        return ",".join(langs) if langs else "pt,pob,en"

    def _start_search(self):
        from ..core.subtitles_finder import SubtitlesFinder

        self._finder = SubtitlesFinder()
        self._results_list.clear()
        self._apply_btn.setEnabled(False)
        self._status_label.setText("A pesquisar legendas online...")
        self._search_btn.setEnabled(False)
        self._progress.show()

        tab_idx = self._tabs.currentIndex()
        query = ""
        year = None
        season = None
        episode = None
        imdb_id = None
        languages = self._selected_languages()

        if tab_idx == 0:
            query = self._movie_title.text().strip()
            year_text = self._movie_year.text().strip()
            if year_text.isdigit():
                year = int(year_text)
        elif tab_idx == 1:
            query = self._series_title.text().strip()
            season = self._season_spin.value()
            episode = self._episode_spin.value()
        elif tab_idx == 2:
            imdb_id = self._imdb_input.text().strip()

        # Stop existing worker if active
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.terminate()

        self._search_worker = SubtitleSearchWorker(
            finder=self._finder,
            query=query,
            languages=languages,
            year=year,
            season=season,
            episode=episode,
            imdb_id=imdb_id,
            parent=self,
        )
        self._search_worker.finished_search.connect(self._on_search_completed)
        self._search_worker.start()

    @Slot(list)
    def _on_search_completed(self, results: list):
        self._progress.hide()
        self._search_btn.setEnabled(True)
        self._results_list.clear()

        if not results:
            self._status_label.setText("Nenhuma legenda encontrada. Tenta ajustar o nome ou ano.")
            return

        self._status_label.setText(f"Encontradas {len(results)} legendas.")
        for item in results:
            lang_code = item.language.upper()
            tag = "PT" if lang_code in ("PT", "PT-PT") else "BR" if lang_code in ("POB", "PT-BR", "BR") else "EN" if lang_code == "EN" else "ES" if lang_code == "ES" else lang_code
            dl_info = f" - {item.downloads_count} dls" if item.downloads_count > 0 else ""
            list_item = QListWidgetItem(f"[{tag}]{dl_info}  {item.release_name}")
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self._results_list.addItem(list_item)

        if self._results_list.count() > 0:
            self._results_list.setCurrentRow(0)
            self._results_list.setFocus()

    def _download_and_apply(self):
        current = self._results_list.currentItem()
        if not current or not self._finder:
            return
        subtitle_data = current.data(Qt.ItemDataRole.UserRole)
        if not subtitle_data:
            return

        self._status_label.setText("A descarregar ficheiro de legendas...")
        self._progress.show()
        self._apply_btn.setEnabled(False)

        if self._dl_worker and self._dl_worker.isRunning():
            self._dl_worker.terminate()

        self._dl_worker = SubtitleDownloadWorker(
            finder=self._finder,
            subtitle_data=subtitle_data,
            parent=self,
        )
        self._dl_worker.finished_download.connect(self._on_download_completed)
        self._dl_worker.start()

    @Slot(object)
    def _on_download_completed(self, saved_path):
        self._progress.hide()
        self._apply_btn.setEnabled(True)
        if saved_path:
            self.selected_file_path = str(saved_path)
            self.accept()
        else:
            self._status_label.setText("Erro ao descarregar a legenda.")

    def _pick_local_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Ficheiro de Legendas",
            "",
            "Legendas (*.srt *.vtt *.sub *.ass);;Todos os ficheiros (*.*)",
        )
        if file_path:
            self.selected_file_path = file_path
            self.accept()


class SubtitleDelayDialog(QDialog):
    """Interactive subtitle delay synchronization dialog with slider and live steps."""

    def __init__(self, media_player, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sincronização de Legendas")
        self.setMinimumWidth(440)
        self._player = media_player

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        info = QLabel("Ajusta o atraso ou avanço das legendas em tempo real:")
        info.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(info)

        current_delay = self._player.get_subtitle_delay() if self._player else 0
        self._delay_label = QLabel(self._format_delay_text(current_delay))
        self._delay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._delay_label.setStyleSheet(f"color: {Palette.ACCENT}; font-size: 26px; font-weight: bold; margin: 4px 0;")
        layout.addWidget(self._delay_label)

        # Interactive Slider (-10s to +10s, step 50ms)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(-10000, 10000)
        self._slider.setSingleStep(50)
        self._slider.setPageStep(250)
        self._slider.setValue(current_delay)
        self._slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self._slider)

        slider_labels = QHBoxLayout()
        lbl_left = QLabel("-10 s (Mais Cedo)")
        lbl_left.setStyleSheet(f"color: {Palette.TEXT_MUTED}; font-size: 10px;")
        lbl_mid = QLabel("0 s")
        lbl_mid.setStyleSheet(f"color: {Palette.TEXT_MUTED}; font-size: 10px;")
        lbl_mid.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_right = QLabel("+10 s (Mais Tarde)")
        lbl_right.setStyleSheet(f"color: {Palette.TEXT_MUTED}; font-size: 10px;")
        lbl_right.setAlignment(Qt.AlignmentFlag.AlignRight)
        slider_labels.addWidget(lbl_left)
        slider_labels.addWidget(lbl_mid)
        slider_labels.addWidget(lbl_right)
        layout.addLayout(slider_labels)

        # Quick step buttons row 1
        steps_row1 = QHBoxLayout()
        for delta in [-1000, -250, -50, 0, 50, 250, 1000]:
            label = "Reset (0s)" if delta == 0 else f"{delta:+d}ms"
            btn = QPushButton(label)
            if delta == 0:
                btn.clicked.connect(lambda: self._set_delay(0))
            else:
                btn.clicked.connect(lambda d=delta: self._adjust_delay(d))
            steps_row1.addWidget(btn)
        layout.addLayout(steps_row1)

        # Large jump row
        steps_row2 = QHBoxLayout()
        btn_minus_5 = QPushButton("⏪ -5.0s")
        btn_minus_5.clicked.connect(lambda: self._adjust_delay(-5000))
        btn_plus_5 = QPushButton("⏩ +5.0s")
        btn_plus_5.clicked.connect(lambda: self._adjust_delay(5000))
        steps_row2.addWidget(btn_minus_5)
        steps_row2.addWidget(btn_plus_5)
        layout.addLayout(steps_row2)

        # Keyboard shortcuts hint
        hint = QLabel("💡 Dica: Podes usar as teclas G (adiantar) e H (atrasar) ou [ e ] durante o vídeo.")
        hint.setStyleSheet(f"color: {Palette.TEXT_MUTED}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Close button
        close_btn = QPushButton("Concluído")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _format_delay_text(self, ms: int) -> str:
        sec = ms / 1000.0
        return f"{ms:+d} ms  ({sec:+.2f} s)"

    def _on_slider_changed(self, value: int):
        self._delay_label.setText(self._format_delay_text(value))
        if self._player:
            self._player.set_subtitle_delay(value)

    def _set_delay(self, ms: int):
        clamped = max(-10000, min(10000, ms))
        self._slider.blockSignals(True)
        self._slider.setValue(clamped)
        self._slider.blockSignals(False)
        self._delay_label.setText(self._format_delay_text(clamped))
        if self._player:
            self._player.set_subtitle_delay(clamped)

    def _adjust_delay(self, delta_ms: int):
        current = self._player.get_subtitle_delay() if self._player else self._slider.value()
        self._set_delay(current + delta_ms)
