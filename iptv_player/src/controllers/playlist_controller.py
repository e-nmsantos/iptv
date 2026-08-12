"""Playlist application operations independent from Qt widgets."""


class PlaylistController:
    def __init__(self, database):
        self._database = database

    def list(self) -> list[dict]:
        return self._database.get_playlists()

    def import_playlist(self, playlist) -> tuple[int, list]:
        playlist_id = self._database.save_playlist(playlist)
        return playlist_id, self._database.get_channels(playlist_id)

    def open(self, playlist_id: int) -> tuple[dict, list]:
        details = self._database.get_playlist(playlist_id)
        if not details:
            raise LookupError("Playlist não encontrada.")
        return details, self._database.get_channels(playlist_id)

    def rename(self, playlist_id: int, name: str) -> None:
        self._database.rename_playlist(playlist_id, name)

    def delete(self, playlist_id: int) -> None:
        self._database.delete_playlist(playlist_id)

    def update_connection(self, playlist_id: int, values: dict) -> None:
        self._database.update_playlist_connection(playlist_id, values)
