"""Settings management for the IPTV Player application."""

import json
import logging
import os
import tempfile
from copy import deepcopy
from pathlib import Path

logger = logging.getLogger(__name__)


class Settings:
    """Manages application settings persisted to a JSON file."""

    DEFAULTS = {
        "vlc_path": "",
        "dark_theme": True,
        "first_run_done": False,
        "auto_check_updates": True,
        "last_update_check_ts": 0,
        "volume": 80,
        "recent_playlists": [],
        "epg_auto_update": True,
        "epg_update_interval_hours": 24,
        "buffer_size_ms": 5000,
        "network_timeout_seconds": 30,
        "max_connections": 5,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "window_geometry": None,
        "window_state": None,
        "splitter_sizes": None,
        "recording_folder": str(Path.home() / "Videos" / "IPTV Recordings"),
        "stream_overlay_enabled": False,
        "deinterlace": False,
        "normalize_audio": True,
        "parental_lock_enabled": False,
        "parental_pin_hash": "",
        "parental_pin_salt": "",
        "image_cache_max_mb": 200,
        "pip_window_size": [360, 202],
        # Playback robustness.
        "auto_next_enabled": True,
        "auto_next_delay_ms": 2000,
        "autoplay_last_channel": True,
        "clean_channel_names": True,
        "sleep_timer_minutes": 0,
        # Session restore.
        "last_playlist_id": None,
        "last_content_tab": 0,
        "last_channel_id": 0,
        "last_group_filter": ["all", ""],
        # Updates.
        "update_manifest_url": "",
    }
    INT_RANGES = {
        "volume": (0, 100),
        "epg_update_interval_hours": (1, 24 * 30),
        "buffer_size_ms": (0, 120_000),
        "network_timeout_seconds": (3, 300),
        "max_connections": (1, 100),
        "image_cache_max_mb": (1, 10_000),
        "auto_next_delay_ms": (0, 60_000),
        "sleep_timer_minutes": (0, 480),
        "last_content_tab": (0, 2),
        "last_channel_id": (0, 2**63 - 1),
    }

    def __init__(self):
        self._config_dir = self._get_config_dir()
        self._config_file = self._config_dir / "settings.json"
        self._settings = deepcopy(self.DEFAULTS)
        self.load()

    @staticmethod
    def _get_config_dir() -> Path:
        """Get the application config directory."""
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            base = Path.home() / ".config"
        config_dir = base / "iptv-player"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir

    @property
    def config_dir(self) -> Path:
        return self._config_dir

    def load(self):
        """Load settings from the JSON file."""
        try:
            if self._config_file.exists():
                with open(self._config_file, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("O ficheiro de definições não contém um objeto JSON.")
                # Versions up to 0.5 stored the last stream URL in plaintext.
                # Never retain it in memory or write it back to disk.
                needs_rewrite = "last_channel_url" in data
                data.pop("last_channel_url", None)
                for key, value in data.items():
                    if key in self.DEFAULTS and self._is_valid_value(key, value):
                        self._settings[key] = value
                    else:
                        needs_rewrite = True
                    if key in self.DEFAULTS and not self._is_valid_value(key, value):
                        logger.warning("Ignoring invalid setting: %s", key)
                if needs_rewrite:
                    self.save()
        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.error("Error loading settings: %s", e)

    def save(self):
        """Atomically save settings to disk."""
        temp_path = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix="settings-", suffix=".tmp", dir=self._config_dir
            )
            temp_path = Path(raw_path)
            with os.fdopen(descriptor, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self._config_file)
        except OSError as e:
            logger.error("Error saving settings: %s", e)
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def get(self, key: str, default=None):
        """Get a setting value by key."""
        return self._settings.get(key, default)

    def set(self, key: str, value):
        """Set a setting value and persist to disk."""
        if key not in self.DEFAULTS:
            raise KeyError(f"Definição desconhecida: {key}")
        if not self._is_valid_value(key, value):
            raise ValueError(f"Valor inválido para a definição: {key}")
        self._settings[key] = value
        self.save()

    def set_many(self, values: dict):
        """Validate and persist several settings with a single disk write."""
        for key, value in values.items():
            if key not in self.DEFAULTS:
                raise KeyError(f"Definição desconhecida: {key}")
            if not self._is_valid_value(key, value):
                raise ValueError(f"Valor inválido para a definição: {key}")
        self._settings.update(values)
        self.save()

    @classmethod
    def _is_valid_value(cls, key: str, value) -> bool:
        """Reject malformed persisted values before they reach the UI/services."""
        default = cls.DEFAULTS[key]
        if default is None:
            if key == "last_playlist_id":
                return value is None or (
                    isinstance(value, int) and not isinstance(value, bool) and value > 0
                )
            if key in ("window_geometry", "window_state"):
                return value is None or isinstance(value, str)
            if key == "splitter_sizes":
                return value is None or (
                    isinstance(value, list)
                    and all(
                        isinstance(item, int) and not isinstance(item, bool) and item >= 0
                        for item in value
                    )
                )
            return value is None
        if isinstance(default, bool):
            return isinstance(value, bool)
        if isinstance(default, int):
            if not isinstance(value, int) or isinstance(value, bool):
                return False
            minimum, maximum = cls.INT_RANGES.get(key, (0, 2**63 - 1))
            return minimum <= value <= maximum
        if isinstance(default, str):
            return isinstance(value, str)
        if isinstance(default, list):
            if not isinstance(value, list):
                return False
            if key == "recent_playlists":
                return len(value) <= 20 and all(isinstance(item, str) for item in value)
            if key == "pip_window_size":
                return len(value) == 2 and all(
                    isinstance(item, int) and not isinstance(item, bool) and item > 0
                    for item in value
                )
            if key == "last_group_filter":
                return len(value) == 2 and all(isinstance(item, str) for item in value)
            return True
        return isinstance(value, type(default))

    def reset(self):
        """Reset all settings to defaults."""
        self._settings = deepcopy(self.DEFAULTS)
        self.save()

    def add_recent_playlist(self, path: str):
        """Add a playlist path to the recent list."""
        recents = self._settings.get("recent_playlists", [])
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        self._settings["recent_playlists"] = recents[:20]
        self.save()
