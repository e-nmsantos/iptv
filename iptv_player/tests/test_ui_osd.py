"""Headless tests for the floating OSD (banner, zap badge and action card)."""

from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QWidget

from src.core.epg import EPGProgram
from src.ui.video_osd import VideoOsd, _clock_duration


@pytest.fixture
def osd(qtbot):
    window = QWidget()
    window.resize(1280, 720)
    window.show()
    video = QWidget(window)
    video.setGeometry(0, 0, 1280, 660)
    video.show()
    qtbot.addWidget(window)
    qtbot.addWidget(video)
    return VideoOsd(video, window)


class TestClockDuration:
    @pytest.mark.parametrize(
        ("milliseconds", "expected"),
        [
            (-5000, "0:00"),
            (0, "0:00"),
            (61_000, "1:01"),
            (3_600_000, "1:00:00"),
            (3_665_000, "1:01:05"),
        ],
    )
    def test_formats_elapsed_time(self, milliseconds, expected):
        assert _clock_duration(milliseconds) == expected


class TestChannelBanner:
    def test_ignored_when_video_is_hidden(self, osd):
        osd._video.hide()

        osd.show_channel_banner("Canal 1")

        assert osd._banner.isHidden()

    def test_shows_live_badge_and_autohides(self, osd):
        osd.show_channel_banner("Canal 1", number=5, behind_live_ms=0)

        banner = osd._banner
        assert not banner.isHidden()
        assert banner._name.text() == "Canal 1"
        assert banner._number.text() == "5"
        assert "DIRETO" in banner._badge.text()
        assert banner._now.text() == "Sem informação de programação"
        assert banner._progress.isHidden()
        assert banner.width() == 1280 - 36
        assert osd._banner_timer.isActive()

        osd.hide_channel_banner()
        assert banner.isHidden()
        assert not osd._banner_timer.isActive()

    def test_shows_delayed_badge_and_programme_details(self, osd):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        current = EPGProgram(
            "c1",
            "Telejornal",
            now - timedelta(minutes=10),
            now + timedelta(minutes=20),
            description="Notícias do dia",
        )
        upcoming = EPGProgram("c1", "Novela", now + timedelta(minutes=20), now + timedelta(hours=1))

        osd.show_channel_banner(
            "Canal 1",
            current=current,
            upcoming=upcoming,
            behind_live_ms=65_000,
        )

        banner = osd._banner
        assert "EM DIFERIDO" in banner._badge.text()
        assert "1:05" in banner._badge.text()
        assert "Telejornal" in banner._now.text()
        assert "–" in banner._now.text()
        assert not banner._progress.isHidden()
        assert banner._description.text() == "Notícias do dia"
        assert not banner._description.isHidden()
        assert "A seguir" in banner._next.text()
        assert "Novela" in banner._next.text()

    def test_hides_upcoming_when_absent(self, osd):
        osd.show_channel_banner("Canal 1")

        assert osd._banner._next.isHidden()


class TestNumberBadge:
    def test_shows_preview_channel(self, osd):
        osd.show_number("12", "Canal Doze")

        badge = osd._number
        assert not badge.isHidden()
        assert badge._digits.text() == "12"
        assert badge._preview.text() == "Canal Doze"
        assert osd._number_timer.isActive()

    def test_reports_missing_channel(self, osd):
        osd.show_number("99", None)

        assert osd._number._preview.text() == "Canal inexistente"

    def test_ignored_when_video_is_hidden(self, osd):
        osd._video.hide()

        osd.show_number("12", "Canal Doze")

        assert osd._number.isHidden()

    def test_hide_all_clears_every_panel(self, osd):
        osd.show_channel_banner("Canal 1")
        osd.show_number("12", "Canal Doze")
        osd.show_card("A seguir", "Episódio 2", "", [])

        osd.hide_all()

        assert osd._banner.isHidden()
        assert osd._number.isHidden()
        assert osd._card.isHidden()


class TestActionCard:
    def test_card_content_and_buttons(self, osd):
        clicks = []
        osd.show_card("A seguir", "Episódio 2", "Sinopse", [("Reproduzir", lambda: clicks.append(1))])

        card = osd._card
        assert not card.isHidden()
        assert card._eyebrow.text() == "A seguir"
        assert card._title.text() == "Episódio 2"
        assert card._subtitle.text() == "Sinopse"
        assert card._buttons.count() == 2  # button + stretch
        card._buttons.itemAt(0).widget().click()
        assert clicks == [1]

    def test_countdown_ticks_and_finishes(self, osd):
        finished = []
        osd.show_card(
            "A seguir",
            "Episódio 2",
            "",
            [],
            countdown_seconds=2,
            countdown_template="Começa em {s} s",
            on_countdown_done=lambda: finished.append(True),
        )

        assert osd._card._eyebrow.text() == "Começa em 2 s"

        osd._tick_countdown()
        assert osd._card._eyebrow.text() == "Começa em 1 s"
        assert finished == []

        osd._tick_countdown()
        assert finished == [True]
        assert osd._card.isHidden()

    def test_hide_card_stops_the_countdown(self, osd):
        """Hiding the card cancels the pending auto-action."""
        finished = []
        osd.show_card("x", "y", "", [], countdown_seconds=3, on_countdown_done=lambda: finished.append(True))
        assert osd._countdown_timer.isActive()

        osd.hide_card()

        assert not osd._countdown_timer.isActive()
        assert osd._countdown_done is None
        osd._tick_countdown()
        assert finished == []


class TestRepositioning:
    def test_reposition_hides_panels_when_video_is_hidden(self, osd):
        osd.show_channel_banner("Canal 1")
        osd.show_number("12", "Canal Doze")

        osd._video.hide()
        osd._reposition()

        assert osd._banner.isHidden()
        assert osd._number.isHidden()

    def test_reposition_resizes_banner_to_the_video(self, osd):
        osd.show_channel_banner("Canal 1")

        osd._video.resize(800, 450)
        osd._reposition()

        assert osd._banner.width() == 800 - 36

    def test_window_moves_trigger_a_reposition(self, osd):
        event = QEvent(QEvent.Type.Resize)

        assert osd.eventFilter(osd._video, event) is False

    def test_other_events_are_passed_through(self, osd):
        event = QEvent(QEvent.Type.KeyPress)

        assert osd.eventFilter(osd._video, event) is False
