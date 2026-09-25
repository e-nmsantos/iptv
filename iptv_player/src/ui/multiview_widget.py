"""Multi-View widget allowing simultaneous playback of 2 to 4 IPTV channels in a grid."""

import logging
from typing import Callable, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.channel import Channel
from ..player.media_player import MediaPlayer

logger = logging.getLogger(__name__)


class ViewportSlot(QWidget):
    """Individual player viewport inside the Multi-View grid."""

    channel_selected = Signal(Channel)
    focus_requested = Signal()

    def __init__(
        self,
        slot_index: int,
        parent: Optional[QWidget] = None,
        on_channel_change: Optional[Callable[[Channel], None]] = None,
    ):
        super().__init__(parent)
        self.slot_index = slot_index
        self._on_channel_change = on_channel_change
        self._current_channel: Optional[Channel] = None
        self._all_channels: list[Channel] = []

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(2)

        # Header bar
        self._header = QWidget()
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(4, 2, 4, 2)
        header_layout.setSpacing(6)

        self._slot_label = QLabel(f"Ecrã {slot_index + 1}")
        self._slot_label.setStyleSheet("font-weight: bold; color: #41D3BD;")
        header_layout.addWidget(self._slot_label)

        self._channel_combo = QComboBox()
        self._channel_combo.currentIndexChanged.connect(self._on_combo_index_changed)
        header_layout.addWidget(self._channel_combo, 1)

        self._mute_btn = QPushButton("🔊 Áudio")
        self._mute_btn.setCheckable(True)
        self._mute_btn.setChecked(slot_index == 0)
        self._mute_btn.clicked.connect(self._on_mute_clicked)
        header_layout.addWidget(self._mute_btn)

        self._layout.addWidget(self._header)

        # Video container
        self._video_widget = QWidget()
        self._video_widget.setStyleSheet("background-color: #000000; border-radius: 4px;")
        self._layout.addWidget(self._video_widget, 1)

        # Media player instance
        self._player = MediaPlayer(self._video_widget)
        self._player.set_volume(80 if slot_index == 0 else 0)

    @property
    def player(self) -> MediaPlayer:
        return self._player

    @property
    def video_widget(self) -> QWidget:
        return self._video_widget

    def set_channels(self, channels: list[Channel]):
        """Populate the channel dropdown with available live channels."""
        self._all_channels = [ch for ch in channels if getattr(ch, "stream_type", "live") == "live"]
        self._channel_combo.blockSignals(True)
        self._channel_combo.clear()
        self._channel_combo.addItem("-- Selecionar Canal --", None)
        for ch in self._all_channels:
            name = ch.name or "Sem nome"
            group = f" [{ch.group}]" if ch.group else ""
            self._channel_combo.addItem(f"{name}{group}", ch)
        self._channel_combo.blockSignals(False)

    def select_channel(self, channel: Channel):
        """Start playing the specified channel in this slot."""
        self._current_channel = channel
        idx = self._channel_combo.findData(channel)
        if idx >= 0:
            self._channel_combo.blockSignals(True)
            self._channel_combo.setCurrentIndex(idx)
            self._channel_combo.blockSignals(False)

        headers = {}
        if getattr(channel, "user_agent", ""):
            headers["User-Agent"] = channel.user_agent
        if getattr(channel, "referer", ""):
            headers["Referer"] = channel.referer

        self._player.play(channel.url, headers, is_live=True)

    def stop(self):
        """Stop playback in this slot."""
        self._player.stop()

    def set_muted(self, muted: bool):
        """Mute or unmute this slot."""
        self._mute_btn.setChecked(not muted)
        self._player.set_volume(0 if muted else 80)
        self._mute_btn.setText("🔇 Mudo" if muted else "🔊 Áudio")

    def _on_combo_index_changed(self, index: int):
        channel = self._channel_combo.currentData()
        if channel:
            self.select_channel(channel)
            if self._on_channel_change:
                self._on_channel_change(channel)

    def _on_mute_clicked(self):
        is_audio_active = self._mute_btn.isChecked()
        self.focus_requested.emit()
        self.set_muted(not is_audio_active)


class MultiViewWidget(QWidget):
    """Grid container managing 2 to 4 simultaneous IPTV viewports."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._grid_layout = QGridLayout(self)
        self._grid_layout.setContentsMargins(4, 4, 4, 4)
        self._grid_layout.setSpacing(4)

        self._slots: list[ViewportSlot] = []
        self._active_slots_count = 2
        self._available_channels: list[Channel] = []

        # Create maximum 4 slots
        for i in range(4):
            slot = ViewportSlot(i, self)
            slot.focus_requested.connect(lambda s=slot: self._on_slot_focused(s))
            self._slots.append(slot)

        self.set_layout_mode(2)

    def set_layout_mode(self, count: int):
        """Set active viewport count (2 or 4)."""
        self._active_slots_count = max(2, min(4, count))

        # Clear existing grid
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        if self._active_slots_count == 2:
            # 1 row x 2 cols
            self._grid_layout.addWidget(self._slots[0], 0, 0)
            self._grid_layout.addWidget(self._slots[1], 0, 1)
            self._slots[0].show()
            self._slots[1].show()
            self._slots[2].hide()
            self._slots[3].hide()
            self._slots[2].stop()
            self._slots[3].stop()
        else:
            # 2 rows x 2 cols
            self._grid_layout.addWidget(self._slots[0], 0, 0)
            self._grid_layout.addWidget(self._slots[1], 0, 1)
            self._grid_layout.addWidget(self._slots[2], 1, 0)
            self._grid_layout.addWidget(self._slots[3], 1, 1)
            for slot in self._slots:
                slot.show()

    def set_channels(self, channels: list[Channel]):
        """Update available channels across all slots."""
        self._available_channels = channels
        for slot in self._slots:
            slot.set_channels(channels)

    def play_initial(self, main_channel: Optional[Channel] = None):
        """Start playing the main channel in slot 0, and secondary channels if available."""
        if not self._available_channels:
            return

        live_channels = [ch for ch in self._available_channels if getattr(ch, "stream_type", "live") == "live"]
        if not live_channels:
            return

        if main_channel:
            self._slots[0].select_channel(main_channel)
        else:
            self._slots[0].select_channel(live_channels[0])
        self._slots[0].set_muted(False)

        # Populate other slots with distinct channels if available
        for i in range(1, self._active_slots_count):
            if i < len(live_channels):
                self._slots[i].select_channel(live_channels[i])
                self._slots[i].set_muted(True)

    def stop_all(self):
        """Stop all media player instances in every slot."""
        for slot in self._slots:
            slot.stop()

    def _on_slot_focused(self, active_slot: ViewportSlot):
        """Ensure only the active slot has unmuted audio."""
        for slot in self._slots:
            if slot == active_slot:
                slot.set_muted(False)
            else:
                slot.set_muted(True)

