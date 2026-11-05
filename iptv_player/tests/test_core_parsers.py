"""Regression tests for the local, network-independent application core."""

import base64
import gzip
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.core import epg_loader
from src.core.channel import Channel
from src.core.epg import EPGSource
from src.core.epg_loader import load_xmltv
from src.parsers.m3u_parser import M3UParser
from src.parsers.stalker_parser import StalkerParser
from src.parsers.xtream_parser import XtreamParser


class ParserTests(unittest.TestCase):
    def test_infer_stream_type_uses_explicit_metadata_and_patterns(self):
        self.assertEqual(
            M3UParser.infer_stream_type("https://example.test/a", explicit_type="movie"),
            "vod",
        )
        self.assertEqual(
            M3UParser.infer_stream_type("https://example.test/a", explicit_type="series"),
            "series",
        )
        self.assertEqual(M3UParser.infer_stream_type("https://example.test/live/a.ts"), "live")
        self.assertEqual(
            M3UParser.infer_stream_type("https://example.test/a.mkv", name="Show S01E02"),
            "series",
        )
        self.assertEqual(
            M3UParser.infer_stream_type("https://example.test/a.mp4", duration=5400.0),
            "vod",
        )
        self.assertEqual(
            M3UParser.infer_stream_type("https://example.test/a.ts", group="VOD | Filmes"),
            "vod",
        )

    def test_m3u_headers_are_parsed(self):
        content = """#EXTM3U x-tvg-url="https://epg.test/guide.xml.gz"
#EXTINF:-1 tvg-id="one" user-agent="UA" referer="https://ref.test/",Canal HD
#EXTVLCOPT:http-cookie=session=test
https://example.test/live.m3u8
"""
        playlist = M3UParser()._parse_content(content, "Test")
        channel = playlist.channels[0]

        self.assertEqual(channel.user_agent, "UA")
        self.assertEqual(channel.referer, "https://ref.test/")
        self.assertEqual(channel.custom_headers, {"Cookie": "session=test"})
        self.assertEqual(channel.quality, "HD")
        self.assertEqual(channel.epg_channel_id, "one")
        self.assertEqual(playlist.epg_url, "https://epg.test/guide.xml.gz")

    def test_m3u_parses_extgrp_and_keeps_channel_number_out_of_epg_id(self):
        content = """#EXTM3U
#EXTINF:-1 tvg-id="one" tvg-chno="12",Canal
#EXTGRP:Desporto
https://example.test/live.m3u8
"""
        channel = M3UParser()._parse_content(content, "Test").channels[0]

        self.assertEqual(channel.group, "Desporto")
        self.assertEqual(channel.epg_channel_id, "one")
        self.assertEqual(channel.channel_number, 12)

    def test_m3u_parse_can_be_cancelled(self):
        from src.core.http_client import RequestCancelled

        parser = M3UParser(should_cancel=lambda: True)
        with self.assertRaises(RequestCancelled):
            parser._parse_content(
                "#EXTM3U\n#EXTINF:-1,Canal\nhttps://example.test/live.m3u8\n",
                "Test",
            )

    def test_gzipped_m3u_playlist_is_decoded(self):
        import gzip as _gzip
        import tempfile as _tempfile
        from pathlib import Path as _Path

        content = (
            b"#EXTM3U\n#EXTINF:-1,Canal\nhttps://example.test/live.m3u8\n"
        )
        with _tempfile.TemporaryDirectory() as directory:
            path = _Path(directory) / "list.m3u.gz"
            path.write_bytes(_gzip.compress(content))

            playlist = M3UParser().parse(str(path), "Test")

        self.assertEqual([channel.name for channel in playlist.channels], ["Canal"])

    def test_xtream_episodes_tolerate_malformed_payload(self):
        parser = XtreamParser("https://example.test", "user", "secret")
        parser.get_series_info = lambda _series_id: {
            "episodes": {
                "not-a-season": [
                    {"id": "1", "title": "Ep 1", "info": None},
                    "not-a-dict",
                ],
                "2": [{"id": "2", "title": "Ep 2", "episode_num": "abc"}],
            }
        }

        episodes = parser.get_episodes_for_series("42")

        self.assertEqual([episode.name for episode in episodes], ["Ep 1", "Ep 2"])
        self.assertEqual(episodes[0].season_number, 0)
        self.assertEqual(episodes[1].season_number, 2)
        self.assertEqual(episodes[1].episode_number, 0)

    def test_m3u_separates_live_vod_and_series(self):
        content = """#EXTM3U
#EXTINF:-1 group-title="Portugal",Canal Live
https://provider.test/live/user/pass/1.ts
#EXTINF:-1 group-title="VOD | Filmes",Filme
https://provider.test/movie/user/pass/2.mp4
#EXTINF:-1 group-title="Séries | Drama",Programa S01E02
https://provider.test/series/user/pass/3.mkv
#EXTINF:-1 type="movie" group-title="Arquivo",Filme explícito
https://cdn.test/watch?id=4
#EXTINF:-1 group-title="Sky Cinema",Canal de cinema ao vivo
https://cdn.test/channel/5.m3u8
"""
        playlist = M3UParser()._parse_content(content, "Mixed")

        self.assertEqual(
            [channel.stream_type for channel in playlist.channels],
            ["live", "vod", "series", "vod", "live"],
        )

    def test_xtream_uses_movie_path_and_container_extensions(self):
        parser = XtreamParser("https://example.test", "user", "password")

        movie_url = parser._build_stream_url("42", "movie", "mkv")
        episode_url = parser._build_stream_url("7", "series", ".mp4")

        self.assertEqual(movie_url, "https://example.test/movie/user/password/42.mkv")
        self.assertEqual(episode_url, "https://example.test/series/user/password/7.mp4")

    def test_xtream_epg_is_decoded_and_normalized(self):
        parser = XtreamParser("https://example.test", "user", "password")
        parser.get_epg = lambda *_args, **_kwargs: [
            {
                "title": base64.b64encode("Notícias".encode()).decode(),
                "description": base64.b64encode(b"Resumo").decode(),
                "start_timestamp": "1784894400",
                "stop_timestamp": "1784898000",
            }
        ]

        programs = parser.get_epg_programs("42", channel_id="channel.one")

        self.assertEqual(programs[0].channel_id, "channel.one")
        self.assertEqual(programs[0].title, "Notícias")
        self.assertEqual(programs[0].description, "Resumo")

    def test_stalker_epg_is_normalized(self):
        parser = StalkerParser(
            "https://example.test", "00:00:00:00:00:00"
        )
        parser.get_epg = lambda **_kwargs: [
            {
                "ch_id": "17",
                "name": "Notícias",
                "descr": "Resumo",
                "start_timestamp": "1784894400",
                "stop_timestamp": "1784898000",
            }
        ]

        programs = parser.get_epg_programs("17")

        self.assertEqual(programs[0].channel_id, "17")
        self.assertEqual(programs[0].title, "Notícias")
        self.assertEqual(programs[0].description, "Resumo")

    def test_stalker_live_channels_include_required_mag_headers(self):
        parser = StalkerParser(
            "https://example.test/c/", "00:00:00:00:00:00"
        )
        parser.get_genres = lambda: {"29": "┃UK┃ GENERAL"}
        parser._paginated_fetch = lambda *_args, **_kwargs: [
            {
                "id": "1",
                "name": "Canal",
                "cmd": "ffmpeg https://stream.example.test/live.ts",
                "tv_genre_id": "29",
            }
        ]

        channel = parser._try_get_channels("get_all_channels")[0]

        self.assertIn("MAG425", channel.user_agent)
        self.assertEqual(channel.referer, "https://example.test/c/")
        self.assertEqual(channel.country_code, "UK")
        self.assertEqual(channel.group, "┃UK┃ GENERAL")

    def test_stalker_uses_canonical_mac_cookie_for_handshake(self):
        parser = StalkerParser(
            "https://example.test/c/", "00-1a-79-76-32-1e"
        )

        class Response:
            status_code = 200
            text = '{"js":{"token":"test-token"}}'

            @staticmethod
            def raise_for_status():
                return None

        parser._session.get = lambda *_args, **_kwargs: Response()
        parser._post = lambda _data: Response()

        parser.authenticate()

        self.assertEqual(
            parser._session.cookies.get("mac"),
            "00:1A:79:76:32:1E",
        )

    def test_stalker_resolves_temporary_live_link(self):
        parser = StalkerParser(
            "https://example.test/c/", "00:1A:79:76:32:1E"
        )
        parser._token = "test-token"
        captured = {}

        class Response:
            text = (
                '{"js":{"cmd":"ffmpeg '
                'https:\\/\\/stream.example.test\\/live\\/1?play_token=abc"}}'
            )

        def post(data):
            captured.update(data)
            return Response()

        parser._post = post

        url = parser.resolve_live_link("http://localhost/ch/1_")

        self.assertEqual(
            url, "https://stream.example.test/live/1?play_token=abc"
        )
        self.assertEqual(captured["type"], "itv")
        self.assertEqual(captured["action"], "create_link")
        self.assertEqual(captured["cmd"], "http://localhost/ch/1_")

    def test_stalker_preserves_unescaped_urls_in_json(self):
        parser = StalkerParser(
            "https://example.test", "00:00:00:00:00:00"
        )

        class Response:
            text = '{"js":{"cmd":"ffmpeg http://stream.example/live/1"}}'

        result = parser._parse_response(Response())

        self.assertEqual(
            result["js"]["cmd"], "ffmpeg http://stream.example/live/1"
        )

    def test_stalker_catalogues_can_be_included_explicitly(self):
        parser = StalkerParser(
            "https://example.test", "00:00:00:00:00:00"
        )
        parser._token = "test-token"
        parser.get_channels = lambda **_kwargs: [Channel("Live", "https://live.test")]
        parser.get_vod_movies = lambda **_kwargs: [
            Channel("Movie", "opaque", stream_type="vod", source="stalker")
        ]
        parser.get_series_shows = lambda **_kwargs: [
            Channel("Show", "", stream_type="series", source="stalker")
        ]

        playlist = parser.get_full_playlist(include_vod=True, include_series=True)

        self.assertEqual(
            [channel.stream_type for channel in playlist.channels],
            ["live", "vod", "series"],
        )

    def test_remote_m3u_download_has_a_size_limit(self):
        class Response:
            headers = {}
            encoding = "utf-8"

            def __enter__(self):
                return self

            def __exit__(self, *_exc_info):
                return False

            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def iter_content(chunk_size):
                del chunk_size
                yield b"#EXTM3U\n"
                yield b"x" * 20

        parser = M3UParser()
        parser.MAX_DOWNLOAD_BYTES = 10
        with patch("src.parsers.m3u_parser.requests.get", return_value=Response()):
            with self.assertRaisesRegex(ValueError, "limite"):
                parser.parse("https://example.test/list.m3u")

    def test_stalker_initial_playlist_does_not_fetch_large_catalogues(self):
        parser = StalkerParser(
            "https://example.test", "00:00:00:00:00:00"
        )
        parser._token = "test-token"
        parser.get_channels = lambda **_kwargs: [
            Channel("Canal", "https://stream.example.test/live.ts")
        ]
        parser.get_vod_movies = lambda: self.fail("VOD should be lazy")
        parser.get_series_shows = lambda: self.fail("Series should be lazy")

        playlist = parser.get_full_playlist()

        self.assertEqual(len(playlist.channels), 1)

    def test_stalker_reauthenticates_when_create_link_token_expired(self):
        parser = StalkerParser("https://example.test", "00:00:00:00:00:00")
        parser._token = "expired-token"
        payloads = [
            {},  # expired token -> portal answers without a cmd
            {"js": {"cmd": "ffmpeg https://stream.example.test/vod/9.mp4"}},
        ]
        auth_calls = []
        parser._post = lambda _data: object()
        parser._parse_response = lambda _response: payloads.pop(0)
        parser.authenticate = lambda: auth_calls.append(1) or True

        url = parser.resolve_link("opaque-cmd")

        self.assertEqual(url, "https://stream.example.test/vod/9.mp4")
        self.assertEqual(len(auth_calls), 1)

    def test_stalker_create_link_skips_reauthentication_when_successful(self):
        parser = StalkerParser("https://example.test", "00:00:00:00:00:00")
        parser._token = "valid-token"
        parser._post = lambda _data: object()
        parser._parse_response = lambda _response: {
            "js": {"cmd": "ffmpeg https://stream.example.test/vod/10.mp4"}
        }
        parser.authenticate = self.fail

        url = parser.resolve_link("opaque-cmd")

        self.assertEqual(url, "https://stream.example.test/vod/10.mp4")

    def test_stalker_catchup_accepts_start_and_duration(self):
        parser = StalkerParser("https://example.test", "00:00:00:00:00:00")
        parser._token = "valid-token"
        sent = {}
        parser._post = lambda data: sent.update(data) or object()
        parser._parse_response = lambda _response: {
            "js": {"cmd": "ffmpeg https://stream.example.test/archive/1.ts"}
        }

        url = parser.resolve_catchup_link("localhost/ch/1", 1784894400, 3600)

        self.assertEqual(url, "https://stream.example.test/archive/1.ts")
        self.assertEqual(sent["archive"], "1")
        self.assertEqual(sent["start"], "1784894400")
        self.assertEqual(sent["end"], "1784898000")

    def test_stalker_playback_headers_can_be_built_without_authenticating(self):
        headers = StalkerParser.playback_headers_for("https://portal.test/c/")

        self.assertIn("MAG425", headers["User-Agent"])
        self.assertEqual(headers["Referer"], "https://portal.test/c/")

    def test_xtream_playlist_counts_reflect_real_channels(self):
        parser = XtreamParser("https://example.test", "user", "password")
        parser._info = {"user_info": {"auth": 1, "max_connections": "2"}}
        parser.get_live_channels = lambda: [Channel("Live", "https://live.test")]
        parser.get_vod_streams = lambda: [
            Channel("Movie", "https://vod.test", stream_type="vod")
        ]
        parser.get_series_channels = lambda *_args, **_kwargs: [
            Channel("Show", "", stream_type="series")
        ]

        playlist = parser.get_full_playlist()

        # max_connections is a concurrency limit, not a channel count: the
        # previous code reported "2" for a playlist holding 3 channels.
        self.assertEqual(playlist.total_channels, 3)
        self.assertEqual(playlist.total_vod, 1)
        self.assertEqual(playlist.total_series, 1)

    def test_xtream_session_leaves_retrying_to_the_api_request_layer(self):
        parser = XtreamParser("https://example.test", "user", "password")
        adapter = parser._session.get_adapter("https://example.test")
        try:
            self.assertEqual(adapter.max_retries.total, 0)
        finally:
            parser.close()


