"""Regression tests for the local, network-independent application core."""

import base64
import gzip
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QSignalSpy

from config.settings import Settings
from src.controllers.epg_controller import EpgController
from src.controllers.playback_controller import PlaybackController
from src.controllers.playlist_controller import PlaylistController
from src.controllers.task_controller import TaskController
from src.core import epg_loader
from src.core.backup import create_backup, read_backup
from src.core.channel import Channel
from src.core.database import DatabaseManager
from src.core.device_sync import export_device_state, import_device_state, media_key
from src.core.diagnostics import diagnose_channel
from src.core.epg import EPGProgram, EPGSource
from src.core.epg_loader import load_xmltv
from src.core.parental import PinAttemptLimiter
from src.core.playlist import Playlist
from src.core.provider_sessions import ProviderSessionManager
from src.core.providers import CatalogKind, Provider
from src.core.secrets import SecretStore
from src.core.task_manager import TaskWorker
from src.core.update_manager import (
    ReleaseArtifact,
    is_newer_version,
    parse_manifest,
    verify_artifact,
)
from src.parsers.m3u_parser import M3UParser
from src.parsers.stalker_parser import StalkerParser
from src.parsers.xtream_parser import XtreamParser
from src.player.media_player import MediaPlayer
from src.utils.logger import redact_sensitive


class SecretStoreTests(unittest.TestCase):
    def test_encrypt_handles_plaintext_with_enc_prefix(self):
        store = SecretStore.for_tests()
        # Plaintext that merely happens to start with the prefix must still
        # be encrypted rather than silently passed through.
        value = "enc:v1:https://example.com/live/seg"
        encrypted = store.encrypt(value)
        self.assertTrue(encrypted.startswith(SecretStore.PREFIX))
        self.assertEqual(store.decrypt(encrypted), value)

    def test_encrypt_passes_genuine_ciphertext_through(self):
        store = SecretStore.for_tests()
        ciphertext = store.encrypt("segredo")
        self.assertEqual(store.encrypt(ciphertext), ciphertext)


