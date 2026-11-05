"""Import flows for M3U, Xtream and Stalker (dialogs and network are stubbed)."""

from types import SimpleNamespace

import pytest
from conftest import drain

from src.core.channel import Channel
from src.core.playlist import Playlist
from src.ui import import_flow_mixin


class _MessageBox:
    """Records the callbacks instead of opening modal dialogs."""

    calls = []

    class Icon:
        Critical = "critical"

    class ButtonRole:
        AcceptRole = 1
        RejectRole = 2

    @classmethod
    def reset(cls):
        cls.calls = []

    @classmethod
    def _record(cls, kind, args):
        cls.calls.append((kind, args[1] if len(args) > 1 else "", args[2] if len(args) > 2 else ""))

    @classmethod
    def information(cls, *args, **kwargs):
        cls._record("information", args)

    @classmethod
    def warning(cls, *args, **kwargs):
        cls._record("warning", args)

    @classmethod
    def critical(cls, *args, **kwargs):
        cls._record("critical", args)

    def __init__(self, *args, **kwargs):
        self.buttons = []
        self._clicked = None

    def setIcon(self, *args, **kwargs):
        pass

    def setWindowTitle(self, *args, **kwargs):
        pass

    def setText(self, *args, **kwargs):
        pass

    def setInformativeText(self, *args, **kwargs):
        pass

    def addButton(self, label, role=None):
        self.buttons.append(label)
        return label

    def setDefaultButton(self, button):
        pass

    def exec(self):
        return 0

    def clickedButton(self):
        return self._clicked


def _fake_dialog(monkeypatch, name, accepted=True, **fields):
    class _Dialog:
        DialogCode = SimpleNamespace(Accepted=1)

        def __init__(self, parent=None, values=None, **kwargs):
            self.values = values
            for key, value in fields.items():
                setattr(self, key, value)

        def exec(self):
            return self.DialogCode.Accepted if accepted else 0

    monkeypatch.setattr(import_flow_mixin, name, _Dialog)


@pytest.fixture
def dialogs(monkeypatch):
    _MessageBox.reset()
    monkeypatch.setattr(import_flow_mixin, "QMessageBox", _MessageBox)
    return _MessageBox


class TestM3UImport:
    def test_cancelled_dialog_does_nothing(self, window, dialogs, monkeypatch):
        _fake_dialog(monkeypatch, "PlaylistDialog", accepted=False)

        window._import_m3u()

        assert window._playlist_widget._list_widget.count() == 0
        assert dialogs.calls == []

    def test_missing_source_warns(self, window, dialogs, monkeypatch):
        _fake_dialog(
            monkeypatch,
            "PlaylistDialog",
            playlist_path="",
            playlist_url="",
            playlist_name="Teste",
            epg_source="",
        )

        window._import_m3u()

        assert dialogs.calls[0][0] == "warning"
        assert "ficheiro ou URL" in dialogs.calls[0][2]

    def test_missing_name_warns(self, window, dialogs, monkeypatch):
        _fake_dialog(
            monkeypatch,
            "PlaylistDialog",
            playlist_path="http://example.test/list.m3u",
            playlist_url="http://example.test/list.m3u",
            playlist_name="",
            epg_source="",
        )

        window._import_m3u()

        assert dialogs.calls[0][0] == "warning"
        assert "nome" in dialogs.calls[0][2]

    def test_import_from_file_persists_the_playlist(self, qtbot, window, dialogs, monkeypatch, tmp_path):
        playlist_file = tmp_path / "lista.m3u"
        playlist_file.write_text(
            "#EXTM3U\n#EXTINF:-1 group-title=\"Notícias\",Canal Um\n"
            "https://example.test/live/1.ts\n",
            encoding="utf-8",
        )
        _fake_dialog(
            monkeypatch,
            "PlaylistDialog",
            playlist_path=str(playlist_file),
            playlist_url="",
            playlist_name="Minha Lista",
            epg_source="",
        )

        window._import_m3u()
        qtbot.waitUntil(
            lambda: window._playlist_widget._list_widget.count() == 1, timeout=10_000
        )
        drain(qtbot, window)

        assert "Playlist importada: Minha Lista" in window.statusBar().currentMessage()
        assert dialogs.calls[0][0] == "information"
        assert window._current_playlist_id is not None

    def test_running_import_is_not_duplicated(self, window, monkeypatch):
        class _Running:
            def isRunning(self):
                return True

        monkeypatch.setattr(window, "_worker", _Running(), raising=False)

        window._run_import(lambda: None, "A importar...")

        assert "Já existe uma importação em curso" in window.statusBar().currentMessage()

    def test_import_result_without_data_reports_cancellation(self, window, dialogs):
        window._on_import_finished(None)

        assert "Importação cancelada" in window.statusBar().currentMessage()


