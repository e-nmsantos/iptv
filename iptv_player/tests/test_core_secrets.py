"""Regression tests for the local, network-independent application core."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config.settings import Settings
from src.core.channel import Channel
from src.core.parental import PinAttemptLimiter
from src.core.providers import CatalogKind
from src.core.secrets import SecretStore
from src.parsers.stalker_parser import StalkerParser


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
        from src.core.providers import XtreamProvider

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
        from src.core.providers import StalkerProvider

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
