"""Xtream Codes parser: URL building, retries, auth, channels and EPG times."""

import base64
from datetime import datetime, timezone

import pytest
import requests
from fakes import FakeResponse, FakeSession

from src.parsers import xtream_parser
from src.parsers.xtream_parser import XtreamParser


def _parser(server="portal.test", user="user", password="secret"):
    parser = XtreamParser(server, user, password)
    parser._session = FakeSession()
    return parser


class TestUrlHandling:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("portal.test", "https://portal.test"),
            ("portal.test/", "https://portal.test"),
            ("http://portal.test/", "http://portal.test"),
            ("  http://portal.test:8080/  ", "http://portal.test:8080"),
        ],
    )
    def test_server_url_is_normalized(self, raw, expected):
        assert XtreamParser._normalize_url(raw) == expected

    @pytest.mark.parametrize(
        ("server_info", "expected"),
        [
            ({"url": "cdn.test", "port": "8080"}, "http://cdn.test:8080"),
            (
                {"url": "cdn.test", "port": "80", "https_port": "443", "server_protocol": "https"},
                "https://cdn.test:443",
            ),
            ({"url": "cdn.test"}, "http://cdn.test"),
            ({}, ""),
            ({"url": ""}, ""),
        ],
    )
    def test_stream_base_url_is_rebuilt(self, server_info, expected):
        assert XtreamParser._build_dns(server_info) == expected

    def test_errors_never_leak_credentials(self):
        parser = _parser()
        error = requests.ConnectionError("failed for user/secret at http://portal.test")

        message = parser._safe_request_error(error)

        assert "user" not in message.replace("user/", "")
        assert "secret" not in message
        assert "***" in message

    def test_stream_urls_use_the_resolved_base(self):
        parser = _parser()
        parser._dns = "http://cdn.test:8080"

        assert parser._build_stream_url("42", "live") == (
            "http://cdn.test:8080/live/user/secret/42.ts"
        )
        assert parser._build_stream_url("42", "movie", ".mkv") == (
            "http://cdn.test:8080/movie/user/secret/42.mkv"
        )

    def test_timeshift_url_format(self):
        parser = _parser()
        parser._dns = "http://cdn.test"

        url = parser.build_timeshift_url(
            "42", datetime(2024, 5, 1, 20, 30, tzinfo=timezone.utc), 60
        )

        assert url == "http://cdn.test/timeshift/user/secret/60/2024-05-01:20-30/42.ts"


class TestApiRequests:
    def _patch_sleep(self, monkeypatch):
        monkeypatch.setattr(xtream_parser.time, "sleep", lambda *_: None)

    def test_retries_transient_server_errors(self, monkeypatch):
        self._patch_sleep(monkeypatch)
        parser = _parser()
        parser._session.queue(
            FakeResponse({}, status_code=520),
            FakeResponse({"ok": True}),
        )

        assert parser._api_request("get_live_categories") == {"ok": True}
        assert len(parser._session.get_calls) == 2

    def test_gives_up_after_max_retries(self, monkeypatch):
        self._patch_sleep(monkeypatch)
        parser = _parser()
        parser._session.queue(*[FakeResponse({}, status_code=503) for _ in range(3)])

        with pytest.raises(ConnectionError, match="erro 503"):
            parser._api_request("get_live_categories", max_retries=3)

    def test_invalid_json_raises_value_error(self, monkeypatch):
        self._patch_sleep(monkeypatch)
        parser = _parser()
        parser._session.queue(FakeResponse({}, invalid_json=True))

        with pytest.raises(ValueError, match="Invalid JSON"):
            parser._api_request("get_live_categories", max_retries=1)

    def test_credentials_are_never_sent_in_the_error(self, monkeypatch):
        self._patch_sleep(monkeypatch)
        parser = _parser()
        parser._session.queue(requests.ConnectionError("boom for user/secret"))

        with pytest.raises(ConnectionError) as excinfo:
            parser._api_request("get_live_categories", max_retries=1)

        assert "secret" not in str(excinfo.value)


class TestAuthentication:
    def test_successful_auth_builds_the_stream_base(self):
        parser = _parser()
        parser._session.queue(
            FakeResponse(
                {
                    "user_info": {"auth": 1, "username": "user"},
                    "server_info": {"url": "cdn.test", "port": "8080"},
                }
            )
        )

        assert parser.authenticate() is True
        assert parser._dns == "http://cdn.test:8080"
        assert parser._info["user_info"]["auth"] == 1

    def test_rejected_credentials_raise_permission_error(self):
        parser = _parser()
        parser._session.queue(FakeResponse({"user_info": {"auth": 0}}))

        with pytest.raises(PermissionError, match="authentication failed"):
            parser.authenticate()


