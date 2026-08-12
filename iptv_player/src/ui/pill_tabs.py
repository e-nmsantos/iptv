"""Segmented pill-style tab bar (Live / Vod / Series content switcher)."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from .theme import Palette


class PillTabBar(QWidget):
    """Rounded segmented control with exclusive checkable tabs."""

    tab_changed = Signal(int)  # index of the selected tab

    def __init__(self, labels: list, parent=None):
        super().__init__(parent)
        self._buttons: list = []
        self._setup_ui(labels)

    def _setup_ui(self, labels: list):
        self.setStyleSheet(f"""
            QWidget#pillContainer {{
                background: {Palette.BG_PANEL};
                border: 1px solid {Palette.BORDER_STRONG};
                border-radius: {Palette.RADIUS_LG}px;
            }}
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: {Palette.RADIUS_MD}px;
                color: {Palette.TEXT_MUTED};
                font-size: 13px;
                font-weight: 600;
                padding: 8px 0;
            }}
            QPushButton:checked {{
                background: {Palette.ACCENT};
                color: {Palette.TEXT_ON_ACCENT};
            }}
            QPushButton:hover:!checked {{
                color: {Palette.TEXT_PRIMARY};
            }}
        """)

        container = QWidget()
        container.setObjectName("pillContainer")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        for index, label in enumerate(labels):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addWidget(btn, 1)
            self._group.addButton(btn, index)
            self._buttons.append(btn)

        if self._buttons:
            self._buttons[0].setChecked(True)

        self._group.idClicked.connect(self.tab_changed.emit)

    def set_current_index(self, index: int):
        """Programmatically select a tab."""
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)
