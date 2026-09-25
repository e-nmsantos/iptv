"""Privacy-safe diagnostics report for troubleshooting and crash support.

The report never includes playlist URLs, credentials, MAC addresses or
encrypted values — only metadata, safe settings and an already-redacted log
tail — so it can be shared or stored without leaking sensitive data.
"""

import platform
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..utils.logger import redact_sensitive

# Settings that are safe to include in a report (no credentials, no paths
# that identify the user, no PIN material).
_SAFE_SETTINGS_KEYS = {
    "buffer_size_ms",
    "network_timeout_seconds",
    "max_connections",
    "epg_auto_update",
    "epg_update_interval_hours",
    "auto_next_enabled",
    "auto_next_delay_ms",
    "dark_theme",
    "stream_overlay_enabled",
    "parental_lock_enabled",
    "image_cache_max_mb",
}


def _sqlite_count(db_path: Path, table: str, where: str = "") -> int:
    """Count rows in a table; return -1 when the database is unavailable."""
    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            query = f"SELECT COUNT(*) FROM {table}"
            if where:
                query += f" WHERE {where}"
            return int(conn.execute(query).fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error:
        return -1


def _read_log_tail(path: Path, limit: int) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.readlines()[-limit:]
    except OSError:
        return []


def build_diagnostics_report(
    db_path: Path,
    settings,
    log_file: Path,
    app_version: str,
) -> str:
    """Assemble a human-readable, credential-free diagnostics report."""
    lines = []
    lines.append("IPTV Player - Relatório de diagnóstico")
    lines.append(
        f"Gerado: {datetime.now(timezone.utc).astimezone().isoformat()}"
    )
    lines.append(f"Versão da aplicação: {app_version}")
    lines.append(f"Sistema: {platform.platform()}")
    lines.append(f"Python: {sys.version.split()[0]}")
    try:
        import vlc

        lines.append(
            f"libVLC: {vlc.libvlc_get_version().decode(errors='ignore')}"
        )
    except Exception:
        pass

    lines.append("")
    lines.append("[Definições]")
    for key in sorted(_SAFE_SETTINGS_KEYS):
        if key in settings.DEFAULTS:
            lines.append(f"  {key} = {settings.get(key)}")

    lines.append("")
    lines.append("[Base de dados]")
    lines.append(f"  ficheiro: {db_path.name}")  # name only: full path reveals the user
    try:
        size_mib = db_path.stat().st_size / 1024 / 1024
        lines.append(f"  tamanho: {size_mib:.2f} MiB")
    except OSError:
        lines.append("  tamanho: indisponível")
    lines.append(f"  playlists: {_sqlite_count(db_path, 'playlists')}")
    lines.append(f"  canais: {_sqlite_count(db_path, 'channels')}")
    for stream_type in ("live", "vod", "movie", "series"):
        where = f"stream_type = '{stream_type}'"
        lines.append(
            f"    {stream_type}: {_sqlite_count(db_path, 'channels', where)}"
        )
    lines.append(f"  programas EPG: {_sqlite_count(db_path, 'epg_cache')}")
    lines.append(f"  histórico: {_sqlite_count(db_path, 'playback_history')}")

    lines.append("")
    lines.append("[Últimas linhas do registo]")
    tail = _read_log_tail(log_file, limit=200)
    if tail:
        lines.extend(redact_sensitive(line.rstrip()) for line in tail)
    else:
        lines.append("  (registo indisponível)")

    return "\n".join(lines)