class ContentTypesTests(unittest.TestCase):
    def test_tab_index_maps_to_a_content_type(self):
        from src.core.content_types import content_type_for_tab

        self.assertEqual(content_type_for_tab(0), "live")
        self.assertEqual(content_type_for_tab(1), "vod")
        self.assertEqual(content_type_for_tab(2), "series")
        self.assertEqual(content_type_for_tab(9, default=""), "")

    def test_stream_types_normalise_the_movie_alias(self):
        from src.core.content_types import content_type_for_stream

        self.assertEqual(content_type_for_stream("live"), "live")
        self.assertEqual(content_type_for_stream("vod"), "vod")
        self.assertEqual(content_type_for_stream("movie"), "vod")
        self.assertEqual(content_type_for_stream("series"), "series")
        self.assertEqual(content_type_for_stream("outro"), "")


class CatalogMixinHelperTests(unittest.TestCase):
    def _window(self):
        from src.ui.catalog_mixin import CatalogMixin

        class Window(CatalogMixin):
            pass

        return Window()

    def test_playlist_channel_cache_is_bounded_and_keeps_the_newest(self):
        from src.ui.catalog_mixin import CatalogMixin

        window = self._window()
        limit = CatalogMixin._PLAYLIST_CACHE_LIMIT
        for playlist_id in range(limit + 3):
            window._cache_playlist_channels(playlist_id, {"live": []})

        self.assertEqual(len(window._playlist_channel_cache), limit)
        self.assertNotIn(0, window._playlist_channel_cache)
        self.assertIn(limit + 2, window._playlist_channel_cache)

    def test_epg_load_key_distinguishes_channels_without_a_row_id(self):
        from src.ui.catalog_mixin import CatalogMixin

        first = CatalogMixin._epg_load_key(
            1, Channel("Canal A", "", database_id=0, tvg_id="a")
        )
        second = CatalogMixin._epg_load_key(
            1, Channel("Canal B", "", database_id=0, tvg_id="b")
        )

        self.assertNotEqual(first, second)

    def test_epg_load_key_prefers_the_database_row(self):
        from src.ui.catalog_mixin import CatalogMixin

        key = CatalogMixin._epg_load_key(
            7, Channel("Canal", "", database_id=42, tvg_id="a")
        )

        self.assertEqual(key, (7, 42))


