"""Regression tests for the local, network-independent application core."""

import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtTest import QSignalSpy

from src.controllers.epg_controller import EpgController
from src.controllers.playback_controller import PlaybackController
from src.controllers.playlist_controller import PlaylistController
from src.controllers.task_controller import TaskController
from src.core.channel import Channel
from src.core.diagnostics import diagnose_channel
from src.core.playlist import Playlist
from src.core.provider_sessions import ProviderSessionManager
from src.core.providers import CatalogKind, Provider
from src.core.task_manager import TaskWorker
from src.parsers.stalker_parser import StalkerParser
from src.parsers.xtream_parser import XtreamParser


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

    def test_failure_explanations_separate_account_refusals_from_channel_faults(self):
        from src.core.diagnostics import explain_failure

        for status in ("HTTP 401", "HTTP 403", "HTTP 407", "HTTP 506"):
            reason, account_level = explain_failure({"status": status})
            self.assertIn(status.split()[1], reason)
            self.assertTrue(account_level, status)
        for status, fragment in (
            ("HTTP 503", "eventos"),
            ("HTTP 404", "já não existe"),
            ("ConnectTimeout", "não responde"),
            ("ConnectionError", "não responde"),
            ("ReadTimeout", "não enviou vídeo"),
        ):
            reason, account_level = explain_failure({"status": status})
            self.assertIn(fragment, reason)
            self.assertFalse(account_level, status)
        # A healthy server means the problem is in the stream, not the provider.
        self.assertEqual(explain_failure({"status": "HTTP 200"}), ("", False))
        self.assertEqual(explain_failure({"status": "protocolo suportado pelo VLC"}), ("", False))
        reason, _ = explain_failure({"status": "ConnectionError", "resolve_error": "sem link"})
        self.assertIn("portal não devolveu", reason)
