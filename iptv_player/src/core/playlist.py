"""Playlist model representing a collection of channels."""

from dataclasses import dataclass, field
from datetime import datetime

from .channel import Channel
from .content_types import SERIES, VOD, content_type_for_stream


@dataclass
class Playlist:
    """Represents an IPTV playlist with its metadata and channels."""

    name: str
    source_type: str  # m3u, m3u_plus, xtream, stalker
    channels: list = field(default_factory=list)
    url: str = ""
    file_path: str = ""
    server_url: str = ""
    username: str = ""
    password: str = ""
    mac_address: str = ""
    total_channels: int = 0
    total_series: int = 0
    total_vod: int = 0
    created_at: str = ""
    updated_at: str = ""
    epg_source: str = ""
    epg_url: str = ""
    player_api: str = ""
    version: str = "1.0"

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()

    def get_groups(self) -> list:
        """Get sorted list of unique channel groups."""
        groups = set()
        for ch in self.channels:
            if ch.group:
                groups.add(ch.group)
        return sorted(groups, key=str.lower)

    def get_channels_by_group(self, group: str) -> list:
        """Get all channels in a specific group."""
        return [ch for ch in self.channels if ch.group == group]

    def search(self, query: str) -> list:
        """Search channels by name (case-insensitive)."""
        q = query.lower()
        return [ch for ch in self.channels if q in ch.name.lower()]

    def get_favorites(self) -> list:
        """Get all favorited channels."""
        return [ch for ch in self.channels if ch.is_favorite]

    def get_channel_count(self) -> int:
        """Get total number of channels."""
        return len(self.channels)

    def add_channel(self, channel: Channel):
        """Add a channel to the playlist."""
        self.channels.append(channel)
        self.total_channels = len(self.channels)
        st = content_type_for_stream(getattr(channel, "stream_type", ""))
        if st == VOD:
            self.total_vod += 1
        elif st == SERIES:
            self.total_series += 1
        self.updated_at = datetime.now().isoformat()

    def remove_channel(self, channel: Channel):
        """Remove a channel from the playlist."""
        self.channels.remove(channel)
        self.total_channels = len(self.channels)
        st = content_type_for_stream(getattr(channel, "stream_type", ""))
        if st == VOD:
            self.total_vod = max(0, self.total_vod - 1)
        elif st == SERIES:
            self.total_series = max(0, self.total_series - 1)
        self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        """Serialize playlist metadata to dict."""
        return {
            "name": self.name,
            "source_type": self.source_type,
            "url": self.url,
            "file_path": self.file_path,
            "server_url": self.server_url,
            "username": self.username,
            "mac_address": self.mac_address,
            "total_channels": self.total_channels,
            "total_series": self.total_series,
            "total_vod": self.total_vod,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "epg_source": self.epg_source,
            "epg_url": self.epg_url,
            "version": self.version,
        }
