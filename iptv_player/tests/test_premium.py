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
