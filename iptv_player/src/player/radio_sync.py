"""Dual-Audio Sports Radio Sync manager for IPTV Player."""

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Popular Portuguese sports and news radio streams
DEFAULT_SPORTS_RADIOS: list[dict[str, str]] = [
    {"name": "Antena 1 (Desporto)", "url": "https://radiocast.rtp.pt/antena180a.mp3"},
    {"name": "Rádio Renascença", "url": "https://stream-icast.ruad示.pt/rr.mp3"},
    {"name": "TSF Rádio Notícias", "url": "https://tsfdirecto.tsf.pt/tsfdirecto.mp3"},
    {"name": "Rádio Observador", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/OBSERVADOR.mp3"},
]


class RadioSyncManager:
    """Manages playing an alternative radio commentary track with video sync delay."""

    def __init__(self):
        self._active_radio_url: Optional[str] = None
        self._delay_ms: int = 0
        self._is_syncing: bool = False
        self._lock = threading.Lock()

    @property
    def is_active(self) -> bool:
        return self._is_syncing and bool(self._active_radio_url)

    @property
    def delay_ms(self) -> int:
        return self._delay_ms

    def get_radio_presets(self) -> list[dict[str, str]]:
        return list(DEFAULT_SPORTS_RADIOS)

    def set_delay(self, delay_ms: int) -> None:
        """Adjust audio offset in milliseconds (+/- 10,000ms)."""
        with self._lock:
            self._delay_ms = max(-10000, min(10000, delay_ms))

    def adjust_delay(self, delta_ms: int) -> int:
        """Increment or decrement delay by delta_ms and return new value."""
        with self._lock:
            self._delay_ms = max(-10000, min(10000, self._delay_ms + delta_ms))
            return self._delay_ms

    def start(self, radio_url: str, initial_delay_ms: int = 0) -> None:
        """Activate radio commentary track with specified initial delay."""
        with self._lock:
            self._active_radio_url = radio_url
            self._delay_ms = initial_delay_ms
            self._is_syncing = True

    def stop(self) -> None:
        """Stop radio commentary and restore primary video audio."""
        with self._lock:
            self._is_syncing = False
            self._active_radio_url = None
            self._delay_ms = 0

