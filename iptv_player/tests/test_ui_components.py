"""Headless Qt tests for the standalone UI components.

Covers the widgets that can be exercised without VLC or a database:
the content tab bar, the EPG guide, toasts and the home-screen cards, plus the
session save/restore logic that the main window delegates to.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from src.core.epg import EPGProgram
from src.ui.epg_widget import EPGWidget
from src.ui.home_view import CHANNEL, POSTER, MediaCard, _format_remaining
from src.ui.pill_tabs import PillTabBar
from src.ui.session_state import SessionStateMixin
from src.ui.theme import Palette
from src.ui.toast import Toast


class TestPillTabBar:
    def test_first_tab_is_selected(self, qtbot):
        bar = PillTabBar(["Direto", "Filmes", "Séries"])
        qtbot.addWidget(bar)

        assert len(bar._buttons) == 3
        assert bar._buttons[0].isChecked()
        assert not bar._buttons[1].isChecked()

    def test_set_current_index_is_bounded(self, qtbot):
        bar = PillTabBar(["Direto", "Filmes"])
        qtbot.addWidget(bar)

        bar.set_current_index(1)
        assert bar._buttons[1].isChecked()
        assert not bar._buttons[0].isChecked()

        bar.set_current_index(7)
        bar.set_current_index(-1)
        assert bar._buttons[1].isChecked()

    def test_clicking_a_tab_emits_its_index(self, qtbot):
        bar = PillTabBar(["Direto", "Filmes", "Séries"])
        qtbot.addWidget(bar)

        with qtbot.waitSignal(bar.tab_changed, timeout=1000) as blocker:
            bar._buttons[2].click()

        assert blocker.args == [2]


class TestToast:
    def _toast(self, qtbot, width=800, height=600):
        parent = QWidget()
        parent.resize(width, height)
        parent.show()
        qtbot.addWidget(parent)
        toast = Toast(parent)
        qtbot.addWidget(toast)
        return parent, toast

    def test_show_message_sets_text_and_starts_fade(self, qtbot):
        _, toast = self._toast(qtbot)

        toast.show_message("EPG atualizado", duration_ms=2600)

        assert toast._label.text() == "EPG atualizado"
        assert not toast.isHidden()
        assert toast._hide_timer.interval() == 2600
        assert toast._fade_in.state() == QAbstractAnimation.State.Running

    def test_short_durations_are_clamped(self, qtbot):
        _, toast = self._toast(qtbot)

        toast.show_message("x", duration_ms=10)

        assert toast._hide_timer.interval() == 500

    def test_toast_is_anchored_bottom_right(self, qtbot):
        parent, toast = self._toast(qtbot)

        toast.show_message("Gravacao iniciada")

        assert toast.x() == parent.width() - toast.width() - 18
        assert toast.y() == parent.height() - toast.height() - 18

        parent.resize(400, 300)
        toast.parent_resized()
        assert toast.x() == parent.width() - toast.width() - 18
        assert toast.y() == parent.height() - toast.height() - 18

    def test_new_message_restarts_the_timer(self, qtbot):
        _, toast = self._toast(qtbot)

        toast.show_message("primeiro", duration_ms=1500)
        toast.show_message("segundo", duration_ms=3000)

        assert toast._label.text() == "segundo"
        assert toast._hide_timer.interval() == 3000
        assert toast._hide_timer.isActive()


class TestEPGWidget:
    @staticmethod
    def _programs():
        now = datetime.now(timezone.utc).replace(microsecond=0)
        past = EPGProgram("c1", "Antigo", now - timedelta(hours=3), now - timedelta(hours=2))
        live = EPGProgram(
            "c1",
            "Direto",
            now - timedelta(minutes=10),
            now + timedelta(minutes=50),
            category="Notícias",
        )
        future = EPGProgram("c1", "Futuro", now + timedelta(hours=1), now + timedelta(hours=2))
        return [future, live, past]

    def test_set_epg_data_fills_channel_selector(self, qtbot):
        widget = EPGWidget()
        qtbot.addWidget(widget)

        widget.set_epg_data({"c1": self._programs()}, {"c1": "Canal 1"})

        assert widget._channel_combo.count() == 2
        assert widget._channel_combo.itemText(0) == "Selecionar canal..."
        assert widget._channel_combo.itemData(1) == "c1"
        assert widget._channel_combo.itemText(1) == "Canal 1"

    def test_selecting_a_channel_sorts_and_highlights(self, qtbot):
        widget = EPGWidget()
        qtbot.addWidget(widget)
        widget.set_epg_data({"c1": self._programs()}, {"c1": "Canal 1"})

        widget.select_channel("c1")

        table = widget._epg_table
        assert table.rowCount() == 3
        assert table.item(0, 1).text() == "Antigo"
        assert table.item(1, 1).text() == "Direto [Notícias]"
        assert table.item(2, 1).text() == "Futuro"

        live_title = table.item(1, 1)
        assert live_title.background().color().name() == QColor(Palette.ACCENT).name()
        assert live_title.font().bold()
        assert " - " in table.item(1, 0).text()

    def test_past_programmes_are_dimmed(self, qtbot):
        widget = EPGWidget()
        qtbot.addWidget(widget)
        widget.set_epg_data({"c1": self._programs()})
        widget.select_channel("c1")

        past_title = widget._epg_table.item(0, 1)
        assert past_title.foreground().color().name() == QColor(Palette.TEXT_MUTED).name()

    def test_placeholder_clears_the_table(self, qtbot):
        widget = EPGWidget()
        qtbot.addWidget(widget)
        widget.set_epg_data({"c1": self._programs()})
        widget.select_channel("c1")
        assert widget._epg_table.rowCount() == 3

        widget.select_channel("")

        assert widget._epg_table.rowCount() == 0

    def test_unknown_channel_is_ignored(self, qtbot):
        widget = EPGWidget()
        qtbot.addWidget(widget)
        widget.set_epg_data({"c1": self._programs()})

        widget.select_channel("desconhecido")

        assert widget._channel_combo.currentData() == ""

    def test_add_channel_programs_is_idempotent(self, qtbot):
        widget = EPGWidget()
        qtbot.addWidget(widget)

        widget.add_channel_programs("c2", self._programs(), "Canal 2")
        widget.add_channel_programs("c2", [], "Canal 2")

        assert widget._channel_combo.count() == 1
        assert widget._channel_combo.currentData() == "c2"
        assert widget.programs_for("c2") == []

    def test_programs_for_returns_a_copy_and_clear_resets(self, qtbot):
        widget = EPGWidget()
        qtbot.addWidget(widget)
        programs = self._programs()
        widget.add_channel_programs("c1", programs, "Canal 1")

        snapshot = widget.programs_for("c1")
        snapshot.clear()
        assert len(widget.programs_for("c1")) == 3

        widget.clear()
        assert widget.programs_for("c1") == []
        assert widget._channel_combo.count() == 0
        assert widget._epg_table.rowCount() == 0

    def test_set_epg_data_keeps_the_selected_channel(self, qtbot):
        widget = EPGWidget()
        qtbot.addWidget(widget)
        widget.set_epg_data({"c1": self._programs(), "c2": []}, {"c1": "Canal 1", "c2": "Canal 2"})
        widget.select_channel("c2")

        widget.set_epg_data({"c1": self._programs(), "c2": []}, {"c1": "Canal 1", "c2": "Canal 2"})

        assert widget._channel_combo.currentData() == "c2"

    def test_refresh_display_keeps_the_rows(self, qtbot):
        widget = EPGWidget()
        qtbot.addWidget(widget)
        widget.set_epg_data({"c1": self._programs()})
        widget.select_channel("c1")

        widget._refresh_display()

        assert widget._epg_table.rowCount() == 3


class TestHomeCards:
    @pytest.mark.parametrize(
        ("milliseconds", "expected"),
        [
            (0, "quase no fim"),
            (-5000, "quase no fim"),
            (59_000, "quase no fim"),
            (60_000, "faltam 1 min"),
            (3_600_000, "faltam 1 h 00 min"),
            (5_400_000, "faltam 1 h 30 min"),
        ],
    )
    def test_format_remaining(self, milliseconds, expected):
        assert _format_remaining(milliseconds) == expected

    def test_card_metadata_and_size(self, qtbot):
        card = MediaCard("Filme", "Sinopse", size=POSTER)
        qtbot.addWidget(card)

        assert card.toolTip() == "Filme\nSinopse"
        assert card.width() == POSTER.width()
        assert card.height() == POSTER.height() + 42

        channel_card = MediaCard("Canal", size=CHANNEL)
        qtbot.addWidget(channel_card)
        assert channel_card.height() == CHANNEL.height()
        assert channel_card.toolTip() == "Canal"

    def test_click_and_keyboard_activate(self, qtbot):
        card = MediaCard("Filme")
        qtbot.addWidget(card)
        card.show()

        with qtbot.waitSignal(card.activated, timeout=1000):
            qtbot.mouseClick(card, Qt.MouseButton.LeftButton)

        with qtbot.waitSignal(card.activated, timeout=1000):
            qtbot.keyClick(card, Qt.Key.Key_Return)

        with qtbot.waitSignal(card.activated, timeout=1000):
            qtbot.keyClick(card, Qt.Key.Key_Space)

    def test_removable_card_emits_remove_request(self, qtbot):
        card = MediaCard("Filme", removable=True)
        qtbot.addWidget(card)

        with qtbot.waitSignal(card.remove_requested, timeout=1000):
            qtbot.keyClick(card, Qt.Key.Key_Delete)

    def test_non_removable_card_ignores_delete(self, qtbot):
        card = MediaCard("Filme")
        qtbot.addWidget(card)

        with qtbot.assertNotEmitted(card.remove_requested):
            qtbot.keyClick(card, Qt.Key.Key_Delete)

    def test_painting_does_not_crash(self, qtbot):
        card = MediaCard("Filme", "Sinopse", progress=0.5, badge="HD", removable=True)
        qtbot.addWidget(card)
        card.show()

        assert not card.grab().isNull()


class _FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.written = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set_many(self, values):
        self.written.append(dict(values))
        self.values.update(values)


class _BrokenSettings:
    def get(self, key, default=None):
        raise RuntimeError("definições indisponíveis")

    def set_many(self, values):
        raise RuntimeError("disco cheio")


class _FakePlaylistWidget:
    def __init__(self):
        self.selected = None

    def select_playlist(self, playlist_id):
        self.selected = playlist_id


class _FakeLiveList:
    def __init__(self, channel=None, restore_ok=True):
        self.channel = channel
        self.restore_ok = restore_ok
        self.group_filter = ("all", "")
        self.restored = None

    def set_group_filter(self, value):
        self.group_filter = value

    def get_group_filter(self):
        return self.group_filter

    def restore_channel_by_url_or_id(self, url, channel_id):
        self.restored = (url, channel_id)
        return self.restore_ok

    def get_current_channel(self):
        return self.channel


class _FakeTabs:
    def __init__(self):
        self.index = None

    def set_current_index(self, index):
        self.index = index


class _FakeStack:
    def __init__(self, index=0):
        self.index = index

    def currentIndex(self):
        return self.index


class _FakePlayer:
    def __init__(self, volume=70):
        self.volume = volume

    def get_volume(self):
        return self.volume


class _FakeLogger:
    def __init__(self):
        self.messages = []

    def warning(self, message):
        self.messages.append(message)


class _Host(SessionStateMixin):
    """Minimal stand-in for MainWindow's session-state collaborators."""

    def __init__(self, settings=None, channel=None):
        self._settings = settings or _FakeSettings()
        self._playlist_widget = _FakePlaylistWidget()
        self._live_list = _FakeLiveList(channel)
        self._content_tabs = _FakeTabs()
        self._content_stack = _FakeStack()
        self._media_player = _FakePlayer()
        self._logger = _FakeLogger()
        self._current_playlist_id = None
        self.after_load = None
        self.content_tab = None
        self.played = None

    def _on_playlist_selected(self, playlist_id, after_load=None):
        self.after_load = after_load

    def _on_content_tab_changed(self, index):
        self.content_tab = index

    def _on_channel_selected(self, channel):
        self.played = channel


