"""Xtream Codes API client and parser.

Xtream Codes is a popular IPTV management panel that provides a JSON API.
This parser supports:
- Authentication with server URL, username, and password
- Fetching live channels, series, and VOD
- Categories/groups
- EPG data
- Stream URLs generation
"""

import base64
import binascii
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.parse import urljoin

import requests

from ..core.channel import Channel
from ..core.epg import EPGProgram
from ..core.http_client import HttpSession
from ..core.playlist import Playlist

logger = logging.getLogger(__name__)


class XtreamParser:
    """
    Client for the Xtream Codes API.
    
    API endpoints (relative to server URL):
    /player_api.php?username={user}&password={pass}&action={action}
    """

    def __init__(self, server_url: str, username: str, password: str, timeout: int = 30):
        self._base_url = self._normalize_url(server_url)
        self._username = username
        self._password = password
        self._timeout = max(5, int(timeout))
        self._session = HttpSession(timeout=self._timeout)
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        })
        self._info: dict = {}
        self._dns: str = ""

    def close(self):
        """Release pooled HTTP connections held by this client."""
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize the server URL."""
        url = url.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return url

    def _safe_request_error(self, error: Exception) -> str:
        """Return an HTTP error without exposing credentials in its URL."""
        message = str(error)
        for secret in (self._username, self._password):
            if secret:
                message = message.replace(secret, "***")
        return message

    @staticmethod
    def _build_dns(server_info: dict) -> str:
        """
        Build the base URL used for stream links from the authenticate()
        response's "server_info". That field only contains a bare
        hostname (no scheme, no port) — using it as-is (as this used to
        do) produces broken stream URLs like "example.com/live/..." with
        no "http://" and no port, which silently fail to play. Reassemble
        scheme+host+port properly here instead.
        """
        host = (server_info.get("url") or "").strip()
        if not host:
            return ""

        protocol = (server_info.get("server_protocol") or "http").strip() or "http"
        port = server_info.get("https_port") if protocol == "https" else server_info.get("port")
        port = str(port).strip() if port else ""

        if port:
            return f"{protocol}://{host}:{port}"
        return f"{protocol}://{host}"

    def _api_request(self, action: str, max_retries: int = 4, **params) -> dict:
        """
        Make a request to the Xtream API. Some panels sit behind Cloudflare
        and their backend is flaky — dynamic endpoints (player_api.php,
        get.php) intermittently return 5xx (e.g. 520 "unknown error") even
        though the panel is otherwise reachable and works fine a few
        seconds later. Retry with backoff before giving up, since a single
        failed attempt doesn't reliably mean the account/URL is wrong.
        """
        api_url = urljoin(self._base_url.rstrip("/") + "/", "player_api.php")
        params.update({
            "username": self._username,
            "password": self._password,
            "action": action,
        })

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                response = self._session.get(api_url, params=params, timeout=self._timeout)
                if response.status_code >= 500:
                    last_error = ConnectionError(
                        f"O servidor Xtream devolveu erro {response.status_code} "
                        f"(instável/em baixo neste momento)."
                    )
                else:
                    response.raise_for_status()
                    try:
                        return response.json()
                    except ValueError as e:
                        raise ValueError(
                            f"Invalid JSON response from Xtream API: {e}"
                        ) from e
            except requests.RequestException as e:
                last_error = ConnectionError(
                    f"Xtream API request failed: {self._safe_request_error(e)}"
                )

            if attempt < max_retries:
                time.sleep(min(2 ** (attempt - 1), 8))

        raise last_error

    def authenticate(self) -> bool:
        """
        Authenticate with the Xtream server.
        
        Returns:
            True if authentication succeeded, raises exception otherwise.
        """
        data = self._api_request("")
        if "user_info" in data and data["user_info"].get("auth", 0):
            self._info = data
            self._dns = self._build_dns(data.get("server_info", {}))
            return True
        raise PermissionError(
            f"Xtream authentication failed for user '{self._username}'. "
            f"Check credentials or server URL."
        )

    def get_live_categories(self) -> list[dict]:
        """Get all live TV categories."""
        data = self._api_request("get_live_categories")
        return data if isinstance(data, list) else []

    def _category_name_map(self, categories: list[dict]) -> dict:
        """category_id -> category_name, for providers whose stream items
        only carry a category_id (very common — `category_name` on the
        stream item itself is often absent even though the docs imply it's
        always there)."""
        return {
            str(cat.get("category_id")): cat.get("category_name", "")
            for cat in categories
            if cat.get("category_id") is not None
        }

    def get_live_channels(self, category_id: Optional[str] = None) -> list[Channel]:
        """Get live TV channels, optionally filtered by category."""
        params = {}
        if category_id:
            params["category_id"] = category_id

        data = self._api_request("get_live_streams", **params)
        channels = []

        try:
            category_names = self._category_name_map(self.get_live_categories())
        except Exception:
            category_names = {}

        for item in data if isinstance(data, list) else []:
            group = (
                item.get("category_name")
                or category_names.get(str(item.get("category_id", "")))
                or "General"
            )
            channel = Channel(
                name=item.get("name", "Unknown"),
                url=self._build_stream_url(
                    item.get("stream_id", ""), "live", item.get("container_extension", "ts")
                ),
                group=group,
                logo=item.get("stream_icon", ""),
                tvg_id=item.get("epg_channel_id", ""),
                epg_channel_id=item.get("epg_channel_id", ""),
                stream_type="live",
                source="xtream",
                xtream_id=str(item.get("stream_id", "")),
                category_id=str(item.get("category_id", "")),
                has_archive=bool(item.get("tv_archive")),
                archive_duration_days=int(item.get("tv_archive_duration") or 0),
            )
            channels.append(channel)

        return channels

    def get_vod_categories(self) -> list[dict]:
        """Get all VOD categories."""
        data = self._api_request("get_vod_categories")
        return data if isinstance(data, list) else []

    def get_vod_streams(self, category_id: Optional[str] = None) -> list[Channel]:
        """Get VOD streams, optionally filtered by category."""
        params = {}
        if category_id:
            params["category_id"] = category_id

        data = self._api_request("get_vod_streams", **params)
        channels = []

        try:
            category_names = self._category_name_map(self.get_vod_categories())
        except Exception:
            category_names = {}

        for item in data if isinstance(data, list) else []:
            group = (
                item.get("category_name")
                or category_names.get(str(item.get("category_id", "")))
                or "VOD"
            )
            channel = Channel(
                name=item.get("name", "Unknown"),
                url=self._build_stream_url(
                    item.get("stream_id", ""), "movie", item.get("container_extension", "mp4")
                ),
                group=group,
                logo=item.get("stream_icon", ""),
                stream_type="vod",
                source="xtream",
                xtream_id=str(item.get("stream_id", "")),
                category_id=str(item.get("category_id", "")),
                container_extension=item.get("container_extension", "mp4"),
            )
            channels.append(channel)

        return channels

    def get_series_categories(self) -> list[dict]:
        """Get all series categories."""
        data = self._api_request("get_series_categories")
        return data if isinstance(data, list) else []

    def get_series(self, category_id: Optional[str] = None) -> list[dict]:
        """Get series list, optionally filtered by category."""
        params = {}
        if category_id:
            params["category_id"] = category_id
        data = self._api_request("get_series", **params)
        return data if isinstance(data, list) else []

    def get_series_info(self, series_id: str) -> dict:
        """Get detailed info about a series including episodes."""
        return self._api_request("get_series_info", series_id=series_id)

    def get_episodes_for_series(self, series_id: str) -> list[Channel]:
        """Get all episodes for a series."""
        info = self.get_series_info(series_id)
        episodes = []
        seasons = info.get("episodes", {})

        for season_num, ep_list in seasons.items():
            for ep in ep_list if isinstance(ep_list, list) else []:
                channel = Channel(
                    name=ep.get("title", "Unknown"),
                    url=self._build_stream_url(
                        ep.get("id", ""), "series", ep.get("container_extension", "mp4")
                    ),
                    group=f"Series - S{int(season_num):02d}",
                    logo=ep.get("info", {}).get("movie_image", ""),
                    stream_type="series",
                    source="xtream",
                    xtream_id=str(ep.get("id", "")),
                    season_number=int(season_num),
                    episode_number=ep.get("episode_num", 0),
                    container_extension=ep.get("container_extension", "mp4"),
                )
                episodes.append(channel)

        return episodes

    def get_series_channels(
        self,
        should_cancel: Optional[Callable[[], bool]] = None,
        progress: Optional[Callable[[str], None]] = None,
    ) -> list[Channel]:
        """Return top-level series records without fetching every episode."""
        channels = []
        categories = self.get_series_categories()
        for index, category in enumerate(categories, start=1):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(f"Séries: categoria {index}/{len(categories)}")
            category_id = category.get("category_id")
            if category_id is None:
                continue
            for item in self.get_series(category_id):
                channels.append(
                    Channel(
                        name=item.get("name", "Unknown"),
                        url="",
                        group=category.get("category_name", "Séries"),
                        logo=item.get("cover", ""),
                        stream_type="series",
                        source="xtream",
                        xtream_id=str(item.get("series_id", "")),
                        category_id=str(category_id),
                    )
                )
        return channels

    def get_epg(self, stream_id: str, limit: int = 24) -> list[dict]:
        """Get EPG data for a live stream."""
        data = self._api_request("get_short_epg", stream_id=stream_id, limit=limit)
        return data.get("epg_data", []) if isinstance(data, dict) else []

    def get_epg_programs(
        self, stream_id: str, channel_id: str = "", limit: int = 48
    ) -> list[EPGProgram]:
        """Fetch and normalize Xtream short-EPG records."""
        programs = []
        normalized_channel_id = str(channel_id or stream_id)
        for item in self.get_epg(stream_id, limit):
            start = self._parse_epg_datetime(
                item.get("start_timestamp"), item.get("start")
            )
            stop = self._parse_epg_datetime(
                item.get("stop_timestamp") or item.get("end_timestamp"),
                item.get("end") or item.get("stop"),
            )
            if start is None or stop is None or stop <= start:
                continue
            programs.append(
                EPGProgram(
                    channel_id=normalized_channel_id,
                    title=self._decode_epg_text(item.get("title")) or "Sem título",
                    start=start,
                    stop=stop,
                    description=self._decode_epg_text(item.get("description")),
                )
            )
        return programs

    @staticmethod
    def _decode_epg_text(value) -> str:
        if value is None:
            return ""
        text = str(value)
        try:
            padded = text + ("=" * (-len(text) % 4))
            return base64.b64decode(padded, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return text

    @staticmethod
    def _parse_epg_datetime(timestamp, text) -> Optional[datetime]:
        if timestamp not in (None, ""):
            try:
                value = float(timestamp)
                if value > 10_000_000_000:
                    value /= 1000
                return datetime.fromtimestamp(value, timezone.utc).astimezone()
            except (TypeError, ValueError, OSError):
                pass

        if text:
            value = str(text).strip()
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.astimezone()
            except ValueError:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S"):
                    try:
                        return datetime.strptime(value, fmt).astimezone()
                    except ValueError:
                        continue
        return None

    def _build_stream_url(
        self, stream_id: str, stream_type: str, extension: str = ""
    ) -> str:
        """
        Build the full stream URL.
        
        Format: {server_url}/live/{username}/{password}/{stream_id}.{ext}
        Format: {server_url}/movie/{username}/{password}/{stream_id}.{ext}
        Format: {server_url}/series/{username}/{password}/{stream_id}.{ext}
        """
        base = self._dns or self._base_url
        ext = (extension or ("ts" if stream_type == "live" else "mp4")).lstrip(".")
        return f"{base.rstrip('/')}/{stream_type}/{self._username}/{self._password}/{stream_id}.{ext}"

    def build_timeshift_url(
        self, stream_id: str, start: datetime, duration_minutes: int, extension: str = "ts"
    ) -> str:
        """Build a catch-up/timeshift URL for a channel with tv_archive enabled.

        Format: {server}/timeshift/{username}/{password}/{duration}/{yyyy-MM-dd:HH-mm}/{stream_id}.{ext}
        """
        base = self._dns or self._base_url
        duration = max(1, int(duration_minutes))
        start_str = start.strftime("%Y-%m-%d:%H-%M")
        ext = (extension or "ts").lstrip(".")
        return (
            f"{base.rstrip('/')}/timeshift/{self._username}/{self._password}/"
            f"{duration}/{start_str}/{stream_id}.{ext}"
        )

    def get_full_playlist(
        self,
        should_cancel: Optional[Callable[[], bool]] = None,
        include_vod: bool = True,
        include_series: bool = True,
    ) -> Playlist:
        """
        Fetch everything and build a complete Playlist object.
        
        Returns:
            Playlist with all live channels, VOD, and series
        """
        if not self._info:
            self.authenticate()

        playlist = Playlist(
            name=f"Xtream - {self._username}",
            source_type="xtream",
            server_url=self._base_url,
            username=self._username,
            password=self._password,
        )

        # Get user info for total counts
        user_info = self._info.get("user_info", {})
        playlist.total_channels = user_info.get("max_connections", 0)

        # Add live channels
        try:
            live_channels = self.get_live_channels()
            for ch in live_channels:
                playlist.add_channel(ch)
        except Exception as e:
            logger.warning("Failed to fetch live channels: %s", e)

        # Add VOD only when requested; the UI normally loads this tab lazily.
        if include_vod:
            try:
                if should_cancel and should_cancel():
                    return playlist
                vod = self.get_vod_streams()
                for ch in vod:
                    playlist.add_channel(ch)
            except Exception as e:
                logger.warning("Failed to fetch VOD: %s", e)

        # Add series shows (top-level only — episodes are fetched lazily
        # via get_episodes_for_series() when the user opens a show, since
        # calling get_series_info for every show up front doesn't scale).
        if include_series:
            try:
                for channel in self.get_series_channels(
                    should_cancel=should_cancel
                ):
                    playlist.add_channel(channel)
            except Exception as e:
                logger.warning("Failed to fetch series: %s", e)

        return playlist
