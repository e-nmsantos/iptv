"""Async logo/poster loading with a memory + disk cache.

Used by PosterCardDelegate to paint channel/VOD/series artwork without
blocking the UI thread. Network fetch + disk I/O happens on a small
QThreadPool; only cheap in-memory lookups and QPixmap creation happen on the
GUI thread.
"""

from collections import OrderedDict
from typing import Optional

import requests
from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap

from config.settings import Settings

from .image_cache import ImageCache

_MEMORY_CACHE_LIMIT = 300
_REQUEST_TIMEOUT_SECONDS = 8


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
                response = requests.get(self._url, timeout=_REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()
                data = response.content
            except Exception:
                self.signals.finished.emit(self._url, self._target_size, None)
                return
            self._disk_cache.write(self._url, data)

        image = QImage()
        if not image.loadFromData(data):
            self.signals.finished.emit(self._url, self._target_size, None)
            return
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
        self._pending: set[str] = set()

    def load(self, url: str, target_size: QSize) -> Optional[QPixmap]:
        """Return a cached pixmap immediately, or kick off a background fetch."""
        if not url:
            return None
        key = self._cache_key(url, target_size)
        cached = self._memory_cache.get(key)
        if cached is not None:
            self._memory_cache.move_to_end(key)
            return cached
        if url in self._pending:
            return None
        self._pending.add(url)
        task = _ImageFetchTask(url, target_size, self._disk_cache)
        task.signals.finished.connect(self._on_fetched)
        self._pool.start(task)
        return None

    @staticmethod
    def _cache_key(url: str, target_size: QSize) -> str:
        return f"{url}|{target_size.width()}x{target_size.height()}"

    def _on_fetched(self, url: str, target_size: QSize, image: Optional[QImage]):
        self._pending.discard(url)
        if image is None or image.isNull():
            return
        pixmap = QPixmap.fromImage(
            image.scaled(
                target_size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        key = self._cache_key(url, target_size)
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
