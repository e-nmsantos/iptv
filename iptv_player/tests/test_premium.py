"""Watch history, continue-watching, next-episode queue and EPG reminders."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.channel import Channel
from src.core.database import DatabaseManager
from src.core.playlist import Playlist
from src.core.secrets import SecretStore


class WatchHistoryTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(
            Path(self._temp.name) / "test.db", secret_store=SecretStore.for_tests()
        )
        self.playlist_id = self.db.save_playlist(
            Playlist(
                "Casa",
                "xtream",
                [
                    Channel("RTP1", "https://live/1", stream_type="live", xtream_id="1"),
                    Channel("Filme", "https://vod/2", stream_type="vod", xtream_id="2"),
                ],
            )
        )

    def tearDown(self):
        self._temp.cleanup()

    def test_episode_progress_appears_with_its_series(self):
        show = Channel("Série X", "", stream_type="series", source="xtream", xtream_id="77", logo="poster")
        episode = Channel(
            "Piloto", "https://user:pass@server/series/9.mkv", stream_type="series",
            source="xtream", xtream_id="9", season_number=1, episode_number=1,
        )
        self.db.record_watch(self.playlist_id, episode, parent=show)
        self.db.save_playback_progress(self.playlist_id, episode, 300_000, 2_400_000)

        items = self.db.get_continue_watching(self.playlist_id)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["channel"].url, episode.url)
        self.assertEqual(item["parent"].xtream_id, "77")
        self.assertEqual(item["subtitle"], "Série X")
        self.assertEqual(item["artwork"], "poster")
        self.assertAlmostEqual(item["fraction"], 0.125)

        with self.db._connection() as conn:
            stored = conn.execute("SELECT channel_data FROM watch_history").fetchone()[0]
        self.assertNotIn("pass@server", stored)

    def test_finished_items_leave_but_queued_next_episode_shows(self):
        movie = self.db.get_channels(self.playlist_id, stream_type="vod")[0]
        self.db.record_watch(self.playlist_id, movie)
        self.db.save_playback_progress(self.playlist_id, movie, 590_000, 600_000)
        self.assertEqual(self.db.get_continue_watching(self.playlist_id), [])

        nxt = Channel("Ep 2", "https://s/10.mkv", stream_type="series", source="xtream", xtream_id="10")
        self.db.record_watch(self.playlist_id, nxt, up_next=True)
        items = self.db.get_continue_watching(self.playlist_id)
        self.assertEqual([i["title"] for i in items], ["Ep 2"])
        self.assertTrue(items[0]["up_next"])

        self.db.remove_watch(self.playlist_id, items[0]["media_key"])
        self.assertEqual(self.db.get_continue_watching(self.playlist_id), [])

    def test_recent_live_and_recently_added(self):
        live = self.db.get_channels(self.playlist_id, stream_type="live")[0]
        self.db.record_watch(self.playlist_id, live)
        self.assertEqual([c.name for c in self.db.get_recent_live(self.playlist_id)], ["RTP1"])
        self.assertEqual(
            [c.name for c in self.db.get_recently_added(self.playlist_id, "vod")], ["Filme"]
        )

    def test_history_is_removed_with_its_playlist(self):
        live = self.db.get_channels(self.playlist_id, stream_type="live")[0]
        self.db.record_watch(self.playlist_id, live)
        self.db.delete_playlist(self.playlist_id)
        with self.db._connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM watch_history").fetchone()[0], 0)


class ReminderTests(unittest.TestCase):
    def test_reminders_round_trip_and_finished_ones_are_purged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(Path(temp_dir) / "test.db", secret_store=SecretStore.for_tests())
            channel = Channel("RTP1", "https://live/1", epg_channel_id="rtp1.pt")
            playlist_id = db.save_playlist(Playlist("Casa", "m3u", [channel]))
            now = datetime.now(timezone.utc)
            db.save_reminder(playlist_id, channel, "Telejornal", now + timedelta(hours=1), now + timedelta(hours=2), "record")
            db.save_reminder(playlist_id, channel, "Antigo", now - timedelta(hours=3), now - timedelta(hours=2))

            reminders = db.get_reminders(playlist_id)
            self.assertEqual([r["title"] for r in reminders], ["Telejornal"])
            self.assertEqual(reminders[0]["action"], "record")
            self.assertEqual(reminders[0]["channel"].url, "https://live/1")

            db.delete_reminder(playlist_id, "rtp1.pt", reminders[0]["start"])
            self.assertEqual(db.get_reminders(playlist_id), [])

            with self.assertRaises(ValueError):
                db.save_reminder(playlist_id, channel, "x", now, now, "explode")


if __name__ == "__main__":
    unittest.main()


class EpisodeHelperTests(unittest.TestCase):
    def test_stalker_episode_round_trips_through_its_url(self):
        from src.ui.premium_mixin import parse_stalker_episode, stalker_episode_channel

        show = Channel("Show", "", stream_type="series", source="stalker", logo="poster")
        season = {"cmd": "eyJ0eXBlIjoic2VyaWVzIn0=/x?y=1", "name": "Temporada 2"}
        episode = stalker_episode_channel(show, season, 7)
        self.assertEqual(parse_stalker_episode(episode.url), (season["cmd"], "7"))
        self.assertEqual(episode.logo, "poster")
        self.assertTrue(episode.tvg_id.endswith("#7"))

    def test_episode_index_prefers_stable_ids(self):
        from src.ui.premium_mixin import episode_index

        episodes = [
            Channel("Ep 1", "https://s/1", source="xtream", xtream_id="1", stream_type="series"),
            Channel("Ep 2", "https://s/2", source="xtream", xtream_id="2", stream_type="series"),
        ]
        replay = Channel("Ep 2", "https://other-host/2", source="xtream", xtream_id="2", stream_type="series")
        self.assertEqual(episode_index(episodes, replay), 1)
        self.assertEqual(episode_index(episodes, Channel("Nope", "https://x", source="xtream", xtream_id="9")), -1)


class TvSyncTests(unittest.TestCase):
    """Exercises the desktop client against a stand-in for the TV's /sync/<pin> endpoint."""

    def _serve(self, handler_cls):
        import threading
        from http.server import HTTPServer

        server = HTTPServer(("127.0.0.1", 0), handler_cls)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_exchange_fetches_tv_state_then_posts_merged_desktop_state(self):
        from http.server import BaseHTTPRequestHandler
        from urllib.parse import parse_qs

        from src.core.tv_sync import TvEndpoint, exchange_with_tv

        posted = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                code = 200 if self.path == "/sync/123456" else 403
                self.send_response(code)
                self.end_headers()
                self.wfile.write(b'{"schema_version":1,"favorites":["media:tv"],"progress":{}}')

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                posted.update(parse_qs(self.rfile.read(length).decode()))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

        port = self._serve(Handler)
        endpoint = TvEndpoint("Sala", "127.0.0.1", port)
        seen = []
        tv_state = exchange_with_tv(endpoint, "123 456", lambda state: seen.append(state) or '{"pc":1}')
        self.assertIn("media:tv", tv_state)
        self.assertEqual(seen, [tv_state])
        self.assertEqual(posted["source_type"], ["sync"])
        self.assertEqual(posted["sync_data"], ['{"pc":1}'])

        with self.assertRaisesRegex(ValueError, "PIN incorreto"):
            exchange_with_tv(endpoint, "654321", lambda state: "{}")
        with self.assertRaisesRegex(ValueError, "6 algarismos"):
            exchange_with_tv(endpoint, "12", lambda state: "{}")
        with self.assertRaisesRegex(ValueError, "rede local"):
            exchange_with_tv(TvEndpoint("x", "8.8.8.8", 80), "123456", lambda state: "{}")

    def test_playlists_for_tv_maps_sources_and_skips_local_files(self):
        from src.core.tv_sync import playlists_for_tv

        entries, skipped = playlists_for_tv([
            {"name": "Lista", "source_type": "m3u_plus", "url": "https://host/list.m3u"},
            {"name": "Ficheiro", "source_type": "m3u", "url": "", "file_path": "C:/lista.m3u"},
            {"name": "Conta", "source_type": "xtream", "server_url": "http://x:8080",
             "username": "u", "password": "p"},
            {"name": "Portal", "source_type": "stalker", "server_url": "http://s/c/",
             "mac_address": "00:1A:79:00:00:01"},
            {"name": "Sem pass", "source_type": "xtream", "server_url": "http://x", "username": "u"},
        ])
        self.assertEqual(
            entries,
            [
                {"source_type": "m3u", "name": "Lista", "url": "https://host/list.m3u"},
                {"source_type": "xtream", "name": "Conta", "url": "http://x:8080",
                 "username": "u", "password": "p"},
                {"source_type": "stalker", "name": "Portal", "url": "http://s/c/",
                 "mac": "00:1A:79:00:00:01"},
            ],
        )
        self.assertEqual(skipped, ["Ficheiro", "Sem pass"])

    def test_send_playlists_posts_json_batch_with_pin(self):
        import json
        from http.server import BaseHTTPRequestHandler
        from urllib.parse import parse_qs

        from src.core.tv_sync import TvEndpoint, send_playlists_to_tv

        posted = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                posted["path"] = self.path
                posted.update(parse_qs(self.rfile.read(length).decode()))
                self.send_response(200 if self.path == "/sync/123456" else 403)
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

        endpoint = TvEndpoint("Sala", "127.0.0.1", self._serve(Handler))
        entries = [{"source_type": "m3u", "name": "Ação", "url": "https://host/list.m3u"}]
        send_playlists_to_tv(endpoint, "123456", entries)
        self.assertEqual(posted["source_type"], ["playlists"])
        self.assertEqual(json.loads(posted["playlists"][0]), entries)

        with self.assertRaisesRegex(ValueError, "PIN incorreto"):
            send_playlists_to_tv(endpoint, "654321", entries)
        with self.assertRaisesRegex(ValueError, "Não há listas"):
            send_playlists_to_tv(endpoint, "123456", [])


