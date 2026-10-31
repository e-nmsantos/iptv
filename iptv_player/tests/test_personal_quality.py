"""Regressions for personal playback, artwork and background recording."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QTabWidget

from config.settings import Settings
from src.core.image_loader import ImageLoaderService
from src.player import recording_engine
from src.player.media_player import MediaPlayer
from src.player.pvr_recorder import RecordingSession
from src.ui.dialogs import SettingsDialog


class PersonalQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_players_never_remove_another_players_timeshift(self):
        with patch("src.player.media_player.timeshift_directory", return_value=self.root), patch(
            "src.player.media_player.vlc.Instance", side_effect=lambda *_: MagicMock()
        ):
            first = MediaPlayer()
            first_file = first._timeshift_dir / "buffer.tmp"
            first_file.write_bytes(b"video")
            second = MediaPlayer()
            self.assertNotEqual(first._timeshift_dir, second._timeshift_dir)
            self.assertEqual(first_file.read_bytes(), b"video")
            second.cleanup()
            self.assertTrue(first_file.exists())
            first.cleanup()
            self.assertFalse(first_file.exists())

    def test_timeshift_returns_to_live_when_disk_is_low(self):
        with patch("src.player.media_player.timeshift_directory", return_value=self.root), patch(
            "src.player.media_player.vlc.Instance", return_value=MagicMock()
        ):
            player = MediaPlayer()
            self.addCleanup(player.cleanup)
            player._current_is_live = True
            (player._timeshift_dir / "buffer.tmp").write_bytes(b"video")
            reached = MagicMock()
            player.timeshift_limit_reached.connect(reached)
            with patch("src.player.media_player.shutil.disk_usage", return_value=SimpleNamespace(free=1)):
                player._check_timeshift_storage()
                player._check_timeshift_storage()
            reached.assert_called_once_with()
            player._player.stop.assert_called_once()

    def test_recording_never_reports_success_for_empty_output(self):
        done = MagicMock()
        session = RecordingSession("https://example.test/live.m3u8", self.root / "empty.ts", on_complete=done)
        with patch("src.player.pvr_recorder.record_stream"):
            session._record_worker()
        self.assertFalse(done.call_args.args[0])
        self.assertFalse(session.output_file.exists())

    def test_failed_recording_preserves_partial_video_and_reports_failure(self):
        done = MagicMock()
        session = RecordingSession("https://example.test/live.m3u8", self.root / "partial.ts", on_complete=done)

        def interrupted(target):
            target.output_file.write_bytes(b"received video")
            raise RuntimeError("A ligação falhou.")

        with patch("src.player.pvr_recorder.record_stream", side_effect=interrupted):
            session._record_worker()
        self.assertFalse(done.call_args.args[0])
        self.assertEqual(session.output_file.read_bytes(), b"received video")

    def test_recording_retries_are_bounded_and_release_vlc(self):
        session = RecordingSession("https://example.test/live.m3u8", self.root / "retry.ts")
        session._stop_event = MagicMock()
        session._stop_event.is_set.return_value = False
        session._stop_event.wait.return_value = False
        instance = MagicMock()
        player = instance.media_player_new.return_value
        player.play.return_value = 0
        player.get_state.return_value = recording_engine.vlc.State.Error
        with patch.object(recording_engine.vlc, "Instance", return_value=instance), patch.object(
            recording_engine, "check_disk"
        ):
            with self.assertRaisesRegex(RuntimeError, "3 tentativas"):
                recording_engine.record_stream(session)
        self.assertEqual(player.play.call_count, 4)
        player.release.assert_called_once()
        instance.release.assert_called_once()
        self.assertEqual(instance.media_new.return_value.release.call_count, 4)

    def test_recording_checks_disk_before_contacting_source(self):
        session = RecordingSession("https://example.test/live.m3u8", self.root / "disk.ts")
        with patch.object(recording_engine.shutil, "disk_usage", return_value=SimpleNamespace(free=0)), patch.object(
            recording_engine.vlc, "Instance"
        ) as instance:
            with self.assertRaisesRegex(RuntimeError, "512 MB"):
                recording_engine.record_stream(session)
        instance.assert_not_called()

    def test_media_remuxes_hls_and_quotes_paths_without_losing_headers(self):
        session = RecordingSession(
            "https://example.test/live.m3u8", self.root / "Film d'arte, 1.ts",
            headers={"User-Agent": "Test agent", "Referer": "https://example.test", "Cookie": "id=private"},
        )
        instance = MagicMock()
        recording_engine.make_media(instance, session)
        options = [call.args[0] for call in instance.media_new.return_value.add_option.call_args_list]
        self.assertIn("mux=ts", options[0])
        self.assertIn("access=file{append}", options[0])
        self.assertIn("d\\'arte, 1.ts'", options[0])
        self.assertIn(":http-user-agent=Test agent", options)
        self.assertIn(":http-cookie=id=private", options)

    def test_failed_artwork_has_backoff_instead_of_retrying_every_paint(self):
        with patch.object(Settings, "_get_config_dir", return_value=self.root):
            loader = ImageLoaderService()
        url = "https://example.test/broken.png"
        loader._on_fetched(url, QSize(150, 225), None)
        with patch.object(loader._pool, "start") as start:
            self.assertIsNone(loader.load(url, QSize(150, 225)))
            self.assertIsNone(loader.load(url, QSize(1280, 720)))
        start.assert_not_called()

    def test_shared_artwork_is_cached_for_card_and_hero_sizes(self):
        with patch.object(Settings, "_get_config_dir", return_value=self.root):
            loader = ImageLoaderService()
        url = "https://example.test/poster.png"
        with patch.object(loader._pool, "start") as start:
            loader.load(url, QSize(150, 225))
            loader.load(url, QSize(1280, 720))
            start.assert_called_once()
            image = QImage(400, 600, QImage.Format.Format_RGB32)
            image.fill(0)
            loader._on_fetched(url, QSize(150, 225), image)
            self.assertIsNotNone(loader.load(url, QSize(150, 225)))
            self.assertIsNotNone(loader.load(url, QSize(1280, 720)))
            start.assert_called_once()

    def test_settings_save_audio_preferences_and_cancel_leaves_them_unchanged(self):
        with patch.object(Settings, "_get_config_dir", return_value=self.root):
            settings = Settings()
            dialog = SettingsDialog(settings)
            self.addCleanup(dialog.deleteLater)
            dialog._normalize_audio.setChecked(False)
            dialog._deinterlace.setChecked(True)
            dialog.reject()
            self.assertTrue(settings.get("normalize_audio"))
            self.assertFalse(settings.get("deinterlace"))
            dialog._save_and_accept()
            saved = Settings()
            self.assertFalse(saved.get("normalize_audio"))
            self.assertTrue(saved.get("deinterlace"))
            self.assertEqual(dialog.findChild(QTabWidget).tabText(0), "Reprodução")
            buttons = dialog.findChild(QDialogButtonBox)
            self.assertEqual(buttons.button(QDialogButtonBox.StandardButton.Ok).text(), "Guardar")

    def test_applying_player_settings_keeps_movie_position_and_mute(self):
        old, new = MagicMock(), MagicMock()
        old.media_player_new.return_value.get_time.return_value = 120_000
        old.media_player_new.return_value.get_state.return_value = recording_engine.vlc.State.Playing
        new.media_player_new.return_value.get_length.return_value = 600_000
        with patch("src.player.media_player.timeshift_directory", return_value=self.root), patch(
            "src.player.media_player.vlc.Instance", side_effect=[old, new]
        ):
            player = MediaPlayer()
            self.addCleanup(player.cleanup)
            player.play("https://example.test/movie.mp4", {"User-Agent": "Personal"})
            player.toggle_mute()
            player.reinitialize(buffer_size_ms=2000, normalize_audio=False)
            self.assertTrue(player.is_playing)
            new.media_player_new.return_value.set_time.assert_called_with(120_000)
            new.media_player_new.return_value.audio_set_mute.assert_called_with(True)
            self.assertFalse(player.is_normalize_audio_enabled())

    def test_applying_settings_preserves_a_paused_movie(self):
        old, new = MagicMock(), MagicMock()
        old.media_player_new.return_value.get_time.return_value = 120_000
        old.media_player_new.return_value.get_state.return_value = recording_engine.vlc.State.Paused
        new.media_player_new.return_value.get_length.return_value = 600_000
        new.media_player_new.return_value.get_state.return_value = recording_engine.vlc.State.Playing
        with patch("src.player.media_player.timeshift_directory", return_value=self.root), patch(
            "src.player.media_player.vlc.Instance", side_effect=[old, new]
        ):
            player = MediaPlayer()
            self.addCleanup(player.cleanup)
            player.play("https://example.test/movie.mp4")
            player._is_playing = False
            player.reinitialize(buffer_size_ms=2000)
            player._update_position()
            new.media_player_new.return_value.pause.assert_called_once()
            self.assertFalse(player.is_playing)

    def test_recovered_playback_clears_buffering_status(self):
        with patch("src.player.media_player.timeshift_directory", return_value=self.root), patch(
            "src.player.media_player.vlc.Instance", return_value=MagicMock()
        ):
            player = MediaPlayer()
            self.addCleanup(player.cleanup)
            player._player.get_length.return_value = 10_000
            player._player.get_time.return_value = 1000
            player._player.get_position.return_value = 0.1
            states = []
            player.state_changed.connect(states.append)
            player._player.get_state.return_value = recording_engine.vlc.State.Buffering
            player._update_position()
            player._player.get_state.return_value = recording_engine.vlc.State.Playing
            player._update_position()
            self.assertEqual(states, ["buffering", "playing"])

    def test_instant_recording_uses_valid_sout_and_resets_on_stop(self):
        with patch("src.player.media_player.timeshift_directory", return_value=self.root), patch(
            "src.player.media_player.vlc.Instance", return_value=MagicMock()
        ):
            player = MediaPlayer()
            self.addCleanup(player.cleanup)
            player.play("https://example.test/live.m3u8", is_live=True)
            self.assertTrue(player.start_recording(str(self.root / "TV d'arte, 1.ts")))
            self.assertIn("dst=display", player._recording_sout)
            self.assertIn("access=file{append}", player._recording_sout)
            self.assertNotIn(":sout-keep", player._recording_sout)
            player.stop()
            self.assertFalse(player.is_recording)
