"""Playlist management widget."""


from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFont
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

from .theme import Palette


class PlaylistWidget(QWidget):
    """Widget for managing multiple playlists."""

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

        # Compact import shortcuts; the same actions are also in the main toolbar.
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
        """Set the list of playlists."""
        self._playlists = playlists
        self._list_widget.clear()

        for pl in playlists:
            source_icons = {
                "m3u": "📺",
                "m3u_plus": "📺+",
                "xtream": "🔗",
                "stalker": "📡",
            }
            icon = source_icons.get(pl.get("source_type", ""), "📁")
            
            display_text = f"{icon}  {pl.get('name', 'Sem Nome')}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, pl.get("id"))
            item.setToolTip(
                f"Tipo: {pl.get('source_type', 'N/A')}\n"
                f"Criado: {pl.get('created_at', 'N/A')[:10]}"
            )
            self._list_widget.addItem(item)

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

        menu = QMenu(self)

        delete_action = menu.addAction("🗑 Eliminar Playlist")
        delete_action.triggered.connect(lambda: self._confirm_delete(playlist_id))
        rename_action = QAction("Alterar nome...", menu)
        rename_action.triggered.connect(lambda: self._prompt_rename_item(item))
        menu.insertAction(delete_action, rename_action)
        edit_action = QAction("Editar e testar ligação...", menu)
        edit_action.triggered.connect(
            lambda: self.playlist_edit_requested.emit(playlist_id)
        )
        menu.insertAction(rename_action, edit_action)
        menu.insertSeparator(delete_action)

        menu.exec(self._list_widget.mapToGlobal(position))

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

