"""Thread-safe lifecycle management for authenticated IPTV provider clients."""

import threading
from typing import Callable, Optional

from ..parsers.stalker_parser import StalkerParser
from ..parsers.xtream_parser import XtreamParser
from .providers import Provider, StalkerProvider, XtreamProvider


class ProviderSessionManager:
    """Cache, serialize and close Xtream/Stalker sessions per playlist."""

    def __init__(self, database, timeout_provider: Callable[[], int]):
        self._database = database
        self._timeout_provider = timeout_provider
        self._stalker: dict[int, StalkerParser] = {}
        self._xtream: dict[int, XtreamParser] = {}
        self._stalker_locks: dict[int, threading.RLock] = {}
        self._xtream_locks: dict[int, threading.RLock] = {}

    def call_provider(self, playlist_id: int, callback: Callable[[Provider], object]):
        """Use the provider-neutral API for new services and controllers."""
        playlist = self._database.get_playlist(playlist_id)
        if not playlist:
            raise LookupError("Playlist não encontrada.")
        source_type = playlist.get("source_type")
        if source_type == "xtream":
            return self.call_xtream(playlist_id, lambda client: callback(XtreamProvider(client)))
        if source_type == "stalker":
            return self.call_stalker(playlist_id, lambda client: callback(StalkerProvider(client)))
        raise ValueError("Esta playlist não usa um fornecedor autenticado.")

    def call_stalker(self, playlist_id: int, callback: Callable):
        lock = self._stalker_locks.setdefault(playlist_id, threading.RLock())
        with lock:
            parser = self._stalker.get(playlist_id)
            if parser is None:
                playlist = self._database.get_playlist(playlist_id)
                if not playlist or playlist.get("source_type") != "stalker":
                    raise ValueError("Esta playlist não é um portal Stalker.")
                parser = StalkerParser(
                    playlist["server_url"],
                    playlist["mac_address"],
                    timeout=self._timeout_provider(),
                )
                try:
                    parser.authenticate()
                except Exception:
                    parser.close()
                    raise
                self._stalker[playlist_id] = parser
            return callback(parser)

    def call_xtream(self, playlist_id: int, callback: Callable):
        lock = self._xtream_locks.setdefault(playlist_id, threading.RLock())
        with lock:
            parser = self._xtream.get(playlist_id)
            if parser is None:
                playlist = self._database.get_playlist(playlist_id)
                if not playlist or playlist.get("source_type") != "xtream":
                    raise ValueError("Esta playlist não é Xtream Codes.")
                parser = XtreamParser(
                    playlist["server_url"],
                    playlist["username"],
                    playlist["password"],
                    timeout=self._timeout_provider(),
                )
                try:
                    parser.authenticate()
                except Exception:
                    parser.close()
                    raise
                self._xtream[playlist_id] = parser
            return callback(parser)

    def discard(self, playlist_id: Optional[int] = None):
        """Close clients for one playlist, or every cached client."""
        maps = (self._stalker, self._xtream)
        if playlist_id is None:
            sessions = [session for mapping in maps for session in mapping.values()]
            for mapping in maps:
                mapping.clear()
            self._stalker_locks.clear()
            self._xtream_locks.clear()
        else:
            sessions = [
                session
                for mapping in maps
                if (session := mapping.pop(playlist_id, None)) is not None
            ]
            self._stalker_locks.pop(playlist_id, None)
            self._xtream_locks.pop(playlist_id, None)
        for session in sessions:
            session.close()
