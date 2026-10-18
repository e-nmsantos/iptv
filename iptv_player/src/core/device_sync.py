"""Credential-free state exchange between desktop and Android TV.

Besides favourites and resume points keyed by catalogue identity, the state
carries a ``continue`` list so "Continuar a ver" (including series episodes,
which never live in the catalogue) follows the viewer between devices. Each
entry holds provider identifiers only; the receiver rebuilds the episode with
its own playlist credentials when it is played.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from .content_types import SERIES, VOD, content_type_for_stream
from .episodes import (
    STALKER_EPISODE_SCHEME,
    episode_extension,
    parse_stalker_episode,
    season_number_from,
    show_reference,
    stalker_episode_channel,
    xtream_episode_channel,
)

MAX_CONTINUE_ENTRIES = 200


def media_key(channel) -> str:
    stream_type = "vod" if channel.stream_type in ("vod", "movie") else channel.stream_type
    identity = "\0".join(
        (channel.tvg_id or channel.name, channel.group, stream_type.upper())
    )
    return "media:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def export_device_state(database, playlist_id: int) -> str:
    """Export favorites and resume points without URLs or credentials."""
    favorites = [
        media_key(channel)
        for channel in database.get_channels(playlist_id)
        if channel.is_favorite
    ]
    progress = {
        media_key(item["channel"]): {
            "position_ms": item["position_ms"],
            "duration_ms": item["length_ms"],
        }
        for item in database.get_resume_candidates(playlist_id)
    }
    continue_entries = [
        entry
        for entry in (
            encode_continue_item(item)
            for item in database.get_continue_watching(playlist_id, limit=MAX_CONTINUE_ENTRIES)
        )
        if entry is not None
    ]
    return json.dumps(
        {
            "schema_version": 1,
            "favorites": favorites,
            "progress": progress,
            "continue": continue_entries,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def import_device_state(database, playlist_id: int, raw_data: str) -> dict[str, int]:
    """Merge a credential-free TV state into the desktop catalogue."""
    data = json.loads(raw_data)
    if data.get("schema_version") != 1:
        raise ValueError("Versão de sincronização incompatível.")
    favorites = set(data.get("favorites", ()))
    progress = data.get("progress", {})
    if len(favorites) > 100_000 or len(progress) > 100_000:
        raise ValueError("A sincronização contém demasiados itens.")
    channels = database.get_channels(playlist_id)
    by_key = {media_key(channel): channel for channel in channels}
    favorite_count = 0
    progress_count = 0
    for key in favorites:
        channel = by_key.get(key)
        if channel and channel.database_id:
            database.set_favorite(channel.database_id, playlist_id, True)
            favorite_count += 1
    for key, item in progress.items():
        channel = by_key.get(key)
        if not channel or not isinstance(item, dict):
            continue
        position = max(0, int(item.get("position_ms", 0)))
        duration = max(0, int(item.get("duration_ms", 0)))
        if position >= 10_000 and duration > 0 and position < duration * 0.95:
            database.save_playback_progress(playlist_id, channel, position, duration)
            progress_count += 1
    continued = _merge_continue_entries(database, playlist_id, data.get("continue"), by_key)
    return {"favorites": favorite_count, "progress": progress_count, "continue": continued}


def _epoch_ms(value) -> int:
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            return 0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


def _text(entry: dict, key: str, limit: int = 2048) -> str:
    value = entry.get(key, "")
    return str(value)[:limit] if isinstance(value, (str, int)) else ""


def encode_continue_item(item: dict) -> Optional[dict]:
    """One "Continuar a ver" entry, without URLs or credentials (None if not portable)."""
    channel = item["channel"]
    parent = item.get("parent")
    entry = {
        "title": channel.name,
        "logo": channel.logo,
        "position_ms": int(item.get("position_ms") or 0),
        "duration_ms": int(item.get("length_ms") or 0),
        "up_next": bool(item.get("up_next")),
        "played_at": _epoch_ms(item.get("played_at")),
    }
    kind = content_type_for_stream(channel.stream_type)
    if kind == SERIES and parent is not None and parent.xtream_id:
        common = {
            "kind": "episode",
            "source": channel.source,
            "series_id": parent.xtream_id,
            "series_name": parent.name,
            "series_logo": parent.logo,
            "season": channel.season_number or season_number_from(channel.group),
        }
        if channel.source == "xtream" and channel.xtream_id:
            return {
                **entry, **common,
                "episode_id": channel.xtream_id,
                "episode": channel.episode_number,
                "ext": episode_extension(channel),
            }
        if channel.source == "stalker" and channel.url.startswith(STALKER_EPISODE_SCHEME):
            cmd, episode = parse_stalker_episode(channel.url)
            return {**entry, **common, "series_category": parent.category_id, "cmd": cmd, "episode": episode}
        return None
    if kind in (VOD, SERIES) and channel.database_id:
        return {**entry, "kind": "catalog", "key": media_key(channel)}
    return None


def decode_continue_entry(entry: dict, source_type: str, by_key: dict) -> Optional[tuple]:
    """Rebuild ``(channel, show)`` for an incoming entry, or None if it doesn't apply here."""
    kind = entry.get("kind")
    if kind == "catalog":
        channel = by_key.get(_text(entry, "key", 200))
        return (channel, None) if channel is not None else None
    if kind != "episode" or entry.get("source") != source_type:
        return None
    season = season_number_from(entry.get("season"))
    show = show_reference(
        source_type,
        _text(entry, "series_id", 200),
        _text(entry, "series_name", 500),
        _text(entry, "series_logo"),
        _text(entry, "series_category", 200),
    )
    if show is None:
        return None
    if source_type == "xtream":
        episode_id = _text(entry, "episode_id", 200)
        if not episode_id:
            return None
        channel = xtream_episode_channel(
            episode_id,
            _text(entry, "title", 500) or f"Episódio {entry.get('episode', '')}",
            season,
            season_number_from(entry.get("episode")),
            _text(entry, "ext", 16) or "mp4",
            _text(entry, "logo"),
        )
        return channel, show
    cmd = _text(entry, "cmd", 4096)
    episode = _text(entry, "episode", 32)
    if not cmd or not episode:
        return None
    season_name = f"Temporada {season}" if season else "Temporada"
    return stalker_episode_channel(show, {"cmd": cmd, "name": season_name, "season": season}, episode), show


def _merge_continue_entries(database, playlist_id: int, entries, by_key: dict) -> int:
    """Apply incoming entries that are newer than what this device last watched."""
    if not isinstance(entries, list):
        return 0
    playlist = database.get_playlist(playlist_id) or {}
    source_type = playlist.get("source_type", "")
    merged = 0
    for entry in entries[:MAX_CONTINUE_ENTRIES]:
        if not isinstance(entry, dict):
            continue
        decoded = decode_continue_entry(entry, source_type, by_key)
        if decoded is None:
            continue
        channel, show = decoded
        played_ms = int(entry.get("played_at") or 0)
        played_at = (
            datetime.fromtimestamp(played_ms / 1000, timezone.utc) if played_ms > 0
            else datetime.now(timezone.utc)
        )
        local = database.get_watch_played_at(playlist_id, database.media_key(channel))
        if local is not None and local >= played_at:
            continue
        up_next = bool(entry.get("up_next"))
        database.record_watch(playlist_id, channel, parent=show, up_next=up_next, played_at=played_at)
        position = max(0, int(entry.get("position_ms") or 0))
        duration = max(0, int(entry.get("duration_ms") or 0))
        if not up_next and duration > 0:
            database.save_playback_progress(playlist_id, channel, position, duration)
        merged += 1
    return merged
