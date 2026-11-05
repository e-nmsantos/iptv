"""Playlist health checks: TLS policy and status mapping (no network)."""

import json
import ssl
import urllib.error

import pytest

from src.core.playlist_health import PlaylistHealthChecker, _is_certificate_error


def _xtream_playlist():
    return {
        "id": 1,
        "name": "Provider",
        "source_type": "xtream",
        "server_url": "https://provider.test:8443",
        "username": "user",
        "password": "secret",
    }


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestTlsPolicy:
    def test_certificates_are_verified_by_default(self):
        context = PlaylistHealthChecker()._ssl_context

        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True

    def test_unverified_context_requires_opt_in(self):
        context = PlaylistHealthChecker(insecure_tls=True)._ssl_context

        assert context.verify_mode == ssl.CERT_NONE

    def test_singleton_honours_the_explicit_flag(self):
        PlaylistHealthChecker._instance = None
        try:
            instance = PlaylistHealthChecker.get_instance(True)
            assert instance._ssl_context.verify_mode == ssl.CERT_NONE
        finally:
            PlaylistHealthChecker._instance = None

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (urllib.error.URLError(ssl.SSLCertVerificationError("bad cert")), True),
            (urllib.error.URLError(ssl.SSLError("handshake")), True),
            (urllib.error.URLError(TimeoutError("timed out")), False),
            (ssl.SSLError("handshake"), True),
            (ValueError("boom"), False),
        ],
    )
    def test_certificate_error_detection(self, error, expected):
        assert _is_certificate_error(error) is expected


class TestStatusMapping:
    def test_online_account_reports_server_details(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: _FakeResponse(
                {
                    "user_info": {
                        "auth": 1,
                        "status": "Active",
                        "max_connections": "2",
                        "active_cons": "1",
                    }
                }
            ),
        )

        status = PlaylistHealthChecker().check_playlist_sync(_xtream_playlist())

        assert status.status == "online"
        assert status.max_connections == "2"
        assert status.active_connections == "1"

    def test_certificate_failure_explains_the_opt_in(self, monkeypatch):
        def boom(*args, **kwargs):
            raise urllib.error.URLError(
                ssl.SSLCertVerificationError("certificate verify failed")
            )

        monkeypatch.setattr("urllib.request.urlopen", boom)

        status = PlaylistHealthChecker().check_playlist_sync(_xtream_playlist())

        assert status.status == "offline"
        assert "Certificado TLS inválido" in status.message
        assert "Definições" in status.message

    def test_network_failure_keeps_the_generic_message(self, monkeypatch):
        def boom(*args, **kwargs):
            raise urllib.error.URLError(TimeoutError("timed out"))

        monkeypatch.setattr("urllib.request.urlopen", boom)

        status = PlaylistHealthChecker().check_playlist_sync(_xtream_playlist())

        assert status.status == "offline"
        assert "Servidor inacessível" in status.message

    def test_local_file_playlist_is_reported_without_network(self, tmp_path):
        playlist_file = tmp_path / "lista.m3u"
        playlist_file.write_text("#EXTM3U\n", encoding="utf-8")

        status = PlaylistHealthChecker().check_playlist_sync(
            {
                "id": 2,
                "name": "Local",
                "source_type": "m3u",
                "file_path": str(playlist_file),
            }
        )

        assert status.status == "local"
        assert "Ficheiro local" in status.message

    def test_missing_local_file_is_offline(self, tmp_path):
        status = PlaylistHealthChecker().check_playlist_sync(
            {
                "id": 3,
                "name": "Local",
                "source_type": "m3u",
                "file_path": str(tmp_path / "nope.m3u"),
            }
        )

        assert status.status == "offline"
        assert "não encontrado" in status.message
