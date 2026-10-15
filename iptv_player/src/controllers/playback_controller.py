import threading
import time
from typing import Callable, Optional

from ..core.channel_cleaner import ChannelCleaner


class PlaybackController:
    def __init__(self, database):
        self._database = database
        self._current_channel = None
        self._previous_channel = None
        self._sleep_timer: Optional[threading.Timer] = None
        self._sleep_timer_end: float = 0.0

    def started(self, playlist_id: int, channel, replay=None, parent=None):
        """Record a playback start and return its saved resume point, if any.

        ``replay`` is the reference to store for playing it again later (e.g.
        a Stalker channel before its short-lived link was resolved); it
        defaults to ``channel``. ``parent`` is the series of an episode.
        """
        # Track the replayable reference so "canal anterior" re-resolves
        # short-lived provider links instead of replaying an expired one.
        reference = replay or channel
        if self._current_channel and reference and self._current_channel != reference:
            self._previous_channel = self._current_channel
        self._current_channel = reference

        self._database.record_playback(playlist_id, channel)
        self._database.record_watch(playlist_id, replay or channel, parent=parent)
        return self._database.get_playback_progress(playlist_id, channel)

    def queue_next_episode(self, playlist_id: int, episode, parent=None) -> None:
        """Show an unwatched next episode in "Continuar a ver"."""
        self._database.record_watch(playlist_id, episode, parent=parent, up_next=True)

    def continue_watching(self, playlist_id: int) -> list[dict]:
        return self._database.get_continue_watching(playlist_id)

    def recent_live(self, playlist_id: int) -> list:
        return self._database.get_recent_live(playlist_id)

    def recently_added(self, playlist_id: int, content_type: str, limit: int = 20) -> list:
        return self._database.get_recently_added(playlist_id, content_type, limit)

    def remove_from_continue(self, playlist_id: int, media_key: str) -> None:
        self._database.remove_watch(playlist_id, media_key)

    @property
    def current_channel(self):
        return self._current_channel

    @property
    def previous_channel(self):
        return self._previous_channel

    def get_recall_channel(self):
        """Return the previous channel for quick zapping/recall."""
        return self._previous_channel

    def find_fallback_channel(self, failed_channel, all_channels: list):
        """Find an alternate or backup stream when the current stream fails."""
        candidates = ChannelCleaner.find_alternate_streams(failed_channel, all_channels)
        return candidates[0] if candidates else None

    def start_sleep_timer(self, minutes: int, on_expired: Callable[[], None]) -> None:
        """Start a sleep timer that triggers on_expired after specified minutes."""
        self.cancel_sleep_timer()
        if minutes <= 0:
            return

        self._sleep_timer_end = time.time() + (minutes * 60)
        self._sleep_timer = threading.Timer(minutes * 60, on_expired)
        self._sleep_timer.daemon = True
        self._sleep_timer.start()

    def cancel_sleep_timer(self) -> None:
        if self._sleep_timer:
            self._sleep_timer.cancel()
            self._sleep_timer = None
        self._sleep_timer_end = 0.0

    def get_sleep_timer_remaining_minutes(self) -> int:
        if not self._sleep_timer or self._sleep_timer_end <= 0:
            return 0
        remaining = max(0, int((self._sleep_timer_end - time.time()) / 60))
        return remaining

    def save_progress(
        self,
        playlist_id: int,
        channel,
        position_ms: int,
        length_ms: int,
    ) -> None:
        self._database.save_playback_progress(
            playlist_id, channel, position_ms, length_ms
        )

    def progress_fraction(self, playlist_id: int, channel):
        progress = self._database.get_playback_progress(playlist_id, channel)
        if not progress or not progress.get("length_ms"):
            return None
        return min(1.0, progress["position_ms"] / progress["length_ms"])

    def history(self, playlist_id: int) -> list[dict]:
        return self._database.get_recent_playback(playlist_id)

    def resume_candidates(self, playlist_id: int) -> list[dict]:
        return self._database.get_resume_candidates(playlist_id)
