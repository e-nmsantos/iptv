"""Shared pytest configuration and fixtures for the IPTV Player test suite."""

import os

# Widget tests must never open real windows: the Qt "offscreen" platform keeps
# construction and painting headless on every OS, and mirrors the CI setup.
# This is read when the QApplication is created, i.e. after this import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from fakes import FakeMediaPlayer  # noqa: E402

from src.core.database import DatabaseManager  # noqa: E402
from src.core.secrets import SecretStore  # noqa: E402
from src.parsers.m3u_parser import M3UParser  # noqa: E402

PLAYLIST_M3U = (
    "#EXTM3U\n"
    '#EXTINF:-1 tvg-id="one" group-title="Notícias",Canal 1\n'
    "https://example.test/live/1.m3u8\n"
    '#EXTINF:-1 group-title="Filmes",Filme A\n'
    "https://example.test/movie/2.mp4\n"
)


@pytest.fixture(scope="session", autouse=True)
def _qt_application(qapp):
    """One QApplication per session: some tests build widgets without qtbot."""
    return qapp


def drain(qtbot, window):
    """Let deferred timers (150/250/1200 ms) and workers finish while alive."""
    qtbot.wait(1300)
    for _ in range(50):
        if not window._task_controller.running():
            return
        qtbot.wait(100)


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    """MainWindow over a temporary database with a fake media player."""
    import src.ui.main_window as main_window
    from config import settings as settings_module

    monkeypatch.setattr(
        settings_module.Settings, "_get_config_dir", staticmethod(lambda: tmp_path)
    )
    settings = settings_module.Settings()
    settings.set_many(
        {
            "first_run_done": True,
            "auto_check_updates": False,
            "epg_auto_update": False,
            "show_home_on_start": False,
        }
    )

    db = DatabaseManager(tmp_path / "app.db", secret_store=SecretStore.for_tests())
    player = FakeMediaPlayer()
    monkeypatch.setattr(main_window, "DatabaseManager", lambda: db)
    monkeypatch.setattr(main_window, "MediaPlayer", lambda **kwargs: player)

    win = main_window.MainWindow()
    qtbot.addWidget(win)
    win.db = db
    win.player = player
    win.settings_path = tmp_path / "settings.json"

    yield win

    # Nothing here may touch the window: Qt may already have destroyed it.
    # Deferred work is drained inside the tests (see drain()).
    win._closing = True
    win._current_playlist_id = None


@pytest.fixture
def import_playlist():
    """Import an M3U playlist into the window's database."""

    def _import(target, content=PLAYLIST_M3U, name="Teste"):
        parsed = M3UParser()._parse_content(content, name)
        playlist_id, channels = target._playlist_controller.import_playlist(parsed)
        target._load_playlists()
        return playlist_id, channels

    return _import


@pytest.fixture
def select_playlist(qtbot):
    """Select a playlist and wait for its live channels to be loaded."""

    def _select(target, playlist_id):
        target._on_playlist_selected(playlist_id)
        qtbot.waitUntil(
            lambda: target._live_list._channel_list.count() > 0, timeout=10_000
        )
        drain(qtbot, target)

    return _select
