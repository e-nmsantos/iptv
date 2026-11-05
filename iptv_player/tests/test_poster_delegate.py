"""Headless painting tests for the poster-card and channel-row delegates."""

import pytest
from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QPainter, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

from src.ui import poster_delegate
from src.ui.poster_delegate import (
    IMAGE_URL_ROLE,
    ChannelRowDelegate,
    PosterCardDelegate,
    _monogram,
    _monogram_color,
)

# Painting needs a QGuiApplication even when no widget is created.
pytestmark = pytest.mark.usefixtures("qapp")


class _FakeLoader:
    """Image loader stub: returns a pixmap without touching the network."""

    def __init__(self, pixmap):
        self._pixmap = pixmap
        self.requests = []

    def load(self, url, size):
        self.requests.append((url, size))
        return self._pixmap


@pytest.fixture
def model():
    model = QStandardItemModel()
    for title in ("Canal Um", "Canal Dois"):
        item = QStandardItem(title)
        item.setData("https://example.test/logo.png", IMAGE_URL_ROLE)
        model.appendRow(item)
    return model


def _paint(delegate, model, index=0, state=QStyle.StateFlag.State_None, rect=None):
    rect = rect or QRect(0, 0, 200, 180)
    canvas = QPixmap(rect.width(), rect.height())
    canvas.fill(Qt.GlobalColor.black)
    option = QStyleOptionViewItem()
    option.rect = rect
    option.state = state
    painter = QPainter(canvas)
    try:
        delegate.paint(painter, option, model.index(index, 0))
    finally:
        painter.end()
    return canvas


class TestMonogramHelpers:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("canal um", "C"),
            ("  Filme", "F"),
            ("123", "1"),
            ("", "?"),
            ("—", "?"),
        ],
    )
    def test_monogram(self, title, expected):
        assert _monogram(title) == expected

    def test_monogram_color_is_deterministic(self):
        assert _monogram_color("Canal Um") == _monogram_color("Canal Um")
        assert _monogram_color("Canal Um") in poster_delegate._MONOGRAM_COLORS
        assert _monogram_color("").startswith("#")


class TestPosterCardDelegate:
    def test_size_hint_uses_card_size(self):
        delegate = PosterCardDelegate(card_size=QSize(180, 140))

        assert delegate.sizeHint(QStyleOptionViewItem(), QModelIndex()) == QSize(180, 140)

    def test_paints_placeholder_monogram_without_image(self, monkeypatch, model):
        monkeypatch.setattr(poster_delegate, "get_image_loader", lambda: _FakeLoader(None))

        canvas = _paint(PosterCardDelegate(), model)

        assert not canvas.isNull()

    def test_paints_loaded_pixmap(self, monkeypatch, model):
        loader = _FakeLoader(QPixmap(80, 120))
        monkeypatch.setattr(poster_delegate, "get_image_loader", lambda: loader)

        _paint(PosterCardDelegate(), model)

        assert loader.requests
        assert loader.requests[0][0] == "https://example.test/logo.png"

    def test_paints_all_badges_and_states(self, monkeypatch, model):
        monkeypatch.setattr(poster_delegate, "get_image_loader", lambda: _FakeLoader(QPixmap(80, 120)))
        delegate = PosterCardDelegate(
            favorite_fn=lambda index: True,
            live_fn=lambda index: True,
            progress_fn=lambda index: 0.4,
            playing_fn=lambda index: True,
        )

        canvas = _paint(
            delegate,
            model,
            state=QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver,
        )

        assert not canvas.isNull()

    def test_paints_selected_and_live_only(self, monkeypatch, model):
        monkeypatch.setattr(poster_delegate, "get_image_loader", lambda: _FakeLoader(QPixmap(80, 120)))
        delegate = PosterCardDelegate(live_fn=lambda index: True)

        canvas = _paint(delegate, model, state=QStyle.StateFlag.State_MouseOver)

        assert not canvas.isNull()

    def test_paints_without_any_callbacks(self, monkeypatch, model):
        monkeypatch.setattr(poster_delegate, "get_image_loader", lambda: _FakeLoader(QPixmap(80, 120)))

        canvas = _paint(PosterCardDelegate(), model, index=1)

        assert not canvas.isNull()


class TestChannelRowDelegate:
    def test_size_hint_uses_row_height(self):
        delegate = ChannelRowDelegate(row_height=52)

        assert delegate.sizeHint(QStyleOptionViewItem(), QModelIndex()) == QSize(0, 52)

    def test_paints_placeholder_row(self, monkeypatch, model):
        monkeypatch.setattr(poster_delegate, "get_image_loader", lambda: _FakeLoader(None))

        canvas = _paint(ChannelRowDelegate(), model, rect=QRect(0, 0, 400, 60))

        assert not canvas.isNull()

    def test_paints_loaded_thumbnail(self, monkeypatch, model):
        loader = _FakeLoader(QPixmap(44, 44))
        monkeypatch.setattr(poster_delegate, "get_image_loader", lambda: loader)

        _paint(ChannelRowDelegate(), model, rect=QRect(0, 0, 400, 60))

        assert loader.requests

    def test_paints_badges_progress_and_selection(self, monkeypatch, model):
        monkeypatch.setattr(poster_delegate, "get_image_loader", lambda: _FakeLoader(QPixmap(44, 44)))
        delegate = ChannelRowDelegate(
            favorite_fn=lambda index: True,
            live_fn=lambda index: True,
            progress_fn=lambda index: 0.75,
            playing_fn=lambda index: True,
        )

        canvas = _paint(
            delegate,
            model,
            state=QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver,
            rect=QRect(0, 0, 400, 60),
        )

        assert not canvas.isNull()

    def test_paints_live_badge_without_playback(self, monkeypatch, model):
        monkeypatch.setattr(poster_delegate, "get_image_loader", lambda: _FakeLoader(QPixmap(44, 44)))
        delegate = ChannelRowDelegate(live_fn=lambda index: True)

        canvas = _paint(delegate, model, rect=QRect(0, 0, 400, 60))

        assert not canvas.isNull()
