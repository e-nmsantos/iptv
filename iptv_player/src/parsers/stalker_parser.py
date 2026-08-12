"""Stalker Portal (MAC) client and parser.

Stalker Middleware is used by many IPTV providers for MAG set-top boxes.
It uses MAC address authentication and communicates via a JSON API.

This parser supports:
- Stalker Portal 5.x (most common)
- MAC address authentication
- Channel list fetching
- EPG data
- Stream URL generation
"""

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from urllib.parse import urljoin

import requests

from ..core.channel import Channel
from ..core.epg import EPGProgram
from ..core.http_client import HttpSession
from ..core.playlist import Playlist

logger = logging.getLogger(__name__)


class StalkerParser:
    """
    Client for Stalker Middleware / Portal (MAG boxes).

    Authentication flow:
    1. GET {portal}/c/ -> establish session, get cookies
    2. POST {portal}/server/load.php  -> handshake (with device info)
    3. POST {portal}/server/load.php  -> get_profile
    4. POST {portal}/server/load.php  -> get_all_channels
    """

    def __init__(self, portal_url: str, mac_address: str, timeout: int = 30):
        self._portal_url = self._normalize_url(portal_url)
        self._mac = self._normalize_mac(mac_address)
        self._mac_clean = self._mac.lower().replace(":", "")
        self._token: str = ""
        self._profile: dict = {}
        self._genre_map: dict = {}
        self._timeout = max(5, int(timeout))

        self._session = HttpSession(timeout=self._timeout)
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG425 STBw3 firmware ver=2.31.0",
            "Accept": "*/*",
            "Accept-Language": "en",
            "X-User-Agent": "Model: MAG425; Link: WiFi",
            "Connection": "Keep-Alive",
        })

    def close(self):
        """Release pooled HTTP connections held by this client."""
        self._session.close()

    def playback_headers(self) -> dict[str, str]:
        """Return the public headers required by Stalker playback requests."""
        return {
            "User-Agent": self._session.headers.get("User-Agent", ""),
            "Referer": f"{self._portal_url}/c/",
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    # Common suffixes providers include when sharing a "portal URL" that
    # are actually the web-player path, not the API root. The API
    # (server/load.php) always lives at the bare host root, one level up
    # from these.
    _PORTAL_PATH_SUFFIXES = (
        "/c/", "/c",
        "/stalker_portal/c/", "/stalker_portal/c",
        "/portal.php", "/index.html", "/server/load.php",
    )

    @classmethod
    def _normalize_url(cls, url: str) -> str:
        """Normalize the portal URL down to its bare host root."""
        url = url.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            url = "http://" + url

        # Strip a trailing web-player/API path if the user pasted the full
        # portal URL (e.g. "http://host:80/c/") instead of just the host.
        lowered = url.lower()
        for suffix in cls._PORTAL_PATH_SUFFIXES:
            if lowered.endswith(suffix):
                url = url[: len(url) - len(suffix)]
                break

        return url.rstrip("/")

    @staticmethod
    def _normalize_mac(mac: str) -> str:
        """Normalize MAC address to format: 00:1A:79:XX:XX:XX."""
        mac = re.sub(r"[^a-fA-F0-9]", "", mac)
        if len(mac) != 12:
            raise ValueError(
                f"MAC inválido: {mac} ({len(mac)} dígitos). "
                "O MAC deve ter 12 dígitos hexadecimais (ex: 00:1A:79:XX:XX:XX)"
            )
        return ":".join(mac[i: i + 2] for i in range(0, 12, 2)).upper()

    @staticmethod
    def _generate_nonce() -> str:
        """Generate a nonce for JsHttpRequest."""
        raw = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()
        return raw[:8]

    def _post(self, data: dict) -> requests.Response:
        """POST to server/load.php."""
        url = urljoin(self._portal_url.rstrip("/") + "/", "server/load.php")
        resp = self._session.post(url, data=data, timeout=self._timeout)
        resp.raise_for_status()
        return resp

    def _parse_response(self, resp: requests.Response) -> dict:
        """
        Parse Stalker JSON responses which may be wrapped in JS comments
        or JSONP callbacks.
        """
        text = resp.text.strip()

        # Never strip ``//`` with a regular expression: it is part of every
        # unescaped http(s) URL inside a JSON string.
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # JSONP and comment-wrapped responses can be decoded from the first
        # object without modifying their string contents.
        object_start = text.find("{")
        if object_start >= 0:
            try:
                decoded, _ = json.JSONDecoder().raw_decode(text[object_start:])
                return decoded if isinstance(decoded, dict) else {}
            except json.JSONDecodeError:
                pass

        logger.warning("Stalker response is not valid JSON")
        return {}

    def authenticate(self) -> bool:
        """
        Perform the full Stalker authentication handshake.

        Returns:
            True if authentication succeeded.

        Raises:
            ConnectionError with details on failure.
        """
        logger.info("Stalker: Starting portal authentication")

        # ---- Step 1: Portal access (get cookies & session) ----
        portal_index = self._portal_url.rstrip("/") + "/c/"
        try:
            r = self._session.get(
                portal_index, timeout=self._timeout, allow_redirects=True
            )
            logger.debug(f"Portal index HTTP {r.status_code}")
        except requests.RequestException as e:
            raise ConnectionError(
                f"Falha ao aceder ao portal ({portal_index}): {e}"
            ) from e

        # Force the MAC cookie – some portals require it
        # MAG portals expect the canonical colon-separated MAC. Some servers
        # reject the compact 12-digit value before returning a handshake token.
        self._session.cookies.set("mac", self._mac)
        self._session.cookies.set("stb_lang", "en")
        self._session.cookies.set("timezone", "Europe/Lisbon")

        # ---- Step 2: Handshake ----
        nonce = self._generate_nonce()
        handshake_data = {
            "type": "stb",
            "action": "handshake",
            "token": "",
            "JsHttpRequest": f"1-xml:{nonce}",
            "device_id": self._mac_clean,
            "device_id2": self._mac_clean,
            "device_type": "MAG425",
            "login": "",
            "sn": self._mac_clean,
            "hw_version": "1.7",
            "image_version": "2.31.0",
            "stb_type": "MAG425",
        }

        resp = self._post(handshake_data)
        result = self._parse_response(resp)
        logger.debug(f"Handshake response keys: {list(result.keys())}")

        # Try to extract token from various possible locations
        token = (
            result.get("token")
            or result.get("js", {}).get("token")
            or (isinstance(result.get("js"), str) and result.get("js"))
        )

        if not token:
            # Some portals return token in a different field or format
            for key in ("auth_key", "auth_token", "session", "uid", "id"):
                val = result.get(key) or result.get("js", {}).get(key)
                if val:
                    token = str(val)
                    break

        if not token:
            error_msg = result.get("msg", result.get("error", "Resposta inesperada"))
            logger.error("Stalker handshake failed: %s", error_msg)
            raise ConnectionError(
                f"Falha na autenticação Stalker. O portal respondeu: {error_msg}\n"
                f"Verifica se o URL do portal e o MAC estão corretos."
            )

        self._token = str(token)
        logger.info("Stalker authentication token obtained")

        # ---- Step 3: Get profile ----
        nonce = self._generate_nonce()
        profile_data = {
            "type": "stb",
            "action": "get_profile",
            "token": self._token,
            "mac": self._mac,
            "JsHttpRequest": f"1-xml:{nonce}",
        }

        resp = self._post(profile_data)
        result = self._parse_response(resp)
        js_data = result.get("js", result)
        self._profile = js_data if isinstance(js_data, dict) else {}

        logger.info("Stalker profile loaded")
        return True

    def get_channels(self) -> list[Channel]:
        """
        Get all TV channels from the Stalker portal.
        Tries multiple endpoint actions in case the portal uses a different API version.
        """
        if not self._token:
            self.authenticate()

        channels: list[Channel] = []

        # ---- Strategy 1: get_all_channels (most common) ----
        channels = self._try_get_channels("get_all_channels")

        # ---- Strategy 2: itv action ----
        if not channels:
            logger.info("Stalker: get_all_channels returned 0, trying 'itv' action...")
            channels = self._try_get_channels("itv")

        # ---- Strategy 3: get_itv_list with pagination ----
        if not channels:
            logger.info("Stalker: 'itv' returned 0, trying 'get_itv_list' action...")
            channels = self._try_get_channels("get_itv_list")

        # ---- Strategy 4: get_genres + get_all_channels ----
        if not channels:
            logger.info("Stalker: trying genre-based channel fetch...")
            channels = self._try_genre_channels()

        # ---- Strategy 5: M3U via get.php (common fallback) ----
        if not channels:
            logger.info("Stalker: trying M3U via get.php...")
            channels = self._try_m3u_fallback()

        if channels:
            logger.info(f"Stalker: loaded {len(channels)} channels successfully")
        else:
            logger.warning(
                "Stalker: 0 channels found. O portal não devolveu canais "
                "para este MAC. Verifica se o MAC está ativo no portal."
            )

        return channels

    def _paginated_fetch(
        self,
        type_: str,
        action: str,
        extra_params: Optional[dict] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> list[dict]:
        """
        Generic paginated fetch against server/load.php, deduplicated by
        item "id" and bounded by the server-reported "total_items". Used
        for live channels, VOD movies and series shows/seasons alike.
        """
        items_out: list[dict] = []
        seen_ids: set = set()
        page = 1
        # Safety cap against buggy portals that keep returning unique items
        # while over-reporting total_items. For realistic catalogs the loop
        # terminates via total_items below (page size ~30 -> 2000 pages is
        # ~60k items, far beyond any real portal).
        max_pages = 2000
        total_items = 0

        while page <= max_pages:
            if should_cancel and should_cancel():
                break
            nonce = self._generate_nonce()
            data = {
                "type": type_,
                "action": action,
                "token": self._token,
                "mac": self._mac,
                "JsHttpRequest": f"1-xml:{nonce}",
                "p": str(page),
            }
            if extra_params:
                data.update(extra_params)

            try:
                resp = self._post(data)
                result = self._parse_response(resp)
            except Exception as e:
                logger.debug(f"Stalker {type_}/{action} page {page} error: {e}")
                break

            # Some portals wrap in "js" key
            js_data = result.get("js", result)

            if not isinstance(js_data, dict):
                break

            if page == 1:
                logger.debug(f"Stalker {type_}/{action} first response keys: {list(js_data.keys())}")

            # Detect total pages from response
            raw_total = js_data.get("total_items", 0)
            try:
                total_items = int(raw_total) if raw_total else 0
                if total_items and page == 1:
                    max_pages = min((total_items // 30) + 1, max_pages)
            except (ValueError, TypeError):
                total_items = 0

            # Try different possible field names for the item list
            items = None
            for field in ("data", "channels", "tv_channels", "list", "items", "itv", "tv"):
                candidate = js_data.get(field, result.get(field))
                if isinstance(candidate, list) and candidate:
                    items = candidate
                    break

            if not items or not isinstance(items, list):
                break

            new_items_found = False
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_id = item.get("id")
                if item_id is not None:
                    if item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)
                new_items_found = True
                items_out.append(item)

            # Stop if the portal ignored pagination and re-sent the same
            # full list (common on some Stalker portals), or if we've
            # already collected everything the server reported.
            if not new_items_found:
                break
            if total_items and len(seen_ids) >= total_items:
                break
            if total_items and len(items) >= total_items:
                # Single response already contained the full list.
                break

            page += 1

        if total_items and len(seen_ids) < total_items:
            logger.warning(
                f"Stalker {type_}/{action}: catálogo truncado — "
                f"obtidos {len(seen_ids)} de {total_items} itens "
                f"(limite de {max_pages} páginas)."
            )
        logger.debug(f"Stalker {type_}/{action}: got {len(items_out)} item(s) from {page - 1} page(s)")
        return items_out

    def _try_get_channels(self, action: str) -> list[Channel]:
        """Fetch live channels using a specific API action."""
        items = self._paginated_fetch("itv", action)
        channels: list[Channel] = []
        self._genre_map = self.get_genres()
        user_agent = self._session.headers.get("User-Agent", "")
        referer = f"{self._portal_url}/c/"
        for item in items:
            genre_id = str(
                item.get("tv_genre_id") or item.get("tv_genre") or ""
            )
            provider_group = self._genre_map.get(genre_id, "")
            channels.append(Channel(
                name=item.get("name", "Unknown"),
                url=self._build_stream_url(item),
                group=provider_group or "General",
                logo=item.get("logo", "") or item.get("tv_logo", "") or "",
                tvg_id=str(item.get("id", "")),
                epg_channel_id=str(item.get("id", "")),
                stream_type="live",
                source="stalker",
                category_id=genre_id,
                country_code=self._country_code_from_group(provider_group),
                provider_group=provider_group,
                user_agent=user_agent,
                referer=referer,
            ))
        return channels

    def get_genres(self) -> dict:
        """Return the portal's original live-category mapping (ID -> title)."""
        if not self._token:
            self.authenticate()
        nonce = self._generate_nonce()
        data = {
            "type": "itv",
            "action": "get_genres",
            "token": self._token,
            "mac": self._mac,
            "JsHttpRequest": f"1-xml:{nonce}",
        }
        try:
            result = self._parse_response(self._post(data))
            js_data = result.get("js", result)
            genres = (
                js_data.get("data", js_data)
                if isinstance(js_data, dict)
                else js_data
            )
            if not isinstance(genres, list):
                return {}
            return {
                str(item.get("id")): str(
                    item.get("title") or item.get("name") or ""
                )
                for item in genres
                if isinstance(item, dict) and item.get("id") not in (None, "*")
            }
        except Exception as exc:
            logger.warning(f"Stalker get_genres failed: {exc}")
            return {}

    @staticmethod
    def _country_code_from_group(group: str) -> str:
        """Extract a portal region prefix such as ┃UK┃ or ┃USA┃."""
        match = re.match(
            r"^\s*[^A-Za-z0-9]*([A-Za-z]{2,4})[^A-Za-z0-9]+",
            group,
        )
        if not match:
            return ""
        code = match.group(1).upper()
        return "US" if code in ("US", "USA") else code

    def _try_genre_channels(self) -> list[Channel]:
        """
        Some Stalker portals require first fetching genres,
        then fetching channels per genre.
        """
        channels: list[Channel] = []
        user_agent = self._session.headers.get("User-Agent", "")
        referer = f"{self._portal_url}/c/"

        # Get genres/categories
        nonce = self._generate_nonce()
        data = {
            "type": "itv",
            "action": "get_genres",
            "token": self._token,
            "mac": self._mac,
            "JsHttpRequest": f"1-xml:{nonce}",
        }

        try:
            resp = self._post(data)
            result = self._parse_response(resp)
            js_data = result.get("js", result)
            genres = js_data.get("data", [])
        except Exception as e:
            logger.debug(f"Stalker get_genres failed: {e}")
            return []

        if not isinstance(genres, list):
            genres = []

        for genre in genres:
            genre_id = genre.get("id")
            if not genre_id:
                continue

            nonce = self._generate_nonce()
            data = {
                "type": "itv",
                "action": "get_ordered_list",
                "token": self._token,
                "mac": self._mac,
                "JsHttpRequest": f"1-xml:{nonce}",
                "genre": str(genre_id),
            }

            try:
                resp = self._post(data)
                result = self._parse_response(resp)
                js_data = result.get("js", result)
                items = (
                    js_data.get("data")
                    or js_data.get("channels")
                    or result.get("data", [])
                )
                genre_name = genre.get("name", genre.get("title", "General"))

                for item in items if isinstance(items, list) else []:
                    if not isinstance(item, dict):
                        continue
                    channel = Channel(
                        name=item.get("name", "Unknown"),
                        url=self._build_stream_url(item),
                        group=genre_name,
                        logo=item.get("logo", "") or item.get("tv_logo", "") or "",
                        tvg_id=str(item.get("id", "")),
                        epg_channel_id=str(item.get("id", "")),
                        stream_type="live",
                        source="stalker",
                        category_id=str(genre_id),
                        country_code=self._country_code_from_group(genre_name),
                        provider_group=genre_name,
                        user_agent=user_agent,
                        referer=referer,
                    )
                    channels.append(channel)
            except Exception as e:
                logger.debug(f"Stalker genre {genre_id} failed: {e}")
                continue

        return channels

    def _try_m3u_fallback(self) -> list:
        """
        Try to get channels via M3U endpoint (get.php).
        Many Stalker portals also serve M3U playlists via:
        {portal}/get.php?username=MAC&password=MAC&type=m3u_plus
        """
        from ..parsers.m3u_parser import M3UParser

        # Note: this fallback authenticates by sending the MAC as both the
        # username and password in the query string — how most Stalker web
        # players do it. The MAC is therefore visible in transit; prefer
        # https:// portals. The MAC itself is never logged here.
        mac_clean = self._mac.lower().replace(":", "")
        m3u_url = (
            f"{self._portal_url.rstrip('/')}/get.php"
            f"?username={mac_clean}&password={mac_clean}&type=m3u_plus"
        )

        try:
            resp = self._session.get(m3u_url, timeout=self._timeout)
            if resp.status_code == 200 and "#EXTM3U" in resp.text:
                logger.info("Stalker: got channels via get.php M3U endpoint!")
                parser = M3UParser()
                # Manually parse the M3U content
                playlist = parser._parse_content(
                    resp.text, f"Stalker - {self._mac}"
                )
                # Mark channels as stalker source
                for ch in playlist.channels:
                    ch.source = "stalker"
                    ch.user_agent = (
                        ch.user_agent or self._session.headers.get("User-Agent", "")
                    )
                    ch.referer = ch.referer or f"{self._portal_url}/c/"
                    ch.provider_group = ch.provider_group or ch.group
                    ch.country_code = (
                        ch.country_code
                        or self._country_code_from_group(ch.provider_group)
                    )
                return playlist.channels
            else:
                logger.debug(
                    f"Stalker get.php returned [{resp.status_code}]: "
                    f"probably behind Cloudflare protection"
                )
                return []
        except requests.RequestException as e:
            logger.debug(f"Stalker get.php failed: {e}")
            return []

    @staticmethod
    def _extract_url_from_cmd(cmd: str) -> str:
        """Extract a playable URL from a Stalker "cmd" string, which is
        often prefixed with a player command, e.g. "ffmpeg http://...".
        Returns "" if no URL is found."""
        url_match = re.search(r"(https?|rtp|udp|rtsp)://\S+", cmd)
        return url_match.group(0) if url_match else ""

    def _build_stream_url(self, channel_data: dict) -> str:
        """Build the stream URL from channel data."""
        cmd = channel_data.get("cmd", "")

        if not cmd:
            ch_id = channel_data.get("id", "")
            return urljoin(
                self._portal_url.rstrip("/") + "/",
                f"ch/{self._mac_clean}/stream/{ch_id}",
            )

        cmd = cmd.strip()

        # Some portals prefix the real URL with a player command, e.g.
        # "ffmpeg http://host/play/live.php?..." – extract just the URL.
        url = self._extract_url_from_cmd(cmd)
        if url:
            return url

        return urljoin(
            self._portal_url.rstrip("/") + "/",
            f"ch/{self._mac_clean}/stream/{cmd}",
        )

    def get_vod_categories(self) -> list[dict]:
        """Get all VOD (movie) categories."""
        if not self._token:
            self.authenticate()
        nonce = self._generate_nonce()
        data = {
            "type": "vod",
            "action": "get_categories",
            "token": self._token,
            "mac": self._mac,
            "JsHttpRequest": f"1-xml:{nonce}",
        }
        try:
            resp = self._post(data)
            result = self._parse_response(resp)
            js_data = result.get("js", result)
            return js_data if isinstance(js_data, list) else []
        except Exception as e:
            logger.warning(f"Stalker get_vod_categories failed: {e}")
            return []

    def get_vod_movies(
        self,
        should_cancel: Optional[Callable[[], bool]] = None,
        progress: Optional[Callable[[str], None]] = None,
    ) -> list[Channel]:
        """Fetch all VOD movies across all categories. The stream URL isn't
        directly playable yet — it's the opaque "cmd" blob, which must be
        resolved via resolve_link() right before playback."""
        if not self._token:
            self.authenticate()

        movies: list[Channel] = []
        user_agent = self._session.headers.get("User-Agent", "")
        referer = f"{self._portal_url}/c/"
        categories = self.get_vod_categories()
        for index, category in enumerate(categories, start=1):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(f"VOD: categoria {index}/{len(categories)}")
            cat_id = category.get("id")
            if cat_id is None:
                continue
            cat_title = category.get("title", category.get("name", "Filmes"))
            items = self._paginated_fetch(
                "vod",
                "get_ordered_list",
                {"category": str(cat_id)},
                should_cancel=should_cancel,
            )
            for item in items:
                movies.append(Channel(
                    name=item.get("name", "Unknown"),
                    url=item.get("cmd", ""),
                    group=cat_title,
                    logo=item.get("screenshot_uri", ""),
                    tvg_id=str(item.get("id", "")),
                    stream_type="vod",
                    source="stalker",
                    xtream_id=str(item.get("id", "")),
                    category_id=str(cat_id),
                    user_agent=user_agent,
                    referer=referer,
                ))
        logger.info(f"Stalker: loaded {len(movies)} VOD movies")
        return movies

    def get_series_categories(self) -> list[dict]:
        """Get all series categories."""
        if not self._token:
            self.authenticate()
        nonce = self._generate_nonce()
        data = {
            "type": "series",
            "action": "get_categories",
            "token": self._token,
            "mac": self._mac,
            "JsHttpRequest": f"1-xml:{nonce}",
        }
        try:
            resp = self._post(data)
            result = self._parse_response(resp)
            js_data = result.get("js", result)
            return js_data if isinstance(js_data, list) else []
        except Exception as e:
            logger.warning(f"Stalker get_series_categories failed: {e}")
            return []

    def get_series_shows(
        self,
        should_cancel: Optional[Callable[[], bool]] = None,
        progress: Optional[Callable[[str], None]] = None,
    ) -> list[Channel]:
        """Fetch the top-level list of TV shows across all series
        categories. Seasons/episodes are NOT fetched here — that would
        require one extra request per show, which doesn't scale (this
        portal alone has 149 series categories). They're fetched lazily
        via get_series_seasons() when the user opens a show."""
        if not self._token:
            self.authenticate()

        shows: list[Channel] = []
        user_agent = self._session.headers.get("User-Agent", "")
        referer = f"{self._portal_url}/c/"
        categories = self.get_series_categories()
        for index, category in enumerate(categories, start=1):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(f"Séries: categoria {index}/{len(categories)}")
            cat_id = category.get("id")
            if cat_id is None:
                continue
            cat_title = category.get("title", category.get("name", "Séries"))
            items = self._paginated_fetch(
                "series",
                "get_ordered_list",
                {"category": str(cat_id)},
                should_cancel=should_cancel,
            )
            for item in items:
                raw_id = str(item.get("id", ""))
                show_id = raw_id.split(":")[0] if raw_id else ""
                if not show_id:
                    continue
                shows.append(Channel(
                    name=item.get("name", "Unknown"),
                    url="",
                    group=cat_title,
                    logo=item.get("screenshot_uri", ""),
                    stream_type="series",
                    source="stalker",
                    xtream_id=show_id,
                    category_id=str(cat_id),
                    user_agent=user_agent,
                    referer=referer,
                ))
        logger.info(f"Stalker: loaded {len(shows)} series shows")
        return shows

    def get_series_seasons(self, category_id: str, show_id: str) -> list[dict]:
        """Lazily fetch the seasons (and their episode-number lists) for a
        single series show. Called on-demand when the user opens a show."""
        if not self._token:
            self.authenticate()
        return self._paginated_fetch(
            "series", "get_ordered_list",
            {"category": str(category_id), "movie_id": str(show_id)}
        )

    def resolve_link(self, cmd: str, series: str = "") -> str:
        """Resolve a VOD/series opaque "cmd" blob into a playable URL via
        the portal's create_link action. Must be called right before
        playback — the returned play_token appears session/time-bound.
        For series episodes, pass the season's cmd plus the episode
        number as `series`."""
        if not self._token:
            self.authenticate()

        nonce = self._generate_nonce()
        data = {
            # create_link always uses type=vod, even for series episodes.
            "type": "vod",
            "action": "create_link",
            "token": self._token,
            "mac": self._mac,
            "JsHttpRequest": f"1-xml:{nonce}",
            "cmd": cmd,
            "series": str(series) if series else "",
        }
        resp = self._post(data)
        result = self._parse_response(resp)
        js_data = result.get("js", result)
        resolved_cmd = js_data.get("cmd", "") if isinstance(js_data, dict) else ""
        url = self._extract_url_from_cmd(resolved_cmd)
        if not url:
            raise ConnectionError(
                "O portal Stalker não devolveu um URL de reprodução válido "
                "para este conteúdo."
            )
        return url

    def resolve_live_link(self, cmd: str) -> str:
        """Resolve a live channel's temporary/localhost command.

        Portals with ``use_http_tmp_link`` return values such as
        ``http://localhost/ch/1_`` in the channel catalogue. Those are
        server-side identifiers and must be exchanged for a short-lived
        public URL immediately before playback.
        """
        if not self._token:
            self.authenticate()

        nonce = self._generate_nonce()
        data = {
            "type": "itv",
            "action": "create_link",
            "token": self._token,
            "mac": self._mac,
            "JsHttpRequest": f"1-xml:{nonce}",
            "cmd": cmd,
            "series": "",
            "forced_storage": "undefined",
            "disable_ad": "0",
            "download": "0",
        }
        resp = self._post(data)
        result = self._parse_response(resp)
        js_data = result.get("js", result)
        resolved_cmd = js_data.get("cmd", "") if isinstance(js_data, dict) else ""
        url = self._extract_url_from_cmd(resolved_cmd)
        if not url:
            raise ConnectionError(
                "O portal Stalker não devolveu um link temporário válido "
                "para o canal."
            )
        return url

    def get_epg(
        self,
        genre: Optional[str] = None,
        channel_id: Optional[str] = None,
    ) -> list[dict]:
        """Get EPG data from the portal."""
        if not self._token:
            self.authenticate()

        nonce = self._generate_nonce()
        data = {
            "type": "itv",
            "action": "get_epg_info",
            "token": self._token,
            "mac": self._mac,
            "JsHttpRequest": f"1-xml:{nonce}",
        }
        if genre:
            data["genre"] = genre
        if channel_id:
            data["ch_id"] = str(channel_id)

        try:
            resp = self._post(data)
            result = self._parse_response(resp)
            js_data = result.get("js", result)
            if isinstance(js_data, list):
                return js_data
            return js_data.get("data", []) if isinstance(js_data, dict) else []
        except Exception as e:
            logger.warning(f"Stalker EPG error: {e}")
            return []

    def get_epg_programs(
        self, channel_id: str, limit: int = 48
    ) -> list[EPGProgram]:
        """Fetch and normalize common Stalker EPG response variants."""
        raw = self.get_epg(channel_id=channel_id)
        if isinstance(raw, dict):
            raw = raw.get(str(channel_id), raw.get("data", []))
        if not isinstance(raw, list):
            return []

        programs = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            item_channel = str(
                item.get("ch_id") or item.get("channel_id") or channel_id
            )
            if item_channel != str(channel_id):
                continue
            start = self._parse_epg_datetime(
                item.get("start_timestamp") or item.get("start")
                or item.get("time")
            )
            stop = self._parse_epg_datetime(
                item.get("stop_timestamp") or item.get("stop")
                or item.get("time_to") or item.get("end")
            )
            if start and not stop and item.get("duration"):
                try:
                    stop = start + timedelta(seconds=int(item["duration"]))
                except (TypeError, ValueError):
                    pass
            if not start or not stop or stop <= start:
                continue
            programs.append(
                EPGProgram(
                    channel_id=str(channel_id),
                    title=str(item.get("name") or item.get("title") or "Sem título"),
                    start=start,
                    stop=stop,
                    description=str(item.get("descr") or item.get("description") or ""),
                    category=str(item.get("category") or ""),
                )
            )
            if len(programs) >= limit:
                break
        return programs

    @staticmethod
    def _parse_epg_datetime(value) -> Optional[datetime]:
        if value in (None, ""):
            return None
        try:
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, timezone.utc).astimezone()
        except (TypeError, ValueError, OSError):
            pass

        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.astimezone()
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S"):
                try:
                    return datetime.strptime(text, fmt).astimezone()
                except ValueError:
                    continue
        return None

    def get_full_playlist(
        self,
        include_vod: bool = False,
        include_series: bool = False,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Playlist:
        """Fetch live channels quickly.

        Large VOD/series catalogues are optional because fetching every
        category can require hundreds or thousands of requests.
        """
        if not self._token:
            self.authenticate()

        playlist = Playlist(
            name=f"Stalker - {self._mac}",
            source_type="stalker",
            server_url=self._portal_url,
            mac_address=self._mac,
        )

        channels = self.get_channels()
        for ch in channels:
            playlist.add_channel(ch)

        if include_vod and not (should_cancel and should_cancel()):
            try:
                for ch in self.get_vod_movies(should_cancel=should_cancel):
                    playlist.add_channel(ch)
            except Exception as e:
                logger.warning(f"Stalker: failed to fetch VOD movies: {e}")

        if include_series and not (should_cancel and should_cancel()):
            try:
                for ch in self.get_series_shows(should_cancel=should_cancel):
                    playlist.add_channel(ch)
            except Exception as e:
                logger.warning(f"Stalker: failed to fetch series shows: {e}")

        return playlist
