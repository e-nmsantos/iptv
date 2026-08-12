"""Multi-channel EPG timeline ("guide grid").

Only ever renders the channels it's explicitly given (`set_channels`) — it
never bulk-fetches EPG for a whole catalog. Whenever the visible channel set
changes it emits `channels_needed` so the host can lazily ensure EPG data is
cached for exactly those channels, reusing whatever per-channel fetch path
already exists (Xtream/Stalker lazy fetch, or the XMLTV cache).
"""

from datetime import datetime, timedelta
from typing import Callable, Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..core.channel import Channel
from ..core.epg import EPGProgram
from .theme import Palette

HOURS_VISIBLE = 3
NAME_COL_WIDTH = 170
ROW_HEIGHT = 56
HEADER_HEIGHT = 26


class _EPGCanvas(QWidget):
    program_clicked = Signal(object, object)  # Channel, EPGProgram

    def __init__(self, parent=None):
        super().__init__(parent)
        self._channels: list[Channel] = []
        self._programs_by_channel: dict[str, list[EPGProgram]] = {}
        self._window_start: datetime = datetime.now().astimezone()
        self.setMouseTracking(True)

    def set_data(self, channels: list[Channel], programs_by_channel: dict, window_start: datetime):
        self._channels = channels
        self._programs_by_channel = programs_by_channel
        self._window_start = window_start
        self.setMinimumHeight(HEADER_HEIGHT + max(1, len(channels)) * ROW_HEIGHT)
        self.update()

    def _px_per_minute(self) -> float:
        timeline_width = max(1, self.width() - NAME_COL_WIDTH)
        return timeline_width / (HOURS_VISIBLE * 60)

    def _channel_epg_key(self, channel: Channel) -> str:
        return channel.epg_channel_id or channel.tvg_id or channel.xtream_id or channel.name

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        px_per_min = self._px_per_minute()
        window_end = self._window_start + timedelta(hours=HOURS_VISIBLE)

        # Header: hour ticks.
        painter.fillRect(QRectF(0, 0, self.width(), HEADER_HEIGHT), QColor(Palette.BG_ELEVATED))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor(Palette.TEXT_SECONDARY))
        tick = self._window_start.replace(minute=0, second=0, microsecond=0)
        if tick < self._window_start:
            tick += timedelta(hours=1)
        while tick <= window_end:
            x = NAME_COL_WIDTH + (tick - self._window_start).total_seconds() / 60 * px_per_min
            painter.drawLine(int(x), HEADER_HEIGHT, int(x), self.height())
            painter.drawText(int(x) + 3, 17, tick.strftime("%H:%M"))
            tick += timedelta(hours=1)

        # Rows.
        now = datetime.now(self._window_start.tzinfo)
        for row, channel in enumerate(self._channels):
            y = HEADER_HEIGHT + row * ROW_HEIGHT
            row_rect = QRectF(0, y, self.width(), ROW_HEIGHT)
            if row % 2 == 1:
                painter.fillRect(row_rect, QColor(Palette.BG_PANEL))

            name_rect = QRectF(6, y, NAME_COL_WIDTH - 12, ROW_HEIGHT)
            painter.setPen(QColor(Palette.TEXT_PRIMARY))
            metrics = painter.fontMetrics()
            elided = metrics.elidedText(channel.name, Qt.TextElideMode.ElideRight, int(name_rect.width()))
            painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)

            programs = self._programs_by_channel.get(self._channel_epg_key(channel), [])
            for program in programs:
                if program.stop <= self._window_start or program.start >= window_end:
                    continue
                start_x = NAME_COL_WIDTH + max(0, (program.start - self._window_start).total_seconds() / 60) * px_per_min
                end_x = NAME_COL_WIDTH + min(
                    HOURS_VISIBLE * 60, (program.stop - self._window_start).total_seconds() / 60
                ) * px_per_min
                block_rect = QRectF(start_x + 1, y + 4, max(2, end_x - start_x - 2), ROW_HEIGHT - 8)
                is_live = program.start <= now <= program.stop
                is_past = program.stop <= now
                color = Palette.ACCENT if is_live else (Palette.BG_CARD_HOVER if is_past else Palette.BG_CARD)
                painter.fillRect(block_rect, QColor(color))
                painter.setPen(QPen(QColor(Palette.BORDER_STRONG)))
                painter.drawRect(block_rect)
                painter.setPen(QColor(Palette.TEXT_ON_ACCENT if is_live else Palette.TEXT_PRIMARY))
                title_rect = block_rect.adjusted(4, 0, -4, 0)
                elided_title = metrics.elidedText(
                    program.title, Qt.TextElideMode.ElideRight, int(title_rect.width())
                )
                painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_title)

        # "Now" line.
        if self._window_start <= now <= window_end:
            now_x = NAME_COL_WIDTH + (now - self._window_start).total_seconds() / 60 * px_per_min
            pen = QPen(QColor(Palette.LIVE_BADGE))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawLine(int(now_x), HEADER_HEIGHT, int(now_x), self.height())

    def mousePressEvent(self, event):
        pos = event.position()
        if pos.x() < NAME_COL_WIDTH:
            return
        row = int((pos.y() - HEADER_HEIGHT) // ROW_HEIGHT)
        if row < 0 or row >= len(self._channels):
            return
        channel = self._channels[row]
        minutes = (pos.x() - NAME_COL_WIDTH) / self._px_per_minute()
        clicked_time = self._window_start + timedelta(minutes=minutes)
        for program in self._programs_by_channel.get(self._channel_epg_key(channel), []):
            if program.start <= clicked_time <= program.stop:
                self.program_clicked.emit(channel, program)
                return


class EPGGridWidget(QWidget):
    """Multi-channel guide: header pan controls + a scrollable timeline canvas."""

    channels_needed = Signal(list)  # list[Channel]
    replay_requested = Signal(object, object)  # Channel, EPGProgram

    def __init__(self, parent=None):
        super().__init__(parent)
        self._channels: list[Channel] = []
        self._programs_provider: Optional[Callable[[Channel], list[EPGProgram]]] = None
        self._window_start = datetime.now().astimezone() - timedelta(minutes=15)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QHBoxLayout()
        prev_btn = QPushButton("◀")
        prev_btn.setFixedWidth(32)
        prev_btn.clicked.connect(lambda: self._shift_window(-1))
        header.addWidget(prev_btn)

        now_btn = QPushButton("🔴 Agora")
        now_btn.clicked.connect(self._jump_to_now)
        header.addWidget(now_btn)

        next_btn = QPushButton("▶")
        next_btn.setFixedWidth(32)
        next_btn.clicked.connect(lambda: self._shift_window(1))
        header.addWidget(next_btn)

        self._range_label = QLabel("")
        self._range_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
        header.addWidget(self._range_label, 1)
        layout.addLayout(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._canvas = _EPGCanvas()
        self._canvas.program_clicked.connect(self._on_program_clicked)
        self._scroll.setWidget(self._canvas)
        layout.addWidget(self._scroll, 1)

    def set_programs_provider(self, provider: Callable[[Channel], list[EPGProgram]]):
        """Inject a `(channel) -> list[EPGProgram]` lookup (host owns the cache)."""
        self._programs_provider = provider

    def set_channels(self, channels: list[Channel]):
        self._channels = list(channels)
        self.channels_needed.emit(self._channels)
        self.refresh()

    def refresh(self):
        """Repaint using whatever EPG data the provider currently has cached."""
        programs_by_channel = {}
        if self._programs_provider:
            for channel in self._channels:
                key = channel.epg_channel_id or channel.tvg_id or channel.xtream_id or channel.name
                programs_by_channel[key] = self._programs_provider(channel) or []
        self._canvas.set_data(self._channels, programs_by_channel, self._window_start)
        self._update_range_label()

    def _shift_window(self, hours: int):
        self._window_start += timedelta(hours=hours)
        self.refresh()

    def _jump_to_now(self):
        self._window_start = datetime.now().astimezone() - timedelta(minutes=15)
        self.refresh()

    def _update_range_label(self):
        end = self._window_start + timedelta(hours=HOURS_VISIBLE)
        self._range_label.setText(
            f"{self._window_start.strftime('%H:%M')} — {end.strftime('%H:%M')}"
        )

    def _on_program_clicked(self, channel: Channel, program: EPGProgram):
        now = datetime.now(program.start.tzinfo)
        is_replayable = (
            channel.source == "xtream"
            and channel.has_archive
            and program.stop <= now
            and (now - program.stop) <= timedelta(days=max(1, channel.archive_duration_days))
        )
        if is_replayable:
            self.replay_requested.emit(channel, program)
