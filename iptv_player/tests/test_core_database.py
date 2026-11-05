"""Regression tests for the local, network-independent application core."""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt

from src.core.channel import Channel
from src.core.database import DatabaseManager
from src.core.epg import EPGProgram
from src.core.playlist import Playlist
from src.core.secrets import SecretStore
from src.parsers.m3u_parser import M3UParser


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
            self.assertEqual(version, "7")
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
