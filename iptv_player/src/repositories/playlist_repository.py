"""Playlist metadata reads isolated from the database facade."""


class PlaylistRepository:
    def __init__(self, connections, decrypt_row):
        self._connections = connections
        self._decrypt_row = decrypt_row

    def all(self) -> list[dict]:
        with self._connections() as conn:
            rows = conn.execute(
                """SELECT id, name, source_type, url, created_at, updated_at
                   FROM playlists ORDER BY updated_at DESC"""
            ).fetchall()
        return [self._decrypt_row(dict(row)) for row in rows]

    def get(self, playlist_id: int):
        with self._connections() as conn:
            row = conn.execute(
                """SELECT id, name, source_type, url, file_path, server_url,
                          username, password, mac_address, epg_source, epg_url
                   FROM playlists WHERE id = ?""",
                (playlist_id,),
            ).fetchone()
        return self._decrypt_row(dict(row)) if row else None
