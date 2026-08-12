"""Load XMLTV EPG data from local files or HTTP(S) sources."""

import gzip
import io
from pathlib import Path
from urllib.parse import urlparse

import requests

from .epg import EPGSource

MAX_SOURCE_BYTES = 100 * 1024 * 1024
MAX_XML_BYTES = 256 * 1024 * 1024


class _LimitedRawReader(io.RawIOBase):
    """Expose a readable stream while enforcing a byte limit incrementally."""

    def __init__(self, stream, limit: int, label: str):
        super().__init__()
        self._stream = stream
        self._limit = limit
        self._label = label
        self._total = 0

    def readable(self):
        return True

    def readinto(self, buffer):
        data = self._stream.read(len(buffer))
        if not data:
            return 0
        self._total += len(data)
        if self._total > self._limit:
            raise ValueError(f"{self._label} excede o limite permitido.")
        buffer[: len(data)] = data
        return len(data)


def _parse_stream(stream, compressed: bool) -> EPGSource:
    source_stream = io.BufferedReader(
        _LimitedRawReader(stream, MAX_SOURCE_BYTES, "A fonte EPG"),
        buffer_size=64 * 1024,
    )
    is_gzip = compressed or source_stream.peek(2)[:2] == b"\x1f\x8b"
    if is_gzip:
        gzip_stream = gzip.GzipFile(fileobj=source_stream)
        xml_stream = io.BufferedReader(
            _LimitedRawReader(gzip_stream, MAX_XML_BYTES, "O XMLTV descomprimido"),
            buffer_size=64 * 1024,
        )
    else:
        xml_stream = source_stream
    return EPGSource.parse_xmltv_stream(xml_stream)


def load_xmltv(
    source: str,
    timeout: int = 30,
    user_agent: str = "",
) -> EPGSource:
    """Download/read and parse an XMLTV document, including gzip sources."""
    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        try:
            response = requests.get(
                source,
                timeout=max(5, int(timeout)),
                headers={"User-Agent": user_agent} if user_agent else None,
                stream=True,
            )
            response.raise_for_status()
            try:
                declared_size = int(response.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                declared_size = 0
            if declared_size > MAX_SOURCE_BYTES:
                raise ValueError("A fonte EPG excede o limite de 100 MB.")
            epg = _parse_stream(
                response.raw,
                compressed=source.lower().endswith(".gz")
                or response.headers.get("Content-Encoding", "").lower() == "gzip",
            )
        except requests.RequestException as exc:
            host = parsed.hostname or "servidor EPG"
            if parsed.port:
                host = f"{host}:{parsed.port}"
            status = exc.response.status_code if exc.response is not None else None
            detail = f"HTTP {status}" if status else type(exc).__name__
            raise ConnectionError(
                f"Falha ao obter EPG de {host}: {detail}"
            ) from exc
        finally:
            if "response" in locals():
                response.close()
    else:
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(f"Fonte EPG não encontrada: {source}")
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("A fonte EPG excede o limite de 100 MB.")
        with path.open("rb") as source_file:
            epg = _parse_stream(source_file, compressed=source.lower().endswith(".gz"))

    epg.url = source if parsed.scheme in ("http", "https") else ""
    epg.file_path = "" if epg.url else source
    return epg
