"""Update checks and backup/TV-sync tools (dialogs and network stubbed)."""

import time
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from config import APP_VERSION
from src.core.device_sync import export_device_state
from src.ui import tools_mixin, updates_mixin


class _MessageBox:
    """Records message boxes instead of opening them."""

    calls = []
    answer = 1

    class StandardButton:
        Yes = 1
        No = 0

    class Icon:
        Critical = "critical"

    class ButtonRole:
        AcceptRole = 1
        RejectRole = 2

    @classmethod
    def reset(cls):
        cls.calls = []
        cls.answer = 1

    @classmethod
    def _record(cls, kind, args):
        title = args[1] if len(args) > 1 else ""
        text = args[2] if len(args) > 2 else ""
        cls.calls.append((kind, title, text))

    @classmethod
    def information(cls, *args, **kwargs):
        cls._record("information", args)

    @classmethod
    def warning(cls, *args, **kwargs):
        cls._record("warning", args)

    @classmethod
    def critical(cls, *args, **kwargs):
        cls._record("critical", args)

    @classmethod
    def question(cls, *args, **kwargs):
        cls._record("question", args)
        return cls.answer

    def __init__(self, *args, **kwargs):
        pass

    def setIcon(self, *args, **kwargs):
        pass

    def setWindowTitle(self, *args, **kwargs):
        pass

    def setText(self, *args, **kwargs):
        pass

    def setInformativeText(self, *args, **kwargs):
        pass

    def addButton(self, label, role=None):
        return label

    def setDefaultButton(self, button):
        pass

    def exec(self):
        return 0

    def clickedButton(self):
        return None


@pytest.fixture
def boxes(monkeypatch):
    _MessageBox.reset()
    monkeypatch.setattr(updates_mixin, "QMessageBox", _MessageBox)
    monkeypatch.setattr(tools_mixin, "QMessageBox", _MessageBox)
    return _MessageBox


def _manifest(version):
    return SimpleNamespace(version=version)


ARTIFACT = SimpleNamespace(filename="IPTV-Setup.exe", url="http://a", sha256="x")


class TestUpdateChecks:
    def test_without_manifest_url_the_user_is_informed(self, window, boxes):
        window._check_for_updates()

        assert boxes.calls[0][0] == "information"
        assert "foi configurado um repositório" in boxes.calls[0][2]

    def test_newer_release_offers_the_update(self, qtbot, window, boxes, monkeypatch):
        window._settings.set("update_manifest_url", "http://updates.test/manifest.json")
        offered = []
        monkeypatch.setattr(
            updates_mixin, "fetch_manifest", lambda url, timeout: _manifest("9.9.9")
        )
        monkeypatch.setattr(window, "_offer_update", offered.append, raising=False)

        window._check_for_updates()
        qtbot.waitUntil(lambda: bool(offered), timeout=5000)

        assert offered[0].version == "9.9.9"

    def test_current_version_reports_up_to_date(self, qtbot, window, boxes, monkeypatch):
        window._settings.set("update_manifest_url", "http://updates.test/manifest.json")
        monkeypatch.setattr(
            updates_mixin, "fetch_manifest", lambda url, timeout: _manifest(APP_VERSION)
        )

        window._check_for_updates()
        qtbot.waitUntil(lambda: bool(boxes.calls), timeout=5000)

        assert boxes.calls[0][0] == "information"
        assert "mais recente" in boxes.calls[0][2]

    def test_failure_is_reported(self, qtbot, window, boxes, monkeypatch):
        window._settings.set("update_manifest_url", "http://updates.test/manifest.json")

        def boom(url, timeout):
            raise ConnectionError("sem rede")

        monkeypatch.setattr(updates_mixin, "fetch_manifest", boom)

        window._check_for_updates()
        qtbot.waitUntil(lambda: bool(boxes.calls), timeout=5000)

        assert boxes.calls[0][0] == "warning"
        assert "sem rede" in boxes.calls[0][2]

    def test_auto_check_skips_without_url(self, window, monkeypatch):
        called = []
        monkeypatch.setattr(
            updates_mixin, "fetch_manifest", lambda *a, **k: called.append(1)
        )

        window._auto_check_updates()

        assert called == []

    def test_auto_check_runs_at_most_once_a_day(self, window, monkeypatch):
        window._settings.set_many(
            {
                "update_manifest_url": "http://updates.test/manifest.json",
                "last_update_check_ts": int(time.time()),
            }
        )
        called = []
        monkeypatch.setattr(
            updates_mixin, "fetch_manifest", lambda *a, **k: called.append(1)
        )

        window._auto_check_updates()

        assert called == []

    def test_auto_check_records_the_timestamp(self, window, monkeypatch):
        window._settings.set_many(
            {
                "update_manifest_url": "http://updates.test/manifest.json",
                "last_update_check_ts": 0,
            }
        )
        monkeypatch.setattr(
            updates_mixin, "fetch_manifest", lambda url, timeout: _manifest(APP_VERSION)
        )

        window._auto_check_updates()

        assert window._settings.get("last_update_check_ts") > 0


