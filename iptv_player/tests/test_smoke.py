"""End-to-end smoke test of the core import/browse/EPG/favorite/resume flow.

Runs entirely offline (temp SQLite + test keyring) and exercises the real
controllers and repository — the same path the UI drives at startup and when
browsing a playlist.
"""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.controllers.playback_controller import PlaybackController
from src.controllers.playlist_controller import PlaylistController
from src.core.database import DatabaseManager
from src.core.epg import EPGProgram
from src.core.secrets import SecretStore
from src.parsers.m3u_parser import M3UParser


class SmokeFlowTests(unittest.TestCase):
    def setUp(self):
        self.secrets = SecretStore.for_tests()

    def _build_db(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return DatabaseManager(
            Path(temp_dir.name) / "smoke.db", secret_store=self.secrets
        )

    def test_import_browse_epg_favorite_resume_flow(self):
        db = self._build_db()
        playlists = PlaylistController(db)

        # 1. Import an M3U playlist through the real parser.
        content = (
            "#EXTM3U\n"
            '#EXTINF:-1 tvg-id="one" group-title="Notícias",Canal 1\n'
            "https://example.test/live/1.m3u8\n"
            '#EXTINF:-1 group-title="Filmes",Filme A\n'
            "https://example.test/movie/2.mp4\n"
        )
        parsed = M3UParser()._parse_content(content, "Teste")
        playlist_id, channels = playlists.import_playlist(parsed)

        self.assertGreater(playlist_id, 0)
        self.assertEqual(len(channels), 2)

        # 2. Open the playlist (session-restore path) and check the light path.
        details, opened = playlists.open(playlist_id)
        self.assertEqual(details["name"], "Teste")
        self.assertEqual(len(opened), 2)

        light = db.get_channels(playlist_id, decrypt_urls=False)
        self.assertEqual(len(light), 2)
        self.assertEqual(light[0].url, "")

        # 3. EPG round-trip for a live channel.
        start = datetime.now(timezone.utc).replace(microsecond=0)
        db.replace_channel_epg(
            playlist_id, "one", [EPGProgram("one", "Telejornal", start, start + timedelta(hours=1))]
        )
        self.assertEqual(
            [program.title for program in db.get_playlist_epg(playlist_id)],
            ["Telejornal"],
        )

        # 4. Favorites toggle.
        db.set_favorite(opened[0].database_id, playlist_id, True)
        favorites = db.get_favorites(playlist_id)
        self.assertEqual([f.database_id for f in favorites], [opened[0].database_id])

        # 5. VOD progress -> resume candidate (no URL stored).
        vod = opened[1]
        PlaybackController(db).save_progress(playlist_id, vod, 120_000, 3_600_000)
        resume = db.get_resume_candidates(playlist_id)
        self.assertEqual([entry["channel"].name for entry in resume], ["Filme A"])

    def test_light_hydration_restores_url_for_playback(self):
        db = self._build_db()
        playlists = PlaylistController(db)
        playlist_id, channels = playlists.import_playlist(
            M3UParser()._parse_content(
                "#EXTM3U\n#EXTINF:-1,Canal\nhttps://example.test/live/1.ts\n",
                "Hidratação",
            )
        )
        channel = db.get_channels(playlist_id, decrypt_urls=False)[0]
        self.assertEqual(channel.url, "")
        self.assertTrue(channel.database_id > 0)

        hydrated = db.get_channel(channel.database_id, playlist_id)
        self.assertEqual(hydrated.url, "https://example.test/live/1.ts")