class EPGTests(unittest.TestCase):
    def test_gzipped_local_xmltv_is_loaded(self):
        xml = (
            b'<tv><programme channel="c" start="20260724120000 +0000" '
            b'stop="20260724130000 +0000"><title>Programa</title>'
            b"</programme></tv>"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "guide.xml.gz"
            path.write_bytes(gzip.compress(xml))

            source = load_xmltv(str(path))

        self.assertEqual(source.get_programs("c")[0].title, "Programa")

    def test_timezone_aware_xmltv_can_be_compared(self):
        source = EPGSource.parse_xmltv(
            """<tv><programme channel="c"
            start="20260724120000 +0000" stop="20260724130000 +0000">
            <title>Programa</title></programme></tv>"""
        )
        program = source.get_programs("c")[0]

        self.assertIsNotNone(program.start.tzinfo)
        self.assertIsInstance(program.is_live, bool)
        self.assertIsInstance(source.get_next_program("c"), (type(None), type(program)))

    def test_plain_xmltv_timestamp_is_supported(self):
        source = EPGSource.parse_xmltv(
            """<tv><programme channel="c"
            start="20260724120000" stop="20260724130000">
            <title>Programa</title></programme></tv>"""
        )
        self.assertEqual(
            source.get_programs("c")[0].start,
            datetime(2026, 7, 24, 12, 0, 0),
        )

    def test_gzip_expansion_has_a_size_limit(self):
        original_limit = epg_loader.MAX_XML_BYTES
        try:
            epg_loader.MAX_XML_BYTES = 32
            with tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "large.xml.gz"
                path.write_bytes(gzip.compress(b"<tv>" + b" " * 64 + b"</tv>"))
                with self.assertRaisesRegex(ValueError, "limite"):
                    load_xmltv(str(path))
        finally:
            epg_loader.MAX_XML_BYTES = original_limit
