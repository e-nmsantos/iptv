"""Início, OSD, number zapping, next episode, reminders and scheduled recordings.

``PremiumMixin`` is mixed into ``MainWindow`` next to ``PlaybackMixin`` and
relies on the same collaborators (``_db``, ``_settings``, ``_media_player``,
``_player_widget``, ``_live_list``, ``_run_background``, ``_call_stalker``,
``_call_xtream``, ...). ``_setup_premium()`` must run after ``_setup_ui()``.
"""

from dataclasses import replace as dc_replace
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMessageBox

from ..core.channel import Channel
from ..core.content_types import LIVE, SERIES, VOD, content_type_for_stream
from ..player.pvr_recorder import PvrRecorderManager
from .icons import icon
from .video_osd import VideoOsd

STALKER_EPISODE_SCHEME = "stalker-episode://"
_REMINDER_LEAD = timedelta(minutes=1)
_RECORDING_TAIL = timedelta(minutes=2)
_NEXT_EPISODE_COUNTDOWN_S = 10


def stalker_episode_channel(show: Channel, season: dict, episode) -> Channel:
    """A replayable Channel for one Stalker episode (its link is resolved on play)."""
    cmd = season.get("cmd", "")
    season_name = season.get("name", "") or "Temporada"
    return Channel(
        name=f"{show.name} - {season_name} - Ep {episode}",
        url=f"{STALKER_EPISODE_SCHEME}{quote(cmd, safe='')}?episode={quote(str(episode), safe='')}",
        group=season_name,
        logo=show.logo,
        stream_type="series",
        source="stalker",
        tvg_id=f"stalker-episode:{cmd}#{episode}",
        user_agent=show.user_agent,
        referer=show.referer,
    )


