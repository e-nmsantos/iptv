"""Stalker portal parser: URL/MAC normalization, auth, channels and EPG times."""

from datetime import datetime, timezone

import pytest
import requests
from fakes import FakeResponse, FakeSession

from src.parsers.stalker_parser import StalkerParser

MAC = "00:1A:79:AA:BB:CC"


def _parser(portal="http://portal.test/c/"):
    parser = StalkerParser(portal, MAC)
    parser._session = FakeSession()
    parser._token = "tok"
    return parser


class TestNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("portal.test", "http://portal.test"),
            ("http://portal.test/", "http://portal.test"),
            ("http://portal.test:8080/c/", "http://portal.test:8080"),
            ("https://portal.test/stalker_portal/c/", "https://portal.test/stalker_portal"),
            ("https://portal.test/portal.php", "https://portal.test"),
            ("https://portal.test/server/load.php", "https://portal.test"),
            ("https://portal.test/index.html", "https://portal.test"),
        ],
    )
    def test_portal_url_is_reduced_to_the_host(self, raw, expected):
        assert StalkerParser._normalize_url(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("00:1a:79:aa:bb:cc", MAC),
            ("001a79aabbcc", MAC),
            ("00-1A-79-AA-BB-CC", MAC),
        ],
    )
    def test_mac_is_canonicalized(self, raw, expected):
        assert StalkerParser._normalize_mac(raw) == expected

    @pytest.mark.parametrize("raw", ["", "00:11:22", "not-a-mac"])
    def test_invalid_mac_is_rejected(self, raw):
        with pytest.raises(ValueError, match="MAC inválido"):
            StalkerParser._normalize_mac(raw)

    def test_playback_headers_point_at_the_player_path(self):
        headers = StalkerParser.playback_headers_for("http://portal.test")

        assert headers["Referer"] == "http://portal.test/c/"
        assert "MAG425" in headers["User-Agent"]

    def test_playback_headers_keep_an_existing_c_path(self):
        headers = StalkerParser.playback_headers_for("http://portal.test/c/")

        assert headers["Referer"] == "http://portal.test/c/"


class TestResponseParsing:
    def test_plain_json(self):
        parser = _parser()

        assert parser._parse_response(FakeResponse({"js": {"a": 1}})) == {"js": {"a": 1}}

    def test_comment_and_jsonp_wrapped_json(self):
        parser = _parser()
        wrapped = '/* "eyJ0b2tlbiI6MX0=" */ {"js": {"token": "abc"}}'

        assert parser._parse_response(FakeResponse(text=wrapped)) == {"js": {"token": "abc"}}

    def test_invalid_payload_returns_empty_dict(self):
        parser = _parser()

        assert parser._parse_response(FakeResponse(text="not json at all")) == {}


class TestAuthentication:
    def test_successful_handshake_stores_token_and_profile(self):
        parser = _parser()
        parser._token = ""
        parser._session.queue(
            FakeResponse(text="<html></html>"),
            FakeResponse({"token": "handshake-token"}),
            FakeResponse({"js": {"name": "perfil", "phone": "123"}}),
        )

        assert parser.authenticate() is True
        assert parser._token == "handshake-token"
        assert parser._profile["name"] == "perfil"
        assert parser._session.cookies.values["mac"] == MAC
        assert len(parser._session.post_calls) == 2

    def test_missing_token_raises_with_provider_reason(self):
        parser = _parser()
        parser._token = ""
        parser._session.queue(
            FakeResponse(text="<html></html>"),
            FakeResponse({"msg": "MAC não autorizado"}),
        )

        with pytest.raises(ConnectionError, match="MAC não autorizado"):
            parser.authenticate()

    def test_portal_unreachable_raises_connection_error(self):
        parser = _parser()
        parser._token = ""
        parser._session.queue(requests.ConnectionError("sem rota"))

        with pytest.raises(ConnectionError, match="Falha ao aceder ao portal"):
            parser.authenticate()


