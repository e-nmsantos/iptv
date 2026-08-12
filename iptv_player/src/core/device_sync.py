"""Credential-free state exchange between desktop and Android TV."""

import hashlib
import json


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
    return json.dumps(
        {"schema_version": 1, "favorites": favorites, "progress": progress},
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
    return {"favorites": favorite_count, "progress": progress_count}
