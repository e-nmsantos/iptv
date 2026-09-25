"""SQLite database manager for local storage."""

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..repositories import CatalogRepository, PlaylistRepository
from .backup_data import export_backup_data as build_backup_data
from .backup_data import parse_backup_data
from .channel import Channel
from .epg import EPGProgram
from .migrations import fts_query, run_migrations
from .playlist import Playlist
from .secrets import SecretStore


class DatabaseManager:
    """Manages the local SQLite database for playlists, favorites, and EPG cache."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        secret_store: Optional[SecretStore] = None,
    ):
        if db_path is None:
            from config.settings import Settings
            settings = Settings()
            db_path = settings.config_dir / "iptv_data.db"
        self._db_path = db_path
        self._secrets = secret_store or SecretStore()
        self._purge_thread: Optional[threading.Thread] = None
        self._init_database()
        self.catalogs = CatalogRepository(
            self._connection, self._row_to_channel, self._catalog_stream_types
        )
        self.playlists = PlaylistRepository(
            self._connection, self._decrypt_playlist_row
        )

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(str(self._db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-32000")
        conn.execute("PRAGMA mmap_size=268435456")
        conn.execute("PRAGMA foreign_keys=ON")
        # Avoid spurious "database is locked" failures when a worker writes
        # (e.g. replace_catalog) concurrently with main-thread reads/writes.
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def _connection(self):
        """Yield a transactional connection and always close it afterwards."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_database(self):
        """Initialize database tables."""
        migrated_sensitive_data = False
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    url TEXT,
                    file_path TEXT,
                    server_url TEXT,
                    username TEXT,
                    password TEXT,
                    mac_address TEXT,
                    epg_source TEXT DEFAULT '',
                    epg_url TEXT DEFAULT '',
                    created_at TEXT,
                    updated_at TEXT,
                    is_active INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    group_name TEXT DEFAULT 'General',
                    logo TEXT DEFAULT '',
                    tvg_id TEXT DEFAULT '',
                    tvg_name TEXT DEFAULT '',
                    epg_channel_id TEXT DEFAULT '',
                    stream_type TEXT DEFAULT 'live',
                    source TEXT DEFAULT 'm3u',
                    xtream_id TEXT DEFAULT '',
                    user_agent TEXT DEFAULT '',
                    referer TEXT DEFAULT '',
                    custom_headers TEXT DEFAULT '{}',
                    quality TEXT DEFAULT '',
                    extension TEXT DEFAULT '',
                    container_extension TEXT DEFAULT '',
                    country_code TEXT DEFAULT '',
                    provider_group TEXT DEFAULT '',
                    is_favorite INTEGER DEFAULT 0,
                    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS epg_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    stop_time TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    category TEXT DEFAULT '',
                    UNIQUE(channel_id, start_time, title)
                );

                CREATE TABLE IF NOT EXISTS playlist_epg_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_id INTEGER NOT NULL,
                    channel_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    stop_time TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    category TEXT DEFAULT '',
                    UNIQUE(playlist_id, channel_id, start_time, title),
                    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS epg_metadata (
                    playlist_id INTEGER PRIMARY KEY,
                    last_updated TEXT NOT NULL,
                    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS catalog_state (
                    playlist_id INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ready',
                    item_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    error TEXT DEFAULT '',
                    PRIMARY KEY (playlist_id, content_type),
                    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS app_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS playback_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_id INTEGER NOT NULL,
                    channel_id INTEGER DEFAULT 0,
                    title TEXT NOT NULL,
                    stream_type TEXT NOT NULL,
                    played_at TEXT NOT NULL,
                    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS playback_progress (
                    playlist_id INTEGER NOT NULL,
                    media_key TEXT NOT NULL,
                    position_ms INTEGER NOT NULL,
                    length_ms INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (playlist_id, media_key),
                    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS locked_groups (
                    playlist_id INTEGER NOT NULL,
                    group_name TEXT NOT NULL,
                    PRIMARY KEY (playlist_id, group_name),
                    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_channels_playlist ON channels(playlist_id);
                CREATE INDEX IF NOT EXISTS idx_channels_group ON channels(group_name);
                CREATE INDEX IF NOT EXISTS idx_channels_fav ON channels(is_favorite);
                CREATE INDEX IF NOT EXISTS idx_epg_channel ON epg_cache(channel_id);
                CREATE INDEX IF NOT EXISTS idx_epg_time ON epg_cache(start_time, stop_time);
                CREATE INDEX IF NOT EXISTS idx_playlist_epg_channel
                    ON playlist_epg_cache(playlist_id, channel_id);
                CREATE INDEX IF NOT EXISTS idx_channels_playlist_type
                    ON channels(playlist_id, stream_type);
                CREATE INDEX IF NOT EXISTS idx_channels_playlist_stream
                    ON channels(playlist_id, stream_type, id);
                CREATE INDEX IF NOT EXISTS idx_channels_playlist_group
                    ON channels(playlist_id, group_name);
                CREATE INDEX IF NOT EXISTS idx_channels_playlist_favorite
                    ON channels(playlist_id, is_favorite);
                CREATE INDEX IF NOT EXISTS idx_channels_catalog_page
                    ON channels(playlist_id, stream_type, group_name, name, id);
                CREATE INDEX IF NOT EXISTS idx_history_playlist_time
                    ON playback_history(playlist_id, played_at DESC);

            """)

            # Lightweight, additive migrations for existing databases.
            existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(channels)")}
            migrations = {
                "category_id": "TEXT DEFAULT ''",
                "user_agent": "TEXT DEFAULT ''",
                "referer": "TEXT DEFAULT ''",
                "custom_headers": "TEXT DEFAULT '{}'",
                "quality": "TEXT DEFAULT ''",
                "extension": "TEXT DEFAULT ''",
                "container_extension": "TEXT DEFAULT ''",
                "country_code": "TEXT DEFAULT ''",
                "provider_group": "TEXT DEFAULT ''",
                "has_archive": "INTEGER DEFAULT 0",
                "archive_duration_days": "INTEGER DEFAULT 0",
                "content_hash": "TEXT DEFAULT ''",
                "channel_number": "INTEGER DEFAULT 0",
            }
            for column, definition in migrations.items():
                if column not in existing_cols:
                    conn.execute(
                        f"ALTER TABLE channels ADD COLUMN {column} {definition}"
                    )

            playlist_cols = {
                row["name"] for row in conn.execute("PRAGMA table_info(playlists)")
            }
            playlist_migrations = {
                "url": "TEXT DEFAULT ''",
                "file_path": "TEXT DEFAULT ''",
                "server_url": "TEXT DEFAULT ''",
                "username": "TEXT DEFAULT ''",
                "password": "TEXT DEFAULT ''",
                "mac_address": "TEXT DEFAULT ''",
                "epg_source": "TEXT DEFAULT ''",
                "epg_url": "TEXT DEFAULT ''",
                "created_at": "TEXT DEFAULT ''",
                "updated_at": "TEXT DEFAULT ''",
                "is_active": "INTEGER DEFAULT 0",
            }
            for column, definition in playlist_migrations.items():
                if column not in playlist_cols:
                    conn.execute(
                        f"ALTER TABLE playlists ADD COLUMN {column} {definition}"
                    )

            run_migrations(conn)

            # The legacy plaintext -> ciphertext migration scans every channel
            # row and AES-verifies each encrypted field. Gate it behind a
            # one-time flag so a large catalog is not re-scanned on every launch.
            flag = conn.execute(
                "SELECT value FROM app_metadata WHERE key = 'sensitive_encrypted'"
            ).fetchone()
            if not (flag and flag["value"] == "1"):
                migrated_sensitive_data = self._migrate_sensitive_values(conn)
                conn.execute(
                    """INSERT INTO app_metadata(key, value)
                       VALUES ('sensitive_encrypted', '1')
                       ON CONFLICT(key) DO UPDATE SET value = excluded.value"""
                )

        if migrated_sensitive_data:
            self._schedule_plaintext_purge()

    def _schedule_plaintext_purge(self):
        """Defer the expensive VACUUM so application startup is not blocked.

        The ciphertext update already happened synchronously in
        ``_init_database``; only the physical reclaim (VACUUM) is deferred
        to a daemon thread with retries, since it can take seconds on large
        databases and would otherwise stall the window opening.
        """
        def _run():
            for _attempt in range(5):
                try:
                    self._purge_plaintext_pages()
                    return
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower():
                        raise
                    time.sleep(1.0)

        self._purge_thread = threading.Thread(
            target=_run, daemon=True, name="iptv-db-vacuum"
        )
        self._purge_thread.start()

    def _migrate_sensitive_values(self, conn: sqlite3.Connection):
        """Encrypt legacy plaintext credentials and URLs in-place."""
        migrated = False
        playlist_columns = (
            "name",
            "url",
            "server_url",
            "username",
            "password",
            "mac_address",
            "epg_source",
            "epg_url",
        )
        for row in conn.execute(
            """SELECT id, name, url, server_url, username, password,
                      mac_address, epg_source, epg_url FROM playlists"""
        ):
            encrypted = {
                column: self._secrets.encrypt(row[column] or "")
                for column in playlist_columns
            }
            if any(encrypted[column] != (row[column] or "") for column in playlist_columns):
                conn.execute(
                    """UPDATE playlists
                       SET name = ?, url = ?, server_url = ?, username = ?,
                           password = ?, mac_address = ?, epg_source = ?, epg_url = ?
                       WHERE id = ?""",
                    (
                        encrypted["name"],
                        encrypted["url"],
                        encrypted["server_url"],
                        encrypted["username"],
                        encrypted["password"],
                        encrypted["mac_address"],
                        encrypted["epg_source"],
                        encrypted["epg_url"],
                        row["id"],
                    ),
                )
                migrated = True

        for row in conn.execute("SELECT id, url, referer, custom_headers FROM channels"):
            encrypted_url = self._secrets.encrypt(row["url"] or "")
            encrypted_referer = self._secrets.encrypt(row["referer"] or "")
            encrypted_headers = self._secrets.encrypt(row["custom_headers"] or "")
            if (
                encrypted_url != row["url"]
                or encrypted_referer != row["referer"]
                or encrypted_headers != row["custom_headers"]
            ):
                conn.execute(
                    """UPDATE channels
                       SET url = ?, referer = ?, custom_headers = ? WHERE id = ?""",
                    (
                        encrypted_url,
                        encrypted_referer,
                        encrypted_headers,
                        row["id"],
                    ),
                )
                migrated = True
        return migrated

    def _purge_plaintext_pages(self):
        """Rebuild SQLite after migration so deleted plaintext cannot linger."""
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("VACUUM")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()

    def save_playlist(self, playlist: Playlist) -> int:
        """Save a playlist and its channels to the database. Returns playlist ID."""
        with self._connection() as conn:
            return self._save_playlist(conn, playlist)

    def _save_playlist(self, conn: sqlite3.Connection, playlist: Playlist) -> int:
        """Insert a playlist using the caller's transaction."""
        cursor = conn.execute(
            """INSERT INTO playlists
               (name, source_type, url, file_path, server_url, username,
                password, mac_address, epg_source, epg_url, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                self._secrets.encrypt(playlist.name),
                playlist.source_type,
                self._secrets.encrypt(playlist.url),
                playlist.file_path,
                self._secrets.encrypt(playlist.server_url),
                self._secrets.encrypt(playlist.username),
                self._secrets.encrypt(playlist.password),
                self._secrets.encrypt(playlist.mac_address),
                self._secrets.encrypt(playlist.epg_source),
                self._secrets.encrypt(playlist.epg_url),
                playlist.created_at,
                playlist.updated_at,
            ),
        )
        playlist_id = cursor.lastrowid

        self._insert_channels(conn, playlist_id, playlist.channels)
        present_types = {
            "vod" if channel.stream_type in ("vod", "movie") else channel.stream_type
            for channel in playlist.channels
        }
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            """INSERT INTO catalog_state
               (playlist_id, content_type, status, item_count, updated_at, error)
               VALUES (?, ?, 'ready', ?, ?, '')
               ON CONFLICT(playlist_id, content_type) DO UPDATE SET
                   status = 'ready', item_count = excluded.item_count,
                   updated_at = excluded.updated_at, error = ''""",
            [
                (
                    playlist_id,
                    content_type,
                    sum(
                        1
                        for channel in playlist.channels
                        if (
                            "vod"
                            if channel.stream_type in ("vod", "movie")
                            else channel.stream_type
                        ) == content_type
                    ),
                    now,
                )
                for content_type in present_types
            ],
        )
        return playlist_id

    def _insert_channels(self, conn, playlist_id: int, channels: list):
        conn.executemany(
            """INSERT INTO channels
               (playlist_id, name, url, group_name, logo, tvg_id, tvg_name,
                epg_channel_id, stream_type, source, xtream_id, category_id,
                user_agent, referer, custom_headers, quality, extension,
                container_extension, country_code, provider_group, is_favorite,
                has_archive, archive_duration_days, content_hash, channel_number)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    playlist_id, channel.name, self._secrets.encrypt(channel.url),
                    channel.group, channel.logo, channel.tvg_id, channel.tvg_name,
                    channel.epg_channel_id, channel.stream_type, channel.source,
                    channel.xtream_id, channel.category_id, channel.user_agent,
                    self._secrets.encrypt(channel.referer),
                    self._secrets.encrypt(json.dumps(channel.custom_headers)),
                    channel.quality, channel.extension, channel.container_extension,
                    channel.country_code, channel.provider_group,
                    int(channel.is_favorite),
                    int(channel.has_archive), channel.archive_duration_days,
                    self._channel_hash(channel),
                    int(channel.channel_number or 0),
                )
                for channel in channels
            ],
        )

    def get_playlists(self) -> list[dict]:
        """Get all saved playlists."""
        return self.playlists.all()

    def get_playlist(self, playlist_id: int) -> Optional[dict]:
        """Get full connection details for a single playlist (needed to
        reconstruct an authenticated parser for lazy VOD/series calls)."""
        return self.playlists.get(playlist_id)

    def get_metadata_flag(self, key: str) -> bool:
        """Read a boolean flag from ``app_metadata`` (gates one-time migrations)."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT value FROM app_metadata WHERE key = ?", (key,)
            ).fetchone()
        return bool(row and row["value"] == "1")

    def set_metadata_flag(self, key: str) -> None:
        """Set a boolean flag in ``app_metadata``."""
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO app_metadata(key, value) VALUES (?, '1')
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key,),
            )

    def export_backup_data(self) -> dict:
        return build_backup_data(self)

    def import_backup_data(self, data: dict) -> list[int]:
        validated_playlists = parse_backup_data(data)

        # Validate the complete payload before writing, then restore everything
        # in one transaction so a failure cannot leave a partial import behind.
        with self._connection() as conn:
            return [
                self._save_playlist(conn, playlist)
                for playlist in validated_playlists
            ]

    def rename_playlist(self, playlist_id: int, new_name: str):
        """Change only the user-facing name of an existing playlist."""
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("O nome da playlist não pode ficar vazio.")
        with self._connection() as conn:
            cursor = conn.execute(
                """UPDATE playlists
                   SET name = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    self._secrets.encrypt(new_name),
                    datetime.now(timezone.utc).isoformat(),
                    playlist_id,
                ),
            )
            if cursor.rowcount != 1:
                raise LookupError("Playlist não encontrada.")

    def update_playlist_connection(self, playlist_id: int, values: dict):
        """Update tested connection details while preserving the playlist ID."""
        current = self.get_playlist(playlist_id)
        if not current:
            raise LookupError("Playlist não encontrada.")
        current.update(values)
        name = str(current.get("name", "")).strip()
        if not name:
            raise ValueError("O nome da playlist não pode ficar vazio.")
        with self._connection() as conn:
            conn.execute(
                """UPDATE playlists SET name = ?, url = ?, file_path = ?,
                   server_url = ?, username = ?, password = ?, mac_address = ?,
                   epg_source = ?, epg_url = ?, updated_at = ? WHERE id = ?""",
                (
                    self._secrets.encrypt(name),
                    self._secrets.encrypt(current.get("url", "")),
                    current.get("file_path", ""),
                    self._secrets.encrypt(current.get("server_url", "")),
                    self._secrets.encrypt(current.get("username", "")),
                    self._secrets.encrypt(current.get("password", "")),
                    self._secrets.encrypt(current.get("mac_address", "")),
                    self._secrets.encrypt(current.get("epg_source", "")),
                    self._secrets.encrypt(current.get("epg_url", "")),
                    datetime.now(timezone.utc).isoformat(),
                    playlist_id,
                ),
            )

    def _decrypt_playlist_row(self, row: dict) -> dict:
        for column in (
            "name",
            "url",
            "server_url",
            "username",
            "password",
            "mac_address",
            "epg_source",
            "epg_url",
        ):
            if column in row:
                row[column] = self._secrets.decrypt(row[column] or "")
        return row

    def _row_to_channel(self, row, decrypt_urls: bool = True) -> Channel:
        """Build a Channel from a `channels` table row.

        ``decrypt_urls=False`` skips the expensive AES-GCM work on the encrypted
        columns (``url``/``referer``/``custom_headers``), leaving them empty.
        Listing/search/EPG code that only needs metadata uses this to avoid
        decrypting an entire catalogue on the hot path.
        """
        return Channel(
            database_id=row["id"],
            name=row["name"],
            url=self._secrets.decrypt(row["url"]) if decrypt_urls else "",
            group=row["group_name"],
            logo=row["logo"],
            tvg_id=row["tvg_id"],
            tvg_name=row["tvg_name"],
            epg_channel_id=row["epg_channel_id"],
            stream_type=row["stream_type"],
            source=row["source"],
            xtream_id=row["xtream_id"],
            category_id=row["category_id"],
            user_agent=row["user_agent"],
            referer=self._secrets.decrypt(row["referer"]) if decrypt_urls else "",
            custom_headers=(
                DatabaseManager._decode_headers(self._secrets.decrypt(row["custom_headers"]))
                if decrypt_urls
                else {}
            ),
            quality=row["quality"],
            extension=row["extension"],
            container_extension=row["container_extension"],
            country_code=row["country_code"],
            provider_group=row["provider_group"],
            is_favorite=bool(row["is_favorite"]),
            has_archive=bool(row["has_archive"]),
            archive_duration_days=row["archive_duration_days"],
            channel_number=int(row["channel_number"] or 0),
        )

    @staticmethod
    def _decode_headers(value: str) -> dict:
        try:
            decoded = json.loads(value or "{}")
            return decoded if isinstance(decoded, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    def get_channels(
        self,
        playlist_id: int,
        group: Optional[str] = None,
        stream_type: Optional[str] = None,
        decrypt_urls: bool = True,
    ) -> list[Channel]:
        """Get channels for a playlist, optionally filtered by group and stream_type."""
        with self._connection() as conn:
            query = "SELECT * FROM channels WHERE playlist_id = ?"
            params: list = [playlist_id]
            if stream_type:
                if stream_type == "vod":
                    query += " AND stream_type IN ('vod', 'movie')"
                else:
                    query += " AND stream_type = ?"
                    params.append(stream_type)
            if group:
                query += " AND group_name = ?"
                params.append(group)
            query += " ORDER BY id"
            cursor = conn.execute(query, params)
            return [
                self._row_to_channel(row, decrypt_urls=decrypt_urls)
                for row in cursor.fetchall()
            ]

    def get_channel(self, channel_id: int, playlist_id: int) -> Optional[Channel]:
        """Fetch and decrypt a single channel (used to hydrate light rows)."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM channels WHERE id = ? AND playlist_id = ?",
                (channel_id, playlist_id),
            ).fetchone()
        return self._row_to_channel(row) if row else None

    def get_groups(self, playlist_id: int, stream_type: Optional[str] = None) -> list[str]:
        """Get unique channel groups for a playlist, optionally filtered by stream_type."""
        with self._connection() as conn:
            query = "SELECT DISTINCT group_name FROM channels WHERE playlist_id = ?"
            params: list = [playlist_id]
            if stream_type:
                if stream_type == "vod":
                    query += " AND stream_type IN ('vod', 'movie')"
                else:
                    query += " AND stream_type = ?"
                    params.append(stream_type)
            query += " AND group_name != '' ORDER BY group_name"
            cursor = conn.execute(query, params)
            return [row["group_name"] for row in cursor.fetchall()]

    def set_favorite(self, channel_id: int, playlist_id: int, is_favorite: bool) -> bool:
        """Set favorite status for one channel identified by its database ID."""
        with self._connection() as conn:
            cursor = conn.execute(
                """UPDATE channels SET is_favorite = ?
                   WHERE id = ? AND playlist_id = ?""",
                (int(is_favorite), channel_id, playlist_id),
            )
            if cursor.rowcount != 1:
                raise LookupError("Canal não encontrado na playlist.")
        return is_favorite

    def update_stalker_headers(
        self, playlist_id: int, user_agent: str, referer: str
    ):
        """Repair playback headers for Stalker channels saved by older versions."""
        with self._connection() as conn:
            conn.execute(
                """UPDATE channels
                   SET user_agent = ?, referer = ?
                   WHERE playlist_id = ? AND source = 'stalker'""",
                (user_agent, self._secrets.encrypt(referer), playlist_id),
            )

    def update_stalker_channel_metadata(
        self, playlist_id: int, channels: list
    ):
        """Update origin categories for channels saved by older versions."""
        with self._connection() as conn:
            conn.executemany(
                """UPDATE channels
                   SET group_name = ?, category_id = ?, country_code = ?,
                       provider_group = ?, user_agent = ?, referer = ?
                   WHERE playlist_id = ? AND source = 'stalker' AND tvg_id = ?""",
                [
                    (
                        channel.group,
                        channel.category_id,
                        channel.country_code,
                        channel.provider_group,
                        channel.user_agent,
                        self._secrets.encrypt(channel.referer),
                        playlist_id,
                        channel.tvg_id,
                    )
                    for channel in channels
                    if channel.tvg_id
                ],
            )

    def update_channel_stream_types(self, playlist_id: int, channels: list):
        """Persist repaired media types and rebuild catalogue counts."""
        allowed = {"live", "vod", "movie", "series"}
        updates = [
            (channel.stream_type, channel.database_id, playlist_id)
            for channel in channels
            if channel.database_id and channel.stream_type in allowed
        ]
        with self._connection() as conn:
            conn.executemany(
                """UPDATE channels SET stream_type = ?
                   WHERE id = ? AND playlist_id = ?""",
                updates,
            )
            counts = {"live": 0, "vod": 0, "series": 0}
            for channel in channels:
                content_type = (
                    "vod"
                    if channel.stream_type in ("vod", "movie")
                    else channel.stream_type
                )
                if content_type in counts:
                    counts[content_type] += 1
            now = datetime.now(timezone.utc).isoformat()
            conn.executemany(
                """INSERT INTO catalog_state
                   (playlist_id, content_type, status, item_count, updated_at, error)
                   VALUES (?, ?, 'ready', ?, ?, '')
                   ON CONFLICT(playlist_id, content_type) DO UPDATE SET
                       status = 'ready', item_count = excluded.item_count,
                       updated_at = excluded.updated_at, error = ''""",
                [
                    (playlist_id, content_type, count, now)
                    for content_type, count in counts.items()
                ],
            )

    def get_favorites(self, playlist_id: int) -> list[Channel]:
        """Get all favorited channels for a playlist."""
        with self._connection() as conn:
            cursor = conn.execute(
                """SELECT * FROM channels
                   WHERE playlist_id = ? AND is_favorite = 1
                   ORDER BY group_name, name""",
                (playlist_id,),
            )
            return [self._row_to_channel(row) for row in cursor.fetchall()]

    def get_channel_page(
        self,
        playlist_id: int,
        content_type: str,
        page: int = 0,
        page_size: int = 250,
        group: str = "",
        query: str = "",
    ) -> list[Channel]:
        """Return one deterministic catalogue page without loading all rows."""
        return self.catalogs.page(
            playlist_id, content_type, page, page_size, group, query
        )

    def count_channels(
        self,
        playlist_id: int,
        content_type: str,
        group: str = "",
        query: str = "",
    ) -> int:
        """Count rows matching the same filters used by get_channel_page()."""
        return self.catalogs.count(
            playlist_id, content_type, group, query
        )

    @staticmethod
    def _catalog_stream_types(content_type: str) -> tuple:
        if content_type == "vod":
            return ("vod", "movie")
        if content_type in ("live", "series"):
            return (content_type,)
        raise ValueError(f"Tipo de catálogo inválido: {content_type}")

    @staticmethod
    def _channel_identity(channel: Channel) -> tuple:
        stable_id = (
            channel.xtream_id
            or channel.tvg_id
            or channel.epg_channel_id
            or channel.name.casefold().strip()
        )
        stream_type = (
            "vod" if channel.stream_type in ("vod", "movie") else channel.stream_type
        )
        return channel.source, stream_type, str(stable_id)

    @staticmethod
    def _row_identity(row) -> tuple:
        stable_id = (
            row["xtream_id"]
            or row["tvg_id"]
            or row["epg_channel_id"]
            or row["name"].casefold().strip()
        )
        stream_type = (
            "vod" if row["stream_type"] in ("vod", "movie") else row["stream_type"]
        )
        return row["source"], stream_type, str(stable_id)

    @staticmethod
    def _channel_hash(channel: Channel) -> str:
        fields = (
            channel.name,
            channel.url,
            channel.group,
            channel.logo,
            channel.tvg_id,
            channel.tvg_name,
            channel.epg_channel_id,
            channel.stream_type,
            channel.source,
            channel.xtream_id,
            channel.category_id,
            channel.user_agent,
            channel.referer,
            json.dumps(channel.custom_headers, sort_keys=True, separators=(",", ":")),
            channel.quality,
            channel.extension,
            channel.container_extension,
            channel.country_code,
            channel.provider_group,
            int(channel.has_archive),
            channel.archive_duration_days,
        )
        payload = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _update_channel(
        self,
        conn: sqlite3.Connection,
        channel_id: int,
        playlist_id: int,
        channel: Channel,
    ) -> None:
        conn.execute(
            """UPDATE channels SET name = ?, url = ?, group_name = ?, logo = ?,
               tvg_id = ?, tvg_name = ?, epg_channel_id = ?, stream_type = ?,
               source = ?, xtream_id = ?, category_id = ?, user_agent = ?,
               referer = ?, custom_headers = ?, quality = ?, extension = ?,
               container_extension = ?, country_code = ?, provider_group = ?,
               has_archive = ?, archive_duration_days = ?, content_hash = ?,
               channel_number = ?
               WHERE id = ? AND playlist_id = ?""",
            (
                channel.name,
                self._secrets.encrypt(channel.url),
                channel.group,
                channel.logo,
                channel.tvg_id,
                channel.tvg_name,
                channel.epg_channel_id,
                channel.stream_type,
                channel.source,
                channel.xtream_id,
                channel.category_id,
                channel.user_agent,
                self._secrets.encrypt(channel.referer),
                self._secrets.encrypt(json.dumps(channel.custom_headers)),
                channel.quality,
                channel.extension,
                channel.container_extension,
                channel.country_code,
                channel.provider_group,
                int(channel.has_archive),
                channel.archive_duration_days,
                self._channel_hash(channel),
                int(channel.channel_number or 0),
                channel_id,
                playlist_id,
            ),
        )

    def get_catalog_state(self, playlist_id: int, content_type: str) -> Optional[dict]:
        """Return persisted lazy-catalog state, detecting legacy cached data."""
        stream_types = self._catalog_stream_types(content_type)
        with self._connection() as conn:
            row = conn.execute(
                """SELECT playlist_id, content_type, status, item_count,
                          updated_at, error
                   FROM catalog_state
                   WHERE playlist_id = ? AND content_type = ?""",
                (playlist_id, content_type),
            ).fetchone()
            if row:
                return dict(row)

            placeholders = ",".join("?" for _ in stream_types)
            count = conn.execute(
                f"""SELECT COUNT(*) FROM channels
                    WHERE playlist_id = ? AND stream_type IN ({placeholders})""",
                (playlist_id, *stream_types),
            ).fetchone()[0]
            if count:
                return {
                    "playlist_id": playlist_id,
                    "content_type": content_type,
                    "status": "ready",
                    "item_count": count,
                    "updated_at": "",
                    "error": "",
                }
            return None

    def set_catalog_state(
        self,
        playlist_id: int,
        content_type: str,
        status: str,
        item_count: int = 0,
        error: str = "",
    ):
        self._catalog_stream_types(content_type)
        with self._connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM playlists WHERE id = ?", (playlist_id,)
            ).fetchone()
            if not exists:
                # A background catalog load may still be running when its
                # playlist is deleted; there is no state row left to update.
                return
            conn.execute(
                """INSERT INTO catalog_state
                   (playlist_id, content_type, status, item_count, updated_at, error)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(playlist_id, content_type) DO UPDATE SET
                       status = excluded.status,
                       item_count = excluded.item_count,
                       updated_at = excluded.updated_at,
                       error = excluded.error""",
                (
                    playlist_id,
                    content_type,
                    status,
                    max(0, int(item_count)),
                    datetime.now(timezone.utc).isoformat(),
                    error[:500],
                ),
            )

    def replace_catalog(
        self, playlist_id: int, content_type: str, channels: list
    ) -> list[Channel]:
        """Differentially refresh one catalogue while retaining IDs and favorites."""
        stream_types = self._catalog_stream_types(content_type)
        with self._connection() as conn:
            placeholders = ",".join("?" for _ in stream_types)
            old_rows = conn.execute(
                f"""SELECT * FROM channels
                    WHERE playlist_id = ? AND stream_type IN ({placeholders})""",
                (playlist_id, *stream_types),
            ).fetchall()
            old_by_identity: dict[tuple, list] = {}
            for row in old_rows:
                old_by_identity.setdefault(self._row_identity(row), []).append(row)
            inserts = []
            for channel in channels:
                bucket = old_by_identity.get(self._channel_identity(channel), [])
                old = bucket.pop(0) if bucket else None
                if old is None:
                    inserts.append(channel)
                    continue
                channel.is_favorite = channel.is_favorite or bool(old["is_favorite"])
                if (old["content_hash"] or "") != self._channel_hash(channel):
                    self._update_channel(conn, old["id"], playlist_id, channel)
            stale_ids = [
                row["id"] for bucket in old_by_identity.values() for row in bucket
            ]
            if stale_ids:
                conn.executemany(
                    "DELETE FROM channels WHERE id = ? AND playlist_id = ?",
                    [(channel_id, playlist_id) for channel_id in stale_ids],
                )
            if inserts:
                self._insert_channels(conn, playlist_id, inserts)
            conn.execute(
                """INSERT INTO catalog_state
                   (playlist_id, content_type, status, item_count, updated_at, error)
                   VALUES (?, ?, 'ready', ?, ?, '')
                   ON CONFLICT(playlist_id, content_type) DO UPDATE SET
                       status = 'ready', item_count = excluded.item_count,
                       updated_at = excluded.updated_at, error = ''""",
                (
                    playlist_id,
                    content_type,
                    len(channels),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return self.get_channels(playlist_id)

    def search_channels(self, playlist_id: int, query: str) -> list[Channel]:
        """Search channels by name (SQL LIKE wildcards treated literally)."""
        expression = fts_query(query)
        if expression:
            with self._connection() as conn:
                rows = conn.execute(
                    """SELECT channels.* FROM channels_fts
                       JOIN channels ON channels.id = channels_fts.rowid
                       WHERE channels.playlist_id = ? AND channels_fts MATCH ?
                       ORDER BY rank, channels.group_name, channels.name""",
                    (playlist_id, expression),
                ).fetchall()
                if rows:
                    return [self._row_to_channel(row) for row in rows]
        escaped = (
            query.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        with self._connection() as conn:
            cursor = conn.execute(
                """SELECT * FROM channels
                   WHERE playlist_id = ? AND name LIKE ? ESCAPE '\\'
                   ORDER BY group_name, name""",
                (playlist_id, f"%{escaped}%"),
            )
            return [self._row_to_channel(row) for row in cursor.fetchall()]

    def search_all_channels(self, query: str, limit: int = 500) -> list[dict]:
        """Search every local catalogue and include its decrypted playlist name."""
        query = query.strip()
        if len(query) < 2:
            return []
        limit = max(1, min(int(limit), 1000))
        with self._connection() as conn:
            playlist_names = {
                row["id"]: self._secrets.decrypt(row["name"] or "")
                for row in conn.execute("SELECT id, name FROM playlists")
            }
            expression = fts_query(query)
            rows = (
                conn.execute(
                    """SELECT channels.* FROM channels_fts
                       JOIN channels ON channels.id = channels_fts.rowid
                       WHERE channels_fts MATCH ?
                       ORDER BY rank, channels.name COLLATE NOCASE LIMIT ?""",
                    (expression, limit),
                ).fetchall()
                if expression
                else []
            )
            if not rows:
                rows = conn.execute(
                    """SELECT * FROM channels
                       WHERE instr(lower(name), lower(?)) > 0
                          OR instr(lower(group_name), lower(?)) > 0
                       ORDER BY name COLLATE NOCASE, id LIMIT ?""",
                    (query, query, limit),
                ).fetchall()
            return [
                {
                    "playlist_id": row["playlist_id"],
                    "playlist_name": playlist_names.get(row["playlist_id"], "Playlist"),
                    "channel": self._row_to_channel(row),
                }
                for row in rows
            ]

    def delete_playlist(self, playlist_id: int):
        """Delete a playlist and its channels."""
        with self._connection() as conn:
            conn.execute("DELETE FROM channels WHERE playlist_id = ?", (playlist_id,))
            conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))

    def record_playback(self, playlist_id: int, channel: Channel):
        """Store minimal recent-playback metadata and keep the list bounded."""
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO playback_history
                   (playlist_id, channel_id, title, stream_type, played_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    playlist_id,
                    max(0, int(channel.database_id or 0)),
                    channel.name,
                    channel.stream_type,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.execute(
                """DELETE FROM playback_history
                   WHERE playlist_id = ? AND id NOT IN (
                       SELECT id FROM playback_history
                       WHERE playlist_id = ? ORDER BY played_at DESC, id DESC
                       LIMIT 100
                   )""",
                (playlist_id, playlist_id),
            )

    def get_recent_playback(self, playlist_id: int, limit: int = 20) -> list[dict]:
        """Return recent playback entries without exposing stream URLs."""
        limit = max(1, min(int(limit), 100))
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT channel_id, title, stream_type, played_at
                   FROM playback_history WHERE playlist_id = ?
                   ORDER BY played_at DESC, id DESC LIMIT ?""",
                (playlist_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    @classmethod
    def _playback_key(cls, channel: Channel) -> str:
        source, stream_type, stable_id = cls._channel_identity(channel)
        return json.dumps(
            [source, stream_type, stable_id], ensure_ascii=False, separators=(",", ":")
        )

    def save_playback_progress(
        self,
        playlist_id: int,
        channel: Channel,
        position_ms: int,
        length_ms: int,
    ):
        """Persist resumable VOD/series progress without storing a stream URL."""
        if channel.stream_type == "live" or length_ms <= 0:
            return
        media_key = self._playback_key(channel)
        with self._connection() as conn:
            if position_ms < 10_000 or position_ms >= length_ms * 0.95:
                conn.execute(
                    "DELETE FROM playback_progress WHERE playlist_id = ? AND media_key = ?",
                    (playlist_id, media_key),
                )
                return
            conn.execute(
                """INSERT INTO playback_progress
                   (playlist_id, media_key, position_ms, length_ms, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(playlist_id, media_key) DO UPDATE SET
                       position_ms = excluded.position_ms,
                       length_ms = excluded.length_ms,
                       updated_at = excluded.updated_at""",
                (
                    playlist_id,
                    media_key,
                    max(0, int(position_ms)),
                    max(0, int(length_ms)),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_playback_progress(self, playlist_id: int, channel: Channel) -> Optional[dict]:
        if channel.stream_type == "live":
            return None
        with self._connection() as conn:
            row = conn.execute(
                """SELECT position_ms, length_ms, updated_at FROM playback_progress
                   WHERE playlist_id = ? AND media_key = ?""",
                (playlist_id, self._playback_key(channel)),
            ).fetchone()
            return dict(row) if row else None

    def get_resume_candidates(self, playlist_id: int) -> list[dict]:
        """Non-live channels with in-progress playback, newest first.

        Each entry carries the full Channel (with decrypted URL) so the UI can
        resume it directly, plus position/length/fraction for display.
        """
        progress_by_key = {}
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT media_key, position_ms, length_ms, updated_at
                   FROM playback_progress WHERE playlist_id = ?""",
                (playlist_id,),
            ).fetchall()
            for row in rows:
                progress_by_key[row["media_key"]] = dict(row)
        if not progress_by_key:
            return []

        results = []
        for channel in self.get_channels(playlist_id):
            if channel.stream_type == "live":
                continue
            progress = progress_by_key.get(self._playback_key(channel))
            if not progress or not progress.get("length_ms"):
                continue
            fraction = progress["position_ms"] / progress["length_ms"]
            if 0.0 < fraction < 0.95:
                results.append({
                    "channel": channel,
                    "position_ms": progress["position_ms"],
                    "length_ms": progress["length_ms"],
                    "fraction": fraction,
                    "updated_at": progress["updated_at"],
                })
        results.sort(key=lambda item: item["updated_at"], reverse=True)
        return results

    def cache_epg(self, programs: list):
        """Cache EPG programs in the database."""
        with self._connection() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO epg_cache (channel_id, title, start_time, stop_time, description, category)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [(p.channel_id, p.title, p.start.isoformat(), p.stop.isoformat(),
                  p.description, p.category) for p in programs]
            )

    def get_epg(self, channel_id: str) -> list[dict]:
        """Get cached EPG data for a channel."""
        with self._connection() as conn:
            cursor = conn.execute(
                """SELECT * FROM epg_cache WHERE channel_id = ? ORDER BY start_time LIMIT 50""",
                (channel_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def replace_playlist_epg(self, playlist_id: int, programs: list):
        """Atomically replace a playlist's full XMLTV cache."""
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM playlist_epg_cache WHERE playlist_id = ?",
                (playlist_id,),
            )
            self._insert_playlist_epg(conn, playlist_id, programs)
            conn.execute(
                """INSERT INTO epg_metadata (playlist_id, last_updated)
                   VALUES (?, ?)
                   ON CONFLICT(playlist_id) DO UPDATE
                   SET last_updated = excluded.last_updated""",
                (playlist_id, datetime.now(timezone.utc).isoformat()),
            )

    def replace_channel_epg(
        self, playlist_id: int, channel_id: str, programs: list
    ):
        """Replace cached EPG for one channel without marking the full source fresh."""
        with self._connection() as conn:
            conn.execute(
                """DELETE FROM playlist_epg_cache
                   WHERE playlist_id = ? AND channel_id = ?""",
                (playlist_id, channel_id),
            )
            self._insert_playlist_epg(conn, playlist_id, programs)

    @staticmethod
    def _insert_playlist_epg(conn, playlist_id: int, programs: list):
        conn.executemany(
            """INSERT OR REPLACE INTO playlist_epg_cache
               (playlist_id, channel_id, title, start_time, stop_time,
                description, category)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    playlist_id,
                    program.channel_id,
                    program.title,
                    program.start.isoformat(),
                    program.stop.isoformat(),
                    program.description,
                    program.category,
                )
                for program in programs
            ],
        )

    def get_playlist_epg(
        self, playlist_id: int, channel_id: Optional[str] = None
    ) -> list[EPGProgram]:
        """Load cached EPG programs for a playlist or one of its channels."""
        with self._connection() as conn:
            if channel_id:
                cursor = conn.execute(
                    """SELECT * FROM playlist_epg_cache
                       WHERE playlist_id = ? AND channel_id = ?
                       ORDER BY start_time""",
                    (playlist_id, channel_id),
                )
            else:
                cursor = conn.execute(
                    """SELECT * FROM playlist_epg_cache
                       WHERE playlist_id = ? ORDER BY channel_id, start_time""",
                    (playlist_id,),
                )
            return [
                EPGProgram(
                    channel_id=row["channel_id"],
                    title=row["title"],
                    start=datetime.fromisoformat(row["start_time"]),
                    stop=datetime.fromisoformat(row["stop_time"]),
                    description=row["description"],
                    category=row["category"],
                )
                for row in cursor.fetchall()
            ]

    def get_epg_last_updated(self, playlist_id: int) -> Optional[datetime]:
        """Return the UTC timestamp of the last complete EPG refresh."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT last_updated FROM epg_metadata WHERE playlist_id = ?",
                (playlist_id,),
            ).fetchone()
            return datetime.fromisoformat(row["last_updated"]) if row else None

    def lock_group(self, playlist_id: int, group_name: str):
        """Mark a category as parental-locked for a playlist."""
        with self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO locked_groups (playlist_id, group_name) VALUES (?, ?)",
                (playlist_id, group_name),
            )

    def unlock_group(self, playlist_id: int, group_name: str):
        """Permanently remove a category's parental lock."""
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM locked_groups WHERE playlist_id = ? AND group_name = ?",
                (playlist_id, group_name),
            )

    def get_locked_groups(self, playlist_id: int) -> set:
        """Return the set of category names locked for a playlist."""
        with self._connection() as conn:
            cursor = conn.execute(
                "SELECT group_name FROM locked_groups WHERE playlist_id = ?",
                (playlist_id,),
            )
            return {row["group_name"] for row in cursor.fetchall()}
