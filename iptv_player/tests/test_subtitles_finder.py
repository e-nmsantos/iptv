"""Subtitles: VLSub token flow, CDN download, decoding and cache writes."""

import base64
import gzip

import pytest
import requests

from src.core import subtitles_finder
from src.core.subtitles_finder import SubtitleResult, SubtitlesFinder


@pytest.fixture
def finder(tmp_path):
    return SubtitlesFinder(cache_dir=tmp_path / "subs")


class TestSubtitleResult:
    def test_repr_shows_language_and_release(self):
        result = SubtitleResult("1", "por", "Filme.2020.1080p")

        assert repr(result) == "<SubtitleResult [por] Filme.2020.1080p>"


class TestVlsubToken:
    def test_token_is_cached_after_login(self, finder, monkeypatch):
        calls = []

        class _Proxy:
            def LogIn(self, *args):
                calls.append(args)
                return {"status": "200 OK", "token": "abc123"}

        monkeypatch.setattr(finder, "_get_vlsub_proxy", lambda: _Proxy())

        assert finder._get_vlsub_token() == "abc123"
        assert finder._get_vlsub_token() == "abc123"
        assert len(calls) == 1

    def test_failed_login_returns_none(self, finder, monkeypatch):
        class _Proxy:
            def LogIn(self, *args):
                return {"status": "401 Unauthorized"}

        monkeypatch.setattr(finder, "_get_vlsub_proxy", lambda: _Proxy())

        assert finder._get_vlsub_token() is None

    def test_login_exception_is_swallowed(self, finder, monkeypatch):
        def boom():
            raise OSError("sem rede")

        monkeypatch.setattr(finder, "_get_vlsub_proxy", boom)

        assert finder._get_vlsub_token() is None


class TestDownload:
    def test_cdn_download_is_saved_as_utf8(self, finder, monkeypatch, tmp_path):
        class _Response:
            status_code = 200
            content = "1\n00:00:01,000 --> 00:00:02,000\nOlá\n".encode()

        monkeypatch.setattr(
            subtitles_finder.requests, "get", lambda *a, **k: _Response()
        )
        result = SubtitleResult(
            "9", "por", "Filme 2020", download_url="https://cdn.test/sub.srt", source="stremio"
        )

        path = finder.download_subtitle_file(result)

        assert path is not None
        assert path.suffix == ".srt"
        assert "Olá" in path.read_text(encoding="utf-8")
        assert path.parent == finder.cache_dir

    def test_gzip_payload_is_decompressed(self, finder, monkeypatch):
        payload = gzip.compress("1\n00:00:01,000 --> 00:00:02,000\nOi\n".encode("cp1252"))

        class _Response:
            status_code = 200
            content = payload

        monkeypatch.setattr(
            subtitles_finder.requests, "get", lambda *a, **k: _Response()
        )
        result = SubtitleResult("9", "por", "Filme", download_url="https://cdn.test/s.gz", source="stremio")

        path = finder.download_subtitle_file(result)

        assert path is not None
        assert "Oi" in path.read_text(encoding="utf-8")

    def test_vlsub_payload_is_decoded(self, finder, monkeypatch):
        encoded = base64.b64encode(gzip.compress(b"texto\n")).decode("ascii")

        class _Proxy:
            def DownloadSubtitles(self, token, ids):
                return {"data": [{"data": encoded}]}

        monkeypatch.setattr(finder, "_get_vlsub_token", lambda: "tok")
        monkeypatch.setattr(finder, "_get_vlsub_proxy", lambda: _Proxy())
        result = SubtitleResult("42", "por", "Filme", source="vlsub")

        path = finder.download_subtitle_file(result)

        assert path is not None
        assert path.read_text(encoding="utf-8") == "texto\n"

    def test_http_error_returns_none(self, finder, monkeypatch):
        class _Response:
            status_code = 404
            content = b""

        monkeypatch.setattr(
            subtitles_finder.requests, "get", lambda *a, **k: _Response()
        )
        result = SubtitleResult("9", "por", "Filme", download_url="https://cdn.test/x.srt")

        assert finder.download_subtitle_file(result) is None

    def test_network_exception_returns_none(self, finder, monkeypatch):
        def boom(*args, **kwargs):
            raise requests.ConnectionError("offline")

        monkeypatch.setattr(subtitles_finder.requests, "get", boom)
        result = SubtitleResult("9", "por", "Filme", download_url="https://cdn.test/x.srt")

        assert finder.download_subtitle_file(result) is None

    def test_result_without_content_returns_none(self, finder):
        assert finder.download_subtitle_file(SubtitleResult("1", "por", "Filme")) is None

    def test_filename_is_sanitized_and_extended(self, finder):
        path = finder.save_subtitle_file("conteudo", "Filme/Bom: 2020")

        assert path.name.endswith(".srt")
        assert "/" not in path.name
        assert path.read_text(encoding="utf-8") == "conteudo"
