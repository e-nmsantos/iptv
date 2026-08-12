"""EPG normalization, freshness and persistence services."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from ..core.epg_loader import load_xmltv


class EpgController:
    def __init__(self, database, settings):
        self._database = database
        self._settings = settings

    @staticmethod
    def channel_maps(channels: list) -> tuple[dict, dict]:
        canonical = {}
        names = {}
        for channel in channels:
            if channel.stream_type != "live":
                continue
            channel_id = channel.epg_channel_id or channel.tvg_id
            if channel_id:
                channel_id = str(channel_id)
                canonical[channel_id.casefold()] = channel_id
                names[channel_id] = channel.name
        return canonical, names

    def cached(self, playlist_id: int, channel_id: str = "") -> list:
        return self._database.get_playlist_epg(playlist_id, channel_id)

    def should_refresh(self, playlist_id: int, cached: list, force: bool) -> bool:
        if force:
            return True
        if not self._settings.get("epg_auto_update", True):
            return False
        last_updated = self._database.get_epg_last_updated(playlist_id)
        if not cached or not last_updated:
            return True
        if not last_updated.tzinfo:
            last_updated = last_updated.replace(tzinfo=timezone.utc)
        interval = timedelta(
            hours=max(1, self._settings.get("epg_update_interval_hours", 24))
        )
        return datetime.now(timezone.utc) - last_updated >= interval

    def refresh_xmltv(self, playlist_id: int, source: str, channels: list) -> list:
        epg = load_xmltv(
            source,
            timeout=self._settings.get("network_timeout_seconds", 30),
            user_agent=self._settings.get("user_agent", ""),
        )
        canonical, _ = self.channel_maps(channels)
        programs = []
        for source_id, source_programs in epg.channels.items():
            target_id = canonical.get(source_id.casefold())
            if not target_id:
                continue
            programs.extend(
                program
                if program.channel_id == target_id
                else replace(program, channel_id=target_id)
                for program in source_programs
            )
        self._database.replace_playlist_epg(playlist_id, programs)
        return programs