class TestUpdateOffer:
    def test_missing_artifact_for_this_platform(self, window, boxes, monkeypatch):
        monkeypatch.setattr(updates_mixin, "select_artifact", lambda info: None)

        window._offer_update(_manifest("9.9.9"))

        assert boxes.calls[0][0] == "information"
        assert "não existe um" in boxes.calls[0][2]

    def test_accepted_offer_starts_the_download(self, window, boxes, monkeypatch):
        monkeypatch.setattr(updates_mixin, "select_artifact", lambda info: ARTIFACT)
        downloaded = []
        monkeypatch.setattr(
            window, "_download_and_install", downloaded.append, raising=False
        )
        boxes.answer = boxes.StandardButton.Yes

        window._offer_update(_manifest("9.9.9"))

        assert downloaded == [ARTIFACT]

    def test_declined_offer_downloads_nothing(self, window, boxes, monkeypatch):
        monkeypatch.setattr(updates_mixin, "select_artifact", lambda info: ARTIFACT)
        downloaded = []
        monkeypatch.setattr(
            window, "_download_and_install", downloaded.append, raising=False
        )
        boxes.answer = boxes.StandardButton.No

        window._offer_update(_manifest("9.9.9"))

        assert downloaded == []

    def test_download_launches_the_installer(self, qtbot, window, monkeypatch, tmp_path):
        destination = tmp_path / "setup.exe"
        installed = []
        monkeypatch.setattr(
            updates_mixin, "download_artifact", lambda art, dest: destination
        )
        monkeypatch.setattr(window, "_launch_installer", installed.append, raising=False)

        window._download_and_install(ARTIFACT)
        qtbot.waitUntil(lambda: bool(installed), timeout=5000)

        assert installed == [destination]

    def test_launch_on_other_platforms_shows_the_path(self, window, boxes, monkeypatch, tmp_path):
        monkeypatch.setattr(updates_mixin, "sys", SimpleNamespace(platform="linux"))

        window._launch_installer(tmp_path / "setup.run")

        assert boxes.calls[0][0] == "information"
        assert "setup.run" in boxes.calls[0][2]

    def test_launch_failure_warns(self, window, boxes, monkeypatch, tmp_path):
        monkeypatch.setattr(updates_mixin, "sys", SimpleNamespace(platform="win32"))

        def broken_startfile(path):
            raise OSError("sem permissão")

        monkeypatch.setattr(updates_mixin.os, "startfile", broken_startfile, raising=False)

        window._launch_installer(tmp_path / "setup.exe")

        assert boxes.calls[0][0] == "warning"
        assert "sem permissão" in boxes.calls[0][2]