class SettingsTests(unittest.TestCase):
    def test_load_removes_legacy_stream_url_and_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "settings.json"
            config_file.write_text(
                json.dumps(
                    {
                        "volume": "máximo",
                        "last_channel_url": "https://user:password@example.test/live",
                        "unknown": "ignored",
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(Settings, "_get_config_dir", return_value=config_dir):
                settings = Settings()

            persisted = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertEqual(settings.get("volume"), 80)
            self.assertNotIn("last_channel_url", persisted)
            self.assertNotIn("unknown", persisted)
            self.assertFalse(list(config_dir.glob("settings-*.tmp")))

    def test_set_many_validates_before_changing_any_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(Settings, "_get_config_dir", return_value=Path(temp_dir)):
                settings = Settings()
                with self.assertRaises(ValueError):
                    settings.set_many({"volume": 25, "max_connections": "many"})

            self.assertEqual(settings.get("volume"), 80)

    def test_nullable_ids_and_numeric_ranges_are_validated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(Settings, "_get_config_dir", return_value=Path(temp_dir)):
                settings = Settings()
                settings.set_many({"last_playlist_id": 42, "volume": 100})
                with self.assertRaises(ValueError):
                    settings.set("volume", 101)

            self.assertEqual(settings.get("last_playlist_id"), 42)
            self.assertEqual(settings.get("volume"), 100)


class ParentalSecurityTests(unittest.TestCase):
    def test_pin_attempts_are_temporarily_rate_limited(self):
        now = [100.0]
        limiter = PinAttemptLimiter(
            max_attempts=3,
            lock_seconds=30,
            clock=lambda: now[0],
        )
        for _ in range(3):
            limiter.register_failure()
        self.assertFalse(limiter.is_allowed())
        self.assertEqual(limiter.remaining_seconds, 30)
        now[0] += 30
        self.assertTrue(limiter.is_allowed())

    def test_pin_hash_is_verifiable_and_tamper_proof(self):
        from src.core.parental import generate_salt, hash_pin, verify_pin

        salt = generate_salt()
        digest = hash_pin("1234", salt)

        self.assertTrue(verify_pin("1234", salt, digest))
        self.assertFalse(verify_pin("4321", salt, digest))
        self.assertFalse(verify_pin("1234", salt, digest[:-2] + "00"))


class HelpersAndCacheTests(unittest.TestCase):
    def test_format_duration_handles_hours_minutes_and_negative(self):
        from src.utils.helpers import format_duration

        self.assertEqual(format_duration(0), "00:00")
        self.assertEqual(format_duration(65), "01:05")
        self.assertEqual(format_duration(3661), "01:01:01")
        self.assertEqual(format_duration(-5), "00:00")

    def test_sanitize_filename_strips_invalid_characters(self):
        from src.utils.helpers import sanitize_filename

        self.assertEqual(sanitize_filename('a<b>c:d"e/f\\g|h?i*j'), "abcdefghij")
        self.assertEqual(sanitize_filename("...name..."), "name")

    def test_parse_epg_time_supports_common_formats(self):
        from src.utils.helpers import parse_epg_time

        self.assertIsNotNone(parse_epg_time("20260724120000 +0000"))
        self.assertIsNotNone(parse_epg_time("2026-07-24 12:00:00"))
        self.assertIsNone(parse_epg_time("not-a-date"))

    def test_http_session_cancels_before_request(self):
        from src.core.http_client import HttpSession, RequestCancelled

        session = HttpSession(timeout=30, cancel_requested=lambda: True)
        with self.assertRaises(RequestCancelled):
            session.get("https://example.test/")

    def test_http_session_applies_default_timeout(self):
        from src.core.http_client import HttpSession

        self.assertEqual(HttpSession(timeout=15)._default_timeout, 15)
        self.assertEqual(HttpSession(timeout=1)._default_timeout, 5)

    def test_http_retry_methods_are_configurable(self):
        from src.core.http_client import HttpSession

        default_adapter = HttpSession().get_adapter("https://example.test")
        post_adapter = HttpSession(
            retry_methods=frozenset({"GET", "POST"})
        ).get_adapter("https://example.test")

        self.assertNotIn("POST", default_adapter.max_retries.allowed_methods)
        self.assertIn("POST", post_adapter.max_retries.allowed_methods)

    def test_http_session_cancellation_predicate_can_be_swapped(self):
        from src.core.http_client import HttpSession, RequestCancelled

        session = HttpSession()
        session.set_cancel_requested(lambda: True)
        with self.assertRaises(RequestCancelled):
            session.get("https://example.test/")

    def test_stalker_session_retries_post_requests(self):
        parser = StalkerParser("https://example.test", "00:00:00:00:00:00")
        adapter = parser._session.get_adapter("https://example.test")
        try:
            self.assertIn("POST", adapter.max_retries.allowed_methods)
        finally:
            parser.close()

    def test_image_cache_round_trips_and_reports_misses(self):
        import tempfile as _tempfile
        from pathlib import Path as _Path

        from src.core.image_cache import ImageCache

        with _tempfile.TemporaryDirectory() as directory:
            cache = ImageCache(_Path(directory), max_mb=1)
            cache.write("https://example.test/logo.png", b"data")
            self.assertEqual(cache.read("https://example.test/logo.png"), b"data")
            self.assertIsNone(cache.read("https://example.test/missing.png"))

    def test_xtream_provider_dispatches_catalog_kinds(self):
        from src.core.providers import CatalogKind, XtreamProvider

        class FakeParser:
            def get_live_channels(self):
                return [Channel("Live", "https://live.test")]

            def get_vod_streams(self):
                return [Channel("Vod", "https://vod.test")]

            def get_series_channels(self, should_cancel=None, progress=None):
                return [Channel("Series", "https://series.test")]

        provider = XtreamProvider(FakeParser())
        self.assertEqual(provider.load_catalog(CatalogKind.LIVE)[0].name, "Live")
        self.assertEqual(provider.load_catalog(CatalogKind.VOD)[0].name, "Vod")
        self.assertEqual(provider.load_catalog(CatalogKind.SERIES)[0].name, "Series")

    def test_stalker_provider_dispatches_catalog_kinds_and_headers(self):
        from src.core.providers import CatalogKind, StalkerProvider

        class FakeParser:
            def get_channels(self):
                return [Channel("Live", "https://live.test")]

            def get_vod_movies(self, should_cancel=None, progress=None):
                return [Channel("Movie", "opaque", stream_type="vod", source="stalker")]

            def get_series_shows(self, should_cancel=None, progress=None):
                return [Channel("Show", "", stream_type="series", source="stalker")]

            def playback_headers(self):
                return {"User-Agent": "MAG"}

        provider = StalkerProvider(FakeParser())
        self.assertEqual(provider.load_catalog(CatalogKind.LIVE)[0].name, "Live")
        self.assertEqual(provider.load_catalog(CatalogKind.VOD)[0].name, "Movie")
        self.assertEqual(provider.load_catalog(CatalogKind.SERIES)[0].name, "Show")
        self.assertEqual(provider.playback_headers(), {"User-Agent": "MAG"})


class ControllerTests(unittest.TestCase):
    def test_playback_controller_finds_a_backup_stream(self):
        from src.controllers.playback_controller import PlaybackController

        controller = PlaybackController(MagicMock())
        primary = Channel("Canal HD", "https://a.test/1.ts", stream_type="live")
        backup = Channel("Canal HD", "https://b.test/1.ts", stream_type="live")
        other = Channel("Outro Canal", "https://c.test/1.ts", stream_type="live")

        fallback = controller.find_fallback_channel(
            primary, [primary, backup, other]
        )

        self.assertIs(fallback, backup)

    def test_playback_controller_returns_no_fallback_without_a_mirror(self):
        from src.controllers.playback_controller import PlaybackController

        controller = PlaybackController(MagicMock())
        primary = Channel("Canal HD", "https://a.test/1.ts", stream_type="live")

        self.assertIsNone(
            controller.find_fallback_channel(primary, [primary])
        )

    def test_playlist_and_playback_controllers_delegate_domain_operations(self):
        database = MagicMock()
        playlist = Playlist("Teste", "m3u")
        database.save_playlist.return_value = 7
        database.get_channels.return_value = [Channel("Canal", "https://test")]
        database.get_playback_progress.return_value = {
            "position_ms": 25,
            "length_ms": 100,
        }

        playlists = PlaylistController(database)
        playback = PlaybackController(database)
        playlist_id, channels = playlists.import_playlist(playlist)

        self.assertEqual(playlist_id, 7)
        self.assertEqual(channels[0].name, "Canal")
        self.assertEqual(
            playback.progress_fraction(7, channels[0]),
            0.25,
        )

    def test_task_controller_limits_execution_and_tracks_workers(self):
        controller = TaskController(2)
        worker = MagicMock()
        worker.isRunning.return_value = True
        controller.add(worker)

        self.assertEqual(controller.execute(lambda: "ok"), "ok")
        self.assertEqual(controller.running(), [worker])
        controller.cancel_all()
        worker.requestInterruption.assert_called_once_with()

    def test_epg_controller_channel_mapping_is_case_insensitive(self):
        controller = EpgController(MagicMock(), MagicMock())
        canonical, names = controller.channel_maps(
            [Channel("Notícias", "https://test", tvg_id="PT.News")]
        )
        self.assertEqual(canonical["pt.news"], "PT.News")
        self.assertEqual(names["PT.News"], "Notícias")

class TaskWorkerTests(unittest.TestCase):
    def test_interrupted_worker_emits_cancelled_instead_of_success(self):
        worker = None

        def task():
            worker.requestInterruption()
            return "resultado tardio"

        worker = TaskWorker(task)
        cancelled = QSignalSpy(worker.cancelled)
        succeeded = QSignalSpy(worker.succeeded)
        worker.start()
        self.assertTrue(worker.wait(5_000))

        self.assertEqual(cancelled.count(), 1)
        self.assertEqual(succeeded.count(), 0)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.secrets = SecretStore.for_tests()

    def test_existing_database_is_migrated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "old.db"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE playlists (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                    source_type TEXT NOT NULL
                );
                CREATE TABLE channels (
                    id INTEGER PRIMARY KEY, playlist_id INTEGER NOT NULL,
                    name TEXT NOT NULL, url TEXT NOT NULL,
                    group_name TEXT DEFAULT 'General', logo TEXT DEFAULT '',
                    tvg_id TEXT DEFAULT '', tvg_name TEXT DEFAULT '',
                    epg_channel_id TEXT DEFAULT '', stream_type TEXT DEFAULT 'live',
                    source TEXT DEFAULT 'm3u', xtream_id TEXT DEFAULT '',
                    is_favorite INTEGER DEFAULT 0
                );
                CREATE TABLE epg_cache (
                    id INTEGER PRIMARY KEY, channel_id TEXT NOT NULL,
                    title TEXT NOT NULL, start_time TEXT NOT NULL,
                    stop_time TEXT NOT NULL, description TEXT DEFAULT '',
                    category TEXT DEFAULT ''
                );
                INSERT INTO playlists (id, name, source_type)
                VALUES (1, 'Legacy', 'm3u');
                INSERT INTO channels (id, playlist_id, name, url)
                VALUES (1, 1, 'Canal', 'https://legacy.test/secret');
                """
            )
            connection.close()

            db1 = DatabaseManager(db_path, secret_store=self.secrets)
            connection = sqlite3.connect(db_path)
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(channels)")
            }
            raw_name = connection.execute(
                "SELECT name FROM playlists WHERE id = 1"
            ).fetchone()[0]
            raw_url = connection.execute(
                "SELECT url FROM channels WHERE id = 1"
            ).fetchone()[0]
            connection.close()

            self.assertIn("user_agent", columns)
            self.assertIn("referer", columns)
            self.assertIn("container_extension", columns)
            self.assertTrue(raw_name.startswith(SecretStore.PREFIX))
            self.assertTrue(raw_url.startswith(SecretStore.PREFIX))
            # The VACUUM that reclaims the plaintext pages is deferred to a
            # background thread; wait for it before inspecting raw bytes.
            if db1._purge_thread is not None:
                db1._purge_thread.join(timeout=30)
            database_bytes = db_path.read_bytes()
            self.assertNotIn(b"https://legacy.test/secret", database_bytes)
            self.assertNotIn(b"Legacy", database_bytes)

            db = DatabaseManager(db_path, secret_store=self.secrets)
            self.assertEqual(db.get_playlists()[0]["name"], "Legacy")
            self.assertEqual(
                db.get_channels(1)[0].url, "https://legacy.test/secret"
            )

    def test_connections_close_and_channel_metadata_round_trips(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            db = DatabaseManager(db_path, secret_store=self.secrets)
            playlist = Playlist(
                "Local",
                "m3u",
                channels=[
                    Channel(
                        "Canal",
                        "https://example.test/live",
                        user_agent="Test UA",
                        referer="https://referrer.test/",
                        custom_headers={"Cookie": "a=b"},
                        quality="HD",
                        extension="m3u8",
                        country_code="UK",
                        provider_group="┃UK┃ GENERAL",
                        is_favorite=True,
                        channel_number=12,
                    )
                ],
            )

            playlist_id = db.save_playlist(playlist)
            loaded = db.get_channels(playlist_id)[0]

            raw_connection = sqlite3.connect(db_path)
            raw_channel = raw_connection.execute(
                "SELECT url, referer, custom_headers FROM channels"
            ).fetchone()
            raw_playlist_name = raw_connection.execute(
                "SELECT name FROM playlists"
            ).fetchone()[0]
            raw_connection.close()

            self.assertGreater(loaded.database_id, 0)
            self.assertEqual(loaded.user_agent, "Test UA")
            self.assertEqual(loaded.referer, "https://referrer.test/")
            self.assertEqual(loaded.custom_headers, {"Cookie": "a=b"})
            self.assertEqual(loaded.quality, "HD")
            self.assertEqual(loaded.extension, "m3u8")
            self.assertEqual(loaded.country_code, "UK")
            self.assertEqual(loaded.provider_group, "┃UK┃ GENERAL")
            self.assertTrue(loaded.is_favorite)
            self.assertEqual(loaded.channel_number, 12)
            self.assertTrue(raw_playlist_name.startswith(SecretStore.PREFIX))
            self.assertTrue(raw_channel[0].startswith(SecretStore.PREFIX))
            self.assertTrue(raw_channel[1].startswith(SecretStore.PREFIX))
            self.assertTrue(raw_channel[2].startswith(SecretStore.PREFIX))

        self.assertFalse(db_path.exists(), "Temporary DB should not remain locked")

    def test_light_load_skips_decryption_and_single_channel_hydrates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            playlist = Playlist(
                "Light",
                "m3u",
                channels=[
                    Channel(
                        "Canal A",
                        "https://example.test/live/a",
                        referer="https://referrer.test/",
                        custom_headers={"Cookie": "a=b"},
                    ),
                    Channel("Canal B", "https://example.test/live/b"),
                ],
            )
            playlist_id = db.save_playlist(playlist)

            light = db.get_channels(playlist_id, decrypt_urls=False)
            self.assertEqual(len(light), 2)
            self.assertEqual(light[0].name, "Canal A")
            self.assertEqual(light[0].url, "")
            self.assertEqual(light[0].referer, "")
            self.assertEqual(light[0].custom_headers, {})
            self.assertGreater(light[0].database_id, 0)

            hydrated = db.get_channel(light[0].database_id, playlist_id)
            self.assertEqual(hydrated.url, "https://example.test/live/a")
            self.assertEqual(hydrated.referer, "https://referrer.test/")
            self.assertEqual(hydrated.custom_headers, {"Cookie": "a=b"})

    def test_metadata_flags_are_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            self.assertFalse(db.get_metadata_flag("some:flag"))
            db.set_metadata_flag("some:flag")
            self.assertTrue(db.get_metadata_flag("some:flag"))

    def test_set_catalog_state_is_safe_when_playlist_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            # A background catalog load can outlive its playlist; writing its
            # state for a deleted playlist must not raise (FK constraint).
            db.set_catalog_state(999, "live", "error", 0, "falhou")
            self.assertIsNone(db.get_catalog_state(999, "live"))

    def test_favorites_are_filtered_and_use_channel_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            playlist = Playlist(
                "Duplicates",
                "m3u",
                channels=[
                    Channel("Mesmo nome", "https://example.test/1"),
                    Channel("Mesmo nome", "https://example.test/2"),
                ],
            )
            playlist_id = db.save_playlist(playlist)
            first, second = db.get_channels(playlist_id)

            db.set_favorite(first.database_id, playlist_id, True)
            favorites = db.get_favorites(playlist_id)

            self.assertEqual([channel.database_id for channel in favorites], [first.database_id])
            self.assertFalse(second.is_favorite)

    def test_playlist_can_be_renamed_and_remains_encrypted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            db = DatabaseManager(db_path, secret_store=self.secrets)
            playlist_id = db.save_playlist(Playlist("Nome antigo", "m3u"))

            db.rename_playlist(playlist_id, "  Sala principal  ")

            self.assertEqual(
                db.get_playlist(playlist_id)["name"], "Sala principal"
            )
            connection = sqlite3.connect(db_path)
            raw_name = connection.execute(
                "SELECT name FROM playlists WHERE id = ?", (playlist_id,)
            ).fetchone()[0]
            connection.close()
            self.assertTrue(raw_name.startswith(SecretStore.PREFIX))
            self.assertNotEqual(raw_name, "Sala principal")

    def test_playlist_connection_update_remains_encrypted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "test.db"
            db = DatabaseManager(path, secret_store=self.secrets)
            playlist_id = db.save_playlist(
                Playlist(
                    "Conta",
                    "xtream",
                    server_url="https://old.test",
                    username="old",
                    password="old-secret",
                )
            )
            db.update_playlist_connection(
                playlist_id,
                {
                    "server_url": "https://new.test",
                    "username": "new-user",
                    "password": "new-secret",
                },
            )
            details = db.get_playlist(playlist_id)
            self.assertEqual(details["server_url"], "https://new.test")
            self.assertEqual(details["password"], "new-secret")
            connection = sqlite3.connect(path)
            try:
                raw = connection.execute(
                    "SELECT server_url, username, password FROM playlists WHERE id = ?",
                    (playlist_id,),
                ).fetchone()
            finally:
                connection.close()
            self.assertTrue(all(value.startswith("enc:v1:") for value in raw))

    def test_playlist_epg_cache_round_trips(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            playlist_id = db.save_playlist(Playlist("EPG", "m3u"))
            program = EPGProgram(
                channel_id="channel.one",
                title="Notícias",
                start=datetime(2026, 7, 24, 12, tzinfo=timezone.utc),
                stop=datetime(2026, 7, 24, 13, tzinfo=timezone.utc),
            )

            db.replace_playlist_epg(playlist_id, [program])
            loaded = db.get_playlist_epg(playlist_id)

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].title, "Notícias")
            self.assertEqual(loaded[0].start, program.start)
            self.assertIsNotNone(db.get_epg_last_updated(playlist_id))

    def test_stalker_headers_can_be_repaired_for_existing_playlist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            playlist_id = db.save_playlist(
                Playlist(
                    "Stalker",
                    "stalker",
                    channels=[
                        Channel(
                            "Canal",
                            "https://stream.example.test/live.ts",
                            source="stalker",
                        )
                    ],
                )
            )

            db.update_stalker_headers(
                playlist_id, "MAG User Agent", "https://portal.example.test/c/"
            )
            channel = db.get_channels(playlist_id)[0]

            self.assertEqual(channel.user_agent, "MAG User Agent")
            self.assertEqual(
                channel.referer, "https://portal.example.test/c/"
            )

    def test_incremental_catalog_preserves_favorites_and_empty_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            playlist_id = db.save_playlist(
                Playlist(
                    "Lazy",
                    "stalker",
                    channels=[
                        Channel("Live", "https://live.test", source="stalker"),
                        Channel(
                            "Movie old",
                            "opaque-old",
                            stream_type="vod",
                            source="stalker",
                            xtream_id="42",
                            is_favorite=True,
                        ),
                    ],
                )
            )

            refreshed = db.replace_catalog(
                playlist_id,
                "vod",
                [
                    Channel(
                        "Movie renamed",
                        "opaque-new",
                        stream_type="movie",
                        source="stalker",
                        xtream_id="42",
                    )
                ],
            )

            movie = next(ch for ch in refreshed if ch.stream_type == "movie")
            self.assertTrue(movie.is_favorite)
            self.assertEqual(db.get_catalog_state(playlist_id, "vod")["item_count"], 1)

            db.replace_catalog(playlist_id, "series", [])
            empty_state = db.get_catalog_state(playlist_id, "series")
            self.assertEqual(empty_state["status"], "ready")
            self.assertEqual(empty_state["item_count"], 0)

    def test_catalogue_pages_are_filtered_and_bounded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            playlist_id = db.save_playlist(
                Playlist(
                    "Paged",
                    "m3u",
                    channels=[
                        Channel(
                            f"Canal {index:04d}",
                            f"https://example.test/{index}",
                            group="News" if index % 2 else "Sports",
                        )
                        for index in range(620)
                    ],
                )
            )

            page = db.get_channel_page(
                playlist_id, "live", page=1, page_size=250
            )
            self.assertEqual(len(page), 250)
            self.assertEqual(db.count_channels(playlist_id, "live"), 620)
            self.assertEqual(
                db.count_channels(playlist_id, "live", group="News"), 310
            )
            matches = db.get_channel_page(
                playlist_id, "live", query="061", page_size=100
            )
            self.assertTrue(matches)
            self.assertTrue(all("061" in channel.name for channel in matches))

    def test_schema_v6_fts_search_is_versioned_and_kept_in_sync(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            playlist_id = db.save_playlist(
                Playlist(
                    "FTS",
                    "m3u",
                    [Channel("Notícias Europa", "https://test/1", group="Informação")],
                )
            )
            self.assertEqual(
                [channel.name for channel in db.search_channels(playlist_id, "notic")],
                ["Notícias Europa"],
            )
            with db._connection() as conn:
                version = conn.execute(
                    "SELECT value FROM app_metadata WHERE key = 'schema_version'"
                ).fetchone()[0]
                conn.execute(
                    "UPDATE channels SET name = 'Cinema Europeu' WHERE playlist_id = ?",
                    (playlist_id,),
                )
            self.assertEqual(version, "6")
            self.assertEqual(
                [channel.name for channel in db.search_channels(playlist_id, "cinema")],
                ["Cinema Europeu"],
            )

    def test_differential_catalog_preserves_ids_and_skips_unchanged_ciphertext(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            original = Channel(
                "Canal",
                "https://test/one",
                tvg_id="stable.one",
                source="m3u",
            )
            playlist_id = db.save_playlist(Playlist("Diff", "m3u", [original]))
            saved = db.get_channels(playlist_id)[0]
            db.set_favorite(saved.database_id, playlist_id, True)
            with db._connection() as conn:
                before = conn.execute(
                    "SELECT id, url, content_hash FROM channels WHERE playlist_id = ?",
                    (playlist_id,),
                ).fetchone()

            db.replace_catalog(
                playlist_id,
                "live",
                [Channel("Canal", "https://test/one", tvg_id="stable.one", source="m3u")],
            )
            with db._connection() as conn:
                unchanged = conn.execute(
                    "SELECT id, url, content_hash FROM channels WHERE playlist_id = ?",
                    (playlist_id,),
                ).fetchone()
            self.assertEqual(tuple(before), tuple(unchanged))

            db.replace_catalog(
                playlist_id,
                "live",
                [Channel("Canal HD", "https://test/two", tvg_id="stable.one", source="m3u")],
            )
            changed = db.get_channels(playlist_id)[0]
            self.assertEqual(changed.database_id, saved.database_id)
            self.assertTrue(changed.is_favorite)
            self.assertEqual(changed.url, "https://test/two")

    def test_playback_history_is_bounded_and_contains_no_urls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            playlist_id = db.save_playlist(Playlist("History", "m3u"))
            for index in range(105):
                db.record_playback(
                    playlist_id,
                    Channel(
                        f"Canal {index}",
                        f"https://secret.example/{index}",
                    ),
                )

            recent = db.get_recent_playback(playlist_id, limit=100)
            self.assertEqual(len(recent), 100)
            self.assertEqual(recent[0]["title"], "Canal 104")
            self.assertNotIn("url", recent[0])

    def test_legacy_m3u_stream_types_can_be_repaired(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            playlist_id = db.save_playlist(
                Playlist(
                    "Legacy mixed",
                    "m3u",
                    channels=[
                        Channel("Live", "https://test/live/u/p/1.ts"),
                        Channel("Movie", "https://test/movie/u/p/2.mp4"),
                        Channel("Episode S01E01", "https://test/series/u/p/3.mkv"),
                    ],
                )
            )
            channels = db.get_channels(playlist_id)
            for channel in channels:
                channel.stream_type = M3UParser.infer_stream_type(
                    channel.url, channel.group, channel.name
                )
            db.update_channel_stream_types(playlist_id, channels)

            repaired = db.get_channels(playlist_id)
            self.assertEqual(
                [channel.stream_type for channel in repaired],
                ["live", "vod", "series"],
            )
            self.assertEqual(db.get_catalog_state(playlist_id, "vod")["item_count"], 1)

    def test_vod_progress_round_trips_and_completed_items_are_cleared(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            channel = Channel(
                "Movie", "https://secret.test/movie", stream_type="vod", xtream_id="42"
            )
            playlist_id = db.save_playlist(Playlist("Movies", "xtream", [channel]))
            saved = db.get_channels(playlist_id)[0]

            db.save_playback_progress(playlist_id, saved, 120_000, 600_000)
            progress = db.get_playback_progress(playlist_id, saved)
            self.assertEqual(progress["position_ms"], 120_000)

            db.save_playback_progress(playlist_id, saved, 590_000, 600_000)
            self.assertIsNone(db.get_playback_progress(playlist_id, saved))

    def test_global_search_covers_names_groups_and_playlists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            db.save_playlist(
                Playlist(
                    "Sala segura",
                    "m3u",
                    [Channel("Notícias", "https://test/live", group="Portugal")],
                )
            )
            result = db.search_all_channels("Portugal")
            self.assertEqual(result[0]["playlist_name"], "Sala segura")
            self.assertEqual(result[0]["channel"].name, "Notícias")

    def test_connections_use_explicit_busy_timeout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            with db._connection() as conn:
                busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            self.assertEqual(busy_timeout, 5000)

    def test_search_channels_escapes_like_wildcards(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(
                Path(temp_dir) / "test.db", secret_store=self.secrets
            )
            playlist_id = db.save_playlist(
                Playlist(
                    "Pesquisa",
                    "m3u",
                    [
                        Channel("Canal 100% HD", "https://test/1", group="G"),
                        Channel("Canal_Extra", "https://test/2", group="G"),
                        Channel("Canal Normal", "https://test/3", group="G"),
                    ],
                )
            )
            self.assertEqual(
                [c.name for c in db.search_channels(playlist_id, "100%")],
                ["Canal 100% HD"],
            )
            self.assertEqual(
                [c.name for c in db.search_channels(playlist_id, "Canal_")],
                ["Canal_Extra"],
            )
            # Without escaping these wildcards would match everything; with
            # escaping they match only channels containing a literal char.
            self.assertEqual(
                [c.name for c in db.search_channels(playlist_id, "%")],
                ["Canal 100% HD"],
            )
            self.assertEqual(
                [c.name for c in db.search_channels(playlist_id, "_")],
                ["Canal_Extra"],
            )


class ChannelListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_large_list_only_creates_one_ui_page(self):
        from src.ui.channel_list import ChannelListWidget

        widget = ChannelListWidget()
        widget.PAGE_SIZE = 250  # exercise the pagination mechanism itself
        widget.set_channels(
            [
                Channel(
                    f"Canal {index:04d}",
                    f"https://example.test/{index}",
                    group="News",
                )
                for index in range(501)
            ]
        )

        self.assertEqual(widget._channel_list.count(), widget.PAGE_SIZE)
        self.assertEqual(widget._page_count, 3)
        widget._next_page()
        self.assertEqual(widget._current_page, 1)
        self.assertEqual(widget._channel_list.count(), widget.PAGE_SIZE)
        widget._next_page()
        self.assertEqual(widget._channel_list.count(), 1)
        widget.close()

    def test_double_clicking_playlist_does_not_open_rename_dialog(self):
        from PySide6.QtWidgets import QInputDialog

        from src.ui.playlist_widget import PlaylistWidget

        widget = PlaylistWidget()
        widget.set_playlists(
            [{"id": 7, "name": "Sala", "source_type": "m3u", "created_at": ""}]
        )
        item = widget._list_widget.item(0)
        with patch.object(QInputDialog, "getText") as rename_dialog:
            widget._list_widget.itemDoubleClicked.emit(item)
        rename_dialog.assert_not_called()
        widget.close()

    def test_single_click_selects_but_activation_starts_channel(self):
        from src.ui.channel_list import ChannelListWidget

        widget = ChannelListWidget()
        widget.set_channels([Channel("Canal", "https://example.test/live")])
        activated = []
        widget.channel_selected.connect(activated.append)
        item = widget._channel_list.item(0)
        widget._channel_list.setCurrentItem(item)
        self.assertEqual(activated, [])
        widget._channel_list.itemActivated.emit(item)
        self.assertEqual([channel.name for channel in activated], ["Canal"])
        widget.close()

    def test_category_restores_selected_channel_and_page(self):
        from src.ui.channel_list import ChannelListWidget

        widget = ChannelListWidget()
        widget.PAGE_SIZE = 250  # exercise the pagination mechanism itself
        channels = [
            Channel(f"A {index}", f"https://test/a/{index}", group="A")
            for index in range(300)
        ] + [Channel("B 0", "https://test/b/0", group="B")]
        widget.set_channels(channels)
        group_a = widget._group_combo.topLevelItem(2)
        group_b = widget._group_combo.topLevelItem(3)
        widget._on_group_selected(group_a, 0)
        widget._next_page()
        selected = widget._channel_list.item(10)
        widget._channel_list.setCurrentItem(selected)
        selected_url = selected.data(Qt.ItemDataRole.UserRole).url

        widget._on_group_selected(group_b, 0)
        widget._on_group_selected(group_a, 0)

        self.assertEqual(widget._current_page, 1)
        self.assertEqual(
            widget.get_current_channel().url,
            selected_url,
        )
        widget.close()

    def test_adjacent_channel_crosses_page_without_leaving_player(self):
        from src.ui.channel_list import ChannelListWidget

        widget = ChannelListWidget()
        widget.PAGE_SIZE = 250  # exercise the pagination mechanism itself
        widget.set_channels(
            [Channel(f"Canal {index}", f"https://test/{index}") for index in range(251)]
        )
        last_on_page = widget._channel_list.item(widget.PAGE_SIZE - 1)
        widget._channel_list.setCurrentItem(last_on_page)
        played = []
        widget.channel_selected.connect(played.append)

        widget.play_adjacent(1)

        self.assertEqual(widget._current_page, 1)
        self.assertEqual(played[-1].url, "https://test/250")
        widget.close()

    def test_m3u_episodes_are_grouped_by_show_and_season(self):
        from src.ui.series_browser import SeriesBrowserWidget

        widget = SeriesBrowserWidget()
        widget.set_shows(
            [
                Channel(
                    "Programa S01E02", "https://test/2", group="Drama", source="m3u"
                ),
                Channel(
                    "Programa S01E01", "https://test/1", group="Drama", source="m3u"
                ),
                Channel(
                    "Programa S02E01", "https://test/3", group="Drama", source="m3u"
                ),
            ]
        )
        self.assertEqual(widget._shows_list._channel_list.count(), 1)
        grouped = widget._shows_list._channel_list.item(0).data(
            Qt.ItemDataRole.UserRole
        )
        widget._on_show_clicked(grouped)
        self.assertEqual(widget._season_combo.count(), 2)
        self.assertEqual(widget._seasons[0]["episodes"][0]["label"], "Programa S01E01")
        widget.close()


class UpdateManagerTests(unittest.TestCase):
    def test_manifest_requires_https_and_valid_hashes(self):
        manifest = {
            "schema_version": 1,
            "version": "0.4.0",
            "published_at": "2026-08-03T00:00:00Z",
            "notes_url": "https://example.test/notes",
            "artifacts": [
                {
                    "platform": "windows-x86_64-portable",
                    "filename": "IPTVPlayer.zip",
                    "url": "https://example.test/IPTVPlayer.zip",
                    "sha256": "a" * 64,
                    "size": 123,
                }
            ],
        }
        release = parse_manifest(manifest)
        self.assertEqual(release.version, "0.4.0")
        self.assertTrue(is_newer_version(release.version, "0.3.0"))

        manifest["artifacts"][0]["url"] = "http://example.test/file.zip"
        with self.assertRaises(ValueError):
            parse_manifest(manifest)

    def test_artifact_integrity_checks_size_and_sha256(self):
        import hashlib

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "artifact.zip"
            content = b"synthetic release"
            path.write_bytes(content)
            artifact = ReleaseArtifact(
                platform="windows-x86_64-portable",
                filename=path.name,
                url="",
                sha256=hashlib.sha256(content).hexdigest(),
                size=len(content),
            )
            self.assertTrue(verify_artifact(path, artifact))
            path.write_bytes(b"tampered")
            self.assertFalse(verify_artifact(path, artifact))

    def test_select_artifact_prefers_installer_on_windows(self):
        from src.core.update_manager import ReleaseInfo, select_artifact

        info = ReleaseInfo(
            version="0.5.3",
            published_at="",
            notes_url="",
            artifacts=(
                ReleaseArtifact(
                    "windows-x86_64-portable",
                    "p.zip",
                    "https://example.test/p.zip",
                    "a" * 64,
                    1,
                ),
                ReleaseArtifact(
                    "windows-x86_64-installer",
                    "s.exe",
                    "https://example.test/s.exe",
                    "b" * 64,
                    2,
                ),
            ),
        )
        with patch("platform.system", return_value="Windows"):
            self.assertEqual(select_artifact(info).filename, "s.exe")

    def test_select_artifact_returns_none_on_unsupported_platform(self):
        from src.core.update_manager import ReleaseInfo, select_artifact

        info = ReleaseInfo(
            version="0.5.3",
            published_at="",
            notes_url="",
            artifacts=(
                ReleaseArtifact(
                    "windows-x86_64-installer",
                    "s.exe",
                    "https://example.test/s.exe",
                    "b" * 64,
                    2,
                ),
            ),
        )
        with patch("platform.system", return_value="Linux"):
            self.assertIsNone(select_artifact(info))


class BackupTests(unittest.TestCase):
    def test_encrypted_backup_round_trip_and_wrong_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "backup.iptvbackup"
            data = {"schema_version": 1, "playlists": [{"name": "Sala"}]}
            create_backup(path, data, "password segura")
            self.assertNotIn(b"Sala", path.read_bytes())
            self.assertEqual(read_backup(path, "password segura"), data)
            with self.assertRaises(ValueError):
                read_backup(path, "password errada")

    def test_database_backup_import_preserves_existing_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = DatabaseManager(
                Path(temp_dir) / "source.db", SecretStore.for_tests(b"\x02" * 32)
            )
            source.save_playlist(
                Playlist(
                    "Origem",
                    "xtream",
                    [Channel("Movie", "https://secret.test/42", stream_type="vod")],
                    server_url="https://provider.test",
                    username="user",
                    password="secret",
                )
            )
            target = DatabaseManager(
                Path(temp_dir) / "target.db", SecretStore.for_tests(b"\x03" * 32)
            )
            target.save_playlist(Playlist("Existente", "m3u"))
            restored = target.import_backup_data(source.export_backup_data())

            self.assertEqual(len(restored), 1)
            self.assertEqual(len(target.get_playlists()), 2)
            details = target.get_playlist(restored[0])
            self.assertEqual(details["password"], "secret")
            self.assertEqual(target.get_channels(restored[0])[0].url, "https://secret.test/42")

    def test_database_backup_import_rolls_back_every_playlist_on_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = DatabaseManager(
                Path(temp_dir) / "target.db", SecretStore.for_tests(b"\x04" * 32)
            )
            target.save_playlist(Playlist("Existente", "m3u"))
            data = {
                "schema_version": 1,
                "playlists": [
                    {
                        "details": {"name": "Primeira", "source_type": "m3u"},
                        "channels": [Channel("Um", "https://test/1").to_dict()],
                    },
                    {
                        "details": {"name": "Segunda", "source_type": "m3u"},
                        "channels": [Channel("Dois", "https://test/2").to_dict()],
                    },
                ],
            }
            original_insert = target._insert_channels
            calls = 0

            def fail_on_second_playlist(conn, playlist_id, channels):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise sqlite3.OperationalError("falha simulada")
                return original_insert(conn, playlist_id, channels)

            with patch.object(target, "_insert_channels", side_effect=fail_on_second_playlist):
                with self.assertRaises(sqlite3.OperationalError):
                    target.import_backup_data(data)

            self.assertEqual(
                [playlist["name"] for playlist in target.get_playlists()],
                ["Existente"],
            )


class DeviceSyncTests(unittest.TestCase):
    def test_sync_state_contains_no_urls_or_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = DatabaseManager(
                Path(temp_dir) / "sync.db", SecretStore.for_tests(b"\x07" * 32)
            )
            channel = Channel(
                "Filme",
                "https://user:password@example.test/movie/7",
                group="Cinema",
                stream_type="vod",
                is_favorite=True,
            )
            playlist_id = database.save_playlist(Playlist("Sala", "m3u", [channel]))
            saved = database.get_channels(playlist_id)[0]
            database.save_playback_progress(playlist_id, saved, 60_000, 600_000)

            payload = export_device_state(database, playlist_id)
            parsed = json.loads(payload)

            self.assertEqual(parsed["schema_version"], 1)
            self.assertEqual(len(parsed["favorites"]), 1)
            self.assertEqual(len(parsed["progress"]), 1)
            self.assertNotIn("example.test", payload)
            self.assertNotIn("password", payload)

    def test_tv_state_merges_favorites_and_resume_into_desktop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = DatabaseManager(
                Path(temp_dir) / "sync.db", SecretStore.for_tests(b"\x08" * 32)
            )
            channel = Channel("Filme", "https://example.test/movie", group="Cinema", stream_type="vod")
            playlist_id = database.save_playlist(Playlist("Sala", "m3u", [channel]))
            saved = database.get_channels(playlist_id)[0]
            key = media_key(saved)
            payload = json.dumps(
                {
                    "schema_version": 1,
                    "favorites": [key],
                    "progress": {key: {"position_ms": 30_000, "duration_ms": 300_000}},
                }
            )

            result = import_device_state(database, playlist_id, payload)

            self.assertEqual(result, {"favorites": 1, "progress": 1})
            self.assertTrue(database.get_channels(playlist_id)[0].is_favorite)
            self.assertEqual(database.get_playback_progress(playlist_id, saved)["position_ms"], 30_000)


class ProviderClientLifecycleTests(unittest.TestCase):
    def test_provider_context_managers_close_http_sessions(self):
        clients = (
            XtreamParser("https://example.test", "user", "secret"),
            StalkerParser("https://example.test", "00:00:00:00:00:00"),
        )
        for client in clients:
            with patch.object(client._session, "close") as close:
                with client:
                    pass
                close.assert_called_once_with()

    def test_cached_provider_session_is_reused_and_closed(self):
        database = MagicMock()
        database.get_playlist.return_value = {
            "source_type": "xtream",
            "server_url": "https://example.test",
            "username": "user",
            "password": "secret",
        }
        parser = MagicMock()
        manager = ProviderSessionManager(database, lambda: 15)
        with patch("src.core.provider_sessions.XtreamParser", return_value=parser) as factory:
            self.assertIs(manager.call_xtream(7, lambda client: client), parser)
            self.assertIs(manager.call_xtream(7, lambda client: client), parser)
            manager.discard(7)

        factory.assert_called_once()
        parser.authenticate.assert_called_once_with()
        parser.close.assert_called_once_with()

    def test_discard_does_not_close_a_session_that_is_in_use(self):
        import threading
        import time

        database = MagicMock()
        database.get_playlist.return_value = {
            "source_type": "xtream",
            "server_url": "https://example.test",
            "username": "user",
            "password": "secret",
        }
        parser = MagicMock()
        manager = ProviderSessionManager(database, lambda: 15)
        entered = threading.Event()
        release = threading.Event()

        with patch("src.core.provider_sessions.XtreamParser", return_value=parser):

            def blocking_call(_client):
                entered.set()
                release.wait(5)
                return "done"

            worker = threading.Thread(
                target=manager.call_xtream, args=(7, blocking_call)
            )
            worker.start()
            self.assertTrue(entered.wait(5))

            # discard() must not tear the parser down while a call is in
            # flight, and must not block the caller waiting for it.
            started = time.monotonic()
            manager.discard(7)
            self.assertLess(time.monotonic() - started, 1.0)
            parser.close.assert_not_called()

            release.set()
            worker.join(5)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and parser.close.call_count == 0:
            time.sleep(0.01)
        parser.close.assert_called_once_with()

    def test_provider_sessions_receive_a_live_cancel_predicate(self):
        database = MagicMock()
        database.get_playlist.return_value = {
            "source_type": "xtream",
            "server_url": "https://example.test",
            "username": "user",
            "password": "secret",
        }
        cancelled = {"value": False}
        parser = MagicMock()
        manager = ProviderSessionManager(
            database, lambda: 15, lambda: cancelled["value"]
        )
        with patch(
            "src.core.provider_sessions.XtreamParser", return_value=parser
        ) as factory:
            manager.call_xtream(7, lambda client: client)
            kwargs = factory.call_args.kwargs
            try:
                # The predicate is evaluated lazily, on every request, so a
                # task cancelled after the session was built still aborts.
                self.assertFalse(kwargs["cancel_requested"]())
                cancelled["value"] = True
                self.assertTrue(kwargs["cancel_requested"]())
            finally:
                manager.discard(7)

    def test_provider_neutral_contract_wraps_cached_client(self):
        database = MagicMock()
        database.get_playlist.return_value = {
            "source_type": "xtream",
            "server_url": "https://example.test",
            "username": "user",
            "password": "secret",
        }
        parser = MagicMock()
        parser.get_live_channels.return_value = [Channel("Canal", "https://test")]
        manager = ProviderSessionManager(database, lambda: 15)
        with patch("src.core.provider_sessions.XtreamParser", return_value=parser):
            result = manager.call_provider(
                7,
                lambda provider: (
                    isinstance(provider, Provider),
                    provider.load_catalog(CatalogKind.LIVE),
                ),
            )
        self.assertTrue(result[0])
        self.assertEqual(result[1][0].name, "Canal")


class DiagnosticTests(unittest.TestCase):
    def test_http_diagnostic_returns_no_url_or_credentials(self):
        response = MagicMock()
        response.status_code = 206
        response.headers = {"Content-Type": "video/mp2t; charset=binary"}
        with patch("src.core.diagnostics.requests.get", return_value=response):
            result = diagnose_channel(
                Channel(
                    "Canal",
                    "https://user:secret@example.test/live/token.ts",
                    user_agent="UA",
                )
            )
        self.assertEqual(result["status"], "HTTP 206")
        self.assertEqual(result["host"], "example.test")
        self.assertEqual(result["content_type"], "video/mp2t")
        self.assertNotIn("url", result)
        self.assertNotIn("secret", str(result))

    def test_non_http_diagnostic_does_not_make_network_request(self):
        with patch("src.core.diagnostics.requests.get") as request:
            result = diagnose_channel(Channel("UDP", "udp://239.0.0.1:1234"))
        request.assert_not_called()
        self.assertEqual(result["protocol"], "UDP")


class ParserTests(unittest.TestCase):
    def test_infer_stream_type_uses_explicit_metadata_and_patterns(self):
        self.assertEqual(
            M3UParser.infer_stream_type("https://example.test/a", explicit_type="movie"),
            "vod",
        )
        self.assertEqual(
            M3UParser.infer_stream_type("https://example.test/a", explicit_type="series"),
            "series",
        )
        self.assertEqual(M3UParser.infer_stream_type("https://example.test/live/a.ts"), "live")
        self.assertEqual(
            M3UParser.infer_stream_type("https://example.test/a.mkv", name="Show S01E02"),
            "series",
        )
        self.assertEqual(
            M3UParser.infer_stream_type("https://example.test/a.mp4", duration=5400.0),
            "vod",
        )
        self.assertEqual(
            M3UParser.infer_stream_type("https://example.test/a.ts", group="VOD | Filmes"),
            "vod",
        )

    def test_m3u_headers_are_parsed(self):
        content = """#EXTM3U x-tvg-url="https://epg.test/guide.xml.gz"
#EXTINF:-1 tvg-id="one" user-agent="UA" referer="https://ref.test/",Canal HD
#EXTVLCOPT:http-cookie=session=test
https://example.test/live.m3u8
"""
        playlist = M3UParser()._parse_content(content, "Test")
        channel = playlist.channels[0]

        self.assertEqual(channel.user_agent, "UA")
        self.assertEqual(channel.referer, "https://ref.test/")
        self.assertEqual(channel.custom_headers, {"Cookie": "session=test"})
        self.assertEqual(channel.quality, "HD")
        self.assertEqual(channel.epg_channel_id, "one")
        self.assertEqual(playlist.epg_url, "https://epg.test/guide.xml.gz")

    def test_m3u_parses_extgrp_and_keeps_channel_number_out_of_epg_id(self):
        content = """#EXTM3U
#EXTINF:-1 tvg-id="one" tvg-chno="12",Canal
#EXTGRP:Desporto
https://example.test/live.m3u8
"""
        channel = M3UParser()._parse_content(content, "Test").channels[0]

        self.assertEqual(channel.group, "Desporto")
        self.assertEqual(channel.epg_channel_id, "one")
        self.assertEqual(channel.channel_number, 12)

    def test_m3u_parse_can_be_cancelled(self):
        from src.core.http_client import RequestCancelled

        parser = M3UParser(should_cancel=lambda: True)
        with self.assertRaises(RequestCancelled):
            parser._parse_content(
                "#EXTM3U\n#EXTINF:-1,Canal\nhttps://example.test/live.m3u8\n",
                "Test",
            )

    def test_gzipped_m3u_playlist_is_decoded(self):
        import gzip as _gzip
        import tempfile as _tempfile
        from pathlib import Path as _Path

        content = (
            b"#EXTM3U\n#EXTINF:-1,Canal\nhttps://example.test/live.m3u8\n"
        )
        with _tempfile.TemporaryDirectory() as directory:
            path = _Path(directory) / "list.m3u.gz"
            path.write_bytes(_gzip.compress(content))

            playlist = M3UParser().parse(str(path), "Test")

        self.assertEqual([channel.name for channel in playlist.channels], ["Canal"])

    def test_xtream_episodes_tolerate_malformed_payload(self):
        parser = XtreamParser("https://example.test", "user", "secret")
        parser.get_series_info = lambda _series_id: {
            "episodes": {
                "not-a-season": [
                    {"id": "1", "title": "Ep 1", "info": None},
                    "not-a-dict",
                ],
                "2": [{"id": "2", "title": "Ep 2", "episode_num": "abc"}],
            }
        }

        episodes = parser.get_episodes_for_series("42")

        self.assertEqual([episode.name for episode in episodes], ["Ep 1", "Ep 2"])
        self.assertEqual(episodes[0].season_number, 0)
        self.assertEqual(episodes[1].season_number, 2)
        self.assertEqual(episodes[1].episode_number, 0)

    def test_m3u_separates_live_vod_and_series(self):
        content = """#EXTM3U
#EXTINF:-1 group-title="Portugal",Canal Live
https://provider.test/live/user/pass/1.ts
#EXTINF:-1 group-title="VOD | Filmes",Filme
https://provider.test/movie/user/pass/2.mp4
#EXTINF:-1 group-title="Séries | Drama",Programa S01E02
https://provider.test/series/user/pass/3.mkv
#EXTINF:-1 type="movie" group-title="Arquivo",Filme explícito
https://cdn.test/watch?id=4
#EXTINF:-1 group-title="Sky Cinema",Canal de cinema ao vivo
https://cdn.test/channel/5.m3u8
"""
        playlist = M3UParser()._parse_content(content, "Mixed")

        self.assertEqual(
            [channel.stream_type for channel in playlist.channels],
            ["live", "vod", "series", "vod", "live"],
        )

    def test_xtream_uses_movie_path_and_container_extensions(self):
        parser = XtreamParser("https://example.test", "user", "password")

        movie_url = parser._build_stream_url("42", "movie", "mkv")
        episode_url = parser._build_stream_url("7", "series", ".mp4")

        self.assertEqual(movie_url, "https://example.test/movie/user/password/42.mkv")
        self.assertEqual(episode_url, "https://example.test/series/user/password/7.mp4")

    def test_xtream_epg_is_decoded_and_normalized(self):
        parser = XtreamParser("https://example.test", "user", "password")
        parser.get_epg = lambda *_args, **_kwargs: [
            {
                "title": base64.b64encode("Notícias".encode()).decode(),
                "description": base64.b64encode(b"Resumo").decode(),
                "start_timestamp": "1784894400",
                "stop_timestamp": "1784898000",
            }
        ]

        programs = parser.get_epg_programs("42", channel_id="channel.one")

        self.assertEqual(programs[0].channel_id, "channel.one")
        self.assertEqual(programs[0].title, "Notícias")
        self.assertEqual(programs[0].description, "Resumo")

    def test_stalker_epg_is_normalized(self):
        parser = StalkerParser(
            "https://example.test", "00:00:00:00:00:00"
        )
        parser.get_epg = lambda **_kwargs: [
            {
                "ch_id": "17",
                "name": "Notícias",
                "descr": "Resumo",
                "start_timestamp": "1784894400",
                "stop_timestamp": "1784898000",
            }
        ]

        programs = parser.get_epg_programs("17")

        self.assertEqual(programs[0].channel_id, "17")
        self.assertEqual(programs[0].title, "Notícias")
        self.assertEqual(programs[0].description, "Resumo")

    def test_stalker_live_channels_include_required_mag_headers(self):
        parser = StalkerParser(
            "https://example.test/c/", "00:00:00:00:00:00"
        )
        parser.get_genres = lambda: {"29": "┃UK┃ GENERAL"}
        parser._paginated_fetch = lambda *_args, **_kwargs: [
            {
                "id": "1",
                "name": "Canal",
                "cmd": "ffmpeg https://stream.example.test/live.ts",
                "tv_genre_id": "29",
            }
        ]

        channel = parser._try_get_channels("get_all_channels")[0]

        self.assertIn("MAG425", channel.user_agent)
        self.assertEqual(channel.referer, "https://example.test/c/")
        self.assertEqual(channel.country_code, "UK")
        self.assertEqual(channel.group, "┃UK┃ GENERAL")

    def test_stalker_uses_canonical_mac_cookie_for_handshake(self):
        parser = StalkerParser(
            "https://example.test/c/", "00-1a-79-76-32-1e"
        )

        class Response:
            status_code = 200
            text = '{"js":{"token":"test-token"}}'

            @staticmethod
            def raise_for_status():
                return None

        parser._session.get = lambda *_args, **_kwargs: Response()
        parser._post = lambda _data: Response()

        parser.authenticate()

        self.assertEqual(
            parser._session.cookies.get("mac"),
            "00:1A:79:76:32:1E",
        )

    def test_stalker_resolves_temporary_live_link(self):
        parser = StalkerParser(
            "https://example.test/c/", "00:1A:79:76:32:1E"
        )
        parser._token = "test-token"
        captured = {}

        class Response:
            text = (
                '{"js":{"cmd":"ffmpeg '
                'https:\\/\\/stream.example.test\\/live\\/1?play_token=abc"}}'
            )

        def post(data):
            captured.update(data)
            return Response()

        parser._post = post

        url = parser.resolve_live_link("http://localhost/ch/1_")

        self.assertEqual(
            url, "https://stream.example.test/live/1?play_token=abc"
        )
        self.assertEqual(captured["type"], "itv")
        self.assertEqual(captured["action"], "create_link")
        self.assertEqual(captured["cmd"], "http://localhost/ch/1_")

    def test_stalker_preserves_unescaped_urls_in_json(self):
        parser = StalkerParser(
            "https://example.test", "00:00:00:00:00:00"
        )

        class Response:
            text = '{"js":{"cmd":"ffmpeg http://stream.example/live/1"}}'

        result = parser._parse_response(Response())

        self.assertEqual(
            result["js"]["cmd"], "ffmpeg http://stream.example/live/1"
        )

    def test_stalker_catalogues_can_be_included_explicitly(self):
        parser = StalkerParser(
            "https://example.test", "00:00:00:00:00:00"
        )
        parser._token = "test-token"
        parser.get_channels = lambda **_kwargs: [Channel("Live", "https://live.test")]
        parser.get_vod_movies = lambda **_kwargs: [
            Channel("Movie", "opaque", stream_type="vod", source="stalker")
        ]
        parser.get_series_shows = lambda **_kwargs: [
            Channel("Show", "", stream_type="series", source="stalker")
        ]

        playlist = parser.get_full_playlist(include_vod=True, include_series=True)

        self.assertEqual(
            [channel.stream_type for channel in playlist.channels],
            ["live", "vod", "series"],
        )

    def test_remote_m3u_download_has_a_size_limit(self):
        class Response:
            headers = {}
            encoding = "utf-8"

            def __enter__(self):
                return self

            def __exit__(self, *_exc_info):
                return False

            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def iter_content(chunk_size):
                del chunk_size
                yield b"#EXTM3U\n"
                yield b"x" * 20

        parser = M3UParser()
        parser.MAX_DOWNLOAD_BYTES = 10
        with patch("src.parsers.m3u_parser.requests.get", return_value=Response()):
            with self.assertRaisesRegex(ValueError, "limite"):
                parser.parse("https://example.test/list.m3u")

    def test_stalker_initial_playlist_does_not_fetch_large_catalogues(self):
        parser = StalkerParser(
            "https://example.test", "00:00:00:00:00:00"
        )
        parser._token = "test-token"
        parser.get_channels = lambda **_kwargs: [
            Channel("Canal", "https://stream.example.test/live.ts")
        ]
        parser.get_vod_movies = lambda: self.fail("VOD should be lazy")
        parser.get_series_shows = lambda: self.fail("Series should be lazy")

        playlist = parser.get_full_playlist()

        self.assertEqual(len(playlist.channels), 1)

    def test_stalker_reauthenticates_when_create_link_token_expired(self):
        parser = StalkerParser("https://example.test", "00:00:00:00:00:00")
        parser._token = "expired-token"
        payloads = [
            {},  # expired token -> portal answers without a cmd
            {"js": {"cmd": "ffmpeg https://stream.example.test/vod/9.mp4"}},
        ]
        auth_calls = []
        parser._post = lambda _data: object()
        parser._parse_response = lambda _response: payloads.pop(0)
        parser.authenticate = lambda: auth_calls.append(1) or True

        url = parser.resolve_link("opaque-cmd")

        self.assertEqual(url, "https://stream.example.test/vod/9.mp4")
        self.assertEqual(len(auth_calls), 1)

    def test_stalker_create_link_skips_reauthentication_when_successful(self):
        parser = StalkerParser("https://example.test", "00:00:00:00:00:00")
        parser._token = "valid-token"
        parser._post = lambda _data: object()
        parser._parse_response = lambda _response: {
            "js": {"cmd": "ffmpeg https://stream.example.test/vod/10.mp4"}
        }
        parser.authenticate = self.fail

        url = parser.resolve_link("opaque-cmd")

        self.assertEqual(url, "https://stream.example.test/vod/10.mp4")

    def test_stalker_catchup_accepts_start_and_duration(self):
        parser = StalkerParser("https://example.test", "00:00:00:00:00:00")
        parser._token = "valid-token"
        sent = {}
        parser._post = lambda data: sent.update(data) or object()
        parser._parse_response = lambda _response: {
            "js": {"cmd": "ffmpeg https://stream.example.test/archive/1.ts"}
        }

        url = parser.resolve_catchup_link("localhost/ch/1", 1784894400, 3600)

        self.assertEqual(url, "https://stream.example.test/archive/1.ts")
        self.assertEqual(sent["archive"], "1")
        self.assertEqual(sent["start"], "1784894400")
        self.assertEqual(sent["end"], "1784898000")

    def test_stalker_playback_headers_can_be_built_without_authenticating(self):
        headers = StalkerParser.playback_headers_for("https://portal.test/c/")

        self.assertIn("MAG425", headers["User-Agent"])
        self.assertEqual(headers["Referer"], "https://portal.test/c/")

    def test_xtream_playlist_counts_reflect_real_channels(self):
        parser = XtreamParser("https://example.test", "user", "password")
        parser._info = {"user_info": {"auth": 1, "max_connections": "2"}}
        parser.get_live_channels = lambda: [Channel("Live", "https://live.test")]
        parser.get_vod_streams = lambda: [
            Channel("Movie", "https://vod.test", stream_type="vod")
        ]
        parser.get_series_channels = lambda *_args, **_kwargs: [
            Channel("Show", "", stream_type="series")
        ]

        playlist = parser.get_full_playlist()

        # max_connections is a concurrency limit, not a channel count: the
        # previous code reported "2" for a playlist holding 3 channels.
        self.assertEqual(playlist.total_channels, 3)
        self.assertEqual(playlist.total_vod, 1)
        self.assertEqual(playlist.total_series, 1)

    def test_xtream_session_leaves_retrying_to_the_api_request_layer(self):
        parser = XtreamParser("https://example.test", "user", "password")
        adapter = parser._session.get_adapter("https://example.test")
        try:
            self.assertEqual(adapter.max_retries.total, 0)
        finally:
            parser.close()


class ContentTypesTests(unittest.TestCase):
    def test_tab_index_maps_to_a_content_type(self):
        from src.core.content_types import content_type_for_tab

        self.assertEqual(content_type_for_tab(0), "live")
        self.assertEqual(content_type_for_tab(1), "vod")
        self.assertEqual(content_type_for_tab(2), "series")
        self.assertEqual(content_type_for_tab(9, default=""), "")

    def test_stream_types_normalise_the_movie_alias(self):
        from src.core.content_types import content_type_for_stream

        self.assertEqual(content_type_for_stream("live"), "live")
        self.assertEqual(content_type_for_stream("vod"), "vod")
        self.assertEqual(content_type_for_stream("movie"), "vod")
        self.assertEqual(content_type_for_stream("series"), "series")
        self.assertEqual(content_type_for_stream("outro"), "")


class CatalogMixinHelperTests(unittest.TestCase):
    def _window(self):
        from src.ui.catalog_mixin import CatalogMixin

        class Window(CatalogMixin):
            pass

        return Window()

    def test_playlist_channel_cache_is_bounded_and_keeps_the_newest(self):
        from src.ui.catalog_mixin import CatalogMixin

        window = self._window()
        limit = CatalogMixin._PLAYLIST_CACHE_LIMIT
        for playlist_id in range(limit + 3):
            window._cache_playlist_channels(playlist_id, {"live": []})

        self.assertEqual(len(window._playlist_channel_cache), limit)
        self.assertNotIn(0, window._playlist_channel_cache)
        self.assertIn(limit + 2, window._playlist_channel_cache)

    def test_epg_load_key_distinguishes_channels_without_a_row_id(self):
        from src.ui.catalog_mixin import CatalogMixin

        first = CatalogMixin._epg_load_key(
            1, Channel("Canal A", "", database_id=0, tvg_id="a")
        )
        second = CatalogMixin._epg_load_key(
            1, Channel("Canal B", "", database_id=0, tvg_id="b")
        )

        self.assertNotEqual(first, second)

    def test_epg_load_key_prefers_the_database_row(self):
        from src.ui.catalog_mixin import CatalogMixin

        key = CatalogMixin._epg_load_key(
            7, Channel("Canal", "", database_id=42, tvg_id="a")
        )

        self.assertEqual(key, (7, 42))


class EPGTests(unittest.TestCase):
    def test_gzipped_local_xmltv_is_loaded(self):
        xml = (
            b'<tv><programme channel="c" start="20260724120000 +0000" '
            b'stop="20260724130000 +0000"><title>Programa</title>'
            b"</programme></tv>"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "guide.xml.gz"
            path.write_bytes(gzip.compress(xml))

            source = load_xmltv(str(path))

        self.assertEqual(source.get_programs("c")[0].title, "Programa")

    def test_timezone_aware_xmltv_can_be_compared(self):
        source = EPGSource.parse_xmltv(
            """<tv><programme channel="c"
            start="20260724120000 +0000" stop="20260724130000 +0000">
            <title>Programa</title></programme></tv>"""
        )
        program = source.get_programs("c")[0]

        self.assertIsNotNone(program.start.tzinfo)
        self.assertIsInstance(program.is_live, bool)
        self.assertIsInstance(source.get_next_program("c"), (type(None), type(program)))

    def test_plain_xmltv_timestamp_is_supported(self):
        source = EPGSource.parse_xmltv(
            """<tv><programme channel="c"
            start="20260724120000" stop="20260724130000">
            <title>Programa</title></programme></tv>"""
        )
        self.assertEqual(
            source.get_programs("c")[0].start,
            datetime(2026, 7, 24, 12, 0, 0),
        )

    def test_gzip_expansion_has_a_size_limit(self):
        original_limit = epg_loader.MAX_XML_BYTES
        try:
            epg_loader.MAX_XML_BYTES = 32
            with tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "large.xml.gz"
                path.write_bytes(gzip.compress(b"<tv>" + b" " * 64 + b"</tv>"))
                with self.assertRaisesRegex(ValueError, "limite"):
                    load_xmltv(str(path))
        finally:
            epg_loader.MAX_XML_BYTES = original_limit


class _FakeTimer:
    def start(self):
        pass

    def stop(self):
        pass


class _FakeMedia:
    def __init__(self):
        self.options = []

    def add_option(self, option):
        self.options.append(option)


class _FakeInstance:
    def __init__(self):
        self.media = None

    def media_new(self, _url):
        self.media = _FakeMedia()
        return self.media


class _FakePlayer:
    def __init__(self):
        self.length = 120_000
        self.time = 0
        self.subtitle_track = -1
        self.subtitle_selections = []

    def set_media(self, _media):
        pass

    def play(self):
        return 0

    def get_length(self):
        return self.length

    def get_time(self):
        return self.time

    def set_time(self, value):
        self.time = value
        return 0

    def video_get_spu_description(self):
        return [(-1, b"Disable"), (2, "Português")]

    def video_get_spu(self):
        return self.subtitle_track

    def video_set_spu(self, track_id):
        self.subtitle_selections.append(track_id)
        self.subtitle_track = track_id
        return 0


class LoggingTests(unittest.TestCase):
    def test_credentials_are_redacted_from_logs(self):
        message = (
            "GET https://provider.test/player_api.php?username=user&password=pass "
            "http://provider.test/live/user/pass/1.ts MAC 00:1A:79:12:34:56"
        )

        redacted = redact_sensitive(message)

        self.assertNotIn("password=pass", redacted)
        self.assertNotIn("/live/user/pass/", redacted)
        self.assertNotIn("00:1A:79:12:34:56", redacted)


class MediaPlayerTests(unittest.TestCase):
    def _player_without_vlc(self):
        player = MediaPlayer.__new__(MediaPlayer)
        QObject.__init__(player)
        player._instance = _FakeInstance()
        player._player = _FakePlayer()
        player._update_timer = _FakeTimer()
        player._current_url = ""
        player._current_headers = {}
        player._is_playing = False
        player._retry_count = 0
        player._max_retries = 3
        player._retrying = False
        player._current_is_live = False
        player._buffer_size_ms = 1500
        player._pending_seek_ms = None
        player._seek_retry_count = 0
        player._requested_subtitle_track = None
        player._subtitle_retry_count = 0
        return player

    def test_retry_counter_is_not_reset_during_retry(self):
        player = self._player_without_vlc()
        player.play(
            "https://example.test/live",
            {"User-Agent": "UA", "Referer": "https://ref.test/"},
        )

        for _ in range(3):
            player._on_error("failed")

        self.assertEqual(player._retry_count, 3)
        self.assertIn(":http-user-agent=UA", player._instance.media.options)
        self.assertIn(":http-referrer=https://ref.test/", player._instance.media.options)
        self.assertIn(":http-reconnect", player._instance.media.options)
        self.assertIn(":network-caching=1500", player._instance.media.options)

    def test_live_http_uses_stable_cache_and_continuous_reconnect(self):
        player = self._player_without_vlc()

        player.play("https://example.test/live", is_live=True)

        self.assertIn(":http-reconnect", player._instance.media.options)
        self.assertIn(":http-continuous", player._instance.media.options)
        self.assertIn(":network-caching=1500", player._instance.media.options)
        self.assertIn(":live-caching=1500", player._instance.media.options)

    def test_vod_http_does_not_use_continuous_mode_and_seeks_by_time(self):
        player = self._player_without_vlc()

        player.play("https://example.test/series/episode.mkv", is_live=False)

        self.assertNotIn(":http-continuous", player._instance.media.options)
        self.assertNotIn(":live-caching=1500", player._instance.media.options)
        self.assertIn(":file-caching=1500", player._instance.media.options)
        self.assertTrue(player.seek(0.5))
        self.assertEqual(player._player.time, 60_000)
        self.assertEqual(player._pending_seek_ms, 60_000)

    def test_subtitle_tracks_exclude_disable_and_selection_is_remembered(self):
        player = self._player_without_vlc()

        self.assertEqual(player.get_subtitle_tracks(), [(2, "Português")])
        self.assertTrue(player.set_subtitle_track(2))

        self.assertEqual(player.get_subtitle_track(), 2)
        self.assertEqual(player._requested_subtitle_track, 2)
        self.assertEqual(player._player.subtitle_selections, [2])

    def test_custom_vlc_directory_is_configured_before_instance_creation(self):
        player = MediaPlayer.__new__(MediaPlayer)
        QObject.__init__(player)
        player._buffer_size_ms = 1500
        player._video_widget = None
        player._dll_directory_handle = None
        vlc_path = r"C:\Custom VLC\vlc.exe"
        vlc_dir = os.path.dirname(vlc_path)

        class Handle:
            def close(self):
                pass

        class Instance:
            @staticmethod
            def media_player_new():
                return object()

        def create_instance(_arguments=None):
            self.assertIn(vlc_dir, os.environ.get("PATH", ""))
            return Instance()

        with patch.dict(os.environ, {"PATH": ""}), patch(
            "src.player.media_player.os.path.isfile", return_value=True
        ), patch(
            "src.player.media_player.os.add_dll_directory", return_value=Handle(), create=True
        ), patch(
            "src.player.media_player.vlc.Instance", side_effect=create_instance
        ):
            player._init_vlc(vlc_path)

        self.assertIsNotNone(player._player)


class ChannelCleanerTests(unittest.TestCase):
    def test_clean_name_strips_country_prefix_and_quality_tags(self):
        from src.core.channel_cleaner import ChannelCleaner

        raw1 = "PT | RTP 1 FHD (1080p) [BACKUP]"
        raw2 = "PT: SPORT TV 1 4K [RAW]"
        raw3 = "[PT] SIC NOTICIAS (HEVC)"
        raw4 = "1 - TVI HD"

        self.assertEqual(ChannelCleaner.clean_name(raw1), "RTP 1")
        self.assertEqual(ChannelCleaner.clean_name(raw2), "SPORT TV 1")
        self.assertEqual(ChannelCleaner.clean_name(raw3), "SIC NOTICIAS")
        self.assertEqual(ChannelCleaner.clean_name(raw4), "TVI")

    def test_alternate_stream_finder_matches_backup_channels(self):
        from src.core.channel import Channel
        from src.core.channel_cleaner import ChannelCleaner

        main_ch = Channel("PT: RTP 1 FHD", "http://stream1.ts", stream_type="live")
        backup_ch = Channel("PT | RTP 1 HD (BACKUP)", "http://stream2.ts", stream_type="live")
        other_ch = Channel("PT: SIC HD", "http://stream3.ts", stream_type="live")

        alternates = ChannelCleaner.find_alternate_streams(main_ch, [main_ch, backup_ch, other_ch])
        self.assertEqual(len(alternates), 1)
        self.assertEqual(alternates[0].url, "http://stream2.ts")


class MetadataEnricherTests(unittest.TestCase):
    def test_extract_title_and_year_parses_properly(self):
        from src.core.metadata_enricher import MetadataEnricher

        title1, year1 = MetadataEnricher.extract_title_and_year("Inception (2010) [1080p]")
        title2, year2 = MetadataEnricher.extract_title_and_year("The Matrix (1999) 4K HEVC")
        title3, year3 = MetadataEnricher.extract_title_and_year("Gladiator")

        self.assertEqual(title1, "Inception")
        self.assertEqual(year1, 2010)
        self.assertEqual(title2, "The Matrix")
        self.assertEqual(year2, 1999)
        self.assertEqual(title3, "Gladiator")
        self.assertIsNone(year3)


class RadioSyncTests(unittest.TestCase):
    def test_radio_sync_manages_state_and_delay(self):
        from src.player.radio_sync import RadioSyncManager

        manager = RadioSyncManager()
        self.assertFalse(manager.is_active)
        self.assertEqual(manager.delay_ms, 0)

        manager.start("https://radio.example.com/stream.mp3", initial_delay_ms=250)
        self.assertTrue(manager.is_active)
        self.assertEqual(manager.delay_ms, 250)

        manager.adjust_delay(150)
        self.assertEqual(manager.delay_ms, 400)

        manager.stop()
        self.assertFalse(manager.is_active)


class ServerSpeedtestTests(unittest.TestCase):
    def test_speedtest_result_representation(self):
        from src.core.server_speedtest import SpeedtestResult

        res = SpeedtestResult("server.iptv.com", latency_ms=45.2, download_speed_mbps=38.5, status="Excelente")
        d = res.to_dict()
        self.assertEqual(d["server_host"], "server.iptv.com")
        self.assertEqual(d["latency_ms"], 45.2)
        self.assertEqual(d["download_speed_mbps"], 38.5)
        self.assertEqual(d["status"], "Excelente")


class SubtitlesFinderTests(unittest.TestCase):
    def test_save_subtitle_file_writes_utf8_srt(self):
        import tempfile
        from pathlib import Path

        from src.core.subtitles_finder import SubtitlesFinder

        with tempfile.TemporaryDirectory() as tmp_dir:
            finder = SubtitlesFinder(cache_dir=Path(tmp_dir))
            saved = finder.save_subtitle_file("1\n00:00:01,000 --> 00:00:03,000\nOlá mundo!", "legendas")
            self.assertTrue(saved.exists())
            self.assertTrue(saved.name.endswith(".srt"))
            with open(saved, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Olá mundo!", content)

    def test_subtitle_dialogs_instantiate(self):
        from src.ui.dialogs import SubtitleDelayDialog, SubtitleSearchDialog
        dialog1 = SubtitleSearchDialog(initial_query="")
        self.assertIsNotNone(dialog1)
        dialog_movie = SubtitleSearchDialog(initial_query="[PT] Matrix 1999 [FHD]")
        self.assertEqual(dialog_movie._movie_title.text(), "Matrix")
        self.assertEqual(dialog_movie._movie_year.text(), "1999")
        dialog_series = SubtitleSearchDialog(initial_query="Breaking Bad S02E05")
        self.assertEqual(dialog_series._series_title.text(), "Breaking Bad")
        self.assertEqual(dialog_series._season_spin.value(), 2)
        self.assertEqual(dialog_series._episode_spin.value(), 5)
        dialog2 = SubtitleDelayDialog(media_player=None)
        self.assertIsNotNone(dialog2)


class NewFeaturesTests(unittest.TestCase):
    """Unit tests for VOD Downloader, MultiView, and new Dialogs."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_vod_downloader_lifecycle(self):
        import tempfile

        from src.core.downloader import VODDownloader

        with tempfile.TemporaryDirectory() as tmp_dir:
            mgr = VODDownloader(download_dir=Path(tmp_dir))
            task = mgr.start_download(
                title="Test Movie 2024",
                url="http://example.com/test.mp4",
            )
            self.assertIsNotNone(task)
            self.assertEqual(task.title, "Test Movie 2024")
            self.assertEqual(mgr.get_task(task.task_id), task)
            self.assertIn(task, mgr.list_tasks())

            # Test pause, resume, cancel
            mgr.pause_download(task.task_id)
            mgr.resume_download(task.task_id)
            mgr.cancel_download(task.task_id, delete_file=False)
            self.assertEqual(task.status, "cancelled")

    def test_multiview_and_download_manager_dialogs(self):
        from src.core.channel import Channel
        from src.ui.download_manager_dialog import DownloadManagerDialog
        from src.ui.multi_view_dialog import MultiViewDialog

        ch1 = Channel(database_id=1, name="RTP 1", stream_type="live", url="http://example.com/rtp1.ts")
        ch2 = Channel(database_id=2, name="SIC", stream_type="live", url="http://example.com/sic.ts")

        # Each multiview slot creates a MediaPlayer; keep libvlc out of the test.
        vlc_patch = patch("src.player.media_player.vlc.Instance", return_value=MagicMock())
        vlc_patch.start()
        self.addCleanup(vlc_patch.stop)

        mv_dialog = MultiViewDialog(channels=[ch1, ch2], initial_channel=ch1)
        self.assertIsNotNone(mv_dialog)
        mv_dialog._set_layout(4)
        self.assertEqual(mv_dialog._multiview._active_slots_count, 4)
        mv_dialog.close()

        dl_dialog = DownloadManagerDialog(media_player=None)
        self.assertIsNotNone(dl_dialog)
        dl_dialog.close()

    def test_cast_manager_and_dialog(self):
        from unittest.mock import patch

        from src.core.cast_manager import CastDevice, CastManager
        from src.ui.cast_dialog import CastDialog

        cast_mgr = CastManager.get_instance()
        self.assertIsNotNone(cast_mgr)

        dev = CastDevice(
            device_id="test_tv_1",
            name="Sala de Estar TV",
            device_type="smart_tv",
            location="http://127.0.0.1:8080/desc.xml",
            control_url="http://127.0.0.1:8080/AVTransport/control",
        )
        cast_mgr._devices[dev.device_id] = dev
        self.assertIn(dev, cast_mgr.list_devices())

        with patch.object(cast_mgr, "_send_dlna_play", return_value=True), \
             patch.object(cast_mgr, "_send_dlna_stop", return_value=True):
            cast_mgr.cast_to_device(
                dev,
                "http://example.com/stream.ts?a=1&b=2",
                "RTP 1",
                headers={"User-Agent": "TestUA/1.0"},
                is_live=True,
            )
            self.assertTrue(cast_mgr.is_casting)
            self.assertEqual(cast_mgr.active_device, dev)

            cast_mgr.stop_cast()
            self.assertFalse(cast_mgr.is_casting)

        # Test CastStreamProxy directly
        from src.core.cast_manager import CastStreamProxy
        proxy = CastStreamProxy()
        port = proxy.start()
        self.assertGreater(port, 0)
        proxy_url = proxy.set_target("http://example.com/live.ts", headers={"User-Agent": "Test"}, is_live=True)
        self.assertIn(f":{port}/hls/live.m3u8", proxy_url)
        vod_url = proxy.set_target("http://example.com/movie.mp4", is_live=False)
        self.assertIn(f":{port}/stream.mp4", vod_url)
        proxy.stop()

        # Test Chromecast host fallback
        cc_dev = CastDevice(
            device_id="cast_test_1",
            name="Test Chromecast",
            device_type="chromecast",
            location="192.168.1.100:8009",
            chromecast_obj=None,
        )
        # Fake module so the test does not depend on pychromecast being installed.
        fake_pychromecast = MagicMock()
        with patch.dict("sys.modules", {"pychromecast": fake_pychromecast}):
            mock_get_cc = fake_pychromecast.get_chromecast_from_host
            mock_cc = mock_get_cc.return_value
            mock_cc.media_controller = mock_get_cc
            cast_mgr.cast_to_device(cc_dev, "http://example.com/movie.mp4", "Filme", is_live=False)
            self.assertTrue(cast_mgr.is_casting)
            cast_mgr.stop_cast()

        dialog = CastDialog(
            current_url="http://example.com/test.ts",
            current_title="Filme Teste",
            headers={"User-Agent": "Test"},
            is_live=False,
        )
        self.assertIsNotNone(dialog)
        dialog.close()

    def test_playlist_health_checker_and_widget(self):
        import tempfile

        from src.core.playlist_health import PlaylistHealthChecker
        from src.ui.playlist_widget import PlaylistWidget

        checker = PlaylistHealthChecker.get_instance()
        self.assertIsNotNone(checker)

        # Test Local File Health Check
        with tempfile.NamedTemporaryFile(suffix=".m3u", delete=False) as f:
            f.write(b"#EXTM3U\n#EXTINF:-1,Test\nhttp://example.com/live.ts\n")
            temp_path = f.name

        try:
            local_pl = {
                "id": 999,
                "name": "Local Playlist",
                "source_type": "m3u",
                "file_path": temp_path,
                "is_local": True,
            }
            status = checker.check_playlist_sync(local_pl)
            self.assertEqual(status.status, "local")
            self.assertEqual(status.playlist_id, 999)

            widget = PlaylistWidget()
            widget.set_playlists([local_pl])
            self.assertEqual(widget._list_widget.count(), 1)
            item_text = widget._list_widget.item(0).text()
            self.assertIn("Local Playlist", item_text)
            widget.close()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
