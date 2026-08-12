"""Floating always-on-top picture-in-picture video window."""

from typing import Optional

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .theme import Palette


class PiPWindow(QWidget):
    """Frameless, always-on-top window hosting VLC's video output.

    Dragging is implemented manually since a frameless window has no native
    title bar. `video_frame` is the widget MediaPlayer.set_video_widget()
    should be rebound to while PiP is active.
    """

    closed = Signal()

    def __init__(self, size: Optional[QSize] = None):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setWindowTitle("IPTV Player - PiP")
        self.resize(size or QSize(360, 202))
        self.setMinimumSize(200, 112)
        self.setStyleSheet(f"background: #000; border: 1px solid {Palette.BORDER_STRONG};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.video_frame = QWidget()
        self.video_frame.setStyleSheet("background: #000;")
        layout.addWidget(self.video_frame)

        self._drag_origin: QPoint = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
