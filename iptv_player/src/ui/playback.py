"""Playback orchestration for the main window.

Extracted from ``main_window.py`` to keep ``MainWindow`` focused on layout
and window-level wiring. ``PlaybackMixin`` must be mixed into a class that
provides the expected collaborators (``_media_player``, ``_player_widget``,
``_live_list``, ``_vod_list``, ``_series_browser``, ``_db``, ``_settings``,
``_logger``, ``_run_background``, ``_call_stalker``, ``_call_xtream``, ...).
"""

import threading
from dataclasses import replace as dc_replace
from typing import Optional
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import QListWidgetItem, QMessageBox

from ..core.channel import Channel
from ..core.content_types import LIVE, SERIES, VOD, content_type_for_stream
from ..core.diagnostics import diagnose_channel


class PlaybackMixin:
    """Channel selection, VOD/series playback, history and volume controls."""

    @Slot(object)
    def _on_channel_selected(self, channel):
        """Resolve temporary Stalker commands when required, then play."""
        if not getattr(self, "_fallback_in_progress", False):
            # A deliberate selection starts a fresh fallback budget.
            getattr(self, "_fallback_attempted", set()).clear()
        channel = self._hydrate_channel(channel)
        QTimer.singleShot(60, lambda ch=channel: self._load_channel_epg(ch))
        if channel.source == "stalker":
            url_str = (channel.url or "").strip()
            url_lower = url_str.lower()
            is_temporary = (
                not url_lower.startswith(("http://", "https://", "rtmp://", "rtsp://", "udp://", "rtp://"))
                or "localhost" in url_lower
                or "127.0.0.1" in url_lower
            )

            if is_temporary:
                playlist_id = self._current_playlist_id

                def resolve():
                    cmd = channel.url or channel.tvg_id or str(getattr(channel, "id", "") or "")
                    return self._call_stalker(
                        playlist_id,
                        lambda parser: parser.resolve_live_link(cmd),
                    )

                def on_resolved(url):
                    # Do NOT write the resolved token back onto `channel`: that
                    # object is the one held by the channel list, so the short
                    # lived create_link URL would be replayed on the next click
                    # (expired token) instead of being resolved again.
                    self._play_channel(dc_replace(channel, url=url))

                def on_error(err):
                    self._logger.warning(
                        "Stalker resolve_live_link falhou (%s), a tentar url direta", err
                    )
                    self._play_channel(channel)

                self._run_background(
                    resolve,
                    on_resolved,
                    on_error=on_error,
                    status_message=f"A obter link: {channel.name}...",
                    context_playlist_id=playlist_id,
                )
                return

        self._play_channel(channel)

    def _refresh_history(self):
        self._history_list.clear()
        if not self._current_playlist_id:
            return
        try:
            for entry in self._playback_controller.history(self._current_playlist_id):
                played_at = entry["played_at"].replace("T", " ")[:16]
                self._history_list.addItem(
                    f"{entry['title']}  ·  {played_at}"
                )
        except Exception as exc:
            self._logger.warning(f"Failed to load playback history: {exc}")

    def _refresh_resume(self):
        """Refresh the 'Continuar a ver' list (non-live items with progress)."""
        if not hasattr(self, "_resume_list"):
            return
        self._resume_list.clear()
        if not self._current_playlist_id:
            return
        try:
            for entry in self._playback_controller.resume_candidates(
                self._current_playlist_id
            ):
                channel = entry["channel"]
                percent = round(entry["fraction"] * 100)
                row = QListWidgetItem(f"▶ {channel.name}  ·  {percent}%")
                row.setData(Qt.ItemDataRole.UserRole, channel)
                row.setToolTip(f"Retomar {channel.name} em {percent}%")
                self._resume_list.addItem(row)
        except Exception as exc:
            self._logger.warning(f"Failed to load resume list: {exc}")

    def _on_resume_item_activated(self, item: QListWidgetItem):
        """Resume playback of a VOD/series entry (position restored by _play_channel)."""
        channel = item.data(Qt.ItemDataRole.UserRole)
        if channel:
            self._on_vod_selected(channel)

    def _hydrate_channel(self, channel):
        """Return a channel with decrypted URL/headers.

        Channel lists load metadata without decrypting URLs for speed; this
        hydrates a single channel just before it is played or diagnosed.
        Caches decrypted attributes onto the Channel object so future
        calls return immediately in memory.
        """
        if channel.url:
            return channel
        playlist_id = self._current_playlist_id
        if not playlist_id or not channel.database_id:
            return channel
        fresh = self._db.get_channel(channel.database_id, playlist_id)
        if fresh:
            channel.url = fresh.url
            channel.referer = fresh.referer
            channel.custom_headers = fresh.custom_headers
            channel.user_agent = fresh.user_agent
            return fresh
        return channel

    def _resolve_channel_url(self, channel) -> str:
        """Resolve a channel's URL for display/copy (hydrating light rows)."""
        return self._hydrate_channel(channel).url

    def _play_channel(self, channel):
        """Start playback of a channel whose URL is already resolved/final."""
        try:
            self._persist_playback_progress()
            self._current_playback_channel = channel
            self._current_playback_playlist_id = self._current_playlist_id
            self._playback_position_ms = 0
            self._playback_length_ms = 0
            self._last_progress_save_ms = 0

            # Update visual playing indicators
            ch_id = getattr(channel, "database_id", None) or getattr(channel, "id", None)
            if hasattr(self, "_live_list"):
                self._live_list.set_playing_channel_id(ch_id)
            if hasattr(self, "_vod_list"):
                self._vod_list.set_playing_channel_id(ch_id)

            # Adapt player controls and clear prior error banners
            if hasattr(self, "_player_widget"):
                self._player_widget.set_stream_type(channel.stream_type)
                self._player_widget.clear_error_banner()

            # Set video widget
            self._media_player.set_video_widget(self._player_widget.get_video_widget())
            # Play directly: VLC transitions smoothly to the new media without
            # requiring a synchronous, blocking stop() on the GUI thread.
            headers = dict(channel.custom_headers)
            if channel.user_agent:
                headers["User-Agent"] = channel.user_agent
            if channel.referer:
                headers["Referer"] = channel.referer

            play_url = channel.url
            if channel.source == "xtream" and play_url and self._current_playlist_id:
                try:
                    pl = self._db.get_playlist(self._current_playlist_id)
                    if pl and pl.get("server_url"):
                        parsed_srv = urlparse(pl["server_url"])
                        if parsed_srv.port and ":80/" in play_url:
                            play_url = play_url.replace(":80/", f":{parsed_srv.port}/", 1)
                except Exception:
                    pass

            self._media_player.play(
                play_url,
                headers if headers else None,
                is_live=channel.stream_type == "live",
            )
            self._player_widget.set_channel_info(channel.name)
            self.statusBar().showMessage(f"A reproduzir: {channel.name}")

            # If casting is currently active, seamlessly update stream on the TV
            try:
                from ..core.cast_manager import CastManager
                cast_mgr = CastManager.get_instance()
                if cast_mgr.is_casting and cast_mgr.active_device:
                    cast_mgr.cast_to_device(
                        cast_mgr.active_device,
                        channel.url,
                        channel.name,
                        headers=headers if headers else None,
                        is_live=channel.stream_type == "live",
                    )
            except Exception as e:
                self._logger.debug("Failed to forward channel to active cast: %s", e)

            # Recording the play and reading back the resume position both hit
            # the database. Doing that inline made VOD playback hitch on slower
            # disks (and only the live path was backgrounded before).
            playlist_id = self._current_playlist_id
            if playlist_id:
                def record_start():
                    return self._playback_controller.started(playlist_id, channel)

                def on_started(resume):
                    QTimer.singleShot(150, self._refresh_history)
                    if self._current_playback_channel is not channel:
                        return
                    if content_type_for_stream(channel.stream_type) not in (VOD, SERIES):
                        return
                    if not resume:
                        return
                    position_ms = int(resume["position_ms"])
                    if position_ms < 30_000:
                        return
                    mins = position_ms // 60000
                    secs = (position_ms % 60000) // 1000
                    time_str = f"{mins} min" if secs == 0 else f"{mins}m {secs}s"
                    box = QMessageBox(self.window())
                    box.setWindowTitle("Retomar reprodução")
                    box.setText(f"Já tinhas começado a ver '{channel.name}'.")
                    btn_resume = box.addButton(f"▶ Continuar aos {time_str}", QMessageBox.ButtonRole.AcceptRole)
                    box.addButton("⏮ Ver do início", QMessageBox.ButtonRole.RejectRole)
                    box.setDefaultButton(btn_resume)
                    box.exec()
                    if box.clickedButton() == btn_resume:
                        self._resume_from(position_ms, channel)

                self._run_background(
                    record_start,
                    on_started,
                    use_semaphore=False,
                    context_playlist_id=playlist_id,
                )

            # Automatic subtitles for VOD / Series
            self._trigger_auto_subtitles(channel)
        except Exception as e:
            self._logger.error(f"Playback failed: {e}")
            QMessageBox.warning(self, "Erro", f"Falha ao reproduzir: {e}")

    def _resume_from(self, position_ms: int, channel) -> None:
        """Seek to a saved position once the stream has had time to start."""
        QTimer.singleShot(
            1500,
            lambda active=channel, position=position_ms: (
                self._media_player.set_time(position)
                if self._current_playback_channel is active
                else None
            ),
        )
        self.statusBar().showMessage(
            f"A retomar {channel.name} em {position_ms // 60000} min."
        )

    def _candidate_pool(self, channel) -> list:
        """Channels the fallback search may choose an alternative from."""
        content_type = content_type_for_stream(
            getattr(channel, "stream_type", "live")
        )
        widget = {
            LIVE: getattr(self, "_live_list", None),
            VOD: getattr(self, "_vod_list", None),
        }.get(content_type)
        if widget is not None and hasattr(widget, "get_filtered_channels"):
            return widget.get_filtered_channels()
        cached = getattr(self, "_cached_channels_by_type", None) or {}
        return list(cached.get(content_type) or [])

    def _switch_to_fallback(self, channel) -> bool:
        """Try a backup stream for the same channel before giving up.

        Duplicate/backup entries are common in IPTV playlists and this search
        was never wired up, so playback failed even when a working mirror was
        already in the list. Attempted at most once per channel (the second
        failure finds the original channel in the attempted set and stops).
        """
        attempted = getattr(self, "_fallback_attempted", None)
        if attempted is None:
            attempted = self._fallback_attempted = set()
        key = getattr(channel, "database_id", 0) or channel.name
        if key in attempted:
            return False
        attempted.add(key)

        try:
            fallback = self._playback_controller.find_fallback_channel(
                channel, self._candidate_pool(channel)
            )
        except Exception as exc:
            self._logger.warning(f"Fallback lookup failed: {exc}")
            return False
        if not fallback:
            return False

        self._show_toast(f"↻ A tentar emissão alternativa: {fallback.name}")
        self._fallback_in_progress = True
        try:
            if getattr(fallback, "stream_type", "live") == "live":
                self._on_channel_selected(fallback)
            else:
                self._on_vod_selected(fallback)
        finally:
            self._fallback_in_progress = False
        return True

    def _trigger_auto_subtitles(self, channel):
        """Automatically fetch and attach Portuguese subtitles for VOD movies/series."""
        if content_type_for_stream(getattr(channel, "stream_type", "")) not in (VOD, SERIES):
            return

        from ..core.metadata_enricher import MetadataEnricher
        from ..core.subtitles_finder import SubtitlesFinder

        def worker():
            try:
                title, year = MetadataEnricher.extract_title_and_year(channel.name)
                if not title:
                    return
                finder = SubtitlesFinder()
                results = finder.search_subtitles(
                    query=title,
                    languages="pt,pob",
                    year=year,
                )
                if not results:
                    return
                best = results[0]
                saved_path = finder.download_subtitle_file(best)
                if saved_path and saved_path.exists():
                    def on_loaded(active=channel, path=str(saved_path), b=best):
                        if getattr(self, "_current_playback_channel", None) is active:
                            self._media_player.add_subtitle_file(path)
                            if hasattr(self, "_toast"):
                                self._toast.show_message(f"💬 Legendas: [{b.language}] {b.release_name}")

                    QTimer.singleShot(0, on_loaded)
            except Exception as ex:
                self._logger.debug("Auto subtitle error: %s", ex)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(int)
    def _track_playback_time(self, position_ms: int):
        self._playback_position_ms = max(0, int(position_ms))
        if self._playback_position_ms - self._last_progress_save_ms >= 5000:
            self._persist_playback_progress_async()
            self._last_progress_save_ms = self._playback_position_ms

    def _persist_playback_progress_async(self) -> None:
        """Queue the periodic progress save off the GUI thread.

        This fires every 5 s while something is playing; running the SQLite
        write inline made VOD playback stutter on slower disks.
        """
        playlist_id = (
            getattr(self, "_current_playback_playlist_id", None)
            or self._current_playlist_id
        )
        channel = self._current_playback_channel
        if not (playlist_id and channel and self._playback_length_ms > 0):
            return
        position = self._playback_position_ms
        length = self._playback_length_ms

        def save():
            self._playback_controller.save_progress(
                playlist_id, channel, position, length
            )

        self._run_background(
            save,
            lambda _result: None,
            on_error=lambda message: self._logger.debug(
                "Falha ao guardar progresso: %s", message
            ),
            use_semaphore=False,
        )

    @Slot(int)
    def _track_playback_length(self, length_ms: int):
        self._playback_length_ms = max(0, int(length_ms))

    @Slot()
    def _on_media_ended(self):
        self._playback_position_ms = self._playback_length_ms
        self._persist_playback_progress()
        self._refresh_resume()

    def _persist_playback_progress(self):
        playlist_id = getattr(self, "_current_playback_playlist_id", None) or self._current_playlist_id
        if (
            playlist_id
            and self._current_playback_channel
            and self._playback_length_ms > 0
        ):
            try:
                self._playback_controller.save_progress(
                    playlist_id,
                    self._current_playback_channel,
                    self._playback_position_ms,
                    self._playback_length_ms,
                )
            except Exception as exc:
                self._logger.warning(f"Failed to save playback progress: {exc}")

    def _progress_fraction_for(self, channel: Channel) -> Optional[float]:
        """`(channel) -> 0..1 | None` resume-progress lookup for poster cards."""
        if not self._current_playlist_id:
            return None
        try:
            return self._playback_controller.progress_fraction(
                self._current_playlist_id, channel
            )
        except Exception:
            return None

    @Slot(object)
    def _diagnose_channel(self, channel):
        channel = self._hydrate_channel(channel)
        playlist_id = self._current_playlist_id

        def run():
            ch = channel
            if ch.source == "stalker" and playlist_id:
                url_lower = (ch.url or "").lower()
                if (
                    not url_lower.startswith(("http://", "https://", "rtmp://", "rtsp://", "udp://", "rtp://"))
                    or "localhost" in url_lower
                    or "127.0.0.1" in url_lower
                ):
                    try:
                        resolved_url = self._call_stalker(
                            playlist_id,
                            lambda parser: parser.resolve_live_link(ch.url or ch.tvg_id or str(getattr(ch, "id", "") or "")),
                        )
                        ch = dc_replace(ch, url=resolved_url)
                    except Exception as err:
                        self._logger.debug("Stalker diagnose resolve failed: %s", err)
            return diagnose_channel(
                ch,
                timeout=self._settings.get("network_timeout_seconds", 30),
            )

        def show(result):
            QMessageBox.information(
                self,
                "Diagnóstico do canal",
                f"Canal: {result['name']}\n"
                f"Protocolo: {result['protocol']}\n"
                f"Servidor: {result['host'] or 'não disponível'}\n"
                f"Estado: {result['status']}\n"
                f"Latência: {result['latency_ms']} ms\n"
                f"Conteúdo: {result['content_type'] or 'não indicado'}",
            )

        self._run_background(
            run,
            show,
            status_message=f"A diagnosticar {channel.name}...",
            context_playlist_id=self._current_playlist_id,
        )

    @Slot(object)
    def _on_vod_selected(self, channel):
        """Handle VOD (movie) selection. Stalker movies store an opaque
        cmd blob as `url` that must be resolved via create_link right
        before playback; other sources already have a final URL."""
        if not getattr(self, "_fallback_in_progress", False):
            getattr(self, "_fallback_attempted", set()).clear()
        channel = self._hydrate_channel(channel)
        if channel.source == "stalker":
            playlist_id = self._current_playlist_id
            raw_cmd = channel.url

            def resolve():
                return self._call_stalker(
                    playlist_id,
                    lambda parser: parser.resolve_link(raw_cmd),
                )

            def on_resolved(url):
                self._play_channel(dc_replace(channel, url=url))

            self._run_background(
                resolve, on_resolved,
                status_message=f"A obter link: {channel.name}...",
                context_playlist_id=playlist_id,
            )
        else:
            self._play_channel(channel)

    @Slot(object)
    def _on_series_show_opened(self, show):
        """User opened a series 'show' — fetch its seasons/episodes live."""
        self._series_browser.show_episode_browser(show.name)
        self.statusBar().showMessage(f"A obter temporadas de {show.name}...")
        playlist_id = self._current_playlist_id

        if show.source == "stalker":
            def fetch():
                return self._call_stalker(
                    playlist_id,
                    lambda parser: parser.get_series_seasons(
                        show.category_id, show.xtream_id
                    ),
                )

            def on_seasons(raw_seasons):
                seasons = []
                for season in raw_seasons:
                    episodes = []
                    for ep_num in season.get("series") or []:
                        episodes.append({
                            "label": f"Episódio {ep_num}",
                            "payload": {
                                "source": "stalker",
                                "cmd": season.get("cmd", ""),
                                "episode": ep_num,
                                "show_name": show.name,
                                "season_name": season.get("name", ""),
                                "user_agent": show.user_agent,
                                "referer": show.referer,
                            },
                        })
                    seasons.append({"name": season.get("name", "Temporada"), "episodes": episodes})
                self._series_browser.set_seasons(seasons)
                self.statusBar().showMessage(f"{show.name}: {len(seasons)} temporada(s)")

            self._run_background(
                fetch, on_seasons, context_playlist_id=playlist_id
            )

        elif show.source == "xtream":
            def fetch():
                return self._call_xtream(
                    playlist_id,
                    lambda parser: parser.get_episodes_for_series(show.xtream_id),
                )

            def on_episodes(episode_channels):
                by_season: dict = {}
                for ep in episode_channels:
                    by_season.setdefault(ep.season_number, []).append(ep)
                seasons = []
                for season_num in sorted(by_season.keys()):
                    episodes = [
                        {
                            "label": ep.name,
                            "image": ep.logo,
                            "payload": {"source": "xtream", "channel": ep},
                        }
                        for ep in by_season[season_num]
                    ]
                    seasons.append({"name": f"Temporada {season_num}", "episodes": episodes})
                self._series_browser.set_seasons(seasons)
                self.statusBar().showMessage(f"{show.name}: {len(seasons)} temporada(s)")

            self._run_background(
                fetch, on_episodes, context_playlist_id=playlist_id
            )

        else:
            # M3U playlists normally expose each episode as a directly playable
            # entry rather than a top-level show with a provider API.
            self._play_channel(show)

    @Slot(object)
    def _on_series_episode_selected(self, payload):
        """User selected a specific episode in the season/episode browser."""
        source = payload.get("source")

        if source == "stalker":
            playlist_id = self._current_playlist_id

            def resolve():
                return self._call_stalker(
                    playlist_id,
                    lambda parser: parser.resolve_link(
                        payload["cmd"], payload["episode"]
                    ),
                )

            def on_resolved(url):
                ep_channel = Channel(
                    name=f"{payload.get('show_name', '')} - {payload.get('season_name', '')} - Ep {payload['episode']}",
                    url=url,
                    stream_type="series",
                    source="stalker",
                    user_agent=payload.get("user_agent", ""),
                    referer=payload.get("referer", ""),
                )
                self._play_channel(ep_channel)

            self._run_background(
                resolve, on_resolved,
                status_message="A obter link do episódio...",
                context_playlist_id=playlist_id,
            )

        elif source == "xtream":
            self._play_channel(payload["channel"])
        elif source == "m3u":
            self._play_channel(payload["channel"])

    @Slot(object, bool)
    def _on_favorite_toggled(self, channel: Channel, is_favorite: bool):
        """Handle favorite toggle."""
        if self._current_playlist_id:
            try:
                self._db.set_favorite(
                    channel.database_id, self._current_playlist_id, is_favorite
                )
                channel.is_favorite = is_favorite
                self._live_list.toggle_favorite(channel.database_id, is_favorite)
                self._vod_list.toggle_favorite(channel.database_id, is_favorite)
                self._series_browser.toggle_favorite(channel.database_id, is_favorite)
                status = "adicionado aos" if is_favorite else "removido dos"
                self.statusBar().showMessage(
                    f"⭐ {channel.name} {status} favoritos."
                )
            except Exception as e:
                self._logger.error(f"Failed to toggle favorite: {e}")

    @Slot(str)
    def _on_media_error(self, message: str):
        """Handle unrecoverable playback errors (retries exhausted)."""
        self._logger.warning("Playback error after retries: %s", message)
        channel = self._current_playback_channel
        if channel is not None and self._switch_to_fallback(channel):
            return
        self._show_toast(f"⚠ {message}")
        is_live = bool(
            channel
            and getattr(channel, "stream_type", "live") == "live"
            and hasattr(self, "_content_stack")
            and self._content_stack.currentIndex() == 0
            and self._settings.get("auto_next_enabled", True)
        )
        if hasattr(self, "_player_widget"):
            self._player_widget.show_error_banner(message, is_live=is_live)

    @Slot()
    def _retry_current_channel(self):
        """Retry playback of the channel that encountered an error."""
        channel = self._current_playback_channel
        if channel:
            # An explicit retry re-arms the backup-stream search.
            key = getattr(channel, "database_id", 0) or channel.name
            getattr(self, "_fallback_attempted", set()).discard(key)
            if getattr(channel, "stream_type", "live") == "live":
                self._on_channel_selected(channel)
            else:
                self._on_vod_selected(channel)

    @Slot()
    def _do_auto_next(self):
        """Move to the next live channel after an unrecoverable error."""
        self._auto_next_pending = False
        if (
            self._content_stack.currentIndex() != 0
            or not self._settings.get("auto_next_enabled", True)
        ):
            return
        next_channel = self._live_list.play_adjacent(1)
        if next_channel is not None:
            self._show_toast(f"⏭ A passar para {next_channel.name}...")

    @Slot()
    def _increase_volume(self):
        volume = min(100, self._media_player.get_volume() + 5)
        self._media_player.set_volume(volume)
        self._player_widget.set_volume(volume)
        self.statusBar().showMessage(f"Volume: {volume}%")

    @Slot()
    def _decrease_volume(self):
        volume = max(0, self._media_player.get_volume() - 5)
        self._media_player.set_volume(volume)
        self._player_widget.set_volume(volume)
        self.statusBar().showMessage(f"Volume: {volume}%")

    @Slot()
    def _toggle_mute(self):
        muted = self._media_player.toggle_mute()
        self.statusBar().showMessage(
            "🔇 Mudo" if muted else f"Volume: {self._media_player.get_volume()}%"
        )

    def _show_toast(self, text: str, duration_ms: int = 2600):
        """Show a non-intrusive toast notification."""
        self._toast.show_message(text, duration_ms)