class TestChannels:
    def test_live_channels_are_mapped_with_category_fallback(self):
        parser = _parser()
        parser._dns = "http://cdn.test"
        parser._session.queue(
            FakeResponse(
                [
                    {
                        "stream_id": 42,
                        "name": "Canal Um",
                        "category_id": "7",
                        "stream_icon": "http://logo/1.png",
                        "epg_channel_id": "one",
                        "tv_archive": 1,
                        "tv_archive_duration": 3,
                    }
                ]
            ),
            FakeResponse([{"category_id": "7", "category_name": "Desporto"}]),
        )

        channels = parser.get_live_channels()

        assert len(channels) == 1
        channel = channels[0]
        assert channel.name == "Canal Um"
        assert channel.group == "Desporto"
        assert channel.xtream_id == "42"
        assert channel.url == "http://cdn.test/live/user/secret/42.ts"
        assert channel.has_archive is True
        assert channel.archive_duration_days == 3
        assert channel.source == "xtream"

    def test_non_list_payload_yields_no_channels(self):
        parser = _parser()
        parser._session.queue(FakeResponse({"unexpected": True}), FakeResponse([]))

        assert parser.get_live_channels() == []

    def test_episodes_are_built_with_season_and_number(self):
        parser = _parser()
        parser._dns = "http://cdn.test"
        parser._session.queue(
            FakeResponse(
                {
                    "episodes": {
                        "1": [
                            {
                                "id": "100",
                                "title": "Episódio 1",
                                "episode_num": 1,
                                "container_extension": "mkv",
                                "info": {"movie_image": "http://img/1.jpg"},
                            }
                        ],
                        "especial": [
                            {"id": "101", "title": "Extra", "episode_num": "x"},
                            "ignorado",
                        ],
                    }
                }
            )
        )

        episodes = parser.get_episodes_for_series("5")

        assert [ep.name for ep in episodes] == ["Episódio 1", "Extra"]
        first, extra = episodes
        assert first.group == "Series - S01"
        assert first.season_number == 1
        assert first.episode_number == 1
        assert first.logo == "http://img/1.jpg"
        assert first.url == "http://cdn.test/series/user/secret/100.mkv"
        assert extra.group == "Series - S00"
        assert extra.episode_number == 0

    def test_series_channels_respect_cancellation_and_progress(self):
        parser = _parser()
        parser._session.queue(
            FakeResponse(
                [
                    {"category_id": "1", "category_name": "Drama"},
                    {"category_id": "2", "category_name": "Comédia"},
                ]
            ),
            FakeResponse([{"series_id": 10, "name": "Série A", "cover": "http://c/1.jpg"}]),
        )
        checks = {"count": 0}
        progress = []

        def should_cancel():
            checks["count"] += 1
            return checks["count"] > 1

        channels = parser.get_series_channels(
            should_cancel=should_cancel, progress=progress.append
        )

        assert [item.name for item in channels] == ["Série A"]
        assert channels[0].group == "Drama"
        assert channels[0].url == ""
        assert progress == ["Séries: categoria 1/2"]


class TestEpgParsing:
    def test_base64_text_is_decoded(self):
        encoded = base64.b64encode(b"Sinopse codificada").decode("ascii")

        assert XtreamParser._decode_epg_text(encoded) == "Sinopse codificada"

    @pytest.mark.parametrize("value", ["texto simples", "", None])
    def test_plain_text_is_preserved(self, value):
        assert XtreamParser._decode_epg_text(value) == (value or "")

    def test_epoch_milliseconds(self):
        parsed = XtreamParser._parse_epg_datetime(1_700_000_000_000, "")

        assert parsed == datetime.fromtimestamp(1_700_000_000, timezone.utc).astimezone()

    def test_iso_text(self):
        parsed = XtreamParser._parse_epg_datetime(None, "2024-05-01T20:30:00+00:00")

        assert parsed.year == 2024 and parsed.tzinfo is not None

    def test_compact_timestamp_is_not_read_as_epoch(self):
        parsed = XtreamParser._parse_epg_datetime("20240501203000", "")

        assert parsed is not None
        assert parsed.year == 2024
        assert parsed.month == 5

    def test_unparseable_values_return_none(self):
        assert XtreamParser._parse_epg_datetime(None, "") is None
        assert XtreamParser._parse_epg_datetime("lixo", "lixo") is None
