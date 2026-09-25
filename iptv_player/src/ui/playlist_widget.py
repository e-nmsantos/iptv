"""Playlist management widget with real-time health badges and diagnostics."""

from typing import Optional

from PySide6.QtCore import QEventLoop, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.playlist_health import HealthStatus, PlaylistHealthChecker
from .theme import Palette


class PlaylistWidget(QWidget):
    """Widget for managing multiple playlists with live health indicators."""

    playlist_selected = Signal(int)  # playlist_id
    playlist_deleted = Signal(int)  # playlist_id
    playlist_renamed = Signal(int, str)  # playlist_id, new name
    playlist_edit_requested = Signal(int)
    import_m3u_requested = Signal()
    import_xtream_requested = Signal()
    import_stalker_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._playlists: list = []
        self._health_checker = PlaylistHealthChecker.get_instance()
        self._health_checker.health_updated.connect(self._on_health_updated)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # Title
        title = QLabel("PLAYLISTS")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title.setStyleSheet(
            f"color: {Palette.TEXT_SECONDARY}; padding: 6px 5px 2px 5px; "
            "letter-spacing: 1px;"
        )
        title.setFont(title_font)
        layout.addWidget(title)

        # Compact import shortcuts
        btn_style = f"""
            QPushButton {{
                background: {Palette.BG_ELEVATED};
                border: 1px solid {Palette.BORDER_STRONG};
                border-radius: {Palette.RADIUS_MD}px;
                color: {Palette.TEXT_PRIMARY};
                padding: 7px 6px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {Palette.BG_CARD_HOVER};
                border-color: {Palette.BORDER_STRONG};
            }}
        """

        import_row = QHBoxLayout()
        import_row.setSpacing(5)

        self._m3u_btn = QPushButton("M3U")
        self._m3u_btn.setStyleSheet(btn_style)
        self._m3u_btn.setToolTip("Importar playlist M3U / M3U8")
        self._m3u_btn.clicked.connect(self.import_m3u_requested.emit)
        import_row.addWidget(self._m3u_btn)

        self._xtream_btn = QPushButton("Xtream")
        self._xtream_btn.setStyleSheet(btn_style)
        self._xtream_btn.setToolTip("Adicionar conta Xtream Codes")
        self._xtream_btn.clicked.connect(self.import_xtream_requested.emit)
        import_row.addWidget(self._xtream_btn)

        self._stalker_btn = QPushButton("Stalker")
        self._stalker_btn.setStyleSheet(btn_style)
        self._stalker_btn.setToolTip("Adicionar portal Stalker por MAC")
        self._stalker_btn.clicked.connect(self.import_stalker_requested.emit)
        import_row.addWidget(self._stalker_btn)
        layout.addLayout(import_row)

        # Playlist list
        self._list_widget = QListWidget()
        self._list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self._list_widget.itemClicked.connect(self._on_playlist_selected)
        layout.addWidget(self._list_widget, 1)

    def set_playlists(self, playlists: list):
        """Set the list of playlists and trigger background health checks."""
        self._playlists = playlists
        self._list_widget.clear()

        for pl in playlists:
            item = self._create_playlist_item(pl)
            self._list_widget.addItem(item)

        # Trigger background health monitoring after UI and first playlist load have settled
        from PySide6.QtCore import QTimer
        QTimer.singleShot(
            2500,
            lambda pls=list(playlists): self._health_checker.check_all_playlists_async(pls),
        )

    def _create_playlist_item(self, pl: dict) -> QListWidgetItem:
        source_icons = {
            "m3u": "📺",
            "m3u_plus": "📺+",
            "xtream": "🔗",
            "stalker": "📡",
        }
        icon = source_icons.get(pl.get("source_type", ""), "📁")
        pl_id = pl.get("id")

        health = self._health_checker.get_cached_status(pl_id)
        badge = self._format_health_badge(health)

        display_text = f"{icon}  {pl.get('name', 'Sem Nome')}{badge}"
        item = QListWidgetItem(display_text)
        item.setData(Qt.ItemDataRole.UserRole, pl_id)

        # Tooltip with details
        tip_lines = [
            f"Nome: {pl.get('name', 'Sem Nome')}",
            f"Tipo: {pl.get('source_type', 'N/A').upper()}",
            f"Criado: {pl.get('created_at', 'N/A')[:10]}",
        ]
        if health:
            tip_lines.append(f"Estado: {health.message or health.status}")
            if health.expiry_date:
                tip_lines.append(f"Validade da Conta: {health.expiry_date}")
            if health.latency_ms > 0:
                tip_lines.append(f"Latência: {health.latency_ms} ms")
        item.setToolTip("\n".join(tip_lines))

        return item

    def _format_health_badge(self, health: Optional[HealthStatus]) -> str:
        if not health:
            return "  [⚪]"
        if health.status == "online":
            if health.expiry_date and health.expiry_date != "Ilimitada":
                return f"  [🟢 {health.latency_ms}ms · Exp: {health.expiry_date}]"
            return f"  [🟢 {health.latency_ms}ms]"
        if health.status == "offline":
            return "  [🔴 Offline]"
        if health.status == "expired":
            return f"  [⚠️ Expirado: {health.expiry_date or ''}]"
        if health.status == "unauthorized":
            return "  [⚠️ Não autorizado]"
        if health.status == "local":
            return "  [📁 Local]"
        return ""

    @Slot(object)
    def _on_health_updated(self, status: HealthStatus):
        """Update the visual badge of the playlist when health check completes."""
        for row in range(self._list_widget.count()):
            item = self._list_widget.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == status.playlist_id:
                pl = next((p for p in self._playlists if p.get("id") == status.playlist_id), None)
                if pl:
                    updated = self._create_playlist_item(pl)
                    item.setText(updated.text())
                    item.setToolTip(updated.toolTip())
                    if status.status == "offline":
                        item.setForeground(QColor(Palette.TEXT_MUTED))
                    elif status.status == "online":
                        item.setForeground(QColor(Palette.TEXT_PRIMARY))
                break

    def select_playlist(self, playlist_id: int):
        """Visually select a playlist after an import or rename."""
        for row in range(self._list_widget.count()):
            item = self._list_widget.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == playlist_id:
                self._list_widget.setCurrentItem(item)
                return

    def rename_selected_playlist(self):
        """Open the rename dialog for the currently selected playlist."""
        item = self._list_widget.currentItem()
        if not item:
            QMessageBox.information(
                self, "Alterar nome", "Seleciona primeiro uma playlist."
            )
            return
        self._prompt_rename_item(item)

    def _playlist_name(self, playlist_id: int) -> str:
        return next(
            (
                playlist.get("name", "")
                for playlist in self._playlists
                if playlist.get("id") == playlist_id
            ),
            "",
        )

    def _prompt_rename_item(self, item: QListWidgetItem):
        playlist_id = item.data(Qt.ItemDataRole.UserRole)
        if not playlist_id:
            return
        current_name = self._playlist_name(playlist_id)
        new_name, accepted = QInputDialog.getText(
            self,
            "Alterar nome da playlist",
            "Novo nome:",
            text=current_name,
        )
        new_name = new_name.strip()
        if accepted and new_name and new_name != current_name:
            self.playlist_renamed.emit(playlist_id, new_name)

    def _on_playlist_selected(self, item: QListWidgetItem):
        """Handle playlist selection."""
        playlist_id = item.data(Qt.ItemDataRole.UserRole)
        if playlist_id:
            self.playlist_selected.emit(playlist_id)

    def _show_context_menu(self, position):
        """Show context menu for a playlist."""
        item = self._list_widget.itemAt(position)
        if not item:
            return

        playlist_id = item.data(Qt.ItemDataRole.UserRole)
        if not playlist_id:
            return

        pl = next((p for p in self._playlists if p.get("id") == playlist_id), None)
        if not pl:
            return

        menu = QMenu(self)

        test_action = QAction("🔍 Testar Conexão / Ver Detalhes...", menu)
        test_action.triggered.connect(lambda: self._test_and_show_details(pl))
        menu.addAction(test_action)
        menu.addSeparator()

        edit_action = QAction("Editar e configurar ligação...", menu)
        edit_action.triggered.connect(
            lambda: self.playlist_edit_requested.emit(playlist_id)
        )
        menu.addAction(edit_action)

        rename_action = QAction("Alterar nome...", menu)
        rename_action.triggered.connect(lambda: self._prompt_rename_item(item))
        menu.addAction(rename_action)

        menu.addSeparator()

        delete_action = menu.addAction("🗑 Eliminar Playlist")
        delete_action.triggered.connect(lambda: self._confirm_delete(playlist_id))

        menu.exec(self._list_widget.mapToGlobal(position))

    def _test_and_show_details(self, pl: dict):
        """Test the connection in the background and show the diagnostic report.

        The previous implementation called ``check_playlist_sync`` directly
        from the context-menu handler, which blocked the GUI thread for the
        whole request (up to several seconds, or until timeout) on every
        click. The check now runs on its own thread and a local event loop
        only waits for the result while keeping the UI responsive.
        """
        playlist_id = pl.get("id")
        if not playlist_id:
            return

        result: dict = {}
        loop = QEventLoop()

        def on_updated(status: HealthStatus):
            if status.playlist_id != playlist_id:
                return
            result["status"] = status
            loop.quit()

        self._health_checker.health_updated.connect(on_updated)
        QTimer.singleShot(0, lambda: self._health_checker.check_playlist_async(pl))
        # Safety net: never keep the local event loop (and therefore the
        # caller) waiting forever if the worker never reports back.
        QTimer.singleShot(15000, loop.quit)
        try:
            loop.exec()
        finally:
            self._health_checker.health_updated.disconnect(on_updated)

        status = result.get("status") or self._health_checker.get_cached_status(
            playlist_id
        )
        if status is None:
            status = HealthStatus(
                playlist_id=playlist_id,
                status="offline",
                message="Sem resposta do servidor (tempo limite excedido).",
            )
        self._on_health_updated(status)

        status_icon = "🟢" if status.status == "online" else ("📁" if status.status == "local" else "🔴")
        msg = (
            f"<h3>{status_icon} Estado da Playlist: {pl.get('name', '')}</h3>"
            f"<p><b>Tipo:</b> {pl.get('source_type', '').upper()}</p>"
            f"<p><b>Estado:</b> {status.message}</p>"
        )
        if status.latency_ms > 0:
            msg += f"<p><b>Latência do Servidor:</b> {status.latency_ms} ms</p>"
        if status.expiry_date:
            msg += f"<p><b>Validade da Subscrição:</b> {status.expiry_date}</p>"
        if status.max_connections:
            msg += f"<p><b>Conexões Simultâneas:</b> {status.active_connections or '0'} / {status.max_connections}</p>"

        QMessageBox.information(self, "Diagnóstico da Playlist", msg)

    def _confirm_delete(self, playlist_id: int):
        """Confirm and delete a playlist."""
        reply = QMessageBox.question(
            self,
            "Eliminar Playlist",
            "Tens a certeza que queres eliminar esta playlist?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.playlist_deleted.emit(playlist_id)