class ContinueSyncTests(unittest.TestCase):
    """Episodes and films in "Continuar a ver" travel between devices without credentials."""

    def _db(self, source, channels):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db = DatabaseManager(Path(temp.name) / "s.db", secret_store=SecretStore.for_tests())
        playlist = Playlist("Casa", source, channels)
        playlist.server_url = "http://provider.example:8080"
        playlist.username = "user"
        playlist.password = "secret-pass"
        return db, db.save_playlist(playlist)

    def test_xtream_episode_and_film_reach_the_other_device(self):
        from src.core.device_sync import export_device_state, import_device_state

        film = Channel("Filme", "http://provider.example:8080/movie/user/secret-pass/5.mkv",
                       stream_type="vod", source="xtream", xtream_id="5")
        pc, pc_id = self._db("xtream", [film])
        tv, tv_id = self._db("xtream", [film])

        show = Channel("Série X", "", stream_type="series", source="xtream", xtream_id="77", logo="poster")
        episode = Channel("Piloto", "http://provider.example:8080/series/user/secret-pass/9.mkv",
                          stream_type="series", source="xtream", xtream_id="9",
                          season_number=1, episode_number=1, container_extension="mkv")
        pc.record_watch(pc_id, episode, parent=show)
        pc.save_playback_progress(pc_id, episode, 600_000, 2_400_000)
        saved_film = pc.get_channels(pc_id, stream_type="vod")[0]
        pc.record_watch(pc_id, saved_film)
        pc.save_playback_progress(pc_id, saved_film, 1_200_000, 6_000_000)

        payload = export_device_state(pc, pc_id)
        self.assertNotIn("secret-pass", payload)
        result = import_device_state(tv, tv_id, payload)
        self.assertEqual(result["continue"], 2)

        items = {item["title"]: item for item in tv.get_continue_watching(tv_id)}
        self.assertEqual(set(items), {"Piloto", "Filme"})
        ep = items["Piloto"]
        self.assertEqual(ep["channel"].url, "xtream-episode://9?ext=mkv")
        self.assertEqual(ep["parent"].xtream_id, "77")
        self.assertEqual(ep["position_ms"], 600_000)
        self.assertEqual(items["Filme"]["position_ms"], 1_200_000)

        # Importing the same state again changes nothing: the local entry is not older.
        self.assertEqual(import_device_state(tv, tv_id, payload)["continue"], 0)

    def test_stalker_episode_round_trip_and_newer_local_viewing_wins(self):
        from datetime import timedelta

        from src.core.device_sync import export_device_state, import_device_state
        from src.core.episodes import stalker_episode_channel

        pc, pc_id = self._db("stalker", [Channel("Canal", "ffrt http://x/1", source="stalker")])
        tv, tv_id = self._db("stalker", [Channel("Canal", "ffrt http://x/1", source="stalker")])
        show = Channel("Show", "", stream_type="series", source="stalker", xtream_id="44", category_id="7")
        episode = stalker_episode_channel(show, {"cmd": "eyJzIjoxfQ==", "name": "Temporada 2"}, 3)
        pc.record_watch(pc_id, episode, parent=show, up_next=True)

        import_device_state(tv, tv_id, export_device_state(pc, pc_id))
        received = tv.get_continue_watching(tv_id)[0]
        self.assertTrue(received["up_next"])
        self.assertEqual(received["channel"].tvg_id, episode.tvg_id)
        self.assertEqual(received["parent"].category_id, "7")

        # The TV then watches it further; an older PC state must not roll it back.
        tv.record_watch(tv_id, received["channel"], parent=received["parent"],
                        played_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        tv.save_playback_progress(tv_id, received["channel"], 300_000, 1_800_000)
        self.assertEqual(import_device_state(tv, tv_id, export_device_state(pc, pc_id))["continue"], 0)
        self.assertFalse(tv.get_continue_watching(tv_id)[0]["up_next"])


class ProgressBarTests(unittest.TestCase):
    """The film progress bar follows elapsed time and restarts for each new item."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _widget(self):
        from PySide6.QtCore import QObject, Signal

        from src.ui.player_widget import PlayerWidget

        class FakePlayer(QObject):
            position_changed = Signal(float)
            time_changed = Signal(int)
            state_changed = Signal(str)
            error_occurred = Signal(str)
            recording_state_changed = Signal(bool, str)
            stats_changed = Signal(dict)
            timeshift_limit_reached = Signal()

            def __init__(self):
                super().__init__()
                self.length = 0
                self.is_playing = False
                self.is_recording = False

            def get_volume(self):
                return 80

            def get_length(self):
                return self.length

        player = FakePlayer()
        widget = PlayerWidget(player)
        self.addCleanup(widget.deleteLater)
        return player, widget

    def test_bar_follows_time_not_vlc_byte_position_and_resets_between_films(self):
        player, widget = self._widget()
        widget.set_stream_type("vod")
        player.length = 5_566_000  # 01:32:46
        player.time_changed.emit(5_000)
        player.position_changed.emit(0.38)  # VLC's byte-based estimate for HTTP VOD
        self.assertEqual(widget._progress_slider.value(), 0)
        self.assertEqual(widget._time_label.text(), "00:05 / 01:32:46")

        player.time_changed.emit(2_783_000)
        self.assertEqual(widget._progress_slider.value(), 500)

        widget.set_stream_type("vod")  # next film
        self.assertEqual(widget._progress_slider.value(), 0)
        self.assertEqual(widget._last_seek_value, -1)
