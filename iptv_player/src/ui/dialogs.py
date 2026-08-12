"""Dialog windows for the IPTV Player application."""

from PySide6.QtCore import Qt
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
    QMessageBox,
    QProgressBar,
    QPushButton,
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
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
        buttons.accepted.connect(self._accept_if_transport_confirmed)
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
        buttons.accepted.connect(self._accept_if_transport_confirmed)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def portal_url(self) -> str:
        return self._portal_input.text().strip()

    @property
    def mac_address(self) -> str:
        return self._mac_input.text().strip()

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

    @property
    def playlist_name(self) -> str:
        return self._name_input.text().strip()


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
