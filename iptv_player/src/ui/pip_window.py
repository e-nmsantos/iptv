"""Frameless, floating Always-on-Top Picture-in-Picture (PiP) window for Desktop."""

import logging
from typing import Callable, Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class PipFloatingWindow(QWidget):
    """Floating borderless video overlay window with drag-to-move support."""

    closed = Signal()
    restore_requested = Signal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        on_close: Optional[Callable[[], None]] = None,
        on_restore: Optional[Callable[[], None]] = None,
    ):
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._drag_pos: Optional[QPoint] = None
        self._on_close = on_close
        self._on_restore = on_restore

        self.resize(380, 214)  # 16:9 standard preview size
        self.setMinimumSize(240, 135)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Video embedding target container
        self._video_container = QWidget(self)
        self._video_container.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self._video_container.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen, True)
        self._video_container.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._video_container.setStyleSheet("background-color: #000000;")
        layout.addWidget(self._video_container, 1)

        # Hover overlay bar with close / restore buttons
        self._overlay_bar = QWidget(self)
        self._overlay_bar.setStyleSheet("background-color: rgba(10, 20, 30, 180); border-radius: 4px;")
        bar_layout = QHBoxLayout(self._overlay_bar)
        bar_layout.setContentsMargins(8, 4, 8, 4)

        self._title_label = QLabel("IPTV Mini Player")
        self._title_label.setStyleSheet("color: white; font-size: 11px; font-weight: bold;")
        bar_layout.addWidget(self._title_label, 1)

        self._btn_restore = QPushButton("🗗")
        self._btn_restore.setToolTip("Restaurar para janela principal")
        self._btn_restore.setStyleSheet("color: white; background: transparent; border: none; font-size: 14px;")
        self._btn_restore.clicked.connect(self._handle_restore)
        bar_layout.addWidget(self._btn_restore)

        self._btn_close = QPushButton("✕")
        self._btn_close.setToolTip("Fechar PiP")
        self._btn_close.setStyleSheet("color: #FF5E5B; background: transparent; border: none; font-size: 14px;")
        self._btn_close.clicked.connect(self._handle_close)
        bar_layout.addWidget(self._btn_close)

        layout.addWidget(self._overlay_bar)

    @property
    def video_container(self) -> QWidget:
        return self._video_container

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None

    def _handle_restore(self):
        self.hide()
        self.restore_requested.emit()
        if self._on_restore:
            self._on_restore()

    def _handle_close(self):
        self.close()

    def closeEvent(self, event):
        # Also covers closes not started by our button (Alt+F4, app shutdown).
        self.closed.emit()
        if self._on_close:
            self._on_close()
        super().closeEvent(event)


# Alias for backward compatibility
PiPWindow = PipFloatingWindow
