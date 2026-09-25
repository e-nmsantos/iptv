"""Playlist selection and management operations for the main window.

Extracted from ``main_window.py``. ``PlaylistOpsMixin`` must be mixed into a
class that provides ``_db``, ``_settings``, ``_playlist_controller``,
``_playlist_widget``, ``_epg_widget``, ``_content_stack``, ``_run_background``,
``_load_playlists``, ``_distribute_channels``, ``_load_playlist_epg``,
``_ensure_catalog_for_tab``, ``_refresh_history``, ``_refresh_resume``,
``_discard_provider_sessions``, ``_logger`` and the collection of
``_catalog_loading`` / ``_stalker_metadata_loading`` guards.
"""

from typing import Optional

from PySide6.QtCore import QThread, Slot
from PySide6.QtWidgets import QMessageBox

from ..core.content_types import (
    CONTENT_TYPES,
    STREAM_TYPES_BY_CONTENT,
    content_type_for_tab,
)
from ..parsers.m3u_parser import M3UParser
from ..parsers.stalker_parser import StalkerParser
from ..parsers.xtream_parser import XtreamParser
from .dialogs import PlaylistDialog, StalkerDialog, XtreamDialog


def _worker_cancelled() -> bool:
    """Cooperative-cancellation predicate for calls running on a task worker.

    Evaluated on the worker thread itself, so it reports that specific
    worker's interruption state.
    """
    return QThread.currentThread().isInterruptionRequested()


