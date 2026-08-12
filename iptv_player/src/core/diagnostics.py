"""Privacy-safe, bounded stream availability diagnostics."""

import time
from urllib.parse import urlparse

import requests


def diagnose_channel(channel, timeout: int = 10) -> dict:
    parsed = urlparse(channel.url)
    protocol = parsed.scheme.lower() or "desconhecido"
    result = {
        "name": channel.name,
        "protocol": protocol.upper(),
        "host": parsed.hostname or "",
        "status": "não testado",
        "latency_ms": 0,
        "content_type": "",
    }
    if protocol not in ("http", "https"):
        result["status"] = "protocolo suportado pelo VLC; teste HTTP indisponível"
        return result
    headers = dict(channel.custom_headers or {})
    if channel.user_agent:
        headers["User-Agent"] = channel.user_agent
    if channel.referer:
        headers["Referer"] = channel.referer
    headers["Range"] = "bytes=0-1023"
    started = time.perf_counter()
    try:
        response = requests.get(
            channel.url,
            headers=headers,
            timeout=max(3, min(int(timeout), 30)),
            stream=True,
            allow_redirects=True,
        )
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
        result["status"] = f"HTTP {response.status_code}"
        result["content_type"] = response.headers.get("Content-Type", "").split(";", 1)[0]
        response.close()
    except requests.RequestException as exc:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
        result["status"] = type(exc).__name__
    return result
