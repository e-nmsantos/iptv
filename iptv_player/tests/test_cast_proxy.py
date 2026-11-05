"""Cast proxy: capability token, 404 for unauthenticated paths, HLS manifest."""

import urllib.error
import urllib.request

import pytest

from src.core.cast_manager import CastStreamProxy


@pytest.fixture
def proxy(qtbot):
    instance = CastStreamProxy()
    port = instance.start()
    assert port > 0
    yield instance, port
    instance.stop()


class TestCapabilityToken:
    def test_stream_urls_carry_the_token(self, proxy):
        instance, port = proxy

        live_url = instance.set_target("http://example.invalid/live.ts", is_live=True)
        vod_url = instance.set_target("http://example.invalid/movie.mp4", is_live=False)

        assert f":{port}/{instance._token}/hls/live.m3u8" in live_url
        assert f":{port}/{instance._token}/stream.mp4" in vod_url
        assert instance._token
        assert len(instance._token) >= 16

    def test_tokens_differ_between_instances(self):
        first, second = CastStreamProxy(), CastStreamProxy()

        assert first._token != second._token

    def test_requests_without_the_token_are_rejected(self, proxy):
        _instance, port = proxy

        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/hls/live.m3u8", timeout=5)

        assert excinfo.value.code == 404

    def test_wrong_token_is_rejected(self, proxy):
        _instance, port = proxy

        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/nao-e-o-token/hls/live.m3u8", timeout=5
            )

        assert excinfo.value.code == 404

    def test_manifest_is_served_with_the_token(self, proxy):
        instance, port = proxy
        url = instance.set_target("http://example.invalid/live.ts", is_live=True)
        local_url = url.replace(instance._local_ip, "127.0.0.1")
        server = instance._server
        with server.hls_lock:
            server.hls_chunks[1] = b"\x47" * 188

        with urllib.request.urlopen(local_url, timeout=5) as response:
            body = response.read().decode("utf-8")

        assert "#EXTM3U" in body
        assert f"/{instance._token}/hls/chunk_1.ts" in body
