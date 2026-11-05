"""Server speedtest: latency/throughput measurement with mocked HTTP."""

import pytest

from src.core import server_speedtest
from src.core.server_speedtest import ServerSpeedtest, SpeedtestResult


class _HeadResponse:
    def close(self):
        pass


class _StreamResponse:
    def __init__(self, chunks):
        self._chunks = chunks

    def iter_content(self, chunk_size):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestResultModel:
    def test_dict_rounds_values(self):
        result = SpeedtestResult("host.test", 12.345, 45.6789, "Bom")

        assert result.to_dict() == {
            "server_host": "host.test",
            "latency_ms": 12.3,
            "download_speed_mbps": 45.68,
            "status": "Bom",
        }

    def test_repr_mentions_host_and_speed(self):
        text = repr(SpeedtestResult("host.test", 10.0, 20.5))

        assert "host.test" in text
        assert "20.5" in text


class TestMeasurement:
    def _patch(self, monkeypatch, chunks, head_error=None):
        def fake_head(url, headers=None, timeout=None):
            if head_error:
                raise head_error
            return _HeadResponse()

        monkeypatch.setattr(server_speedtest.requests, "head", fake_head)
        monkeypatch.setattr(
            server_speedtest.requests,
            "get",
            lambda *a, **k: _StreamResponse(chunks),
        )

    def test_fast_server_is_reported_as_excellent(self, monkeypatch):
        # 4 MB in a single chunk: measured duration is the loop time, so the
        # computed rate is very high.
        self._patch(monkeypatch, [b"\0" * (4 * 1024 * 1024)])

        result = ServerSpeedtest.test_endpoint("http://cdn.test/live.ts")

        assert result.server_host == "cdn.test"
        assert result.status == "Excelente"
        assert result.download_speed_mbps > 0

    def test_head_failure_falls_back_to_high_latency(self, monkeypatch):
        self._patch(monkeypatch, [b"\0" * 1024], head_error=OSError("sem rota"))

        result = ServerSpeedtest.test_endpoint("http://cdn.test/live.ts")

        assert result.latency_ms == 999.0

    def test_download_failure_reports_error(self, monkeypatch):
        monkeypatch.setattr(
            server_speedtest.requests, "head", lambda *a, **k: _HeadResponse()
        )

        def boom(*args, **kwargs):
            raise OSError("ligação caiu")

        monkeypatch.setattr(server_speedtest.requests, "get", boom)

        result = ServerSpeedtest.test_endpoint("http://cdn.test/live.ts")

        assert result.status == "Erro"
        assert result.download_speed_mbps == 0.0

    def test_custom_headers_are_sent(self, monkeypatch):
        captured = {}

        def fake_head(url, headers=None, timeout=None):
            captured.update(headers or {})
            return _HeadResponse()

        monkeypatch.setattr(server_speedtest.requests, "head", fake_head)
        monkeypatch.setattr(
            server_speedtest.requests, "get", lambda *a, **k: _StreamResponse([b"x"])
        )

        ServerSpeedtest.test_endpoint("http://cdn.test/live.ts", headers={"Referer": "r"})

        assert captured["Referer"] == "r"
        assert "IPTVPlayer-Speedtest" in captured["User-Agent"]

    def test_host_falls_back_to_path_when_url_has_no_netloc(self, monkeypatch):
        self._patch(monkeypatch, [b"x"])

        result = ServerSpeedtest.test_endpoint("cdn.test/live.ts")

        assert result.server_host == "cdn.test/live.ts"


class _Clock:
    """Deterministic clock: each call advances by a fixed step."""

    def __init__(self, step):
        self.now = 0.0
        self.step = step

    def time(self):
        self.now += self.step
        return self.now


@pytest.mark.parametrize(
    ("mbps", "expected"), [(30.0, "Excelente"), (12.0, "Bom"), (2.0, "Lento")]
)
def test_status_thresholds(mbps, expected, monkeypatch):
    clock = _Clock(0.5)
    monkeypatch.setattr(server_speedtest.time, "time", clock.time)
    monkeypatch.setattr(
        server_speedtest.requests, "head", lambda *a, **k: _HeadResponse()
    )
    chunk = b"\0" * int(mbps * 1_000_000 / 8)
    monkeypatch.setattr(
        server_speedtest.requests, "get", lambda *a, **k: _StreamResponse([chunk])
    )

    result = ServerSpeedtest.test_endpoint(
        "http://cdn.test/live.ts", test_duration_seconds=60
    )

    assert result.status == expected
    assert result.download_speed_mbps == pytest.approx(mbps, rel=0.01)
