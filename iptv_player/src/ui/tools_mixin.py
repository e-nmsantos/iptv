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
from ..core.tv_sync import (
    TvEndpoint,
    discover_tvs,
    exchange_with_tv,
    playlists_for_tv,
    send_playlists_to_tv,
)


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
            f"{result['progress']} pontos de retoma e "
            f"{result.get('continue', 0)} itens de Continuar a ver.",
        )

    @Slot()
    def _sync_with_tv(self):
        """Two-way favourites/resume sync with a TV on the home network (PIN based)."""
        playlist_id = self._current_playlist_id
        if not playlist_id:
            QMessageBox.information(self, "Sincronizar com a TV", "Seleciona primeiro uma playlist.")
            return

        self._discover_tvs_then(
            "Sincronizar com a TV",
            lambda endpoint, pin: self._exchange_with_tv(playlist_id, endpoint, pin),
        )

    def _discover_tvs_then(self, title: str, continue_with) -> None:
        """Browse the LAN for TVs, then ask which one and its PIN."""

        def discover():
            try:
                return discover_tvs()
            except ImportError:
                return []

        def ask(tvs):
            chosen = self._choose_tv_and_pin(title, tvs)
            if chosen:
                continue_with(*chosen)

        self._run_background(
            discover,
            ask,
            on_error=lambda _message: ask([]),
            status_message="A procurar televisões na rede...",
            use_semaphore=False,
        )

    def _choose_tv_and_pin(self, title: str, tvs: list):
        """Ask for the TV (found or typed) and its PIN; ``None`` if cancelled."""
        instructions = (
            "Na TV abre Adicionar → Telemóvel ou computador: aparecem o PIN e o endereço."
        )
        endpoint = None
        if tvs:
            labels = [tv.label for tv in tvs] + ["Outra (escrever endereço)..."]
            choice, accepted = QInputDialog.getItem(
                self, title, "Televisões encontradas na rede:", labels, 0, False
            )
            if not accepted:
                return None
            if choice in labels[:-1]:
                endpoint = tvs[labels.index(choice)]
        if endpoint is None:
            address, accepted = QInputDialog.getText(
                self, title,
                f"{instructions}\n\nEndereço mostrado na TV (por exemplo 192.168.1.20:41234):",
            )
            if not accepted or not address.strip():
                return None
            host, _, port = address.strip().removeprefix("http://").split("/")[0].partition(":")
            if not port.isdigit():
                QMessageBox.warning(self, title, "Indica o endereço com a porta, como aparece na TV.")
                return None
            endpoint = TvEndpoint("TV", host, int(port))
        pin, accepted = QInputDialog.getText(
            self, title, f"PIN de 6 algarismos mostrado em {endpoint.label}:",
        )
        if not accepted or not pin.strip():
            return None
        return endpoint, pin

    @Slot()
    def _send_playlists_to_tv(self):
        """Send every saved playlist (credentials included) to a TV on the home network."""
        title = "Enviar listas para a TV"
        playlists = self._db.get_playlists()
        # The TV makes the last imported playlist active, so the current one goes last.
        playlists.sort(key=lambda playlist: playlist.get("id") == self._current_playlist_id)
        entries, skipped = playlists_for_tv(playlists)
        if not entries:
            QMessageBox.information(
                self, title,
                "Não há listas que a TV consiga carregar. As listas abertas a partir de um "
                "ficheiro do computador não podem ser enviadas: usa o endereço (URL) da lista.",
            )
            return
        names = "\n".join(f"• {entry['name'] or entry['url']}" for entry in entries)
        note = (
            "\n\nNão enviadas (ficheiro local ou dados incompletos):\n"
            + "\n".join(f"• {name}" for name in skipped)
            if skipped else ""
        )
        answer = QMessageBox.question(
            self, title,
            f"Vão ser enviadas {len(entries)} listas para a TV, com as credenciais:\n"
            f"{names}{note}\n\nO envio é feito pela rede local, protegido pelo PIN da TV. "
            "Continuar?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def send(endpoint, pin):
            self._run_background(
                lambda: send_playlists_to_tv(endpoint, pin, entries),
                lambda _result: QMessageBox.information(
                    self, title,
                    f"{len(entries)} listas enviadas para {endpoint.label}.\n"
                    "A TV está a carregá-las; o progresso aparece no ecrã da TV.",
                ),
                on_error=lambda message: QMessageBox.warning(self, title, message),
                status_message=f"A enviar listas para {endpoint.label}...",
                use_semaphore=False,
            )

        self._discover_tvs_then(title, send)

    def _exchange_with_tv(self, playlist_id: int, endpoint: TvEndpoint, pin: str) -> None:

        merged = {}

        def merge_tv_then_export(tv_state: str) -> str:
            merged.update(import_device_state(self._db, playlist_id, tv_state))
            return export_device_state(self._db, playlist_id)

        def run():
            exchange_with_tv(endpoint, pin, merge_tv_then_export)
            return merged

        def done(result):
            self._distribute_channels(self._db.get_channels(playlist_id))
            self._refresh_resume()
            QMessageBox.information(
                self,
                "Sincronizar com a TV",
                f"Sincronização concluída com {endpoint.label}.\n"
                f"Recebidos da TV: {result.get('favorites', 0)} favoritos e "
                f"{result.get('progress', 0)} pontos de retoma e "
                f"{result.get('continue', 0)} itens de Continuar a ver (inclui episódios).\n"
                "O estado deste computador também foi enviado para a TV.",
            )

        self._run_background(
            run, done,
            on_error=lambda message: QMessageBox.warning(self, "Sincronizar com a TV", message),
            status_message=f"A sincronizar com {endpoint.label}...",
            context_playlist_id=playlist_id,
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
