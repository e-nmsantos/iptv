"""Import flows (M3U, Xtream, Stalker) for the main window.

Extracted from ``main_window.py``. ``ImportFlowMixin`` must be mixed into a
class that provides ``_settings``, ``_db``, ``_playlist_controller``,
``_playlist_widget``, ``_task_controller``, ``_run_background``, ``_closing``,
``_load_playlists``, ``_distribute_channels``, ``_load_playlist_epg``,
``_sync_task_widgets``, ``_on_task_cancelled``, ``_on_task_progress``,
``_on_worker_finished`` and ``_logger``.
"""

from PySide6.QtCore import QThread, Slot
from PySide6.QtWidgets import QMessageBox

from ..core.content_types import CONTENT_TYPES, content_type_for_stream
from ..core.task_manager import TaskWorker
from ..parsers.m3u_parser import M3UParser
from ..parsers.stalker_parser import StalkerParser
from ..parsers.xtream_parser import XtreamParser
from .dialogs import PlaylistDialog, StalkerDialog, XtreamDialog


class ImportFlowMixin:
    """Playlist import entry points and their worker orchestration."""

    @Slot()
    def _import_m3u(self, initial_values: dict = None):
        """Open M3U import dialog and parse playlist."""
        dialog = PlaylistDialog(self, values=initial_values)
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

        self._last_import = {
            "type": "m3u",
            "values": {
                "name": name,
                "url": dialog.playlist_url,
                "file_path": dialog.playlist_path,
                "epg_source": epg_source,
            },
        }

        def import_func():
            parser = M3UParser(
                timeout=self._settings.get("network_timeout_seconds", 30),
                user_agent=self._settings.get("user_agent", ""),
                should_cancel=lambda: QThread.currentThread().isInterruptionRequested(),
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
    def _import_xtream(self, initial_values: dict = None):
        """Open Xtream login dialog and fetch channels."""
        dialog = XtreamDialog(self, values=initial_values)
        if dialog.exec() != XtreamDialog.DialogCode.Accepted:
            return

        server = dialog.server_url
        username = dialog.username
        password = dialog.password
        name = dialog.playlist_name

        if not all([name, server, username, password]):
            QMessageBox.warning(self, "Aviso", "Preenche todos os campos.")
            return

        self._last_import = {
            "type": "xtream",
            "values": {
                "name": name,
                "server_url": server,
                "username": username,
                "password": password,
            },
        }

        def import_func():
            with XtreamParser(
                server,
                username,
                password,
                timeout=self._settings.get("network_timeout_seconds", 30),
                cancel_requested=lambda: QThread.currentThread().isInterruptionRequested(),
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
    def _import_stalker(self, initial_values: dict = None):
        """Open Stalker login dialog and fetch channels."""
        dialog = StalkerDialog(self, values=initial_values)
        if dialog.exec() != StalkerDialog.DialogCode.Accepted:
            return

        portal = dialog.portal_url
        mac = dialog.mac_address
        name = dialog.playlist_name

        if not all([name, portal, mac]):
            QMessageBox.warning(self, "Aviso", "Preenche todos os campos.")
            return

        self._last_import = {
            "type": "stalker",
            "values": {
                "name": name,
                "server_url": portal,
                "mac_address": mac,
            },
        }

        def import_func():
            with StalkerParser(
                portal,
                mac,
                timeout=self._settings.get("network_timeout_seconds", 30),
                cancel_requested=lambda: QThread.currentThread().isInterruptionRequested(),
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
            playlist = self._task_controller.execute(import_func)
            if playlist is None:
                return None
            if QThread.currentThread().isInterruptionRequested():
                return None
            # Persist here, on the worker thread. Saving + decrypting a large
            # catalogue is CPU/IO heavy and used to run inside the success
            # slot, which froze the UI for the whole duration of a big import.
            playlist_id, channels = self._playlist_controller.import_playlist(
                playlist
            )
            return (playlist, playlist_id, channels)

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

    @Slot(object)
    def _on_import_finished(self, result):
        """Handle successful playlist import.

        The worker already persisted the catalogue and returned
        ``(playlist, playlist_id, channels)``; a bare ``Playlist`` is still
        accepted for backwards compatibility.
        """
        self._last_import = None
        if result is None:
            self.statusBar().showMessage("Importação cancelada.")
            return
        if isinstance(result, tuple) and len(result) == 3:
            playlist, playlist_id, channels = result
        else:
            playlist = result
            playlist_id, channels = self._playlist_controller.import_playlist(
                playlist
            )
        self.statusBar().showMessage(f"Playlist importada: {playlist.name}")

        try:
            counts = {content_type: 0 for content_type in CONTENT_TYPES}
            for channel in channels:
                bucket = content_type_for_stream(channel.stream_type)
                if bucket:
                    counts[bucket] += 1

            # Freshly imported catalogues already carry correct types/headers;
            # mark their one-time migrations done so the next selection can use
            # the fast (non-decrypting) metadata path immediately.
            source_type = getattr(playlist, "source_type", "")
            if source_type in ("m3u", "m3u_plus"):
                self._db.set_metadata_flag(f"m3u_types_repaired:{playlist_id}")
                self._db.set_catalog_state(playlist_id, "live", "ready", counts["live"])
                self._db.set_catalog_state(playlist_id, "vod", "ready", counts["vod"])
                self._db.set_catalog_state(playlist_id, "series", "ready", counts["series"])
            elif source_type == "stalker":
                self._db.set_metadata_flag(f"stalker_headers_repaired:{playlist_id}")

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
        """Handle import errors with opportunity to retry with filled inputs."""
        self.statusBar().showMessage("Erro na importação")
        last = getattr(self, "_last_import", None)
        if last:
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("Erro de Importação")
            msg_box.setText("Não foi possível importar a playlist:")
            msg_box.setInformativeText(
                f"{error_message}\n\nDesejas verificar os dados introduzidos e tentar novamente?"
            )
            btn_retry = msg_box.addButton("Tentar novamente", QMessageBox.ButtonRole.AcceptRole)
            msg_box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(btn_retry)
            msg_box.exec()
            if msg_box.clickedButton() == btn_retry:
                import_type = last.get("type")
                values = last.get("values", {})
                if import_type == "m3u":
                    self._import_m3u(initial_values=values)
                elif import_type == "xtream":
                    self._import_xtream(initial_values=values)
                elif import_type == "stalker":
                    self._import_stalker(initial_values=values)
                return
        else:
            QMessageBox.critical(self, "Erro de Importação", error_message)
