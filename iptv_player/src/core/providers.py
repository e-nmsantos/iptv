"""Provider-neutral catalogue contract and parser adapters."""

from collections.abc import Callable
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

from .channel import Channel
from .epg import EPGProgram


class CatalogKind(str, Enum):
    LIVE = "live"
    VOD = "vod"
    SERIES = "series"


@runtime_checkable
class Provider(Protocol):
    """Capabilities consumed by services instead of parser internals."""

    def authenticate(self) -> bool: ...

    def load_catalog(
        self,
        kind: CatalogKind,
        should_cancel: Optional[Callable[[], bool]] = None,
        progress: Optional[Callable[[str], None]] = None,
    ) -> list[Channel]: ...

    def load_epg(self, channel: Channel, limit: int = 24) -> list[EPGProgram]: ...

    def playback_headers(self) -> dict[str, str]: ...

    def close(self) -> None: ...


class XtreamProvider:
    def __init__(self, parser):
        self.client = parser

    def authenticate(self) -> bool:
        return self.client.authenticate()

    def load_catalog(self, kind: CatalogKind, should_cancel=None, progress=None) -> list[Channel]:
        if kind == CatalogKind.LIVE:
            return self.client.get_live_channels()
        if kind == CatalogKind.VOD:
            return self.client.get_vod_streams()
        return self.client.get_series_channels(
            should_cancel=should_cancel,
            progress=progress,
        )

    def load_epg(self, channel: Channel, limit: int = 24) -> list[EPGProgram]:
        return self.client.get_epg_programs(
            channel.xtream_id,
            channel.epg_channel_id or channel.tvg_id,
            limit=limit,
        )

    def playback_headers(self) -> dict[str, str]:
        return {}

    def close(self) -> None:
        self.client.close()


class StalkerProvider:
    def __init__(self, parser):
        self.client = parser

    def authenticate(self) -> bool:
        return self.client.authenticate()

    def load_catalog(self, kind: CatalogKind, should_cancel=None, progress=None) -> list[Channel]:
        if kind == CatalogKind.LIVE:
            return self.client.get_channels()
        if kind == CatalogKind.VOD:
            return self.client.get_vod_movies(
                should_cancel=should_cancel,
                progress=progress,
            )
        return self.client.get_series_shows(
            should_cancel=should_cancel,
            progress=progress,
        )

    def load_epg(self, channel: Channel, limit: int = 24) -> list[EPGProgram]:
        channel_id = channel.xtream_id or channel.epg_channel_id or channel.tvg_id
        return self.client.get_epg_programs(channel_id, limit=limit)

    def playback_headers(self) -> dict[str, str]:
        return self.client.playback_headers()

    def close(self) -> None:
        self.client.close()
