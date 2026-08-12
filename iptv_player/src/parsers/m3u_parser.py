"""M3U / M3U8 / M3U_Plus playlist parser."""

import json
import re
import unicodedata
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

import requests

from ..core.channel import Channel
from ..core.playlist import Playlist


class M3UParser:
    """
    Parser for M3U, M3U8, and M3U_Plus (with EXTINF) playlist formats.
    
    Supports:
    - Standard M3U with #EXTINF tags
    - M3U_Plus with extended attributes (tvg-id, tvg-name, tvg-logo, group-title)
    - Local files and remote URLs
    """

    MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024

    def __init__(self, timeout: int = 30, user_agent: str = ""):
        self._timeout = max(5, int(timeout))
        self._user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

    @staticmethod
    def is_m3u(content: str) -> bool:
        """Check if content appears to be M3U format."""
        return content.strip().startswith("#EXTM3U")

    @staticmethod
    def _parse_extinf(extinf_line: str) -> dict:
        """Parse an #EXTINF line extracting all attributes."""
        info = {
            "name": "",
            "logo": "",
            "tvg_id": "",
            "tvg_name": "",
            "tvg_logo": "",
            "group": "General",
            "epg_channel_id": "",
            "quality": "",
            "stream_type": "",
        }

        # Extract duration (first number after #EXTINF:)
        duration_match = re.match(r"#EXTINF:(-?\d+\.?\d*)", extinf_line)
        if duration_match:
            info["duration"] = float(duration_match.group(1))

        # Extract all tvg-* attributes
        attrs = {
            "tvg-id": "tvg_id",
            "tvg-id=\"": "tvg_id",
            "tvg-name": "tvg_name",
            "tvg-logo": "tvg_logo",
            "group-title": "group",
            "tvg-chno": "epg_channel_id",
            "radio": None,
        }

        for attr, key in attrs.items():
            if key is None:
                continue
            pattern = re.escape(attr) + r'="([^"]*)"'
            match = re.search(pattern, extinf_line, re.IGNORECASE)
            if match:
                info[key] = match.group(1).strip()

        # Also check for tvg-id without quotes
        if not info["tvg_id"]:
            match = re.search(r'tvg-id=([^\s"\'&]+)', extinf_line)
            if match:
                info["tvg_id"] = match.group(1).strip()

        # Extract channel name (last comma-separated value)
        name_match = re.search(r',([^,]+)$', extinf_line)
        if name_match:
            info["name"] = name_match.group(1).strip()

        # Extract quality from name or group
        quality_patterns = {
            "4K": ["2160", "4k", "uhd"],
            "FHD": ["1080", "fhd", "full hd"],
            "HD": ["720", "hd"],
            "SD": ["576", "480", "sd"],
        }
        name_lower = info["name"].lower()
        for quality, keywords in quality_patterns.items():
            if any(k in name_lower for k in keywords):
                info["quality"] = quality
                break

        # Extract user-agent and referer from EXTINF line
        ua_match = re.search(r'user-agent="([^"]*)"', extinf_line, re.IGNORECASE)
        if ua_match:
            info["user_agent"] = ua_match.group(1)

        referer_match = re.search(r'referer="([^"]*)"', extinf_line, re.IGNORECASE)
        if referer_match:
            info["referer"] = referer_match.group(1)

        type_match = re.search(
            r'(?:stream-type|media-type|tvg-type|type)\s*=\s*["\']?([^"\'\s]+)',
            extinf_line,
            re.IGNORECASE,
        )
        if type_match:
            info["stream_type"] = type_match.group(1).strip()

        return info

    @staticmethod
    def _plain_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        return "".join(char for char in normalized if not unicodedata.combining(char)).casefold()

    @classmethod
    def infer_stream_type(
        cls,
        url: str,
        group: str = "",
        name: str = "",
        explicit_type: str = "",
        duration: Optional[float] = None,
    ) -> str:
        """Infer live/VOD/series using explicit metadata before safe heuristics."""
        explicit = cls._plain_text(explicit_type).strip()
        if explicit in {"movie", "movies", "vod", "film", "video"}:
            return "vod"
        if explicit in {"series", "serie", "episode", "episodes", "show"}:
            return "series"
        if explicit in {"live", "tv", "channel", "radio"}:
            return "live"

        path_parts = {
            part for part in cls._plain_text(unquote(urlparse(url).path)).split("/") if part
        }
        if path_parts.intersection({"movie", "movies", "vod", "film", "films"}):
            return "vod"
        if path_parts.intersection({"series", "serie", "episodes"}):
            return "series"
        if "live" in path_parts:
            return "live"

        group_text = cls._plain_text(group)
        separators = r"(?:^|[\s|:;/_\-])"
        ending = r"(?:$|[\s|:;/_\-])"
        if re.search(
            separators + r"(?:series?|tv\s*shows?|episodes?)" + ending,
            group_text,
        ):
            return "series"
        if re.search(
            separators + r"(?:vod|movies?|films?|filmes?|peliculas?)" + ending,
            group_text,
        ):
            return "vod"

        name_text = cls._plain_text(name)
        if re.search(r"\bs\d{1,2}\s*e\d{1,3}\b", name_text):
            return "series"
        if duration is not None and duration > 0:
            return "vod"
        return "live"

    def parse(self, source: str, name: Optional[str] = None) -> Playlist:
        """
        Parse an M3U playlist from a file path or URL.
        
        Args:
            source: Local file path or URL to the M3U playlist
            name: Optional name for the playlist
            
        Returns:
            Playlist object with parsed channels
        """
        url_parsed = urlparse(source)
        is_url = url_parsed.scheme in ("http", "https")

        if is_url:
            return self._parse_from_url(source, name)
        else:
            return self._parse_from_file(source, name)

    def _parse_from_url(self, url: str, name: Optional[str] = None) -> Playlist:
        """Fetch and parse M3U from a URL."""
        try:
            response = requests.get(
                url,
                timeout=self._timeout,
                headers={"User-Agent": self._user_agent},
                stream=True,
            )
            response.raise_for_status()
            try:
                declared_size = int(response.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                declared_size = 0
            if declared_size > self.MAX_DOWNLOAD_BYTES:
                raise ValueError("A playlist excede o limite de 100 MB.")
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > self.MAX_DOWNLOAD_BYTES:
                    raise ValueError("A playlist excede o limite de 100 MB.")
                chunks.append(chunk)
            encoding = response.encoding or "utf-8"
            content = b"".join(chunks).decode(encoding, errors="replace")
            playlist_name = name or url.split("/")[-1].split(".")[0] or "Remote Playlist"
            return self._parse_content(content, playlist_name, url=url)
        except requests.RequestException as e:
            parsed = urlparse(url)
            safe_location = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            status = e.response.status_code if e.response is not None else None
            detail = f"HTTP {status}" if status else type(e).__name__
            raise ValueError(
                f"Failed to fetch playlist from {safe_location}: {detail}"
            ) from e

    def _parse_from_file(self, file_path: str, name: Optional[str] = None) -> Playlist:
        """Parse M3U from a local file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Playlist file not found: {file_path}")
        if not path.is_file():
            raise ValueError(f"Playlist path is not a file: {file_path}")
        if path.stat().st_size > self.MAX_DOWNLOAD_BYTES:
            raise ValueError("A playlist excede o limite de 100 MB.")

        content = path.read_text(encoding="utf-8", errors="replace")
        playlist_name = name or path.stem
        return self._parse_content(content, playlist_name, file_path=str(path))

    def _parse_content(self, content: str, name: str, url: str = "", file_path: str = "") -> Playlist:
        """Parse M3U content string into a Playlist object."""
        if not self.is_m3u(content):
            raise ValueError("Invalid M3U format: content must start with #EXTM3U")

        playlist = Playlist(
            name=name,
            source_type=(
                "m3u_plus"
                if re.search(r"(?:x-tvg-url|url-tvg)=", content.split("\n")[0], re.I)
                else "m3u"
            ),
            url=url,
            file_path=file_path,
        )

        # Extract EPG URL from the header
        epg_match = re.search(
            r'(?:x-tvg-url|url-tvg)="([^"]*)"',
            content.split("\n")[0],
            re.IGNORECASE,
        )
        if epg_match:
            playlist.epg_url = epg_match.group(1)

        lines = content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()

            if line.startswith("#EXTINF:"):
                # Parse the EXTINF line
                channel_info = self._parse_extinf(line)

                # Next non-empty, non-comment line should be the URL
                url_line = ""
                for j in range(i + 1, len(lines)):
                    next_line = lines[j].strip()
                    if next_line.lower().startswith("#extvlcopt:"):
                        option = next_line.split(":", 1)[1]
                        key, separator, value = option.partition("=")
                        if separator:
                            normalized_key = key.strip().lower()
                            if normalized_key == "http-user-agent":
                                channel_info["user_agent"] = value.strip()
                            elif normalized_key in ("http-referrer", "http-referer"):
                                channel_info["referer"] = value.strip()
                            elif normalized_key == "http-cookie":
                                channel_info.setdefault("custom_headers", {})[
                                    "Cookie"
                                ] = value.strip()
                    elif next_line.lower().startswith("#exthttp:"):
                        try:
                            headers = json.loads(next_line.split(":", 1)[1])
                            if isinstance(headers, dict):
                                channel_info.setdefault("custom_headers", {}).update(
                                    {str(k): str(v) for k, v in headers.items()}
                                )
                        except json.JSONDecodeError:
                            pass
                    if next_line and not next_line.startswith("#"):
                        url_line = next_line
                        i = j
                        break
                    elif next_line.startswith("#EXTINF:"):
                        # Malformed - next entry without URL
                        url_line = ""
                        i = j - 1
                        break
                    i = j

                if url_line:
                    channel = Channel(
                        name=channel_info.get("name", "Unknown"),
                        url=url_line,
                        group=channel_info.get("group", "General"),
                        logo=channel_info.get("tvg_logo") or channel_info.get("logo", ""),
                        tvg_id=channel_info.get("tvg_id", ""),
                        tvg_name=channel_info.get("tvg_name", ""),
                        tvg_logo=channel_info.get("tvg_logo", ""),
                        epg_channel_id=(
                            channel_info.get("epg_channel_id")
                            or channel_info.get("tvg_id", "")
                        ),
                        quality=channel_info.get("quality", ""),
                        user_agent=channel_info.get("user_agent", ""),
                        referer=channel_info.get("referer", ""),
                        custom_headers=channel_info.get("custom_headers", {}),
                        stream_type=self.infer_stream_type(
                            url_line,
                            channel_info.get("group", ""),
                            channel_info.get("name", ""),
                            channel_info.get("stream_type", ""),
                            channel_info.get("duration"),
                        ),
                        source="m3u",
                    )
                    # Determine stream type from URL extension
                    ext = url_line.rsplit(".", 1)[-1].lower() if "." in url_line else ""
                    channel.extension = ext
                    playlist.add_channel(channel)

            i += 1

        return playlist
