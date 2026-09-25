"""Channel data model."""

from dataclasses import dataclass, field


@dataclass
class Channel:
    """Represents a single IPTV channel/stream."""

    name: str
    url: str
    group: str = "General"
    logo: str = ""
    epg_channel_id: str = ""
    tvg_id: str = ""
    tvg_name: str = ""
    tvg_logo: str = ""
    user_agent: str = ""
    referer: str = ""
    stream_type: str = "live"  # live, series, movie, vod
    extension: str = ""
    quality: str = ""
    source: str = "m3u"  # m3u, xtream, stalker
    xtream_id: str = ""
    series_id: str = ""
    category_id: str = ""
    country_code: str = ""
    provider_group: str = ""
    season_number: int = 0
    episode_number: int = 0
    container_extension: str = ""
    custom_headers: dict = field(default_factory=dict)
    is_favorite: bool = False
    database_id: int = 0
    has_archive: bool = False
    archive_duration_days: int = 0
    channel_number: int = 0

    def to_dict(self) -> dict:
        """Convert channel to dictionary for storage."""
        return {
            "name": self.name,
            "url": self.url,
            "group": self.group,
            "logo": self.logo,
            "epg_channel_id": self.epg_channel_id,
            "tvg_id": self.tvg_id,
            "tvg_name": self.tvg_name,
            "tvg_logo": self.tvg_logo,
            "user_agent": self.user_agent,
            "referer": self.referer,
            "stream_type": self.stream_type,
            "source": self.source,
            "xtream_id": self.xtream_id,
            "series_id": self.series_id,
            "category_id": self.category_id,
            "country_code": self.country_code,
            "provider_group": self.provider_group,
            "season_number": self.season_number,
            "episode_number": self.episode_number,
            "container_extension": self.container_extension,
            "extension": self.extension,
            "quality": self.quality,
            "custom_headers": self.custom_headers,
            "is_favorite": self.is_favorite,
            "database_id": self.database_id,
            "has_archive": self.has_archive,
            "archive_duration_days": self.archive_duration_days,
            "channel_number": self.channel_number,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Channel":
        """Create channel from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