class TestSessionState:
    def test_save_persists_the_current_selection(self):
        channel = SimpleNamespace(database_id=5)
        host = _Host(channel=channel)
        host._media_player = _FakePlayer(volume=42)
        host._current_playlist_id = 7
        host._content_stack = _FakeStack(index=2)
        host._live_list.group_filter = ("Notícias", "")

        host._save_session_state()

        assert host._settings.written == [
            {
                "volume": 42,
                "last_playlist_id": 7,
                "last_content_tab": 2,
                "last_channel_id": 5,
                "last_group_filter": ["Notícias", ""],
            }
        ]

    def test_save_without_playlist_or_channel_omits_them(self):
        host = _Host()

        host._save_session_state()

        written = host._settings.written[-1]
        assert "last_playlist_id" not in written
        assert "last_channel_id" not in written

    def test_restore_selects_playlist_and_tab(self):
        host = _Host(settings=_FakeSettings({"last_playlist_id": 7, "last_content_tab": 1}))

        host._restore_session_state([{"id": 7}])

        assert host._playlist_widget.selected == 7
        assert host.after_load == host._restore_session_group_and_channel
        assert host._content_tabs.index == 1
        assert host.content_tab == 1

    def test_restore_ignores_unknown_playlist_and_invalid_tab(self):
        host = _Host(settings=_FakeSettings({"last_playlist_id": 9, "last_content_tab": 5}))

        host._restore_session_state([{"id": 7}])

        assert host._playlist_widget.selected is None
        assert host._content_tabs.index is None
        assert host.content_tab is None

    def test_restore_group_and_channel_autoplays(self):
        channel = SimpleNamespace(database_id=12)
        host = _Host(
            settings=_FakeSettings(
                {
                    "last_group_filter": ["Desporto", "Futebol"],
                    "last_channel_id": 12,
                    "autoplay_last_channel": True,
                }
            ),
            channel=channel,
        )

        host._restore_session_group_and_channel()

        assert host._live_list.group_filter == ("Desporto", "Futebol")
        assert host._live_list.restored == ("", 12)
        assert host.played is channel

    def test_restore_group_and_channel_respects_autoplay_setting(self):
        channel = SimpleNamespace(database_id=12)
        host = _Host(
            settings=_FakeSettings(
                {"last_channel_id": 12, "autoplay_last_channel": False}
            ),
            channel=channel,
        )

        host._restore_session_group_and_channel()

        assert host.played is None

    def test_restore_does_not_autoplay_when_channel_is_missing(self):
        host = _Host(
            settings=_FakeSettings({"last_channel_id": 12}),
        )
        host._live_list.restore_ok = False

        host._restore_session_group_and_channel()

        assert host.played is None

    def test_failures_are_logged_not_raised(self):
        host = _Host(settings=_BrokenSettings())

        host._restore_session_state([{"id": 7}])
        host._restore_session_group_and_channel()
        host._save_session_state()

        assert len(host._logger.messages) == 3
        assert "Failed to restore session state" in host._logger.messages[0]
        assert "Failed to restore group/channel" in host._logger.messages[1]
        assert "Failed to save session state" in host._logger.messages[2]
