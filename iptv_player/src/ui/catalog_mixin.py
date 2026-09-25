"""Catalog, EPG and parental group-lock orchestration for the main window.

Extracted from ``main_window.py`` to keep that class focused on layout and
window-level wiring. ``CatalogMixin`` must be mixed into a class that provides
the expected collaborators (``_db``, ``_settings``, ``_epg_controller``,
``_live_list``, ``_vod_list``, ``_series_browser``, ``_epg_widget``,
``_epg_grid_widget``, ``_bottom_tabs``, ``_content_stack``, ``_run_background``,
``_call_xtream``, ``_call_stalker``, ``_play_channel``, ``_pin_attempts``,
``_catalog_loading``, ``_epg_loading_playlists``, ``_epg_loading_channels``,
``_epg_grid_cache``, ``_epg_grid_cache_playlist_id``, ``_current_playlist_id``,
``_catalog_controller``, ``_logger`` and the QWidget accessors).
"""

from dataclasses import replace as dc_replace
from datetime import datetime, timedelta
from typing import Optional

from PySide6.QtCore import QThread, QTimer, Slot
from PySide6.QtWidgets import QMessageBox

from ..core.channel import Channel
from ..core.content_types import STREAM_TYPES_BY_CONTENT, content_type_for_tab
from ..core.task_manager import report_progress
from .dialogs import ParentalPinDialog


