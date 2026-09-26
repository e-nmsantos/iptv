import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.core.downloader import DownloadTask, VODDownloader
from src.core.subtitles_finder import (
    OPENSUBTITLES_REST_BASE,
    OPENSUBTITLES_USER_AGENT,
    SubtitleResult,
    SubtitlesFinder,
)
from src.player.media_player import MediaPlayer
from src.player.pvr_recorder import PvrRecorderManager
from src.ui.cast_dialog import CastDialog


class DownloaderFixesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.save_dir = Path(self.temp_dir.name)
        self.downloader = VODDownloader(download_dir=self.save_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_filename_collision_avoidance(self):
        existing_file = self.save_dir / 'Movie_1.mp4'
        existing_file.write_text('existing content')

        with patch('threading.Thread'):
            task = self.downloader.start_download(
                url='http://example.com/movie.mp4',
                title='Movie 1',
            )
            self.assertIsNotNone(task)
            self.assertNotEqual(task.target_path, existing_file)
            self.assertEqual(task.target_path.name, 'Movie_1_1.mp4')

    def test_resume_download_thread_safety(self):
        task = DownloadTask(
            task_id='test-dl-1',
            url='http://example.com/test.mp4',
            title='Test Stream',
            target_path=self.save_dir / 'test.mp4',
            headers={},
            status='paused',
        )
        self.downloader._tasks[task.task_id] = task

        mock_thread = MagicMock(spec=threading.Thread)
        mock_thread.is_alive.side_effect = [True, False]
        task._thread = mock_thread

        with patch('threading.Thread') as mock_thread_cls:
            self.downloader.resume_download(task.task_id)
            mock_thread.join.assert_called_once_with(timeout=2.0)
            mock_thread_cls.assert_called_once()


class SubtitlesFixesTest(unittest.TestCase):
    def test_constants_defined(self):
        self.assertTrue(len(OPENSUBTITLES_USER_AGENT) > 0)
        self.assertTrue(OPENSUBTITLES_REST_BASE.startswith('https://'))

    @patch('requests.get')
    def test_download_subtitle_file_returns_none_on_failure(self, mock_get):
        mock_get.side_effect = Exception('Network connection failed')
        finder = SubtitlesFinder()
        finder._get_vlsub_token = MagicMock(return_value=None)
        sub_item = SubtitleResult(
            subtitle_id='123',
            language='PT',
            release_name='Movie.2024',
            download_url='https://api.opensubtitles.com/download/123',
            source='http',
        )
        result = finder.download_subtitle_file(sub_item)
        self.assertIsNone(result)


class MediaPlayerAndCastTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Never start a real libvlc instance: headless CI runners cannot rely on it.
        patcher = patch("src.player.media_player.vlc.Instance", return_value=MagicMock())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_media_player_vlc_instance_property(self):
        player = MediaPlayer()
        self.assertEqual(player.vlc_instance, player._instance)

    def test_cast_dialog_vlc_lookup(self):
        mock_player = MagicMock()
        mock_player.vlc_instance = 'vlc_inst_obj'
        with patch('src.ui.cast_dialog.CastManager') as MockCastManager:
            cast_mgr_inst = MockCastManager.get_instance.return_value
            with patch.object(CastDialog, '_populate_list'):
                CastDialog(media_player=mock_player)
                cast_mgr_inst.start_discovery.assert_called_with('vlc_inst_obj')

    def test_media_player_renderer_methods(self):
        player = MediaPlayer()
        self.assertFalse(player.has_renderer())
        self.assertIsNone(player.get_renderer())

        mock_renderer = MagicMock()
        with patch.object(player._player, 'set_renderer', return_value=0) as mock_set:
            success = player.set_renderer(mock_renderer)
            self.assertTrue(success)
            self.assertTrue(player.has_renderer())
            self.assertEqual(player.get_renderer(), mock_renderer)
            mock_set.assert_called_with(mock_renderer)

            clear_success = player.clear_renderer()
            self.assertTrue(clear_success)
            self.assertFalse(player.has_renderer())
            mock_set.assert_called_with(None)

    def test_set_renderer_reopens_current_stream_after_switching_output(self):
        # libVLC ignores set_renderer() on media that is already playing.
        player = MediaPlayer()
        player.play("http://example.com/live.ts", {"User-Agent": "UA"}, is_live=True)
        vlc_player = player._player
        vlc_player.reset_mock()
        vlc_player.set_renderer.return_value = 0
        renderer = MagicMock()

        self.assertTrue(player.set_renderer(renderer))

        calls = [c[0] for c in vlc_player.method_calls if not c[0].startswith(("get_", "video_get"))]
        self.assertEqual(calls[:2], ["stop", "set_renderer"])
        self.assertIn("set_media", calls[2:])
        self.assertIn("play", calls[calls.index("set_media"):])
        self.assertEqual(player._current_url, "http://example.com/live.ts")

    def test_chromecast_port_skips_ports_that_cannot_be_bound(self):
        import socket

        from src.player.media_player import pick_chromecast_http_port

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("0.0.0.0", 0))
            busy.listen(1)
            taken = busy.getsockname()[1]
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("0.0.0.0", 0))
                free = probe.getsockname()[1]
            self.assertEqual(pick_chromecast_http_port((taken, free)), free)

    def test_vlc_instance_uses_the_picked_chromecast_port(self):
        with patch("src.player.media_player.pick_chromecast_http_port", return_value=18010), \
                patch("src.player.media_player.vlc.Instance", return_value=MagicMock()) as make:
            MediaPlayer()
        self.assertIn("--sout-chromecast-http-port=18010", make.call_args[0][0])

    def test_set_renderer_keeps_position_and_subtitle_of_a_movie(self):
        player = MediaPlayer()
        player.play("http://example.com/movie.mkv", is_live=False)
        vlc_player = player._player
        vlc_player.get_time.return_value = 1_800_000
        vlc_player.video_get_spu.return_value = 3
        vlc_player.set_renderer.return_value = 0
        vlc_player.get_length.return_value = 7_200_000

        self.assertTrue(player.set_renderer(MagicMock()))

        vlc_player.video_set_spu.assert_called_with(3)
        vlc_player.set_time.assert_called_with(1_800_000)

    def test_set_renderer_failure_keeps_local_output(self):
        player = MediaPlayer()
        player._player.set_renderer.return_value = -1
        self.assertFalse(player.set_renderer(MagicMock()))
        self.assertFalse(player.has_renderer())

    def test_channel_change_keeps_chromecast_sout(self):
        player = MediaPlayer()
        player.play("http://example.com/one.ts", is_live=True)
        player.set_cast_target("192.168.1.80:8009")
        media = player._instance.media_new.return_value
        media.reset_mock()

        player.play("http://example.com/two.ts", is_live=True)

        options = [c.args[0] for c in media.add_option.call_args_list]
        self.assertIn(":sout=#chromecast{ip=192.168.1.80}", options)

    def test_device_names_match_exactly_not_by_substring(self):
        from src.core.cast_manager import _same_device_name

        self.assertTrue(_same_device_name("📺 TV da sala de família", "tv da sala de FAMÍLIA"))
        self.assertFalse(_same_device_name("📺 [TV] Samsung", "TV"))
        self.assertFalse(_same_device_name("📺 TV da sala de família", "TV"))

    def test_dlna_answer_from_a_chromecast_tv_is_merged(self):
        from src.core.cast_manager import CastDevice, CastManager

        mgr = CastManager()
        mgr._devices["vlc_sala"] = CastDevice(
            device_id="vlc_sala", name="📺 TV da sala", device_type="chromecast",
            location="vlc", vlc_renderer=MagicMock(),
        )
        xml = (
            b'<root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
            b"<friendlyName>TV da sala</friendlyName><serviceList><service>"
            b"<serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>"
            b"<controlURL>/avt</controlURL></service></serviceList></device></root>"
        )
        response = MagicMock()
        response.__enter__.return_value.read.return_value = xml
        with patch("src.core.cast_manager.urllib.request.urlopen", return_value=response):
            mgr._resolve_upnp_device("http://192.168.1.50:52323/MediaRenderer.xml")

        self.assertEqual(len(mgr.list_devices()), 1)
        self.assertEqual(mgr.list_devices()[0].control_url, "http://192.168.1.50:52323/avt")

    def test_cast_manager_vlc_renderer_casting(self):
        from src.core.cast_manager import CastDevice, CastManager
        cast_mgr = CastManager.get_instance()
        mock_r = MagicMock()
        dev = CastDevice(
            device_id="vlc_test_tv",
            name="📺 Test Android TV",
            device_type="vlc_renderer",
            location="vlc",
            vlc_renderer=mock_r,
        )
        mock_media_player = MagicMock()
        mock_media_player.set_renderer.return_value = True

        res = cast_mgr.cast_to_device(
            dev,
            "http://stream.test/live.ts",
            "Test TV",
            media_player=mock_media_player,
        )
        self.assertTrue(res)
        self.assertTrue(cast_mgr.is_casting)
        mock_media_player.set_renderer.assert_called_with(mock_r)

        cast_mgr.stop_cast()
        self.assertFalse(cast_mgr.is_casting)
        mock_media_player.clear_renderer.assert_called_once()

    def test_cast_manager_chromecast_ip_sout_casting(self):
        from src.core.cast_manager import CastDevice, CastManager
        cast_mgr = CastManager.get_instance()
        dev = CastDevice(
            device_id="cast_mitv",
            name="📺 Box de TV Xiaomi (MiTV-AFKR0)",
            device_type="chromecast",
            location="192.168.1.80:8009",
        )
        mock_media_player = MagicMock()
        mock_media_player.set_cast_target.return_value = True

        res = cast_mgr.cast_to_device(
            dev,
            "http://stream.test/live.ts",
            "Test Live",
            media_player=mock_media_player,
        )
        self.assertTrue(res)
        self.assertTrue(cast_mgr.is_casting)
        mock_media_player.set_cast_target.assert_called_with("192.168.1.80")

        cast_mgr.stop_cast()
        self.assertFalse(cast_mgr.is_casting)
        mock_media_player.clear_cast_target.assert_called_once()


