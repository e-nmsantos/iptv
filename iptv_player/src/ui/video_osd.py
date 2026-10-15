"""On-screen display floating above the VLC video surface.

VLC paints straight into the native window handed to it with ``set_hwnd()``
(or the macOS/X11 equivalents), so ordinary Qt child widgets are not
guaranteed to composite above the picture. Each OSD element is therefore a
small frameless, translucent *tool window* owned by the main window and kept
aligned with the video widget: the channel banner ("agora / a seguir"), the
channel-number badge used while zapping by number, and an interactive action
card (next episode, reminders).
"""

from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.image_loader import get_image_loader
from .theme import Palette

_BANNER_MS = 5000
_LOGO_SIZE = QSize(72, 72)


class _FloatingPanel(QWidget):
    """Frameless translucent tool window anchored to a corner of a target widget."""

    def __init__(self, owner: QWidget, interactive: bool = False):
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if not interactive:
            flags |= Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus
        super().__init__(owner, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        if not interactive:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._radius = 14
        self._gradient = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        if self._gradient:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gradient.setColorAt(0.0, QColor(8, 8, 10, 120))
            gradient.setColorAt(0.35, QColor(8, 8, 10, 225))
            gradient.setColorAt(1.0, QColor(8, 8, 10, 245))
            painter.fillPath(path, gradient)
        else:
            painter.fillPath(path, QColor(18, 18, 21, 238))
            painter.setPen(QColor(Palette.BORDER_STRONG))
            painter.drawPath(path)


class _ChannelBanner(_FloatingPanel):
    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self._gradient = True
        self._radius = 16
        self._logo_url = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(18)

        self._logo = QLabel()
        self._logo.setFixedSize(_LOGO_SIZE)
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._logo.setStyleSheet(
            f"background: {Palette.BG_CARD}; border-radius: 12px; color: {Palette.ACCENT};"
            "font-size: 22px; font-weight: 800;"
        )
        layout.addWidget(self._logo, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        self._number = QLabel()
        self._number.setStyleSheet(f"color: {Palette.ACCENT}; font-size: 20px; font-weight: 800;")
        title_row.addWidget(self._number)
        self._name = QLabel()
        self._name.setStyleSheet(f"color: {Palette.TEXT_PRIMARY}; font-size: 20px; font-weight: 700;")
        title_row.addWidget(self._name)
        self._badge = QLabel()
        title_row.addWidget(self._badge)
        title_row.addStretch(1)
        self._clock = QLabel()
        self._clock.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-size: 15px; font-weight: 600;")
        title_row.addWidget(self._clock)
        text.addLayout(title_row)

        self._now = QLabel()
        self._now.setStyleSheet(f"color: {Palette.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;")
        text.addWidget(self._now)
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setRange(0, 1000)
        self._progress.setFixedHeight(4)
        self._progress.setMaximumWidth(460)
        self._progress.setStyleSheet(
            "QProgressBar { background: rgba(255,255,255,40); border: none; border-radius: 2px; }"
            f"QProgressBar::chunk {{ background: {Palette.ACCENT}; border-radius: 2px; }}"
        )
        text.addWidget(self._progress)
        self._description = QLabel()
        self._description.setWordWrap(True)
        self._description.setMaximumHeight(36)
        self._description.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-size: 12px;")
        text.addWidget(self._description)
        self._next = QLabel()
        self._next.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-size: 12px;")
        text.addWidget(self._next)
        layout.addLayout(text, 1)
        get_image_loader().image_ready.connect(self._on_image_ready)

    def set_content(
        self,
        name: str,
        number: int,
        logo_url: str,
        current,
        upcoming,
        behind_live_ms: int,
    ) -> None:
        self._number.setText(str(number) if number > 0 else "")
        self._number.setVisible(number > 0)
        self._name.setText(name)
        if behind_live_ms > 1000:
            self._badge.setText(f" EM DIFERIDO −{_clock_duration(behind_live_ms)} ")
            self._badge.setStyleSheet(
                f"background: {Palette.WARNING_AMBER}; color: #000; border-radius: 4px;"
                "font-size: 10px; font-weight: 800; padding: 2px 4px;"
            )
        else:
            self._badge.setText(" ● DIRETO ")
            self._badge.setStyleSheet(
                f"background: {Palette.LIVE_BADGE}; color: #fff; border-radius: 4px;"
                "font-size: 10px; font-weight: 800; padding: 2px 4px;"
            )
        self._clock.setText(datetime.now().strftime("%H:%M"))
        self._logo_url = logo_url or ""
        pixmap = get_image_loader().load(self._logo_url, _LOGO_SIZE) if self._logo_url else None
        self._set_logo(pixmap, name)
        if current is not None:
            self._now.setText(
                f"{current.start.astimezone().strftime('%H:%M')}–"
                f"{current.stop.astimezone().strftime('%H:%M')}   {current.title}"
            )
            self._progress.setValue(int(current.progress * 1000))
            self._progress.show()
            self._description.setText(current.description or "")
            self._description.setVisible(bool(current.description))
        else:
            self._now.setText("Sem informação de programação")
            self._progress.hide()
            self._description.hide()
        if upcoming is not None:
            self._next.setText(f"A seguir  {upcoming.start.astimezone().strftime('%H:%M')}  {upcoming.title}")
            self._next.show()
        else:
            self._next.hide()

    def _set_logo(self, pixmap: Optional[QPixmap], name: str) -> None:
        if pixmap is not None and not pixmap.isNull():
            self._logo.setText("")
            self._logo.setPixmap(
                pixmap.scaled(
                    _LOGO_SIZE - QSize(10, 10),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self._logo.setPixmap(QPixmap())
            self._logo.setText(name[:2].upper())

    def _on_image_ready(self, url: str, pixmap: QPixmap) -> None:
        if url == self._logo_url:
            self._set_logo(pixmap, self._name.text())


class _NumberBadge(_FloatingPanel):
    def __init__(self, owner: QWidget):
        super().__init__(owner)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 12, 22, 12)
        layout.setSpacing(0)
        self._digits = QLabel()
        self._digits.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._digits.setStyleSheet(f"color: {Palette.TEXT_PRIMARY}; font-size: 40px; font-weight: 800;")
        layout.addWidget(self._digits)
        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._preview)

    def set_content(self, digits: str, preview: Optional[str]) -> None:
        self._digits.setText(digits)
        if preview:
            self._preview.setText(preview)
            self._preview.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-size: 12px;")
        else:
            self._preview.setText("Canal inexistente")
            self._preview.setStyleSheet(f"color: {Palette.WARNING_AMBER}; font-size: 12px;")
        self.adjustSize()


class _ActionCard(_FloatingPanel):
    """Interactive card: eyebrow, title, subtitle and a row of buttons."""

    def __init__(self, owner: QWidget):
        super().__init__(owner, interactive=True)
        self.setFixedWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(4)
        self._eyebrow = QLabel()
        self._eyebrow.setStyleSheet(f"color: {Palette.ACCENT}; font-size: 11px; font-weight: 800;")
        layout.addWidget(self._eyebrow)
        self._title = QLabel()
        self._title.setWordWrap(True)
        self._title.setStyleSheet(f"color: {Palette.TEXT_PRIMARY}; font-size: 17px; font-weight: 700;")
        layout.addWidget(self._title)
        self._subtitle = QLabel()
        self._subtitle.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._subtitle)
        layout.addSpacing(8)
        self._buttons = QHBoxLayout()
        self._buttons.setSpacing(8)
        layout.addLayout(self._buttons)

    def set_content(self, eyebrow: str, title: str, subtitle: str, buttons: list) -> None:
        self._eyebrow.setText(eyebrow)
        self._title.setText(title)
        self._subtitle.setText(subtitle)
        self._subtitle.setVisible(bool(subtitle))
        while self._buttons.count():
            item = self._buttons.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, (label, callback) in enumerate(buttons):
            button = QPushButton(label)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            primary = index == 0
            button.setStyleSheet(
                f"""QPushButton {{
                    background: {Palette.ACCENT if primary else Palette.BG_CARD};
                    color: {Palette.TEXT_ON_ACCENT if primary else Palette.TEXT_PRIMARY};
                    border: 1px solid {Palette.ACCENT if primary else Palette.BORDER_STRONG};
                    border-radius: 8px; padding: 7px 14px; font-weight: 700;
                }}
                QPushButton:hover {{ background: {Palette.ACCENT_HOVER if primary else Palette.BG_CARD_HOVER}; }}"""
            )
            button.clicked.connect(callback)
            self._buttons.addWidget(button)
        self._buttons.addStretch(1)
        self.adjustSize()

    def set_eyebrow(self, text: str) -> None:
        self._eyebrow.setText(text)


class VideoOsd(QObject):
    """Owns the floating OSD panels and keeps them glued to the video widget."""

    def __init__(self, video_widget: QWidget, window: QWidget):
        super().__init__(window)
        self._video = video_widget
        self._window = window
        self._banner = _ChannelBanner(window)
        self._number = _NumberBadge(window)
        self._card = _ActionCard(window)
        self._card_visible = False
        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(self._banner.hide)
        self._number_timer = QTimer(self)
        self._number_timer.setSingleShot(True)
        self._number_timer.timeout.connect(self._number.hide)
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick_countdown)
        self._countdown_left = 0
        self._countdown_template = ""
        self._countdown_done: Optional[Callable[[], None]] = None
        video_widget.installEventFilter(self)
        window.installEventFilter(self)

    # -- public API ---------------------------------------------------
    def show_channel_banner(
        self,
        name: str,
        number: int = 0,
        logo_url: str = "",
        current=None,
        upcoming=None,
        behind_live_ms: int = 0,
        duration_ms: int = _BANNER_MS,
    ) -> None:
        if not self._video_visible():
            return
        self._banner.set_content(name, number, logo_url, current, upcoming, behind_live_ms)
        self._place_banner()
        self._banner.show()
        self._banner.raise_()
        self._banner_timer.start(duration_ms)

    def hide_channel_banner(self) -> None:
        self._banner_timer.stop()
        self._banner.hide()

    def show_number(self, digits: str, preview: Optional[str], duration_ms: int = 2200) -> None:
        if not self._video_visible():
            return
        self._number.set_content(digits, preview)
        self._place_number()
        self._number.show()
        self._number.raise_()
        self._number_timer.start(duration_ms)

    def show_card(
        self,
        eyebrow: str,
        title: str,
        subtitle: str,
        buttons: list,
        countdown_seconds: int = 0,
        countdown_template: str = "",
        on_countdown_done: Optional[Callable[[], None]] = None,
    ) -> None:
        """Show an action card; ``countdown_template`` uses ``{s}`` for the seconds left."""
        self._countdown_timer.stop()
        self._card.set_content(eyebrow, title, subtitle, buttons)
        self._card_visible = True
        if countdown_seconds > 0 and on_countdown_done is not None:
            self._countdown_left = countdown_seconds
            self._countdown_template = countdown_template or "{s} s"
            self._countdown_done = on_countdown_done
            self._card.set_eyebrow(self._countdown_template.format(s=self._countdown_left))
            self._countdown_timer.start()
        if self._video_visible():
            self._place_card()
            self._card.show()
            self._card.raise_()

    def hide_card(self) -> None:
        self._countdown_timer.stop()
        self._countdown_done = None
        self._card_visible = False
        self._card.hide()

    def hide_all(self) -> None:
        self.hide_channel_banner()
        self._number_timer.stop()
        self._number.hide()
        self.hide_card()

    # -- internals ----------------------------------------------------
    def _tick_countdown(self) -> None:
        self._countdown_left -= 1
        if self._countdown_left <= 0:
            done = self._countdown_done
            self.hide_card()
            if done is not None:
                done()
            return
        self._card.set_eyebrow(self._countdown_template.format(s=self._countdown_left))

    def _video_visible(self) -> bool:
        return (
            self._video.isVisible()
            and not self._window.isMinimized()
            and self._video.width() > 80
        )

    def _video_rect(self) -> QRect:
        top_left = self._video.mapToGlobal(QPoint(0, 0))
        return QRect(top_left, self._video.size())

    def _place_banner(self) -> None:
        rect = self._video_rect()
        margin = 18
        width = max(320, rect.width() - 2 * margin)
        self._banner.setFixedWidth(width)
        self._banner.adjustSize()
        self._banner.move(rect.left() + margin, rect.bottom() - self._banner.height() - margin)

    def _place_number(self) -> None:
        rect = self._video_rect()
        self._number.adjustSize()
        self._number.move(rect.right() - self._number.width() - 24, rect.top() + 24)

    def _place_card(self) -> None:
        rect = self._video_rect()
        self._card.adjustSize()
        self._card.move(rect.right() - self._card.width() - 24, rect.top() + 24)

    def _reposition(self) -> None:
        if not self._video_visible():
            self._banner.hide()
            self._number.hide()
            self._card.hide()
            return
        if self._banner.isVisible():
            self._place_banner()
        if self._number.isVisible():
            self._place_number()
        if self._card_visible:
            self._place_card()
            self._card.show()

    def eventFilter(self, watched, event):
        if event.type() in (
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.Hide,
            QEvent.Type.WindowStateChange,
        ):
            QTimer.singleShot(0, self._reposition)
        return False


def _clock_duration(ms: int) -> str:
    seconds = max(0, int(ms // 1000))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
