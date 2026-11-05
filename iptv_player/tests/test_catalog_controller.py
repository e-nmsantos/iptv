"""Catalogue refresh orchestration (M3U parsing + provider delegation)."""

import pytest

from src.controllers.catalog_controller import CatalogController
from src.core.channel import Channel


class FakeDatabase:
    def __init__(self, playlist):
        self.playlist = playlist
        self.replaced = []

    def get_playlist(self, playlist_id):
        return self.playlist

    def replace_catalog(self, playlist_id, content_type, channels):
        self.replaced.append((playlist_id, content_type, channels))
        return playlist_id, channels


class FakeSettings:
    def get(self, key, default=None):
        return default


class FakeProvider:
    def __init__(self, channels):
        self.channels = channels
        self.calls = []

    def load_catalog(self, kind, should_cancel=None, progress=None):
        self.calls.append(kind)
        if progress:
            progress("a carregar")
        return self.channels


class FakeSessions:
    def __init__(self, provider):
        self.provider = provider

    def call_provider(self, playlist_id, callback):
        return callback(self.provider)


def _controller(playlist, provider=None):
    database = FakeDatabase(playlist)
    sessions = FakeSessions(provider or FakeProvider([]))
    return CatalogController(database, sessions, FakeSettings()), database, sessions


class TestValidation:
    def test_unknown_playlist_raises(self):
        controller, _, _ = _controller(None)

        with pytest.raises(LookupError, match="Playlist não encontrada"):
            controller.refresh(1, "live")

    def test_m3u_without_source_raises(self):
        controller, _, _ = _controller(
            {"id": 1, "name": "Sem origem", "source_type": "m3u"}
        )

        with pytest.raises(ValueError, match="não tem uma origem"):
            controller.refresh(1, "live")


class TestM3uRefresh:
    def test_filters_by_content_type_and_persists(self, tmp_path):
        playlist_file = tmp_path / "lista.m3u"
        playlist_file.write_text(
            "#EXTM3U\n"
            '#EXTINF:-1 group-title="Notícias",Canal\n'
            "https://example.test/live/1.ts\n"
            '#EXTINF:-1 group-title="Filmes",Filme\n'
            "https://example.test/movie/2.mp4\n",
            encoding="utf-8",
        )
        controller, database, _ = _controller(
            {
                "id": 7,
                "name": "Lista",
                "source_type": "m3u",
                "file_path": str(playlist_file),
            }
        )

        result = controller.refresh(7, "live")

        playlist_id, content_type, channels = database.replaced[0]
        assert (playlist_id, content_type) == (7, "live")
        assert [channel.name for channel in channels] == ["Canal"]
        assert result == (7, channels)

    def test_vod_bucket_accepts_the_movie_alias(self, tmp_path):
        playlist_file = tmp_path / "lista.m3u"
        playlist_file.write_text(
            "#EXTM3U\n"
            '#EXTINF:-1 group-title="Filmes",Filme\n'
            "https://example.test/movie/2.mp4\n",
            encoding="utf-8",
        )
        controller, database, _ = _controller(
            {
                "id": 8,
                "name": "Lista",
                "source_type": "m3u",
                "file_path": str(playlist_file),
            }
        )

        controller.refresh(8, "vod")

        assert database.replaced[0][1] == "vod"
        assert database.replaced[0][2][0].stream_type in ("vod", "movie")


class TestProviderRefresh:
    def test_provider_channels_are_persisted_with_progress(self):
        channels = [Channel(name="Canal", url="http://h/1.ts", stream_type="live")]
        provider = FakeProvider(channels)
        controller, database, _ = _controller(
            {"id": 3, "name": "Xtream", "source_type": "xtream"}, provider
        )
        messages = []

        result = controller.refresh(3, "live", progress=messages.append)

        assert provider.calls and provider.calls[0].value == "live"
        assert database.replaced == [(3, "live", channels)]
        assert result == (3, channels)
        assert "a carregar" in messages
        assert "Catálogo LIVE: 1 itens recebidos" in messages

    def test_cancellation_before_persisting_returns_none(self):
        channels = [Channel(name="Canal", url="http://h/1.ts", stream_type="live")]
        controller, database, _ = _controller(
            {"id": 3, "name": "Xtream", "source_type": "xtream"},
            FakeProvider(channels),
        )

        result = controller.refresh(3, "live", should_cancel=lambda: True)

        assert result is None
        assert database.replaced == []
