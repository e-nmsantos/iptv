"""EPG (Electronic Program Guide) widget."""

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .theme import Palette


class EPGWidget(QWidget):
    """Widget displaying the Electronic Program Guide."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._programs: dict = {}  # channel_id -> list of programs
        self._channel_names: dict = {}  # channel_id -> channel_name
        self._setup_ui()
        self._refresh_timer = QTimer()
        self._refresh_timer.setInterval(60000)  # Refresh every minute
        self._refresh_timer.timeout.connect(self._refresh_display)
        self._refresh_timer.start()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        title = QLabel("📅 Guia de Programação (EPG)")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title.setStyleSheet(f"color: {Palette.TEXT_PRIMARY}; padding: 5px;")
        title.setFont(title_font)
        layout.addWidget(title)

        # Channel selector
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("Canal:"))
        self._channel_combo = self._create_combo()
        self._channel_combo.currentIndexChanged.connect(self._update_epg_display)
        channel_layout.addWidget(self._channel_combo, 1)
        layout.addLayout(channel_layout)

        # EPG table
        self._epg_table = QTableWidget()
        self._epg_table.setColumnCount(3)
        self._epg_table.setHorizontalHeaderLabels(["Hora", "Programa", "Duração"])
        self._epg_table.horizontalHeader().setStretchLastSection(True)
        self._epg_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._epg_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._epg_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._epg_table.setAlternatingRowColors(True)
        self._epg_table.setStyleSheet(f"gridline-color: {Palette.BORDER};")
        layout.addWidget(self._epg_table)

    def _create_combo(self):
        """Create a combo box (theme-styled globally via the QComboBox QSS rules)."""
        from PySide6.QtWidgets import QComboBox
        return QComboBox()

    def set_epg_data(self, channel_programs: dict, channel_names: Optional[dict] = None):
        """Set EPG data for display."""
        selected_channel = self._channel_combo.currentData()
        self._programs = channel_programs
        channel_names = channel_names or {}
        self._channel_names = channel_names

        # Update channel selector
        self._channel_combo.blockSignals(True)
        self._channel_combo.clear()
        self._channel_combo.addItem("Selecionar canal...", "")
        for ch_id in sorted(channel_programs.keys()):
            display = channel_names.get(ch_id, ch_id)
            self._channel_combo.addItem(display, ch_id)
        self._channel_combo.blockSignals(False)
        if selected_channel:
            self.select_channel(selected_channel)

    def add_channel_programs(self, channel_id: str, programs: list, channel_name: str = ""):
        """Add programs for a specific channel."""
        self._programs[channel_id] = programs
        if channel_name:
            self._channel_names[channel_id] = channel_name

        # Check if already in combo
        for i in range(self._channel_combo.count()):
            if self._channel_combo.itemData(i) == channel_id:
                break
        else:
            display = channel_name or channel_id
            self._channel_combo.addItem(display, channel_id)

    def select_channel(self, channel_id: str):
        """Select a channel in the EPG picker when it is available."""
        index = self._channel_combo.findData(channel_id)
        if index >= 0:
            self._channel_combo.setCurrentIndex(index)

    def _update_epg_display(self):
        """Update the EPG table with selected channel's data."""
        channel_id = self._channel_combo.currentData()
        if not channel_id or channel_id not in self._programs:
            self._epg_table.setRowCount(0)
            return

        programs = self._programs[channel_id]
        programs.sort(key=lambda p: p.start)

        self._epg_table.setRowCount(len(programs))

        for row, prog in enumerate(programs):
            # Time column
            time_item = QTableWidgetItem(
                prog.start.strftime("%H:%M") + " - " + prog.stop.strftime("%H:%M")
            )
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Title column
            title_text = prog.title
            if prog.category:
                title_text += f" [{prog.category}]"
            title_item = QTableWidgetItem(title_text)

            # Duration column
            dur_item = QTableWidgetItem(f"{prog.duration_minutes} min")
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Highlight current program
            if prog.is_live:
                highlight = QColor(Palette.ACCENT)
                time_item.setBackground(highlight)
                title_item.setBackground(highlight)
                dur_item.setBackground(highlight)
                time_item.setForeground(QColor(Palette.TEXT_ON_ACCENT))
                title_item.setForeground(QColor(Palette.TEXT_ON_ACCENT))
                dur_item.setForeground(QColor(Palette.TEXT_ON_ACCENT))
                title_font = QFont()
                title_font.setBold(True)
                title_item.setFont(title_font)

            # Past programs dimmed
            now = datetime.now(prog.stop.tzinfo)
            if prog.stop < now and not prog.is_live:
                dim = QColor(Palette.TEXT_MUTED)
                time_item.setForeground(dim)
                title_item.setForeground(dim)
                dur_item.setForeground(dim)

            self._epg_table.setItem(row, 0, time_item)
            self._epg_table.setItem(row, 1, title_item)
            self._epg_table.setItem(row, 2, dur_item)

        self._epg_table.resizeColumnsToContents()

    def _refresh_display(self):
        """Periodic refresh to update live program highlighting."""
        self._update_epg_display()

    def clear(self):
        """Clear all EPG data."""
        self._programs.clear()
        self._channel_names.clear()
        self._channel_combo.clear()
        self._epg_table.setRowCount(0)