class CatalogMixin:
    """Channel distribution, lazy catalog loading, EPG and group locks."""

    # Keep at most this many playlists' channel lists in memory. Each entry can
    # hold tens of thousands of Channel objects, so the cache used to grow the
    # process footprint for every playlist ever visited in a session.
    _PLAYLIST_CACHE_LIMIT = 4

    def _cache_playlist_channels(self, playlist_id: Optional[int], cached: dict) -> None:
        """Store one playlist's channels, evicting the least recently used."""
        if playlist_id is None:
            return
        if not hasattr(self, "_playlist_channel_cache"):
            self._playlist_channel_cache = {}
        cache = self._playlist_channel_cache
        # Re-inserting marks the playlist as most recently used. This works for
        # both dict and OrderedDict, unlike move_to_end().
        cache.pop(playlist_id, None)
        cache[playlist_id] = cached
        while len(cache) > self._PLAYLIST_CACHE_LIMIT:
            cache.pop(next(iter(cache)))

    @staticmethod
    def _epg_load_key(playlist_id: int, channel: Channel) -> tuple:
        """Loading-guard key for one channel's EPG fetch.

        Uses the EPG identity instead of the database row id: synthetic
        channels (e.g. a Stalker episode built on the fly) have
        ``database_id == 0``, so every one of them collided on the same key and
        all but the first were treated as "already loading".
        """
        identity = (
            getattr(channel, "database_id", 0)
            or channel.epg_channel_id
            or channel.tvg_id
            or channel.xtream_id
            or channel.name
        )
        return (playlist_id, identity)

    def _distribute_channels(self, channels: list):
        """Split channels by stream_type and populate the active tab, deferring other tabs."""
        self._cached_channels_by_type = {
            content_type: [
                channel
                for channel in channels
                if channel.stream_type in accepted
            ]
            for content_type, accepted in STREAM_TYPES_BY_CONTENT.items()
        }
        if getattr(self, "_current_playlist_id", None) is not None:
            self._cache_playlist_channels(
                self._current_playlist_id, self._cached_channels_by_type
            )
        self._dirty_tabs = {0, 1, 2}
        active_tab = self._content_stack.currentIndex()
        self._populate_tab(active_tab)
        self._refresh_locked_groups()

    def _populate_tab(self, index: int):
        """Populate the widget for the given tab index only when needed."""
        cached = getattr(self, "_cached_channels_by_type", None)
        dirty = getattr(self, "_dirty_tabs", None)
        if cached is None or dirty is None:
            return

        current_pl_id = getattr(self, "_current_playlist_id", None)
        cache = getattr(self, "_playlist_channel_cache", {})

        if index == 0 and 0 in dirty:
            channels = cached.get("live")
            if channels is None and current_pl_id:
                channels = self._db.get_channels(current_pl_id, stream_type="live", decrypt_urls=False)
                cached["live"] = channels
                if current_pl_id in cache:
                    cache[current_pl_id]["live"] = channels
            self._live_list.set_channels(channels or [])
            dirty.discard(0)
        elif index == 1 and 1 in dirty:
            channels = cached.get("vod")
            if channels is None and current_pl_id:
                channels = self._db.get_channels(current_pl_id, stream_type="vod", decrypt_urls=False)
                cached["vod"] = channels
                if current_pl_id in cache:
                    cache[current_pl_id]["vod"] = channels
            self._vod_list.set_channels(channels or [])
            dirty.discard(1)
        elif index == 2 and 2 in dirty:
            channels = cached.get("series")
            if channels is None and current_pl_id:
                channels = self._db.get_channels(current_pl_id, stream_type="series", decrypt_urls=False)
                cached["series"] = channels
                if current_pl_id in cache:
                    cache[current_pl_id]["series"] = channels
            self._series_browser.set_shows(channels or [])
            dirty.discard(2)

    @Slot(int)
    def _on_content_tab_changed(self, index: int):
        self._content_stack.setCurrentIndex(index)
        self._populate_tab(index)
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
        content_type = content_type_for_tab(index, default="")
        if not playlist_id or not content_type:
            return

        playlist = self._db.get_playlist(playlist_id)
        source_type = playlist.get("source_type") if playlist else ""
        if not playlist or source_type not in ("stalker", "xtream", "m3u", "m3u_plus"):
            return

        # For M3U playlists, channels are already in SQLite; don't re-download on tab change unless forced.
        if source_type in ("m3u", "m3u_plus") and not force:
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
                accepted_types = STREAM_TYPES_BY_CONTENT.get(
                    content_type, (content_type,)
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
        """Group normalized programs and hand them to the EPG widget."""
        grouped = {}
        for program in programs:
            grouped.setdefault(program.channel_id, []).append(program)
        live_channels = [c for c in channels if c.stream_type == "live"]
        _, channel_names = self._epg_channel_maps(live_channels)
        self._epg_widget.set_epg_data(grouped, channel_names)
        if playlist_id is not None:
            self._epg_grid_cache = grouped
            self._epg_grid_cache_playlist_id = playlist_id

    def _load_playlist_epg(
        self, playlist_id: int, channels: list, force: bool = False
    ):
        """Show cached EPG and refresh a configured XMLTV source when stale."""
        def load_cached_epg():
            return self._epg_controller.cached(playlist_id)

        def on_cached_epg_loaded(cached):
            if self._closing or self._current_playlist_id != playlist_id:
                return
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

        self._run_background(
            load_cached_epg,
            on_cached_epg_loaded,
            use_semaphore=False,
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

        def load_cached():
            return self._epg_controller.cached(playlist_id, channel_id)

        def on_cached(cached):
            if self._closing or self._current_playlist_id != playlist_id:
                return
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

            key = self._epg_load_key(playlist_id, channel)
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
                src_name = "Xtream" if channel.source == "xtream" else "Stalker"
                self._logger.warning(f"Failed to update {src_name} EPG: {message}")

            self._run_background(fetch_and_cache, on_success, on_error)

        self._run_background(load_cached, on_cached, use_semaphore=False)

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
            key = self._epg_load_key(playlist_id, channel)
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
            key = self._epg_load_key(playlist_id, channel)
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
        """Play a past programme via Xtream or Stalker timeshift (catch-up / replay)."""
        playlist_id = self._current_playlist_id
        if not playlist_id:
            return

        if channel.source == "xtream" and channel.has_archive:
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
                        name=f"{channel.name} · ⏪ {program.title}",
                    )
                )

            self._run_background(
                build_url,
                on_built,
                on_error=lambda msg: self._logger.warning(f"Catch-up failed: {msg}"),
                status_message=f"A obter gravação: {channel.name}...",
                context_playlist_id=playlist_id,
            )
        elif channel.source == "stalker":
            # Catch-up is only possible for a hydrated channel: the portal
            # command lives in the (encrypted) URL/tvg_id, not in the SQLite
            # row id that used to be sent here.
            stalker_channel = self._hydrate_channel(channel)

            def resolve_stalker():
                ts = int(program.start.timestamp())
                duration_seconds = max(
                    1, int((program.stop - program.start).total_seconds())
                )
                cmd = (
                    stalker_channel.url
                    or stalker_channel.tvg_id
                    or str(getattr(stalker_channel, "id", "") or "")
                )
                return self._call_stalker(
                    playlist_id,
                    lambda parser: parser.resolve_catchup_link(
                        cmd, ts, duration_seconds
                    ),
                )

            def on_stalker_resolved(catchup_url):
                if catchup_url:
                    self._play_channel(
                        dc_replace(
                            channel,
                            url=catchup_url,
                            name=f"{channel.name} · ⏪ {program.title}",
                        )
                    )

            self._run_background(
                resolve_stalker,
                on_stalker_resolved,
                on_error=lambda msg: self._logger.warning(f"Stalker catchup failed: {msg}"),
                status_message=f"A obter gravação Stalker: {channel.name}...",
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
