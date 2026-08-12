"""Playback history and resume persistence outside the Qt mixin."""


class PlaybackController:
    def __init__(self, database):
        self._database = database

    def started(self, playlist_id: int, channel):
        self._database.record_playback(playlist_id, channel)
        return self._database.get_playback_progress(playlist_id, channel)

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