class PlaylistOpsMixin:
    def _get_playlist_name(self, playlist_id: int) -> str:
        """Get playlist name from memory cache without hitting database."""
        names = getattr(self, "_playlist_names", {})
        if playlist_id in names:
            return names[playlist_id]
        if hasattr(self, "_playlists"):
            for p in self._playlists:
                if p.get("id") == playlist_id:
                    name = p.get("name", "Playlist")
                    names[playlist_id] = name
                    return name
        pl = self._db.get_playlist(playlist_id)
        name = pl.get("name", "Playlist") if pl else "Playlist"
        names[playlist_id] = name
        return name

    def _on_playlist_selected(self, playlist_id: int, after_load=None):
        """Handle playlist selection with instant memory cache and fast indexed loading."""
        if not playlist_id:
            return
        self._current_playlist_id = playlist_id
        from PySide6.QtCore import QTimer
        QTimer.singleShot(150, self._refresh_history)
        QTimer.singleShot(250, self._refresh_resume)

        # Instant switch: if channels are already in memory, display immediately (< 2 ms)
        cache = getattr(self, "_playlist_channel_cache", {})
        if playlist_id in cache:
            cached_types = cache[playlist_id]
            self._cached_channels_by_type = cached_types
            self._dirty_tabs = {0, 1, 2}
            active_tab = self._content_stack.currentIndex()
            self._populate_tab(active_tab)
            self._refresh_locked_groups()
            live_channels = cached_types.get("live") or []
            self._load_playlist_epg(playlist_id, live_channels)
            self._ensure_catalog_for_tab(active_tab)

            pl_name = self._get_playlist_name(playlist_id)
            total_items = sum(
                len(v) for v in cached_types.values() if v is not None
            )
            self.statusBar().showMessage(
                f"Playlist: {pl_name} | {total_items} canais/itens"
            )
            if after_load:
                after_load()
            return

        # First visit: load the active stream type (e.g. Live TV) first via indexed query
        # without consuming HTTP network semaphore tokens.
        active_tab = self._content_stack.currentIndex()
        active_stream_type = content_type_for_tab(active_tab)

        def load():
            playlist_details = self._db.get_playlist(playlist_id)
            if not playlist_details:
                raise LookupError("Playlist não encontrada.")

            # Fast path: load active tab metadata from database without decrypting URLs.
            channels = self._db.get_channels(
                playlist_id, stream_type=active_stream_type, decrypt_urls=False
            )
            return playlist_details, channels, active_stream_type

        def on_success(result):
            if self._closing:
                return
            playlist_details, active_channels, loaded_type = result
            active_channels = self._run_pending_catalog_repairs(
                playlist_id, playlist_details, active_channels
            )
            cached = {
                content_type: (
                    active_channels if loaded_type == content_type else None
                )
                for content_type in CONTENT_TYPES
            }
            self._cache_playlist_channels(playlist_id, cached)
            self._cached_channels_by_type = cached
            self._dirty_tabs = {0, 1, 2}

            self._populate_tab(active_tab)
            self._refresh_locked_groups()
            if loaded_type == "live":
                self._load_playlist_epg(playlist_id, active_channels)
            self._ensure_catalog_for_tab(active_tab)

            pl_name = playlist_details.get("name") or self._get_playlist_name(playlist_id)
            self.statusBar().showMessage(
                f"Playlist: {pl_name} | {len(active_channels)} itens"
            )
            if after_load:
                after_load()

            # Preload remaining stream types in background to populate cache after UI settles
            from PySide6.QtCore import QTimer
            QTimer.singleShot(
                1200,
                lambda pid=playlist_id, lt=loaded_type: (
                    self._preload_remaining_types(pid, exclude_type=lt)
                    if self._current_playlist_id == pid
                    else None
                ),
            )

        def on_error(message):
            self._logger.error(f"Failed to load channels: {message}")
            self.statusBar().showMessage(f"Falha ao carregar canais: {message}")

        self._run_background(
            load,
            on_success,
            on_error,
            status_message="A carregar playlist...",
            context_playlist_id=playlist_id,
            use_semaphore=False,
        )

    def _preload_remaining_types(self, playlist_id: int, exclude_type: str):
        """Preload the non-active stream types into memory cache asynchronously."""
        def load_remaining():
            remaining = {}
            for stype in CONTENT_TYPES:
                if stype != exclude_type:
                    remaining[stype] = self._db.get_channels(
                        playlist_id, stream_type=stype, decrypt_urls=False
                    )
            return remaining

        def on_loaded(remaining):
            if self._closing:
                return
            cache = getattr(self, "_playlist_channel_cache", {})
            if playlist_id in cache:
                cache[playlist_id].update(remaining)
            if self._current_playlist_id == playlist_id:
                if hasattr(self, "_cached_channels_by_type"):
                    self._cached_channels_by_type.update(remaining)
                total = sum(
                    len(v) for v in self._cached_channels_by_type.values() if v is not None
                )
                pl_name = self._get_playlist_name(playlist_id)
                self.statusBar().showMessage(
                    f"Playlist: {pl_name} | {total} canais/itens"
                )

        self._run_background(
            load_remaining,
            on_loaded,
            context_playlist_id=playlist_id,
            use_semaphore=False,
        )

    def _refresh_stalker_metadata_if_needed(
        self, playlist_id: int, playlist: Optional[dict], channels: list
    ):
        """Repair country/category metadata in already-saved Stalker playlists."""
        flag = f"stalker_categories_repaired:{playlist_id}"
        if (
            not playlist
            or playlist.get("source_type") != "stalker"
            or self._db.get_metadata_flag(flag)
            or self._db.get_metadata_flag(f"stalker_headers_repaired:{playlist_id}")
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
                cancel_requested=_worker_cancelled,
            ) as parser:
                refreshed = parser.get_full_playlist().channels
            self._db.update_stalker_channel_metadata(playlist_id, refreshed)
            return self._db.get_channels(playlist_id)

        def on_success(refreshed):
            self._stalker_metadata_loading.discard(playlist_id)
            self._db.set_metadata_flag(flag)
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

    def _run_pending_catalog_repairs(
        self, playlist_id: int, playlist: Optional[dict], channels: list
    ) -> list:
        """Apply the one-time repairs that older versions never ran.

        Both repairs are gated by an ``app_metadata`` flag that a fresh import
        already sets, so a new playlist skips them and each legacy playlist is
        fixed exactly once.
        """
        if not playlist:
            return channels
        source_type = playlist.get("source_type", "")
        repaired = channels
        if source_type in ("m3u", "m3u_plus"):
            repaired = self._repair_m3u_stream_types(playlist_id, channels)
        elif source_type == "stalker":
            repaired = self._repair_stalker_channel_headers(
                playlist_id, playlist, channels
            )
            self._refresh_stalker_metadata_if_needed(
                playlist_id, playlist, repaired
            )
        return repaired

    def _repair_m3u_stream_types(self, playlist_id: int, channels: list) -> list:
        """Re-infer live/vod/series for playlists imported as all-live.

        Older versions stored every M3U entry as ``live``, so films and series
        showed up under "Em direto". The channel URLs are not decrypted here
        (these rows are loaded without them), but the group/name heuristics are
        what actually separate the buckets.
        """
        flag = f"m3u_types_repaired:{playlist_id}"
        if self._db.get_metadata_flag(flag):
            return channels

        updated = []
        for channel in channels:
            inferred = M3UParser.infer_stream_type(
                "", channel.group, channel.name
            )
            if inferred != channel.stream_type:
                channel.stream_type = inferred
                updated.append(channel)

        if updated:
            self._db.update_channel_stream_types(playlist_id, updated)
            self._logger.info(
                "Reparados %d tipos de conteudo na playlist %d",
                len(updated),
                playlist_id,
            )
        self._db.set_metadata_flag(flag)
        return channels

    def _repair_stalker_channel_headers(
        self, playlist_id: int, playlist: dict, channels: list
    ) -> list:
        """Restore the MAG playback headers on channels saved without them."""
        flag = f"stalker_headers_repaired:{playlist_id}"
        if self._db.get_metadata_flag(flag):
            return channels

        missing = [
            channel
            for channel in channels
            if not channel.user_agent or not channel.referer
        ]
        if missing:
            headers = StalkerParser.playback_headers_for(playlist["server_url"])
            self._db.update_stalker_headers(
                playlist_id, headers["User-Agent"], headers["Referer"]
            )
            for channel in channels:
                channel.user_agent = channel.user_agent or headers["User-Agent"]
                channel.referer = channel.referer or headers["Referer"]
            self._logger.info(
                "Restaurados cabecalhos Stalker em %d canais da playlist %d",
                len(missing),
                playlist_id,
            )
        self._db.set_metadata_flag(flag)
        return channels

    @Slot(int)
    def _on_playlist_deleted(self, playlist_id: int):
        """Handle playlist deletion."""
        try:
            self._playlist_controller.delete(playlist_id)
            if self._current_playlist_id == playlist_id:
                self._current_playlist_id = None
            if hasattr(self, "_playlist_channel_cache"):
                self._playlist_channel_cache.pop(playlist_id, None)
            self._load_playlists()
            self._distribute_channels([])
            self._epg_widget.clear()
            self._discard_provider_sessions(playlist_id)
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
                    should_cancel=_worker_cancelled,
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
                    cancel_requested=_worker_cancelled,
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
                cancel_requested=_worker_cancelled,
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
                for content_type, stream_types in STREAM_TYPES_BY_CONTENT.items():
                    self._db.replace_catalog(
                        playlist_id,
                        content_type,
                        [
                            channel
                            for channel in parsed_channels
                            if channel.stream_type in stream_types
                        ],
                    )
            else:
                # Xtream/Stalker credentials determine which catalogue the
                # playlist serves, so whatever was cached belongs to the old
                # account. Without this the "ready" catalog_state made
                # _ensure_catalog_for_tab skip the refetch and the app kept
                # showing (and playing) the previous provider's channels.
                for content_type in ("live", "vod", "series"):
                    self._db.set_catalog_state(
                        playlist_id, content_type, "stale", 0
                    )
            # Drop the in-memory copy in both cases: the catalogue changed.
            getattr(self, "_playlist_channel_cache", {}).pop(playlist_id, None)
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