class PVRRecorderImportTest(unittest.TestCase):
    def test_pvr_recorder_initializes(self):
        with tempfile.TemporaryDirectory() as tmp:
            pvr = PvrRecorderManager(default_output_dir=Path(tmp))
            self.assertIsNotNone(pvr)
            self.assertEqual(pvr.output_dir, Path(tmp))


class PlaylistSwitchingAndOptimizationTests(unittest.TestCase):
    def setUp(self):
        from src.core.channel import Channel
        from src.core.database import DatabaseManager
        from src.core.secrets import SecretStore
        self.Channel = Channel
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        # Test key: CI Linux runners have no system keyring backend.
        self.db = DatabaseManager(db_path=self.db_path, secret_store=SecretStore.for_tests())

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_database_indexes_created(self):
        with self.db._connection() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
            index_names = {row["name"] for row in rows}
            self.assertIn("idx_channels_playlist_stream", index_names)
            self.assertIn("idx_channels_playlist_group", index_names)
            self.assertIn("idx_channels_playlist_favorite", index_names)

    def test_stream_type_filtering_in_get_channels_and_groups(self):
        from src.core.playlist import Playlist
        channels = [
            self.Channel(name="Live 1", url="http://1", stream_type="live", group="News"),
            self.Channel(name="Live 2", url="http://2", stream_type="live", group="Sports"),
            self.Channel(name="Movie 1", url="http://3", stream_type="vod", group="Cinema"),
            self.Channel(name="Movie 2", url="http://4", stream_type="movie", group="Cinema"),
            self.Channel(name="Series 1", url="http://5", stream_type="series", group="Shows"),
        ]
        pl = Playlist(name="Test PL", source_type="m3u", channels=channels)
        pl_id = self.db.save_playlist(pl)

        # Test stream_type filtering
        live = self.db.get_channels(pl_id, stream_type="live")
        self.assertEqual(len(live), 2)
        self.assertTrue(all(c.stream_type == "live" for c in live))

        vod = self.db.get_channels(pl_id, stream_type="vod")
        self.assertEqual(len(vod), 2)
        self.assertTrue(all(c.stream_type in ("vod", "movie") for c in vod))

        series = self.db.get_channels(pl_id, stream_type="series")
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0].name, "Series 1")

        # Test group filtering by stream_type
        live_groups = self.db.get_groups(pl_id, stream_type="live")
        self.assertEqual(set(live_groups), {"News", "Sports"})

        vod_groups = self.db.get_groups(pl_id, stream_type="vod")
        self.assertEqual(vod_groups, ["Cinema"])

    def test_playlist_memory_cache_lifecycle(self):
        from unittest.mock import MagicMock

        from src.ui.catalog_mixin import CatalogMixin
        from src.ui.playlist_ops_mixin import PlaylistOpsMixin

        class DummyWindow(PlaylistOpsMixin, CatalogMixin):
            def __init__(self, db):
                self._db = db
                self._current_playlist_id = None
                self._playlist_channel_cache = {}
                self._cached_channels_by_type = {}
                self._dirty_tabs = set()
                self._content_stack = MagicMock()
                self._content_stack.currentIndex.return_value = 0
                self._live_list = MagicMock()
                self._vod_list = MagicMock()
                self._series_browser = MagicMock()
                self._refresh_locked_groups = MagicMock()
                self._refresh_history = MagicMock()
                self._refresh_resume = MagicMock()
                self._load_playlists = MagicMock()
                self._load_playlist_epg = MagicMock()
                self._ensure_catalog_for_tab = MagicMock()
                self._playlist_controller = MagicMock()
                self._playlist_controller.list.return_value = [{"id": 1, "name": "PL1"}]
                self._playlist_widget = MagicMock()
                self._epg_widget = MagicMock()
                self._discard_provider_sessions = MagicMock()
                self._catalog_loading = set()
                self._logger = MagicMock()
                self._closing = False
                self._status_bar = MagicMock()

            def statusBar(self):
                return self._status_bar

        win = DummyWindow(self.db)
        ch_live = self.Channel(name="L1", url="http://1", stream_type="live")
        ch_vod = self.Channel(name="V1", url="http://2", stream_type="vod")

        win._current_playlist_id = 1
        win._distribute_channels([ch_live, ch_vod])

        # Verify cache has been populated
        self.assertIn(1, win._playlist_channel_cache)
        self.assertEqual(len(win._playlist_channel_cache[1]["live"]), 1)
        self.assertEqual(len(win._playlist_channel_cache[1]["vod"]), 1)

        # Invalidate on delete
        win._on_playlist_deleted(1)
        self.assertNotIn(1, win._playlist_channel_cache)

    def _repair_window(self, database):
        """Minimal window exposing only what the one-time repairs need."""
        from src.ui.catalog_mixin import CatalogMixin
        from src.ui.playlist_ops_mixin import PlaylistOpsMixin

        class DummyWindow(PlaylistOpsMixin, CatalogMixin):
            def __init__(self, db):
                self._db = db
                self._current_playlist_id = 1
                self._playlist_channel_cache = {}
                self._cached_channels_by_type = {}
                self._dirty_tabs = set()
                self._content_stack = MagicMock()
                self._content_stack.currentIndex.return_value = 0
                self._live_list = MagicMock()
                self._vod_list = MagicMock()
                self._series_browser = MagicMock()
                self._refresh_locked_groups = MagicMock()
                self._settings = MagicMock()
                self._settings.get.return_value = 30
                self._run_background = MagicMock()
                self._stalker_metadata_loading = set()
                self._logger = MagicMock()
                self._closing = False
                self._status_bar = MagicMock()

            def statusBar(self):
                return self._status_bar

            def _distribute_channels(self, channels):
                self._distributed = channels

        return DummyWindow(database)

    def test_m3u_type_repair_reclassifies_and_flags_once(self):
        db = MagicMock()
        db.get_metadata_flag.return_value = False
        win = self._repair_window(db)
        channels = [
            self.Channel(name="Filme", url="", group="VOD | Filmes"),
            self.Channel(name="Serie S01E02", url="", group="Séries"),
            self.Channel(name="Noticias", url="", group="News"),
        ]

        win._repair_m3u_stream_types(7, channels)

        self.assertEqual(
            [channel.stream_type for channel in channels],
            ["vod", "series", "live"],
        )
        _, updated = db.update_channel_stream_types.call_args.args
        self.assertEqual(
            {channel.name for channel in updated}, {"Filme", "Serie S01E02"}
        )
        db.set_metadata_flag.assert_called_once_with("m3u_types_repaired:7")

    def test_m3u_type_repair_is_skipped_when_the_flag_is_set(self):
        db = MagicMock()
        db.get_metadata_flag.return_value = True
        win = self._repair_window(db)
        channels = [self.Channel(name="Filme", url="", group="VOD | Filmes")]

        win._repair_m3u_stream_types(7, channels)

        self.assertEqual(channels[0].stream_type, "live")
        db.update_channel_stream_types.assert_not_called()
        db.set_metadata_flag.assert_not_called()

    def test_stalker_header_repair_restores_mag_headers_once(self):
        db = MagicMock()
        db.get_metadata_flag.return_value = False
        win = self._repair_window(db)
        channels = [self.Channel(name="Canal", url="", source="stalker")]

        win._repair_stalker_channel_headers(
            3, {"server_url": "https://portal.test/c/"}, channels
        )

        self.assertIn("MAG425", channels[0].user_agent)
        self.assertEqual(channels[0].referer, "https://portal.test/c/")
        _, user_agent, referer = db.update_stalker_headers.call_args.args
        self.assertIn("MAG425", user_agent)
        self.assertEqual(referer, "https://portal.test/c/")
        db.set_metadata_flag.assert_called_once_with("stalker_headers_repaired:3")

    def test_pending_repairs_dispatch_by_source_type(self):
        db = MagicMock()
        db.get_metadata_flag.return_value = False
        win = self._repair_window(db)
        win._refresh_stalker_metadata_if_needed = MagicMock()
        m3u_channels = [
            self.Channel(name="Filme", url="", group="VOD | Filmes")
        ]

        returned = win._run_pending_catalog_repairs(
            5, {"source_type": "m3u"}, m3u_channels
        )

        self.assertIs(returned, m3u_channels)
        self.assertEqual(m3u_channels[0].stream_type, "vod")
        win._refresh_stalker_metadata_if_needed.assert_not_called()

        stalker_channels = [self.Channel(name="Canal", url="", source="stalker")]
        win._run_pending_catalog_repairs(
            6, {"source_type": "stalker", "server_url": "https://p.test"}, stalker_channels
        )

        win._refresh_stalker_metadata_if_needed.assert_called_once()

    def test_no_repairs_when_the_playlist_is_unknown(self):
        win = self._repair_window(MagicMock())
        channels = [self.Channel(name="Canal", url="")]

        self.assertIs(
            win._run_pending_catalog_repairs(1, None, channels), channels
        )


class PlayerWidgetUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_player_widget_init_and_error_banner(self):
        from src.ui.player_widget import PlayerWidget
        player = MagicMock(spec=MediaPlayer)
        player.get_volume.return_value = 80
        widget = PlayerWidget(media_player=player)
        self.assertIsNotNone(widget._error_countdown_timer)
        widget.set_stream_type("vod")
        self.assertFalse(widget._skip_back_btn.isHidden())
        self.assertFalse(widget._skip_forward_btn.isHidden())
        widget.set_stream_type("live")
        self.assertTrue(widget._skip_back_btn.isHidden())
        self.assertTrue(widget._skip_forward_btn.isHidden())

        widget.show_error_banner("Erro de teste", is_live=True)
        self.assertFalse(widget._error_banner.isHidden())
        self.assertTrue(widget._error_countdown_timer.isActive())
        widget.clear_error_banner()
        self.assertTrue(widget._error_banner.isHidden())
        self.assertFalse(widget._error_countdown_timer.isActive())
        widget.close()

    def test_channel_list_page_size_and_pagination(self):
        from src.core.channel import Channel
        from src.ui.channel_list import ChannelListWidget
        ch_list = ChannelListWidget()
        self.assertEqual(ch_list.PAGE_SIZE, 250)
        channels = [Channel(name=f"Ch {i}", url=f"http://{i}", group="G1") for i in range(600)]
        ch_list.set_channels(channels)
        self.assertEqual(ch_list._page_count, 3)
        self.assertEqual(ch_list._channel_list.count(), 250)
        ch_list.close()

    def test_hydration_caches_url_in_memory(self):
        from src.core.channel import Channel
        from src.ui.playback import PlaybackMixin
        class DummyPlayback(PlaybackMixin):
            def __init__(self):
                self._current_playlist_id = 1
                self._db = MagicMock()
        playback = DummyPlayback()
        ch = Channel(name="Test", url="", database_id=10)
        playback._db.get_channel.return_value = Channel(name="Test", url="http://hydrated.stream", database_id=10)
        hydrated = playback._hydrate_channel(ch)
        self.assertEqual(hydrated.url, "http://hydrated.stream")
        self.assertEqual(ch.url, "http://hydrated.stream")
        # Second call returns cached URL without querying DB
        playback._db.get_channel.reset_mock()
        second = playback._hydrate_channel(ch)
        playback._db.get_channel.assert_not_called()
        self.assertEqual(second.url, "http://hydrated.stream")

    def test_stalker_direct_channel_plays_without_temporary_resolution(self):
        from src.core.channel import Channel
        from src.ui.playback import PlaybackMixin
        class DummyPlayback(PlaybackMixin):
            def __init__(self):
                self._current_playlist_id = 1
                self._db = MagicMock()
                self._play_channel = MagicMock()
                self._run_background = MagicMock()
                self._load_channel_epg = MagicMock()
        playback = DummyPlayback()
        ch = Channel(
            name="Direct Stalker",
            url="http://portal.example.com:80/play/live.php?mac=00:1A:79:00:00:00&stream=1000&extension=ts",
            source="stalker",
            stream_type="live",
        )
        playback._on_channel_selected(ch)
        playback._play_channel.assert_called_once_with(ch)
        playback._run_background.assert_not_called()

    def test_stalker_temporary_channel_triggers_resolution(self):
        from src.core.channel import Channel
        from src.ui.playback import PlaybackMixin
        class DummyPlayback(PlaybackMixin):
            def __init__(self):
                self._current_playlist_id = 1
                self._db = MagicMock()
                self._play_channel = MagicMock()
                self._run_background = MagicMock()
                self._load_channel_epg = MagicMock()
        playback = DummyPlayback()
        ch = Channel(
            name="Localhost Stalker",
            url="http://localhost/ch/129347_",
            source="stalker",
            stream_type="live",
        )
        playback._on_channel_selected(ch)
        playback._run_background.assert_called_once()
        playback._play_channel.assert_not_called()

    def test_stalker_parser_extracts_stream_id_and_rejects_empty_stream(self):
        from src.parsers.stalker_parser import StalkerParser
        parser = StalkerParser("http://example.com/c/", "00:1A:79:00:00:00")
        parser._token = "token123"
        captured = {}

        class DummyResponse:
            text = '{"js": {"cmd": "ffmpeg http://cdn.test/live.php?mac=00:1A:79:00:00:00&stream=9999&extension=ts"}}'

        def dummy_post(data):
            captured.update(data)
            return DummyResponse()

        parser._post = dummy_post
        resolved = parser.resolve_live_link("http://cdn.test/live.php?mac=...&stream=9999&extension=ts")
        self.assertEqual(captured["cmd"], "http://localhost/ch/9999")
        self.assertIn("stream=9999", resolved)

        # Empty stream in response should raise ConnectionError
        class BrokenResponse:
            text = '{"js": {"cmd": "ffmpeg http://cdn.test/live.php?mac=...&stream=&extension=ts"}}'

        parser._post = lambda data: BrokenResponse()
        with self.assertRaises(ConnectionError):
            parser.resolve_live_link("http://localhost/ch/9999")


    def test_media_player_effective_cache_and_watchdog_ticks(self):
        from src.player.media_player import (
            _LIVE_BUFFER_WATCHDOG_TICKS,
            _LIVE_STALL_WATCHDOG_TICKS,
            MediaPlayer,
        )
        self.assertGreaterEqual(_LIVE_BUFFER_WATCHDOG_TICKS, 30)
        self.assertGreaterEqual(_LIVE_STALL_WATCHDOG_TICKS, 30)

        player = MediaPlayer.__new__(MediaPlayer)
        player._current_is_live = True
        player._buffer_size_ms = 1000
        # 1000ms buffer setting should be respected for live streams (not forced to 5000ms)
        self.assertEqual(player._effective_cache_ms(), 1000)

        # Floor of 500ms
        player._buffer_size_ms = 300
        self.assertEqual(player._effective_cache_ms(), 500)

    def test_stalker_resolve_live_link_reauth_on_initial_failure(self):
        from src.parsers.stalker_parser import StalkerParser
        parser = StalkerParser("http://example.com/c/", "00:1A:79:00:00:00")
        parser._token = "old_expired_token"
        call_count = 0

        class BadResponse:
            text = '{"js": {"cmd": ""}}'

        class GoodResponse:
            text = '{"js": {"cmd": "ffmpeg http://cdn.test/live.php?stream=777"}}'

        def dummy_post(data):
            nonlocal call_count
            call_count += 1
            if data.get("token") == "old_expired_token":
                return BadResponse()
            return GoodResponse()

        def dummy_auth():
            parser._token = "fresh_token_456"
            return True

        parser._post = dummy_post
        parser.authenticate = dummy_auth

        resolved = parser.resolve_live_link("777")
        self.assertIn("stream=777", resolved)
        self.assertEqual(parser._token, "fresh_token_456")
        self.assertEqual(call_count, 2)

    def test_playlist_ops_mixin_cached_name_lookup(self):
        from src.ui.playlist_ops_mixin import PlaylistOpsMixin
        class DummyOps(PlaylistOpsMixin):
            def __init__(self):
                self._playlist_names = {10: "Cached Playlist 10"}
                self._playlists = [{"id": 20, "name": "Memory List 20"}]
                self._db = MagicMock()
        ops = DummyOps()
        # Should return from _playlist_names without touching _db
        self.assertEqual(ops._get_playlist_name(10), "Cached Playlist 10")
        ops._db.get_playlist.assert_not_called()
        # Should return from _playlists
    def test_parsers_cancel_requested_support(self):
        """Test that StalkerParser, XtreamParser, and M3UParser accept cancel_requested."""
        from src.parsers.m3u_parser import M3UParser
        from src.parsers.stalker_parser import StalkerParser
        from src.parsers.xtream_parser import XtreamParser

        def cancel_cb():
            return False

        # StalkerParser
        stalker = StalkerParser(
            "http://example.com/c/",
            "00:1A:79:00:00:00",
            timeout=10,
            cancel_requested=cancel_cb,
        )
        self.assertEqual(stalker._timeout, 10)
        self.assertIs(stalker._cancel_requested, cancel_cb)
        stalker.close()

        # XtreamParser
        xtream = XtreamParser(
            "http://example.com:8080",
            "user",
            "pass",
            timeout=15,
            cancel_requested=cancel_cb,
        )
        self.assertEqual(xtream._timeout, 15)
        self.assertIs(xtream._cancel_requested, cancel_cb)
        xtream.close()

        # M3UParser
        m3u = M3UParser(
            timeout=20,
            cancel_requested=cancel_cb,
        )
        self.assertEqual(m3u._timeout, 20)
        self.assertIs(m3u._should_cancel, cancel_cb)


