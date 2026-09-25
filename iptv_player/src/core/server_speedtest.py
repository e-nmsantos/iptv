"""IPTV Server Speedtest and network diagnostics."""

import logging
import time
from typing import Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


class SpeedtestResult:
    """Results of an IPTV server connectivity and throughput test."""

    def __init__(
        self,
        server_host: str,
        latency_ms: float,
        download_speed_mbps: float,
        status: str = "OK",
    ):
        self.server_host = server_host
        self.latency_ms = latency_ms
        self.download_speed_mbps = download_speed_mbps
        self.status = status

    def __repr__(self):
        return (
            f"<SpeedtestResult host={self.server_host} "
            f"latency={self.latency_ms:.1f}ms speed={self.download_speed_mbps:.2f} Mbps>"
        )

    def to_dict(self) -> dict:
        return {
            "server_host": self.server_host,
            "latency_ms": round(self.latency_ms, 1),
            "download_speed_mbps": round(self.download_speed_mbps, 2),
            "status": self.status,
        }


class ServerSpeedtest:
    """Measures latency and bandwidth directly against IPTV provider endpoints."""

    @classmethod
    def test_endpoint(
        cls,
        endpoint_url: str,
        test_duration_seconds: float = 3.0,
        headers: Optional[dict] = None,
    ) -> SpeedtestResult:
        """Measure ping latency and stream download speed in Mbps."""
        parsed = urlparse(endpoint_url)
        host = parsed.netloc or parsed.path

        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) IPTVPlayer-Speedtest/1.0",
            **(headers or {}),
        }

        # 1. Latency test (HEAD/GET with fast timeout)
        start_ping = time.time()
        try:
            requests.head(endpoint_url, headers=req_headers, timeout=5).close()
            latency_ms = (time.time() - start_ping) * 1000.0
        except Exception:
            latency_ms = 999.0

        # 2. Throughput test (Download stream chunks for test_duration_seconds)
        total_bytes = 0
        speed_mbps = 0.0
        try:
            start_dl = time.time()
            with requests.get(endpoint_url, headers=req_headers, stream=True, timeout=5) as r:
                for chunk in r.iter_content(chunk_size=32 * 1024):
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    elapsed = time.time() - start_dl
                    if elapsed >= test_duration_seconds:
                        break

            duration = max(0.1, time.time() - start_dl)
            # Bytes to megabits: (bytes * 8) / (1024 * 1024) / duration
            speed_mbps = (total_bytes * 8.0) / (1_000_000.0 * duration)
            status = "Excelente" if speed_mbps >= 25.0 else ("Bom" if speed_mbps >= 10.0 else "Lento")
        except Exception as e:
            logger.debug("Speedtest download failed: %s", e)
            status = "Erro"

        return SpeedtestResult(
            server_host=host,
            latency_ms=latency_ms,
            download_speed_mbps=speed_mbps,
            status=status,
        )

