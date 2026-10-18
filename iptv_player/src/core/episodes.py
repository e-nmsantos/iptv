"""Replayable series-episode references shared by playback, history and TV sync.

Episodes never live in the ``channels`` table, so they are kept as lightweight
Channel references whose stream link is resolved only when played:

* Stalker: ``stalker-episode://<cmd>?episode=<n>`` (``create_link`` at play time)
* Xtream:  ``xtream-episode://<id>?ext=<container>`` (built from the playlist's
  own credentials at play time, so synced history never carries them)
"""

import re
from typing import Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

from .channel import Channel

STALKER_EPISODE_SCHEME = "stalker-episode://"
XTREAM_EPISODE_SCHEME = "xtream-episode://"


def season_number_from(value) -> int:
    """Season number from a portal value such as ``2`` or ``"Temporada 2"``."""
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else 0


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
        season_number=season_number_from(season.get("season") or season_name),
        episode_number=season_number_from(episode),
    )


def parse_stalker_episode(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    cmd = unquote(url[len(STALKER_EPISODE_SCHEME):].split("?", 1)[0])
    episode = parse_qs(parsed.query).get("episode", [""])[0]
    return cmd, episode


def xtream_episode_channel(
    episode_id: str,
    title: str,
    season: int,
    episode: int,
    extension: str,
    logo: str = "",
) -> Channel:
    """A credential-free Xtream episode reference (see module docstring)."""
    ext = (extension or "mp4").lstrip(".")
    return Channel(
        name=title,
        url=f"{XTREAM_EPISODE_SCHEME}{quote(str(episode_id), safe='')}?ext={quote(ext, safe='')}",
        group=f"Temporada {season}" if season else "Episódios",
        logo=logo,
        stream_type="series",
        source="xtream",
        xtream_id=str(episode_id),
        season_number=season,
        episode_number=episode,
        container_extension=ext,
    )


def parse_xtream_episode(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    episode_id = unquote(url[len(XTREAM_EPISODE_SCHEME):].split("?", 1)[0])
    ext = parse_qs(parsed.query).get("ext", ["mp4"])[0]
    return episode_id, ext


def episode_extension(channel: Channel) -> str:
    """Container extension of an Xtream episode, whatever form its URL takes."""
    if channel.container_extension:
        return channel.container_extension
    if channel.url.startswith(XTREAM_EPISODE_SCHEME):
        return parse_xtream_episode(channel.url)[1]
    tail = urlparse(channel.url).path.rsplit("/", 1)[-1]
    return tail.rsplit(".", 1)[-1] if "." in tail else "mp4"


def show_reference(
    source: str, series_id: str, name: str, logo: str = "", category_id: str = ""
) -> Optional[Channel]:
    """Minimal show Channel that can fetch its episode list again."""
    if not series_id or source not in ("xtream", "stalker"):
        return None
    return Channel(
        name=name or "Série",
        url="",
        logo=logo,
        stream_type="series",
        source=source,
        xtream_id=str(series_id),
        category_id=str(category_id or ""),
    )
