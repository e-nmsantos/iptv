"""Thread-safe lifecycle management for authenticated IPTV provider clients."""

import logging
import threading
from typing import Callable, Optional

from ..parsers.stalker_parser import StalkerParser
from ..parsers.xtream_parser import XtreamParser
from .providers import Provider, StalkerProvider, XtreamProvider

logger = logging.getLogger(__name__)


class ProviderSessionManager:
    """Cache, serialize and close Xtream/Stalker sessions per playlist."""

    def __init__(
        self,
        database,
        timeout_provider: Callable[[], int],
        cancel_provider: Optional[Callable[[], bool]] = None,
    ):
        self._database = database
        self._timeout_provider = timeout_provider
        # Evaluated on every HTTP request, on whichever thread makes it, so a
        # cancelled worker aborts its provider call instead of finishing the
        # whole catalogue first.
        self._cancel_provider = cancel_provider or (lambda: False)
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
                    cancel_requested=lambda: self._cancel_provider(),
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
                    cancel_requested=lambda: self._cancel_provider(),
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
        if playlist_id is None:
            playlist_ids = set(self._stalker) | set(self._xtream)
            for cached_id in playlist_ids:
                self._close_session(cached_id)
            # The application is shutting down: nothing else needs the locks.
            self._stalker_locks.clear()
            self._xtream_locks.clear()
            return
        self._close_session(playlist_id)

    def _close_session(self, playlist_id: int) -> None:
        """Detach and close one playlist's clients without racing in-flight calls.

        The parser is only torn down while holding the same per-playlist lock
        that ``call_stalker``/``call_xtream`` hold for the duration of a call,
        so a background worker is never left using a closed session. When the
        lock is busy the close is handed to a short-lived worker instead of
        blocking the caller (which is often the GUI thread). The lock objects
        themselves are never removed - a concurrent ``call_*`` may already hold
        a reference to them, and replacing one would break mutual exclusion.
        """
        for locks, sessions in (
            (self._stalker_locks, self._stalker),
            (self._xtream_locks, self._xtream),
        ):
            lock = locks.setdefault(playlist_id, threading.RLock())
            if lock.acquire(blocking=False):
                try:
                    session = sessions.pop(playlist_id, None)
                finally:
                    lock.release()
                if session is not None:
                    self._safe_close(session)
            elif playlist_id in sessions:
                threading.Thread(
                    target=self._deferred_close,
                    args=(lock, sessions, playlist_id),
                    daemon=True,
                ).start()

    def _deferred_close(self, lock, sessions: dict, playlist_id: int) -> None:
        with lock:
            session = sessions.pop(playlist_id, None)
        if session is not None:
            self._safe_close(session)

    @staticmethod
    def _safe_close(session) -> None:
        try:
            session.close()
        except Exception as exc:  # pragma: no cover - defensive teardown
            logger.debug("Falha ao fechar sessão do fornecedor: %s", exc)
