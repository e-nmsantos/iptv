"""Catalogue orchestration independent from Qt widgets."""

from collections.abc import Callable

from ..core.providers import CatalogKind
from ..parsers.m3u_parser import M3UParser


class CatalogController:
    def __init__(self, database, provider_sessions, settings):
        self._database = database
        self._providers = provider_sessions
        self._settings = settings

    def refresh(
        self,
        playlist_id: int,
        content_type: str,
        should_cancel: Callable[[], bool] = lambda: False,
        progress: Callable[[str], None] = lambda _message: None,
    ):
        """Fetch and atomically persist one provider-neutral catalogue."""
        playlist = self._database.get_playlist(playlist_id)
        if not playlist:
            raise LookupError("Playlist não encontrada.")
        kind = CatalogKind(content_type)
        source_type = playlist.get("source_type", "")
        if source_type in ("m3u", "m3u_plus"):
            source = playlist.get("url") or playlist.get("file_path")
            if not source:
                raise ValueError("A playlist não tem uma origem para atualizar.")
            parsed = M3UParser(
                timeout=self._settings.get("network_timeout_seconds", 30),
                user_agent=self._settings.get("user_agent", ""),
            ).parse(source, playlist.get("name"))
            accepted = ("vod", "movie") if kind == CatalogKind.VOD else (kind.value,)
            channels = [item for item in parsed.channels if item.stream_type in accepted]
        else:
            channels = self._providers.call_provider(
                playlist_id,
                lambda provider: provider.load_catalog(
                    kind,
                    should_cancel=should_cancel,
                    progress=progress,
                ),
            )
            progress(f"Catálogo {kind.value.upper()}: {len(channels)} itens recebidos")
        if should_cancel():
            return None
        return self._database.replace_catalog(playlist_id, kind.value, channels)
