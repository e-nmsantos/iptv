"""Playback orchestration for the main window.

Extracted from ``main_window.py`` to keep ``MainWindow`` focused on layout
and window-level wiring. ``PlaybackMixin`` must be mixed into a class that
provides the expected collaborators (``_media_player``, ``_player_widget``,
``_live_list``, ``_vod_list``, ``_series_browser``, ``_db``, ``_settings``,
``_logger``, ``_run_background``, ``_call_stalker``, ``_call_xtream``, ...).
"""

import re
from dataclasses import replace as dc_replace
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import QListWidgetItem, QMessageBox

from ..core.channel import Channel
from ..core.diagnostics import diagnose_channel


class PlaybackMixin:
    """Channel selection, VOD/series playback, history and volume controls."""

    @Slot(object)
    def _on_channel_selected(self, channel):
        """Resolve temporary Stalker commands when required, then play."""
        self._load_channel_epg(channel)
        if (
            channel.source == "stalker"
            and re.search(r"://(?:localhost|127\.0\.0\.1)(?::\d+)?/", channel.url)
        ):
            playlist_id = self._current_playlist_id

            def resolve():
                return self._call_stalker(
                    playlist_id,
                    lambda parser: parser.resolve_live_link(channel.url),
                )

            def on_resolved(url):
                self._play_channel(dc_replace(channel, url=url))

            self._run_background(
                resolve,
                on_resolved,
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

    def _play_channel(self, channel):
        """Start playback of a channel whose URL is already resolved/final."""
        try:
            self._persist_playback_progress()
            self._media_player.stop()
            self._current_playback_channel = channel
            self._playback_position_ms = 0
            self._playback_length_ms = 0
            self._last_progress_save_ms = 0
            # Set video widget
            self._media_player.set_video_widget(self._player_widget.get_video_widget())
            # Play
            headers = dict(channel.custom_headers)
            if channel.user_agent:
                headers["User-Agent"] = channel.user_agent
            if channel.referer:
                headers["Referer"] = channel.referer

            self._media_player.play(
                channel.url,
                headers if headers else None,
                is_live=channel.stream_type == "live",
            )
            self._player_widget.set_channel_info(channel.name)
            self.statusBar().showMessage(f"A reproduzir: {channel.name}")
            if self._current_playlist_id:
                resume = self._playback_controller.started(
                    self._current_playlist_id, channel
                )
                self._refresh_history()
                if resume:
                    position_ms = int(resume["position_ms"])
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
        except Exception as e:
            self._logger.error(f"Playback failed: {e}")
            QMessageBox.warning(self, "Erro", f"Falha ao reproduzir: {e}")

    @Slot(int)
    def _track_playback_time(self, position_ms: int):
        self._playback_position_ms = max(0, int(position_ms))
        if self._playback_position_ms - self._last_progress_save_ms >= 5000:
            self._persist_playback_progress()
            self._last_progress_save_ms = self._playback_position_ms

    @Slot(int)
    def _track_playback_length(self, length_ms: int):
        self._playback_length_ms = max(0, int(length_ms))

    @Slot()
    def _on_media_ended(self):
        self._playback_position_ms = self._playback_length_ms
        self._persist_playback_progress()
        self._refresh_resume()

    def _persist_playback_progress(self):
        if (
            self._current_playlist_id
            and self._current_playback_channel
            and self._playback_length_ms > 0
        ):
            try:
                self._playback_controller.save_progress(
                    self._current_playlist_id,
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
        def run():
            return diagnose_channel(
                channel,
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
        self._show_toast(f"⚠ {message}")
        channel = self._current_playback_channel
        if (
            not channel
            or channel.stream_type != "live"
            or self._content_stack.currentIndex() != 0
            or not self._settings.get("auto_next_enabled", True)
        ):
            return
        # One zap per failure; the guard resets when the next zap runs.
        if self._auto_next_pending:
            return
        delay = max(0, int(self._settings.get("auto_next_delay_ms", 2000)))
        self._auto_next_pending = True
        QTimer.singleShot(delay, self._do_auto_next)

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