def parse_stalker_episode(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    cmd = unquote(url[len(STALKER_EPISODE_SCHEME):].split("?", 1)[0])
    episode = parse_qs(parsed.query).get("episode", [""])[0]
    return cmd, episode


def episode_index(episodes: list, channel: Channel) -> int:
    """Position of ``channel`` in ``episodes`` (-1 when absent)."""
    for index, episode in enumerate(episodes):
        if channel.tvg_id and episode.tvg_id == channel.tvg_id:
            return index
        if channel.xtream_id and episode.xtream_id == channel.xtream_id and episode.source == channel.source:
            return index
        if episode.url and episode.url == channel.url:
            return index
        if not channel.tvg_id and not channel.xtream_id and episode.name == channel.name:
            return index
    return -1


class PremiumMixin:
    """Personal-premium features layered on top of the classic main window."""

    def _setup_premium(self) -> None:
        self._osd = VideoOsd(self._player_widget.get_video_widget(), self)
        self._episode_context: Optional[tuple] = None  # (show Channel | None, [Channel])
        self._series_browser_show: Optional[Channel] = None
        self._series_browser_episodes: list = []
        self._current_replay_channel: Optional[Channel] = None
        self._current_parent: Optional[Channel] = None
        self._handled_reminders: set = set()
        self._pvr = PvrRecorderManager(
            Path(self._settings.get("recording_folder", "") or Path.home() / "Videos" / "IPTV Recordings")
        )
        self._typed_digits = ""
        self._digit_timer = QTimer(self)
        self._digit_timer.setSingleShot(True)
        self._digit_timer.setInterval(1600)
        self._digit_timer.timeout.connect(self._commit_channel_number)

        home = self._home_view
        home.play_requested.connect(self._play_from_home)
        home.resume_requested.connect(self._resume_from_home)
        home.remove_requested.connect(self._remove_from_continue)
        home.browse_requested.connect(self._browse_from_home)
        home.back_to_player_requested.connect(self._show_player_page)

        self._player_widget.go_live_requested.connect(self._go_live)
        self._player_widget.next_episode_requested.connect(self._play_next_episode)
        self._epg_grid_widget.play_requested.connect(self._on_channel_selected)
        self._epg_grid_widget.schedule_requested.connect(self._schedule_from_guide)

        for digit in range(10):
            for sequence in (QKeySequence(str(digit)), QKeySequence(f"Num+{digit}")):
                shortcut = QShortcut(sequence, self)
                shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
                shortcut.activated.connect(partial(self._on_digit, digit))
        info = QShortcut(QKeySequence("I"), self)
        info.setContext(Qt.ShortcutContext.WindowShortcut)
        info.activated.connect(self._show_current_channel_banner)
        backspace = QShortcut(QKeySequence(Qt.Key.Key_Backspace), self)
        backspace.setContext(Qt.ShortcutContext.WindowShortcut)
        backspace.activated.connect(self._recall_previous_channel)

        self._action_home = QAction(icon("home"), "Início", self)
        self._action_home.setShortcut(QKeySequence("Ctrl+H"))
        self._action_home.triggered.connect(self._show_home_page)
        first = self._toolbar.actions()[0] if self._toolbar.actions() else None
        self._toolbar.insertAction(first, self._action_home)
        if first is not None:
            self._toolbar.insertSeparator(first)
        self._main_menus[2].insertAction(self._main_menus[2].actions()[0], self._action_home)

        self._reminder_timer = QTimer(self)
        self._reminder_timer.setInterval(20_000)
        self._reminder_timer.timeout.connect(self._check_reminders)
        self._reminder_timer.start()
        QTimer.singleShot(3000, self._check_reminders)

        if self._settings.get("show_home_on_start", True):
            self._show_home_page()
        else:
            self._show_player_page()

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    @Slot()
    def _show_home_page(self) -> None:
        if self._is_fullscreen:
            self._exit_fullscreen()
        self._osd.hide_all()
        playing = self._current_playback_channel if self._media_player.is_playing else None
        self._home_view.set_now_playing(playing.name if playing else None)
        self._right_stack.setCurrentWidget(self._home_view)
        self._refresh_home()

    @Slot()
    def _show_player_page(self) -> None:
        self._right_stack.setCurrentWidget(self._player_page)

    def _refresh_home(self) -> None:
        playlist_id = self._current_playlist_id
        if not playlist_id or not hasattr(self, "_home_view"):
            return
        controller = self._playback_controller

        def load():
            return {
                "continue": controller.continue_watching(playlist_id),
                "recent": controller.recent_live(playlist_id),
                "favorites": self._db.get_favorites(playlist_id)[:30],
                "movies": controller.recently_added(playlist_id, VOD),
                "series": controller.recently_added(playlist_id, SERIES),
            }

        def show(rows):
            now_titles = {}
            for channel in list(rows["recent"]) + list(rows["favorites"]):
                current, _ = self._now_and_next(channel)
                if current is not None:
                    now_titles[channel.name] = current.title
            self._home_view.set_content(
                rows["continue"], rows["recent"], rows["favorites"],
                rows["movies"], rows["series"], now_titles,
            )

        self._run_background(
            load, show,
            on_error=lambda message: self._logger.debug("Início indisponível: %s", message),
            use_semaphore=False,
            context_playlist_id=playlist_id,
        )

    @Slot(object)
    def _play_from_home(self, channel: Channel) -> None:
        kind = content_type_for_stream(channel.stream_type)
        if kind == LIVE:
            self._on_channel_selected(channel)
        elif kind == SERIES and channel.source in ("xtream", "stalker"):
            self._content_tabs.set_current_index(2)
            self._on_content_tab_changed(2)
            self._on_series_show_opened(channel)
        else:
            self._on_vod_selected(channel)

    @Slot(object)
    def _resume_from_home(self, item: dict) -> None:
        channel: Channel = item["channel"]
        parent: Optional[Channel] = item.get("parent")
        kind = content_type_for_stream(channel.stream_type)
        if kind == LIVE:
            self._on_channel_selected(channel)
            return
        if kind == SERIES:
            context = self._episode_context
            if context is None or episode_index(context[1], channel) < 0:
                self._episode_context = (parent, [])
                if parent is not None:
                    self._load_episode_context(parent, channel)
            self._play_episode(channel, parent, auto_resume=not item.get("up_next"))
            return
        self._on_vod_selected(channel, auto_resume=True)

    @Slot(str)
    def _remove_from_continue(self, media_key: str) -> None:
        if self._current_playlist_id:
            self._playback_controller.remove_from_continue(self._current_playlist_id, media_key)
            self._refresh_home()

    @Slot(int)
    def _browse_from_home(self, tab_index: int) -> None:
        self._left_panel.show()
        self._content_tabs.set_current_index(tab_index)
        self._on_content_tab_changed(tab_index)

    # ------------------------------------------------------------------
    # Episodes
    # ------------------------------------------------------------------
    def _play_episode(self, channel: Channel, show: Optional[Channel], auto_resume: bool = False) -> None:
        if channel.url.startswith(STALKER_EPISODE_SCHEME):
            playlist_id = self._current_playlist_id
            cmd, episode = parse_stalker_episode(channel.url)

            def resolve():
                return self._call_stalker(playlist_id, lambda parser: parser.resolve_link(cmd, episode))

            self._run_background(
                resolve,
                lambda url: self._play_channel(
                    dc_replace(channel, url=url), replay=channel, parent=show, auto_resume=auto_resume
                ),
                status_message="A obter link do episódio...",
                context_playlist_id=playlist_id,
            )
            return
        self._play_channel(channel, replay=channel, parent=show, auto_resume=auto_resume)

    def _load_episode_context(self, show: Channel, current: Channel) -> None:
        """Fetch a show's episode list in the background so "next episode" works."""
        playlist_id = self._current_playlist_id
        if not playlist_id or show.source not in ("xtream", "stalker"):
            return

        def fetch():
            if show.source == "xtream":
                return self._call_xtream(playlist_id, lambda parser: parser.get_episodes_for_series(show.xtream_id))
            raw = self._call_stalker(
                playlist_id, lambda parser: parser.get_series_seasons(show.category_id, show.xtream_id)
            )
            return [
                stalker_episode_channel(show, season, number)
                for season in raw
                for number in (season.get("series") or [])
            ]

        def done(episodes):
            if episodes and episode_index(episodes, current) >= 0:
                self._episode_context = (show, list(episodes))
                self._update_next_episode_button()

        self._run_background(
            fetch, done,
            on_error=lambda message: self._logger.debug("Lista de episódios indisponível: %s", message),
            context_playlist_id=playlist_id,
        )

    def _next_episode(self) -> Optional[Channel]:
        channel = self._current_replay_channel or self._current_playback_channel
        if channel is None or self._episode_context is None:
            return None
        if content_type_for_stream(channel.stream_type) != SERIES:
            return None
        episodes = self._episode_context[1]
        index = episode_index(episodes, channel)
        if index < 0 or index + 1 >= len(episodes):
            return None
        return episodes[index + 1]

    def _update_next_episode_button(self) -> None:
        upcoming = self._next_episode()
        self._player_widget.set_next_episode(upcoming.name if upcoming else None)

    @Slot()
    def _play_next_episode(self) -> None:
        upcoming = self._next_episode()
        if upcoming is None:
            return
        self._osd.hide_card()
        show = self._episode_context[0] if self._episode_context else None
        self._play_episode(upcoming, show)

    def _handle_episode_end(self) -> None:
        upcoming = self._next_episode()
        if upcoming is None:
            return
        show = self._episode_context[0] if self._episode_context else None
        playlist_id = self._current_playlist_id

        def cancel():
            self._osd.hide_card()
            if playlist_id:
                self._playback_controller.queue_next_episode(playlist_id, upcoming, parent=show)
                self._refresh_home()

        subtitle = show.name if show else upcoming.group
        if self._settings.get("autoplay_next_episode", True):
            self._osd.show_card(
                "", upcoming.name, subtitle,
                [("▶ Ver agora", self._play_next_episode), ("Cancelar", cancel)],
                countdown_seconds=_NEXT_EPISODE_COUNTDOWN_S,
                countdown_template="PRÓXIMO EPISÓDIO EM {s} S",
                on_countdown_done=self._play_next_episode,
            )
        else:
            self._osd.show_card(
                "PRÓXIMO EPISÓDIO", upcoming.name, subtitle,
                [("▶ Ver agora", self._play_next_episode), ("Mais tarde", cancel)],
            )
            if playlist_id:
                self._playback_controller.queue_next_episode(playlist_id, upcoming, parent=show)

    # ------------------------------------------------------------------
    # Live: banner, number zapping, go live
    # ------------------------------------------------------------------
    def _programmes_for(self, channel: Channel) -> list:
        key = channel.epg_channel_id or channel.tvg_id or channel.xtream_id
        if not key:
            return []
        programmes = self._epg_widget.programs_for(key)
        if not programmes and getattr(self, "_epg_grid_cache_playlist_id", None) == self._current_playlist_id:
            programmes = list(self._epg_grid_cache.get(key, []))
        return programmes

    def _now_and_next(self, channel: Channel) -> tuple:
        programmes = sorted(self._programmes_for(channel), key=lambda p: p.start)
        current = upcoming = None
        for programme in programmes:
            now = datetime.now(programme.start.tzinfo)
            if programme.start <= now < programme.stop:
                current = programme
            elif programme.start >= now and upcoming is None and (current is None or programme.start >= current.stop):
                upcoming = programme
                if current is not None:
                    break
        return current, upcoming

    def _channel_number(self, channel: Channel) -> int:
        if channel.channel_number:
            return channel.channel_number
        ordered = self._live_list.get_filtered_channels() or []
        for index, candidate in enumerate(ordered):
            if (candidate.database_id and candidate.database_id == channel.database_id) or candidate.name == channel.name:
                return index + 1
        return 0

    def _show_live_banner(self, channel: Channel, attempt: int = 0) -> None:
        if self._current_playback_channel is not channel or channel.stream_type != "live":
            return
        current, upcoming = self._now_and_next(channel)
        self._osd.show_channel_banner(
            channel.name,
            self._channel_number(channel),
            channel.logo or channel.tvg_logo,
            current,
            upcoming,
            self._player_widget.behind_live_ms,
        )
        if current is None and attempt < 2:
            # The channel's EPG is fetched lazily right after selection.
            QTimer.singleShot(1500, lambda: self._show_live_banner(channel, attempt + 1))

    @Slot()
    def _show_current_channel_banner(self) -> None:
        channel = self._current_playback_channel
        if channel is not None and channel.stream_type == "live":
            self._show_live_banner(channel, attempt=2)

    def _channel_for_number(self, number: int) -> Optional[Channel]:
        live = (getattr(self, "_cached_channels_by_type", None) or {}).get(LIVE) or []
        for channel in live:
            if channel.channel_number == number:
                return channel
        ordered = self._live_list.get_filtered_channels() or live
        return ordered[number - 1] if 1 <= number <= len(ordered) else None

    def _on_digit(self, digit: int) -> None:
        if not self._current_playlist_id:
            return
        self._typed_digits = ("" if len(self._typed_digits) >= 4 else self._typed_digits) + str(digit)
        preview = self._channel_for_number(int(self._typed_digits))
        if self._right_stack.currentWidget() is self._player_page:
            self._osd.show_number(self._typed_digits, preview.name if preview else None)
        else:
            self.statusBar().showMessage(
                f"Canal {self._typed_digits}: {preview.name if preview else 'inexistente'}"
            )
        self._digit_timer.start()

    def _commit_channel_number(self) -> None:
        digits, self._typed_digits = self._typed_digits, ""
        if not digits:
            return
        channel = self._channel_for_number(int(digits))
        if channel is None:
            self._show_toast(f"O canal {digits} não existe nesta lista")
            return
        self._on_channel_selected(channel)

    @Slot()
    def _go_live(self) -> None:
        channel = self._current_playback_channel
        if channel is None:
            return
        self._show_toast("⏭ De volta ao direto")
        self._retry_current_channel()

    # ------------------------------------------------------------------
    # Reminders and scheduled recordings
    # ------------------------------------------------------------------
    def _refresh_scheduled_marks(self) -> None:
        if not self._current_playlist_id:
            return
        try:
            reminders = self._db.get_reminders(self._current_playlist_id)
        except Exception as exc:
            self._logger.debug("Lembretes indisponíveis: %s", exc)
            return
        self._epg_grid_widget.set_scheduled({
            (reminder["channel_key"], reminder["start"].astimezone(timezone.utc).isoformat()): reminder["action"]
            for reminder in reminders
        })

    @Slot(object, object, str)
    def _schedule_from_guide(self, channel: Channel, programme, action: str) -> None:
        playlist_id = self._current_playlist_id
        if not playlist_id:
            return
        if action == "cancel":
            self._db.delete_reminder(playlist_id, self._db.reminder_channel_key(channel), programme.start)
            self._show_toast(f"Agendamento cancelado: {programme.title}")
        else:
            self._db.save_reminder(playlist_id, channel, programme.title, programme.start, programme.stop, action)
            when = programme.start.astimezone().strftime("%d/%m %H:%M")
            self._show_toast(
                f"⏺ Gravação agendada: {programme.title} ({when})" if action == "record"
                else f"🔔 Lembrete criado: {programme.title} ({when})"
            )
        self._refresh_scheduled_marks()

    def _check_reminders(self) -> None:
        if self._closing:
            return
        try:
            reminders = self._db.get_reminders()
        except Exception as exc:
            self._logger.debug("Falha ao ler lembretes: %s", exc)
            return
        now = datetime.now(timezone.utc)
        for reminder in reminders:
            key = (reminder["playlist_id"], reminder["channel_key"], reminder["start"].isoformat())
            if key in self._handled_reminders:
                continue
            if not (reminder["start"] - _REMINDER_LEAD <= now < reminder["stop"]):
                continue
            self._handled_reminders.add(key)
            if reminder["action"] == "record":
                self._start_scheduled_recording(reminder)
            else:
                self._announce_reminder(reminder)
        self._refresh_scheduled_marks()

    def _announce_reminder(self, reminder: dict) -> None:
        channel = reminder["channel"]
        start = reminder["start"].astimezone().strftime("%H:%M")
        QApplication.alert(self)

        def watch():
            self._osd.hide_card()
            if reminder["playlist_id"] != self._current_playlist_id:
                self._playlist_widget.select_playlist(reminder["playlist_id"])
                self._on_playlist_selected(reminder["playlist_id"])
            self._on_channel_selected(channel)

        if self._right_stack.currentWidget() is self._player_page and self._media_player.is_playing:
            self._osd.show_card(
                "🔔 LEMBRETE", reminder["title"], f"{channel.name} · {start}",
                [("Ver agora", watch), ("Ignorar", self._osd.hide_card)],
            )
            return
        box = QMessageBox(self)
        box.setWindowTitle("Lembrete")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"<b>{reminder['title']}</b><br>{channel.name} · {start}")
        watch_button = box.addButton("Ver agora", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Ignorar", QMessageBox.ButtonRole.RejectRole)
        box.setModal(False)
        box.buttonClicked.connect(lambda button: watch() if button is watch_button else None)
        box.show()

    def _start_scheduled_recording(self, reminder: dict) -> None:
        channel: Channel = reminder["channel"]
        playlist_id = reminder["playlist_id"]
        stop = reminder["stop"] + _RECORDING_TAIL
        title = reminder["title"]

        def resolve():
            target = channel
            if not target.url and target.database_id:
                fresh = self._db.get_channel(target.database_id, playlist_id)
                target = fresh or target
            url = (target.url or "").strip()
            if target.source == "stalker" and not url.lower().startswith(("http://", "https://")):
                url = self._call_stalker(playlist_id, lambda parser: parser.resolve_live_link(url or target.tvg_id))
            return target, url

        def start(result):
            target, url = result
            if not url:
                self._show_toast(f"⚠ Não foi possível gravar {title}: sem endereço")
                return
            headers = dict(target.custom_headers or {})
            if target.user_agent:
                headers["User-Agent"] = target.user_agent
            if target.referer:
                headers["Referer"] = target.referer
            self._pvr.output_dir = Path(
                self._settings.get("recording_folder", "") or self._pvr.output_dir
            )
            self._pvr.output_dir.mkdir(parents=True, exist_ok=True)
            seconds = max(60, int((stop - datetime.now(timezone.utc)).total_seconds()))
            self._pvr.start_recording(f"{target.name} - {title}", url, seconds, headers or None)
            self._show_toast(f"⏺ A gravar: {title} ({seconds // 60} min)")

        self._run_background(
            resolve, start,
            on_error=lambda message: self._show_toast(f"⚠ Gravação de {title} falhou: {message}"),
            use_semaphore=False,
        )
