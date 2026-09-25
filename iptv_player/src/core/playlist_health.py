"""Health and connectivity checker for IPTV playlists (M3U, Xtream, Stalker)."""

import json
import logging
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

# SSL context that allows self-signed/expired provider certificates common in IPTV
try:
    UNVERIFIED_SSL = ssl._create_unverified_context()
except Exception:
    UNVERIFIED_SSL = None


@dataclass
class HealthStatus:
    playlist_id: int
    status: str  # "online", "offline", "unauthorized", "expired", "local", "checking"
    latency_ms: int = 0
    message: str = ""
    expiry_date: Optional[str] = None
    max_connections: Optional[str] = None
    active_connections: Optional[str] = None
    checked_at: Optional[datetime] = None


class PlaylistHealthChecker(QObject):
    """Asynchronous checker for playlist server availability and account expiration."""

    health_updated = Signal(object)  # HealthStatus

    _instance: Optional["PlaylistHealthChecker"] = None

    @classmethod
    def get_instance(cls) -> "PlaylistHealthChecker":
        if cls._instance is None:
            cls._instance = PlaylistHealthChecker()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._cache: dict[int, HealthStatus] = {}
        self._checking: set = set()
        self._lock = threading.Lock()

    def get_cached_status(self, playlist_id: int) -> Optional[HealthStatus]:
        with self._lock:
            return self._cache.get(playlist_id)

    def check_all_playlists_async(self, playlists: list[dict]):
        """Trigger non-blocking background health checks for all saved playlists."""
        for pl in playlists:
            self.check_playlist_async(pl)

    def check_playlist_async(self, playlist: dict):
        """Check a single playlist in background thread."""
        pl_id = playlist.get("id")
        if not pl_id:
            return

        with self._lock:
            if pl_id in self._checking:
                return
            self._checking.add(pl_id)

        threading.Thread(
            target=self._check_worker,
            args=(playlist,),
            daemon=True,
        ).start()

    def _check_worker(self, playlist: dict):
        pl_id = playlist.get("id")
        try:
            status = self.check_playlist_sync(playlist)
            with self._lock:
                self._cache[pl_id] = status
            self.health_updated.emit(status)
        except Exception as exc:
            logger.debug("Health check error for playlist %s: %s", pl_id, exc)
            err_status = HealthStatus(
                playlist_id=pl_id,
                status="offline",
                message=f"Erro de conexão: {exc}",
                checked_at=datetime.now(),
            )
            with self._lock:
                self._cache[pl_id] = err_status
            self.health_updated.emit(err_status)
        finally:
            with self._lock:
                self._checking.discard(pl_id)

    def check_playlist_sync(self, playlist: dict) -> HealthStatus:
        """Synchronously check connectivity and return HealthStatus."""
        pl_id = playlist.get("id", 0)
        source_type = (playlist.get("source_type") or "m3u").lower()
        checked_time = datetime.now()

        # 1. Local file M3U
        if playlist.get("is_local") or playlist.get("file_path"):
            path_str = playlist.get("file_path") or playlist.get("url") or ""
            if path_str and Path(path_str).exists():
                return HealthStatus(
                    playlist_id=pl_id,
                    status="local",
                    latency_ms=0,
                    message="Ficheiro local disponível",
                    checked_at=checked_time,
                )
            return HealthStatus(
                playlist_id=pl_id,
                status="offline",
                latency_ms=0,
                message="Ficheiro local não encontrado",
                checked_at=checked_time,
            )

        # 2. Xtream Codes
        if source_type == "xtream":
            server_url = (playlist.get("server_url") or playlist.get("url") or "").strip()
            username = (playlist.get("username") or "").strip()
            password = (playlist.get("password") or "").strip()

            if not server_url or not username:
                return HealthStatus(
                    playlist_id=pl_id,
                    status="offline",
                    message="Credenciais Xtream em falta",
                    checked_at=checked_time,
                )

            if not server_url.startswith(("http://", "https://")):
                server_url = "http://" + server_url
            base = server_url.rstrip("/")
            api_url = f"{base}/player_api.php?username={urllib.parse.quote(username)}&password={urllib.parse.quote(password)}"

            t0 = time.time()
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "IPTVSmartersPlayer/1.0.0 (Linux; Android 11)"},
            )
            try:
                with urllib.request.urlopen(req, timeout=4.0, context=UNVERIFIED_SSL) as resp:
                    latency = int((time.time() - t0) * 1000)
                    raw_data = resp.read()
                    data = json.loads(raw_data.decode("utf-8", errors="ignore"))

                user_info = data.get("user_info", {})
                auth = user_info.get("auth")
                status_str = str(user_info.get("status", "")).lower()
                exp_date_raw = user_info.get("exp_date")

                exp_date_formatted = None
                if exp_date_raw:
                    try:
                        exp_ts = int(exp_date_raw)
                        exp_dt = datetime.fromtimestamp(exp_ts)
                        exp_date_formatted = exp_dt.strftime("%d/%m/%Y")
                        if exp_dt < datetime.now():
                            return HealthStatus(
                                playlist_id=pl_id,
                                status="expired",
                                latency_ms=latency,
                                message=f"Subscrição expirada em {exp_date_formatted}",
                                expiry_date=exp_date_formatted,
                                checked_at=checked_time,
                            )
                    except Exception:
                        exp_date_formatted = str(exp_date_raw)

                if auth == 0 or status_str in ("disabled", "banned", "expired"):
                    return HealthStatus(
                        playlist_id=pl_id,
                        status="unauthorized",
                        latency_ms=latency,
                        message=f"Conta não autorizada ({status_str or 'Auth=0'})",
                        expiry_date=exp_date_formatted,
                        checked_at=checked_time,
                    )

                max_cons = str(user_info.get("max_connections", "1"))
                active_cons = str(user_info.get("active_cons", "0"))

                return HealthStatus(
                    playlist_id=pl_id,
                    status="online",
                    latency_ms=latency,
                    message="Servidor Xtream Online",
                    expiry_date=exp_date_formatted or "Ilimitada",
                    max_connections=max_cons,
                    active_connections=active_cons,
                    checked_at=checked_time,
                )
            except Exception as e:
                return HealthStatus(
                    playlist_id=pl_id,
                    status="offline",
                    message=f"Servidor inacessível: {e}",
                    checked_at=checked_time,
                )

        # 3. Stalker Portal
        if source_type == "stalker":
            server_url = (playlist.get("server_url") or playlist.get("url") or "").strip()
            mac = (playlist.get("mac_address") or "").strip()

            if not server_url:
                return HealthStatus(
                    playlist_id=pl_id,
                    status="offline",
                    message="URL do Portal Stalker em falta",
                    checked_at=checked_time,
                )

            if not server_url.startswith(("http://", "https://")):
                server_url = "http://" + server_url

            # Normalize portal root
            base = server_url.rstrip("/")
            for suffix in ("/c/", "/c", "/stalker_portal/c/", "/stalker_portal/c", "/server/load.php"):
                if base.lower().endswith(suffix):
                    base = base[: len(base) - len(suffix)].rstrip("/")
                    break

            # Normalize MAC
            clean_mac = re.sub(r"[^a-fA-F0-9]", "", mac)
            if len(clean_mac) == 12:
                formatted_mac = ":".join(clean_mac[i: i + 2] for i in range(0, 12, 2)).upper()
            else:
                formatted_mac = mac.upper()

            handshake_url = f"{base}/server/load.php?type=stb&action=handshake&token=&JsHttpRequest=1-xml"

            t0 = time.time()
            req = urllib.request.Request(
                handshake_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG425 STBw3 firmware ver=2.31.0",
                    "Cookie": f"mac={urllib.parse.quote(formatted_mac)}",
                    "X-User-Agent": "Model: MAG425; Link: WiFi",
                    "Accept": "*/*",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=4.0, context=UNVERIFIED_SSL) as resp:
                    latency = int((time.time() - t0) * 1000)
                    raw_data = resp.read()
                    text = raw_data.decode("utf-8", errors="ignore")
                    
                    if "token" in text.lower() or resp.status in (200, 302):
                        return HealthStatus(
                            playlist_id=pl_id,
                            status="online",
                            latency_ms=latency,
                            message="Portal Stalker Online (Token OK)",
                            checked_at=checked_time,
                        )
                return HealthStatus(
                    playlist_id=pl_id,
                    status="offline",
                    message="Portal Stalker não respondeu adequadamente",
                    checked_at=checked_time,
                )
            except Exception as e:
                return HealthStatus(
                    playlist_id=pl_id,
                    status="offline",
                    message=f"Portal inacessível: {e}",
                    checked_at=checked_time,
                )

        # 4. Remote M3U / M3U8
        url = (playlist.get("url") or playlist.get("server_url") or "").strip()
        if not url.startswith(("http://", "https://")):
            url = "http://" + url

        t0 = time.time()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "VLC/3.0.18 LibVLC/3.0.18",
                "Range": "bytes=0-1024",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=4.0, context=UNVERIFIED_SSL) as resp:
                latency = int((time.time() - t0) * 1000)
                if resp.status in (200, 206, 302):
                    return HealthStatus(
                        playlist_id=pl_id,
                        status="online",
                        latency_ms=latency,
                        message="Lista M3U Online",
                        checked_at=checked_time,
                    )
                return HealthStatus(
                    playlist_id=pl_id,
                    status="offline",
                    latency_ms=latency,
                    message=f"HTTP {resp.status}",
                    checked_at=checked_time,
                )
        except Exception as e:
            return HealthStatus(
                playlist_id=pl_id,
                status="offline",
                message=f"Servidor inacessível: {e}",
                checked_at=checked_time,
            )
