"""Explicit, ordered SQLite schema migrations."""

import re
import sqlite3
from collections.abc import Callable

CURRENT_SCHEMA_VERSION = 6
BASELINE_SCHEMA_VERSION = 4


def _migration_5_catalog_fts(conn: sqlite3.Connection) -> None:
    """Add a contentless search index kept in sync with ``channels``."""
    conn.executescript(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS channels_fts USING fts5(
            name, group_name, tvg_id,
            content='channels', content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TRIGGER IF NOT EXISTS channels_fts_insert AFTER INSERT ON channels BEGIN
            INSERT INTO channels_fts(rowid, name, group_name, tvg_id)
            VALUES (new.id, new.name, new.group_name, new.tvg_id);
        END;
        CREATE TRIGGER IF NOT EXISTS channels_fts_delete AFTER DELETE ON channels BEGIN
            INSERT INTO channels_fts(channels_fts, rowid, name, group_name, tvg_id)
            VALUES ('delete', old.id, old.name, old.group_name, old.tvg_id);
        END;
        CREATE TRIGGER IF NOT EXISTS channels_fts_update AFTER UPDATE ON channels BEGIN
            INSERT INTO channels_fts(channels_fts, rowid, name, group_name, tvg_id)
            VALUES ('delete', old.id, old.name, old.group_name, old.tvg_id);
            INSERT INTO channels_fts(rowid, name, group_name, tvg_id)
            VALUES (new.id, new.name, new.group_name, new.tvg_id);
        END;
        INSERT INTO channels_fts(channels_fts) VALUES ('rebuild');
        """
    )


def _migration_6_catalog_hashes(conn: sqlite3.Connection) -> None:
    """Persist hashes used to skip unchanged encrypted catalogue rows."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(channels)")}
    if "content_hash" not in columns:
        conn.execute("ALTER TABLE channels ADD COLUMN content_hash TEXT DEFAULT ''")
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_channels_differential
           ON channels(playlist_id, stream_type, source, xtream_id, tvg_id, name)"""
    )


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    5: _migration_5_catalog_fts,
    6: _migration_6_catalog_hashes,
}


def run_migrations(conn: sqlite3.Connection) -> int:
    """Upgrade a baseline database atomically and return its final version."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    row = conn.execute(
        "SELECT value FROM app_metadata WHERE key = 'schema_version'"
    ).fetchone()
    version = int(row[0]) if row else BASELINE_SCHEMA_VERSION
    if version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"Base de dados v{version} não suportada por esta aplicação "
            f"(máximo v{CURRENT_SCHEMA_VERSION})."
        )
    for target in range(version + 1, CURRENT_SCHEMA_VERSION + 1):
        migration = MIGRATIONS.get(target)
        if migration is None:
            raise RuntimeError(f"Migração SQLite v{target} em falta.")
        migration(conn)
        conn.execute(
            """INSERT INTO app_metadata(key, value) VALUES ('schema_version', ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (str(target),),
        )
    if row is None and version == CURRENT_SCHEMA_VERSION:
        conn.execute(
            "INSERT INTO app_metadata(key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )
    return CURRENT_SCHEMA_VERSION


def fts_query(value: str) -> str:
    """Build a safe prefix query; an empty result requests the SQL fallback."""
    if any(not char.isalnum() and not char.isspace() for char in value):
        return ""
    tokens = re.findall(r"[\w]+", value.casefold(), flags=re.UNICODE)
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens)
