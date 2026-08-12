"""Validation and model conversion for portable database backup payloads."""

from .channel import Channel
from .playlist import Playlist


def export_backup_data(database) -> dict:
    playlists = []
    for summary in database.get_playlists():
        playlist_id = summary["id"]
        details = database.get_playlist(playlist_id)
        if not details:
            continue
        details = dict(details)
        details.pop("id", None)
        playlists.append(
            {
                "details": details,
                "channels": [
                    channel.to_dict() for channel in database.get_channels(playlist_id)
                ],
            }
        )
    return {"schema_version": 1, "playlists": playlists}


def parse_backup_data(data: dict) -> list[Playlist]:
    """Validate the complete payload and return safe domain models."""
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Backup incompatível.")
    raw_playlists = data.get("playlists")
    if not isinstance(raw_playlists, list) or len(raw_playlists) > 100:
        raise ValueError("Lista de playlists inválida no backup.")

    playlists = []
    for item in raw_playlists:
        details = item.get("details") if isinstance(item, dict) else None
        raw_channels = item.get("channels") if isinstance(item, dict) else None
        if not isinstance(details, dict) or not isinstance(raw_channels, list):
            raise ValueError("Playlist inválida no backup.")
        if len(raw_channels) > 500_000:
            raise ValueError("Uma playlist do backup excede 500 000 itens.")
        channels = []
        for raw_channel in raw_channels:
            if not isinstance(raw_channel, dict):
                raise ValueError("Canal inválido no backup.")
            channel = Channel.from_dict(raw_channel)
            channel.database_id = 0
            channels.append(channel)
        playlists.append(
            Playlist(
                name=str(details.get("name", "Restauro")),
                source_type=str(details.get("source_type", "m3u")),
                channels=channels,
                url=str(details.get("url", "")),
                file_path=str(details.get("file_path", "")),
                server_url=str(details.get("server_url", "")),
                username=str(details.get("username", "")),
                password=str(details.get("password", "")),
                mac_address=str(details.get("mac_address", "")),
                epg_source=str(details.get("epg_source", "")),
                epg_url=str(details.get("epg_url", "")),
            )
        )
    return playlists
