"""Cast Dialog for streaming IPTV content to Chromecast and Smart TVs."""

from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..core.cast_manager import CastDevice, CastManager
from .theme import Palette


class CastDialog(QDialog):
    """Dialog allowing users to discover and stream to local Smart TVs and Chromecast."""

    def __init__(
        self,
        current_url: str = "",
        current_title: str = "",
        headers: Optional[dict] = None,
        is_live: bool = True,
        media_player=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("📡 Transmitir para TV / Chromecast")
        self.resize(480, 360)
        self._url = current_url
        self._title = current_title
        self._headers = headers or {}
        self._is_live = is_live
        self._player = media_player
        self._cast_mgr = CastManager.get_instance()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header
        header = QLabel("📡 Dispositivos na Rede Wi-Fi")
        header.setStyleSheet(f"color: {Palette.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        layout.addWidget(header)

        # Info
        self._info_lbl = QLabel("A procurar Smart TVs e Chromecast na rede...")
        self._info_lbl.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._info_lbl)

        # Device List
        self._list = QListWidget()
        self._list.setStyleSheet(
            f"background-color: {Palette.BG_PANEL}; color: {Palette.TEXT_PRIMARY}; border-radius: 6px; padding: 4px;"
        )
        self._list.itemDoubleClicked.connect(self._on_connect_clicked)
        layout.addWidget(self._list, 1)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        self._refresh_btn = QPushButton("🔄 Procurar")
        self._refresh_btn.clicked.connect(self._start_scan)
        btn_layout.addWidget(self._refresh_btn)

        btn_layout.addStretch()

        self._disconnect_btn = QPushButton("⏹️ Parar Transmissão")
        self._disconnect_btn.setEnabled(self._cast_mgr.is_casting)
        self._disconnect_btn.clicked.connect(self._on_disconnect_clicked)
        btn_layout.addWidget(self._disconnect_btn)

        self._connect_btn = QPushButton("📡 Transmitir")
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        btn_layout.addWidget(self._connect_btn)

        layout.addLayout(btn_layout)

        # Signals
        self._cast_mgr.device_found.connect(self._on_device_found)
        self._cast_mgr.casting_state_changed.connect(self._on_casting_state_changed)

        # Start initial discovery
        self._start_scan()
        self._populate_list()

    def _start_scan(self):
        vlc_inst = None
        if self._player:
            vlc_inst = (
                getattr(self._player, "vlc_instance", None)
                or getattr(self._player, "_instance", None)
                or getattr(self._player, "_vlc_instance", None)
            )
        self._cast_mgr.start_discovery(vlc_inst)
        self._info_lbl.setText("A procurar Smart TVs e Chromecast na rede local...")

    def _populate_list(self):
        self._list.clear()
        devices = self._cast_mgr.list_devices()
        active = self._cast_mgr.active_device

        for dev in devices:
            is_active = active and active.device_id == dev.device_id
            label = f"{dev.name} {'(A transmitir... 🔴)' if is_active else ''}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, dev)
            if is_active:
                item.setForeground(Qt.GlobalColor.green)
            self._list.addItem(item)

        if not devices:
            self._info_lbl.setText("Nenhum dispositivo encontrado ainda. Certifica-te que a TV está ligada à mesma rede Wi-Fi.")
        else:
            self._info_lbl.setText(f"{len(devices)} dispositivo(s) encontrado(s).")

    @Slot(object)
    def _on_device_found(self, device: CastDevice):
        self._populate_list()

    @Slot()
    def _on_connect_clicked(self):
        curr_item = self._list.currentItem()
        if not curr_item:
            QMessageBox.information(self, "Transmitir", "Por favor seleciona um dispositivo da lista.")
            return

        device = curr_item.data(Qt.ItemDataRole.UserRole)
        if not device or not self._url:
            QMessageBox.warning(self, "Transmitir", "Não há nenhuma emissão ativa para transmitir.")
            return

        self._cast_mgr.cast_to_device(
            device,
            self._url,
            self._title,
            headers=self._headers,
            is_live=self._is_live,
            media_player=self._player,
        )
        self._disconnect_btn.setEnabled(True)
        self._populate_list()

    @Slot()
    def _on_disconnect_clicked(self):
        self._cast_mgr.stop_cast()
        self._disconnect_btn.setEnabled(False)
        self._populate_list()

    @Slot(bool, str)
    def _on_casting_state_changed(self, is_casting: bool, dev_name: str):
        self._disconnect_btn.setEnabled(is_casting)
        self._populate_list()

