"""Multi-View Dialog allowing simultaneous playback of 2 to 4 IPTV channels."""

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..core.channel import Channel
from .multiview_widget import MultiViewWidget
from .theme import Palette


class MultiViewDialog(QDialog):
    """Standalone window for multi-channel video mosaic (2 or 4 screens)."""

    def __init__(
        self,
        channels: list[Channel],
        initial_channel: Optional[Channel] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Modo Mosaico (Multi-View 2x2)")
        self.resize(1080, 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Top Control Bar
        toolbar = QHBoxLayout()
        title_lbl = QLabel("📺 Multi-View")
        title_lbl.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Palette.ACCENT};")
        toolbar.addWidget(title_lbl)

        toolbar.addSpacing(16)
        toolbar.addWidget(QLabel("Grelha:"))

        self._btn_2 = QPushButton("2 Ecrãs (1x2)")
        self._btn_2.setCheckable(True)
        self._btn_2.setChecked(True)
        self._btn_2.clicked.connect(lambda: self._set_layout(2))
        toolbar.addWidget(self._btn_2)

        self._btn_4 = QPushButton("4 Ecrãs (2x2)")
        self._btn_4.setCheckable(True)
        self._btn_4.clicked.connect(lambda: self._set_layout(4))
        toolbar.addWidget(self._btn_4)

        toolbar.addStretch()

        help_lbl = QLabel("💡 Clica em '🔊 Áudio' num ecrã para ouvir esse canal")
        help_lbl.setStyleSheet(f"color: {Palette.TEXT_MUTED}; font-size: 11px;")
        toolbar.addWidget(help_lbl)

        toolbar.addSpacing(16)
        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(self.close)
        toolbar.addWidget(close_btn)

        layout.addLayout(toolbar)

        # Multi-View Container
        self._multiview = MultiViewWidget(self)
        self._multiview.set_channels(channels)
        self._multiview.play_initial(initial_channel)
        layout.addWidget(self._multiview, 1)

    def _set_layout(self, count: int):
        self._btn_2.setChecked(count == 2)
        self._btn_4.setChecked(count == 4)
        self._multiview.set_layout_mode(count)

    def closeEvent(self, event):
        self._multiview.stop_all()
        super().closeEvent(event)

