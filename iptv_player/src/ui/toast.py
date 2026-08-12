"""Lightweight toast notifications for the IPTV Player."""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QVBoxLayout, QWidget


class Toast(QWidget):
    """A small transient notification that fades in and out.

    Lives as an overlay child of the given parent widget (typically the main
    window) and never steals focus or intercepts mouse events. Used for
    non-intrusive feedback such as "EPG atualizado", "Gravação iniciada" or
    auto-zap notifications.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "Toast {"
            "  background: rgba(30, 30, 34, 235);"
            "  border: 1px solid #3a3a40;"
            "  border-radius: 9px;"
            "}"
            "QLabel {"
            "  background: transparent;"
            "  color: #f5f5f7;"
            "  font-size: 12px;"
            "  padding: 10px 16px;"
            "}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(self)
        layout.addWidget(self._label)
        self.adjustSize()

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        self._fade_in = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_in.setDuration(180)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._fade_out = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_out.setDuration(320)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(self.hide)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out.start)
        self.hide()

    def show_message(self, text: str, duration_ms: int = 2600):
        """Display a toast for the given duration (ms)."""
        self._label.setText(text)
        self.adjustSize()
        self._reposition()
        self.raise_()
        self.show()
        self._hide_timer.stop()
        self._hide_timer.start(max(500, int(duration_ms)))
        self._fade_in.stop()
        self._fade_out.stop()
        self._opacity.setOpacity(0.0)
        self._fade_in.start()

    def _reposition(self):
        parent = self.parentWidget()
        if not parent:
            return
        self.move(
            parent.width() - self.width() - 18,
            parent.height() - self.height() - 18,
        )

    def parent_resized(self):
        """Keep the toast anchored bottom-right when the parent is resized."""
        self._reposition()
