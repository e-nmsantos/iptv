"""Integration tests for MainWindow: real widgets over a temporary database.

The VLC player and the settings/database locations are replaced (see
``conftest.py``) so the whole window can be built and driven headlessly,
exercising the real mixins, controllers and repositories.
"""

import json

import pytest

from src.core.channel import Channel


class TestShell:
    def test_window_is_fully_built(self, window):
        assert window.windowTitle() == "IPTV Player"
        assert window.minimumWidth() == 980
        assert window._content_stack.count() == 3
        assert [button.text() for button in window._content_tabs._buttons] == [
            "Em direto",
            "Filmes",
            "Séries",
        ]
        assert window._bottom_tabs.count() == 4
        assert window._right_stack.currentWidget() is window._player_page
        assert window.statusBar().currentMessage().startswith("Pronto")

    def test_menu_actions_have_shortcuts(self, window):
        assert window._action_import_m3u.shortcut().toString() == "Ctrl+N"
        assert window._action_refresh_epg.shortcut().toString() == "F5"
        assert window._action_import_stalker.shortcut().toString() == "Ctrl+Shift+S"


class TestPlaylistFlow:
    def test_import_lists_the_playlist(self, window, import_playlist):
        import_playlist(window)

        assert window._playlist_widget._list_widget.count() == 1
        assert "Teste" in window._playlist_widget._list_widget.item(0).text()

    def test_selecting_a_playlist_loads_live_channels(
        self, window, import_playlist, select_playlist
    ):
        playlist_id, _ = import_playlist(window)

        select_playlist(window, playlist_id)

        assert window._current_playlist_id == playlist_id
        assert window._live_list._channel_list.count() == 1
        assert "Teste" in window.statusBar().currentMessage()

    def test_second_selection_uses_the_memory_cache(
        self, window, import_playlist, select_playlist
    ):
        playlist_id, _ = import_playlist(window)
        select_playlist(window, playlist_id)

        window._current_playlist_id = None
        window._on_playlist_selected(playlist_id)

        assert window._current_playlist_id == playlist_id
        assert window._live_list._channel_list.count() == 1

    def test_switching_content_tab_updates_the_stack(self, window):
        window._content_tabs._buttons[1].click()

        assert window._content_stack.currentIndex() == 1
        assert window._content_tabs._buttons[1].isChecked()

        window._content_tabs._buttons[2].click()
        assert window._content_stack.currentIndex() == 2

    def test_refresh_catalog_without_playlist_warns(self, window):
        window._refresh_current_catalog()

        assert "Seleciona primeiro uma playlist" in window.statusBar().currentMessage()


class TestPlayback:
    def test_selecting_a_channel_starts_playback(
        self, qtbot, window, import_playlist, select_playlist
    ):
        playlist_id, _ = import_playlist(window)
        select_playlist(window, playlist_id)
        channel_list = window._live_list._channel_list
        channel_list.setCurrentRow(0)
        channel = window._live_list.get_current_channel()
        assert channel is not None

        with qtbot.waitSignal(window._live_list.channel_selected, timeout=1000):
            window._live_list._on_channel_activated(channel_list.item(0))

        assert window.player.last_play is not None
        assert window.player.last_play["url"] == "https://example.test/live/1.m3u8"
        assert window._current_playback_channel is not None

        # The banner retries twice (1.5 s apart) when a channel has no EPG yet.
        qtbot.wait(3300)

    def test_playback_error_shows_a_toast(self, window):
        window._current_playback_channel = None

        window.player.error_occurred.emit("Falha de rede")

        assert "Falha de rede" in window._toast._label.text()

    def test_volume_controls_update_the_player(self, window):
        assert window.player.volume == 80

        window._increase_volume()
        assert window.player.volume == 85
        assert "Volume: 85%" in window.statusBar().currentMessage()

        window._decrease_volume()
        assert window.player.volume == 80

        window._toggle_mute()
        assert window.player.volume == 0
        assert "Mudo" in window.statusBar().currentMessage()

    def test_favorite_toggle_is_persisted(
        self, window, import_playlist, select_playlist
    ):
        playlist_id, _ = import_playlist(window)
        select_playlist(window, playlist_id)
        channel = window.db.get_channels(playlist_id, stream_type="live")[0]

        window._on_favorite_toggled(channel, True)

        favorites = window.db.get_favorites(playlist_id)
        assert [fav.name for fav in favorites] == ["Canal 1"]

        window._on_favorite_toggled(channel, False)
        assert window.db.get_favorites(playlist_id) == []

    def test_progress_fraction_reflects_saved_progress(self, window, import_playlist):
        playlist_id, _ = import_playlist(window)
        vod = window.db.get_channels(playlist_id, stream_type="vod")[0]
        window._current_playlist_id = playlist_id

        window._playback_controller.save_progress(playlist_id, vod, 900_000, 3_600_000)

        fraction = window._progress_fraction_for(vod)
        assert fraction == pytest.approx(0.25, abs=0.01)

    def test_unknown_channel_has_no_progress(self, window):
        window._current_playlist_id = None

        assert window._progress_fraction_for(Channel(name="x", url="y")) is None


class TestSessionPersistence:
    def test_closing_the_window_saves_the_session(self, window):
        window._current_playlist_id = 4
        window._content_stack.setCurrentIndex(1)

        window.close()

        saved = json.loads(window.settings_path.read_text(encoding="utf-8"))
        assert saved["volume"] == 80
        assert saved["last_playlist_id"] == 4
        assert saved["last_content_tab"] == 1

    def test_close_is_deferred_while_workers_run(self, window, monkeypatch):
        class _BusyTasks:
            def running(self):
                return ["worker"]

            def cancel_all(self):
                self.cancelled = True

        tasks = _BusyTasks()
        monkeypatch.setattr(window, "_task_controller", tasks)

        window.close()

        assert tasks.cancelled
        assert window._closing is True
        assert not window.isEnabled()