class TestDiagnosticsReport:
    def test_cancelled_save_dialog_writes_nothing(self, window, boxes, monkeypatch):
        monkeypatch.setattr(
            updates_mixin,
            "QFileDialog",
            SimpleNamespace(getSaveFileName=lambda *a, **k: ("", "")),
        )

        window._export_diagnostics_report()

        assert boxes.calls == []

    def test_report_is_written_to_the_chosen_file(self, window, boxes, monkeypatch, tmp_path):
        target = tmp_path / "diagnostico.txt"
        monkeypatch.setattr(
            updates_mixin,
            "QFileDialog",
            SimpleNamespace(getSaveFileName=lambda *a, **k: (str(target), "")),
        )

        window._export_diagnostics_report()

        assert target.exists()
        assert "IPTV" in target.read_text(encoding="utf-8")
        assert boxes.calls[0][0] == "information"

    def test_write_failure_is_reported(self, window, boxes, monkeypatch, tmp_path):
        monkeypatch.setattr(
            updates_mixin,
            "QFileDialog",
            SimpleNamespace(
                getSaveFileName=lambda *a, **k: (str(tmp_path / "ausente" / "y.txt"), "")
            ),
        )

        window._export_diagnostics_report()

        assert boxes.calls[0][0] == "warning"


class TestFirstRun:
    def test_welcome_is_shown_once(self, window, boxes):
        window._settings.set("first_run_done", False)

        window._show_first_run_welcome()
        window._show_first_run_welcome()

        assert len(boxes.calls) == 1
        assert window._settings.get("first_run_done") is True


class TestDeviceSync:
    def test_copy_requires_a_playlist(self, window, boxes):
        window._current_playlist_id = None

        window._copy_device_sync()

        assert boxes.calls[0][0] == "information"
        assert "Seleciona primeiro uma playlist" in boxes.calls[0][2]

    def test_copy_places_a_credential_free_payload_on_the_clipboard(
        self, window, boxes, import_playlist
    ):
        playlist_id, _ = import_playlist(window)
        window._current_playlist_id = playlist_id

        window._copy_device_sync()

        payload = QApplication.clipboard().text()
        assert payload
        assert "example.test" not in payload
        assert boxes.calls[0][0] == "information"

    def test_import_requires_a_playlist(self, window, boxes):
        window._current_playlist_id = None

        window._import_device_sync()

        assert boxes.calls[0][0] == "information"

    def test_import_round_trip_restores_state(
        self, window, boxes, import_playlist, monkeypatch
    ):
        playlist_id, _ = import_playlist(window)
        window._current_playlist_id = playlist_id
        payload = export_device_state(window.db, playlist_id)
        monkeypatch.setattr(
            tools_mixin,
            "QInputDialog",
            SimpleNamespace(getMultiLineText=lambda *a, **k: (payload, True)),
        )

        window._import_device_sync()

        assert boxes.calls[0][0] == "information"
        assert "Importados" in boxes.calls[0][2]

    def test_invalid_payload_warns(self, window, boxes, import_playlist, monkeypatch):
        playlist_id, _ = import_playlist(window)
        window._current_playlist_id = playlist_id
        monkeypatch.setattr(
            tools_mixin,
            "QInputDialog",
            SimpleNamespace(getMultiLineText=lambda *a, **k: ("isto nao e json", True)),
        )

        window._import_device_sync()

        assert boxes.calls[0][0] == "warning"


class TestTvPairing:
    def test_address_without_port_is_rejected(self, window, boxes, monkeypatch):
        answers = iter([("192.168.1.20", True)])
        monkeypatch.setattr(
            tools_mixin,
            "QInputDialog",
            SimpleNamespace(getText=lambda *a, **k: next(answers)),
        )

        assert window._choose_tv_and_pin("Título", []) is None
        assert boxes.calls[0][0] == "warning"

    def test_valid_address_and_pin_return_an_endpoint(self, window, boxes, monkeypatch):
        answers = iter([("192.168.1.20:41234", True), ("123456", True)])
        monkeypatch.setattr(
            tools_mixin,
            "QInputDialog",
            SimpleNamespace(getText=lambda *a, **k: next(answers)),
        )

        endpoint, pin = window._choose_tv_and_pin("Título", [])

        assert endpoint.host == "192.168.1.20"
        assert endpoint.port == 41234
        assert pin == "123456"

    def test_cancelled_pin_returns_none(self, window, boxes, monkeypatch):
        answers = iter([("192.168.1.20:41234", True), ("", False)])
        monkeypatch.setattr(
            tools_mixin,
            "QInputDialog",
            SimpleNamespace(getText=lambda *a, **k: next(answers)),
        )

        assert window._choose_tv_and_pin("Título", []) is None
