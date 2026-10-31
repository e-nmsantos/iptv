"""Async logo/poster loading with a memory + disk cache.

Used by PosterCardDelegate to paint channel/VOD/series artwork without
blocking the UI thread. Network fetch + disk I/O happens on a small
QThreadPool; only cheap in-memory lookups and QPixmap creation happen on the
GUI thread.
"""

import logging
import time
from collections import OrderedDict
from typing import Optional

import requests
from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap

from config.settings import Settings

from .image_cache import ImageCache

logger = logging.getLogger(__name__)

_MEMORY_CACHE_LIMIT = 300
_REQUEST_TIMEOUT_SECONDS = 8
_MAX_IMAGE_BYTES = 12 * 1024 * 1024


class _FetchSignals(QObject):
    finished = Signal(str, QSize, object)  # url, target_size, QImage|None


class _ImageFetchTask(QRunnable):
    def __init__(self, url: str, target_size: QSize, disk_cache: ImageCache):
        super().__init__()
        self.signals = _FetchSignals()
        self._url = url
        self._target_size = target_size
        self._disk_cache = disk_cache

    def run(self):
        data = self._disk_cache.read(self._url)
        if data is None:
            try:
                with requests.get(self._url, timeout=_REQUEST_TIMEOUT_SECONDS, stream=True) as response:
                    response.raise_for_status()
                    chunks = []
                    downloaded = 0
                    for chunk in response.iter_content(64 * 1024):
                        downloaded += len(chunk)
                        if downloaded > _MAX_IMAGE_BYTES:
                            raise ValueError("Artwork exceeds the download limit")
                        chunks.append(chunk)
                    data = b"".join(chunks)
            except Exception as exc:
                logger.debug("Artwork unavailable (%s)", type(exc).__name__)
                self.signals.finished.emit(self._url, self._target_size, None)
                return

        image = QImage()
        if not image.loadFromData(data):
            self.signals.finished.emit(self._url, self._target_size, None)
            return
        self._disk_cache.write(self._url, data)
        self.signals.finished.emit(self._url, self._target_size, image)


class ImageLoaderService(QObject):
    """Loads and caches remote artwork; emits `image_ready` when fetches land."""

    image_ready = Signal(str, QPixmap)

    def __init__(self):
        super().__init__()
        settings = Settings()
        self._disk_cache = ImageCache(
            settings.config_dir / "cache" / "images",
            max_mb=settings.get("image_cache_max_mb", 200),
        )
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(4)
        self._memory_cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._pending: dict[str, set[tuple[int, int]]] = {}
        self._failed_until: dict[str, float] = {}

    def load(self, url: str, target_size: QSize) -> Optional[QPixmap]:
        """Return a cached pixmap immediately, or kick off a background fetch."""
        if not url:
            return None
        key = self._cache_key(url, target_size)
        cached = self._memory_cache.get(key)
        if cached is not None:
            self._memory_cache.move_to_end(key)
            return cached
        if self._failed_until.get(url, 0) > time.monotonic():
            return None
        size = (target_size.width(), target_size.height())
        if url in self._pending:
            self._pending[url].add(size)
            return None
        self._pending[url] = {size}
        task = _ImageFetchTask(url, target_size, self._disk_cache)
        task.signals.finished.connect(self._on_fetched)
        self._pool.start(task)
        return None

    @staticmethod
    def _cache_key(url: str, target_size: QSize) -> str:
        return f"{url}|{target_size.width()}x{target_size.height()}"

    def _on_fetched(self, url: str, target_size: QSize, image: Optional[QImage]):
        sizes = self._pending.pop(url, {(target_size.width(), target_size.height())})
        if image is None or image.isNull():
            # Do not retry a broken logo on every paint event.
            if len(self._failed_until) >= _MEMORY_CACHE_LIMIT:
                self._failed_until.clear()
            self._failed_until[url] = time.monotonic() + 60
            return
        self._failed_until.pop(url, None)
        pixmap = None
        for width, height in sorted(sizes, key=lambda size: size[0] * size[1]):
            size = QSize(width, height)
            pixmap = QPixmap.fromImage(
                image.scaled(
                    size,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            key = self._cache_key(url, size)
            self._memory_cache[key] = pixmap
            self._memory_cache.move_to_end(key)
        while len(self._memory_cache) > _MEMORY_CACHE_LIMIT:
            self._memory_cache.popitem(last=False)
        self.image_ready.emit(url, pixmap)


_instance: Optional[ImageLoaderService] = None


def get_image_loader() -> ImageLoaderService:
    """Lazily construct the singleton loader (needs a live QApplication)."""
    global _instance
    if _instance is None:
        _instance = ImageLoaderService()
    return _instance
