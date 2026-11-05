"""Regression tests for the local, network-independent application core."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QObject

from src.core.channel import Channel
from src.player.media_player import MediaPlayer
from src.utils.logger import redact_sensitive


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
        player._is_recording = False
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
        player._timeshift_timer = MagicMock()
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
        self.assertIn(f":{port}/{proxy._token}/hls/live.m3u8", proxy_url)
        vod_url = proxy.set_target("http://example.com/movie.mp4", is_live=False)
        self.assertIn(f":{port}/{proxy._token}/stream.mp4", vod_url)
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