class ReviewFindingsRegressionTests(unittest.TestCase):
    def test_gzip_playlist_is_limited_after_decompression(self):
        import gzip

        from src.parsers.m3u_parser import M3UParser

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "big.m3u.gz"
            path.write_bytes(gzip.compress(b"#EXTM3U\n" + b"x" * 5000))
            parser = M3UParser()
            parser.MAX_DOWNLOAD_BYTES = 1000  # compressed file is far smaller than this
            with self.assertRaises(ValueError):
                parser.parse(str(path))

    def test_recordings_started_together_get_distinct_files(self):
        from src.player.pvr_recorder import PvrRecorderManager, RecordingSession

        with tempfile.TemporaryDirectory() as temp_dir,                 patch.object(RecordingSession, "start"),                 patch("src.player.pvr_recorder.datetime") as fake_datetime:
            fake_datetime.now.return_value.strftime.return_value = "20260101_000000_000000"
            manager = PvrRecorderManager(Path(temp_dir))
            first = manager.start_recording("RTP 1", "http://example.com/a.ts")
            second = manager.start_recording("RTP 1", "http://example.com/a.ts")
            self.assertNotEqual(first.output_file, second.output_file)

    def test_movie_stream_type_counts_as_vod(self):
        from src.core.channel import Channel
        from src.core.playlist import Playlist

        playlist = Playlist(name="Test", source_type="xtream")
        movie = Channel(name="Filme", url="http://example.com/f.mp4", stream_type="movie")
        playlist.add_channel(movie)
        self.assertEqual(playlist.total_vod, 1)
        playlist.remove_channel(movie)
        self.assertEqual(playlist.total_vod, 0)

    def test_pip_window_emits_closed_and_exposes_video_container(self):
        from PySide6.QtWidgets import QApplication

        from src.ui.pip_window import PiPWindow

        QApplication.instance() or QApplication([])
        window = PiPWindow()
        closed = MagicMock()
        window.closed.connect(closed)
        self.assertIsNotNone(window.video_container)
        window.show()
        window.close()
        closed.assert_called_once()

if __name__ == '__main__':
    unittest.main()

