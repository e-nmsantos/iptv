"""Backup export/import and TV sync for the main window.

Extracted from ``main_window.py``. ``ToolsMixin`` must be mixed into a class
that provides ``_db``, ``_current_playlist_id``, ``_run_background``,
``_distribute_channels``, ``_load_playlists`` and the QMainWindow accessors.
"""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QLineEdit, QMessageBox

from ..core.backup import create_backup, read_backup
from ..core.device_sync import export_device_state, import_device_state


class ToolsMixin:
    """Backup export/import and credential-free TV synchronization."""

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
