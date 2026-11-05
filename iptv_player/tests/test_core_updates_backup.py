"""Regression tests for the local, network-independent application core."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.backup import create_backup, read_backup
from src.core.channel import Channel
from src.core.database import DatabaseManager
from src.core.device_sync import export_device_state, import_device_state, media_key
from src.core.playlist import Playlist
from src.core.secrets import SecretStore
from src.core.update_manager import (
    ReleaseArtifact,
    is_newer_version,
    parse_manifest,
    verify_artifact,
)


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

            self.assertEqual(result, {"favorites": 1, "progress": 1, "continue": 0})
            self.assertTrue(database.get_channels(playlist_id)[0].is_favorite)
            self.assertEqual(database.get_playback_progress(playlist_id, saved)["position_ms"], 30_000)