class TestChannelFetching:
    def test_channels_are_mapped_from_the_portal_payload(self):
        parser = _parser()
        parser._session.queue(
            FakeResponse(
                {
                    "js": {
                        "total_items": "1",
                        "data": [
                            {
                                "id": "42",
                                "name": "Canal Um",
                                "tv_genre_id": "5",
                                "logo": "http://logo/1.png",
                            }
                        ],
                    }
                }
            ),
            FakeResponse({"js": [{"id": "5", "title": "┃PT┃ Desporto"}]}),
        )

        channels = parser._try_get_channels("get_all_channels")

        assert len(channels) == 1
        channel = channels[0]
        assert channel.name == "Canal Um"
        assert channel.group == "┃PT┃ Desporto"
        assert channel.provider_group == "┃PT┃ Desporto"
        assert channel.country_code == "PT"
        assert channel.stream_type == "live"
        assert channel.source == "stalker"
        assert channel.url == "http://portal.test/ch/001a79aabbcc/stream/42"
        assert channel.referer == "http://portal.test/c/"

    def test_get_channels_falls_back_to_the_next_strategy(self):
        parser = _parser()
        seen = []

        def fake_try(action):
            seen.append(action)
            return [] if action == "get_all_channels" else ["canal"]

        parser._try_get_channels = fake_try

        assert parser.get_channels() == ["canal"]
        assert seen == ["get_all_channels", "itv"]

    def test_get_channels_tries_every_strategy_before_giving_up(self):
        parser = _parser()
        parser._try_get_channels = lambda action: []
        parser._try_genre_channels = lambda: []
        parser._try_m3u_fallback = lambda: []

        assert parser.get_channels() == []


class TestStreamUrls:
    def test_player_command_prefix_is_stripped(self):
        parser = _parser()

        url = parser._build_stream_url({"cmd": "ffmpeg http://cdn.test/play/live.php?x=1"})

        assert url == "http://cdn.test/play/live.php?x=1"

    def test_bare_command_becomes_a_portal_stream_path(self):
        parser = _parser()

        url = parser._build_stream_url({"cmd": "1234"})

        assert url == "http://portal.test/ch/001a79aabbcc/stream/1234"

    def test_missing_command_falls_back_to_the_channel_id(self):
        parser = _parser()

        url = parser._build_stream_url({"id": "77"})

        assert url == "http://portal.test/ch/001a79aabbcc/stream/77"

    @pytest.mark.parametrize(
        ("cmd", "expected"),
        [
            ("ffmpeg http://h/a.ts", "http://h/a.ts"),
            ("udp://@239.0.0.1:1234 extra", "udp://@239.0.0.1:1234"),
            ("rtsp://h/live", "rtsp://h/live"),
            ("1234", ""),
            ("", ""),
        ],
    )
    def test_extract_url_from_cmd(self, cmd, expected):
        assert StalkerParser._extract_url_from_cmd(cmd) == expected


class TestEpgDatetime:
    def test_epoch_seconds(self):
        parsed = StalkerParser._parse_epg_datetime(1_700_000_000)

        assert parsed.tzinfo is not None
        assert parsed == datetime.fromtimestamp(1_700_000_000, timezone.utc).astimezone()

    def test_epoch_milliseconds(self):
        assert StalkerParser._parse_epg_datetime(1_700_000_000_000) == (
            datetime.fromtimestamp(1_700_000_000, timezone.utc).astimezone()
        )

    def test_iso_string(self):
        parsed = StalkerParser._parse_epg_datetime("2023-11-14T22:13:20+00:00")

        assert parsed.year == 2023 and parsed.tzinfo is not None

    def test_plain_and_compact_formats(self):
        assert StalkerParser._parse_epg_datetime("2023-11-14 22:13:20").year == 2023
        assert StalkerParser._parse_epg_datetime("20231114221320").year == 2023

    @pytest.mark.parametrize("value", [None, "", "not-a-date", object()])
    def test_invalid_values_return_none(self, value):
        assert StalkerParser._parse_epg_datetime(value) is None