class TestXtreamImport:
    def test_dialog_fields_are_imported_and_credentials_encrypted(
        self, qtbot, window, dialogs, monkeypatch
    ):
        _fake_dialog(
            monkeypatch,
            "XtreamDialog",
            server_url="http://portal.test:8080",
            username="joao",
            password="segredo",
            playlist_name="Xtream Teste",
        )

        class _FakeXtream:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def authenticate(self):
                return True

            def get_full_playlist(self, **kwargs):
                return Playlist(
                    name="",
                    source_type="xtream",
                    server_url="http://portal.test:8080",
                    username="joao",
                    password="segredo",
                    channels=[
                        Channel(name="Canal", url="http://portal.test/live/1.ts", stream_type="live")
                    ],
                )

        monkeypatch.setattr(import_flow_mixin, "XtreamParser", _FakeXtream)

        window._import_xtream()
        qtbot.waitUntil(
            lambda: window._playlist_widget._list_widget.count() == 1, timeout=10_000
        )
        drain(qtbot, window)

        playlist_id = window._playlist_widget._list_widget.item(0).data(256)
        details = window.db.get_playlist(playlist_id or window._current_playlist_id)
        assert details["name"] == "Xtream Teste"
        assert details["source_type"] == "xtream"
        assert details["password"] == "segredo"  # decrypted for the UI
        with window.db._connection() as conn:
            stored = conn.execute(
                "SELECT password FROM playlists WHERE id = ?", (details["id"],)
            ).fetchone()[0]
        assert stored.startswith("enc:v1:")
        assert "segredo" not in stored

    def test_incomplete_fields_warn(self, window, dialogs, monkeypatch):
        _fake_dialog(
            monkeypatch,
            "XtreamDialog",
            server_url="",
            username="joao",
            password="segredo",
            playlist_name="X",
        )

        window._import_xtream()

        assert dialogs.calls[0][0] == "warning"
        assert "todos os campos" in dialogs.calls[0][2]


class TestStalkerImport:
    def test_dialog_fields_are_imported(self, qtbot, window, dialogs, monkeypatch):
        _fake_dialog(
            monkeypatch,
            "StalkerDialog",
            portal_url="http://portal.test/c/",
            mac_address="00:1A:79:AA:BB:CC",
            playlist_name="Portal Teste",
        )

        class _FakeStalker:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def authenticate(self):
                return True

            def get_full_playlist(self, **kwargs):
                return Playlist(
                    name="",
                    source_type="stalker",
                    server_url="http://portal.test",
                    mac_address="00:1A:79:AA:BB:CC",
                    channels=[
                        Channel(name="Canal", url="http://portal.test/ch/1", stream_type="live")
                    ],
                )

        monkeypatch.setattr(import_flow_mixin, "StalkerParser", _FakeStalker)

        window._import_stalker()
        qtbot.waitUntil(
            lambda: window._playlist_widget._list_widget.count() == 1, timeout=10_000
        )
        drain(qtbot, window)

        details = window.db.get_playlist(window._current_playlist_id)
        assert details["name"] == "Portal Teste"
        assert details["source_type"] == "stalker"
        assert details["mac_address"] == "00:1A:79:AA:BB:CC"


class TestImportErrors:
    def test_error_without_pending_import_shows_a_critical_box(self, window, dialogs):
        window._last_import = None

        window._on_import_error("timeout")

        assert dialogs.calls[0][0] == "critical"
        assert "timeout" in dialogs.calls[0][2]
        assert "Erro na importação" in window.statusBar().currentMessage()

    def test_error_keeps_the_form_values_for_retry(self, window, dialogs):
        window._last_import = {"type": "m3u", "values": {"name": "Teste"}}

        window._on_import_error("timeout")

        assert window._last_import == {"type": "m3u", "values": {"name": "Teste"}}
