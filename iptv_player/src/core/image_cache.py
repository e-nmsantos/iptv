"""On-disk cache for remotely-fetched channel/VOD/series artwork."""

import hashlib
import os
from pathlib import Path
from typing import Optional


class ImageCache:
    """Simple content-addressed disk cache with LRU-by-mtime eviction."""

    def __init__(self, cache_dir: Path, max_mb: int = 200):
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max(1, int(max_mb)) * 1024 * 1024

    def _path_for(self, url: str) -> Path:
        digest = hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()
        return self._dir / digest

    def read(self, url: str) -> Optional[bytes]:
        path = self._path_for(url)
        try:
            data = path.read_bytes()
        except OSError:
            return None
        try:
            os.utime(path, None)
        except OSError:
            pass
        return data

    def write(self, url: str, data: bytes) -> None:
        path = self._path_for(url)
        try:
            path.write_bytes(data)
        except OSError:
            return
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        try:
            entries = [(p, p.stat()) for p in self._dir.iterdir() if p.is_file()]
        except OSError:
            return
        total = sum(st.st_size for _, st in entries)
        if total <= self._max_bytes:
            return
        entries.sort(key=lambda item: item[1].st_mtime)
        for path, st in entries:
            if total <= self._max_bytes:
                break
            try:
                path.unlink()
                total -= st.st_size
            except OSError:
                continue
