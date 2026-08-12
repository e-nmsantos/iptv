"""Video player widget with playback controls."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..player.media_player import MediaPlayer
from ..utils.helpers import format_duration
from .pip_window import PiPWindow
from .theme import Palette


class SeekSlider(QSlider):
    """Horizontal QSlider that jumps to the clicked position on the track.

    The stock QSlider moves by a page-step when the groove is clicked and only
    emits ``sliderMoved`` while the knob is being dragged, so clicking on the
    timeline would never trigger a seek. This override jumps straight to the
    clicked position and reports it as a user move.
    """

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            value = self._value_at(event.position().x())
            self.setSliderDown(True)
            self.setValue(value)
            self.sliderMoved.emit(value)
            event.accept()
            return
        super().mousePressEvent(event)

    def _value_at(self, x: float) -> int:
        ratio = x / max(1.0, float(self.width()))
        ratio = max(0.0, min(1.0, ratio))
        return round(self.minimum() + (self.maximum() - self.minimum()) * ratio)


class PlayerWidget(QWidget):
    """Widget containing the video output and playback controls."""

    fullscreen_toggled = Signal(bool)
    previous_channel_requested = Signal()
    next_channel_requested = Signal()

    def __init__(self, media_player: MediaPlayer, settings=None, parent=None):
        super().__init__(parent)
        self._media_player = media_player
        self._settings = settings
        self._is_fullscreen = False
        self._channel_name = ""
        self._pip_window: Optional[PiPWindow] = None
        self._last_seek_value = -1
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        self.setStyleSheet("background: #000;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Video output area
        self._video_frame = QWidget()
        self._video_frame.setStyleSheet("background: #000;")
        self._video_frame.setMinimumSize(320, 240)
        self._video_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._video_frame, 1)

        # Controls overlay
        controls_container = QWidget()
        controls_container.setStyleSheet(f"""
            QWidget {{
                background: rgba(14, 14, 16, 225);
                border-top: 1px solid {Palette.BORDER_STRONG};
            }}
        """)
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setContentsMargins(10, 5, 10, 10)
        controls_layout.setSpacing(5)

        # Progress bar
        self._progress_slider = SeekSlider(Qt.Orientation.Horizontal)
        self._progress_slider.setRange(0, 1000)
        self._progress_slider.sliderMoved.connect(self._on_seek)
        self._progress_slider.sliderReleased.connect(
            lambda: self._on_seek(self._progress_slider.value())
        )
        controls_layout.addWidget(self._progress_slider)

        # Control buttons row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._play_btn = self._make_button("▶", "Play/Pause")
        self._play_btn.clicked.connect(self._toggle_play)
        btn_layout.addWidget(self._play_btn)

        self._stop_btn = self._make_button("⏹", "Stop")
        self._stop_btn.clicked.connect(self._stop)
        btn_layout.addWidget(self._stop_btn)

        self._previous_channel_btn = self._make_button("⏮", "Canal anterior (Page Up)")
        self._previous_channel_btn.clicked.connect(self.previous_channel_requested.emit)
        btn_layout.addWidget(self._previous_channel_btn)

        self._next_channel_btn = self._make_button("⏭", "Canal seguinte (Page Down)")
        self._next_channel_btn.clicked.connect(self.next_channel_requested.emit)
        btn_layout.addWidget(self._next_channel_btn)

        btn_layout.addSpacing(20)

        # Time labels
        self._time_label = QLabel("00:00 / 00:00")
        self._time_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-size: 12px;")
        btn_layout.addWidget(self._time_label)

        btn_layout.addStretch()

        # Volume
        vol_label = QLabel("🔊")
        vol_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY}; font-size: 14px;")
        btn_layout.addWidget(vol_label)

        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(self._media_player.get_volume())
        self._volume_slider.setFixedWidth(100)
        self._volume_slider.valueChanged.connect(self._on_volume_change)
        btn_layout.addWidget(self._volume_slider)

        self._audio_btn = self._make_button("A", "Faixa de áudio")
        self._audio_btn.clicked.connect(self._show_audio_menu)
        btn_layout.addWidget(self._audio_btn)

        self._subtitle_btn = self._make_button("CC", "Legendas")
        self._subtitle_btn.clicked.connect(self._show_subtitle_menu)
        btn_layout.addWidget(self._subtitle_btn)

        # Recording/overlay/PiP are secondary controls tucked behind one
        # button so the row stays compact at the window's minimum width.
        self._more_btn = self._make_button("⋯", "Mais opções")
        self._more_btn.clicked.connect(self._show_more_menu)
        btn_layout.addWidget(self._more_btn)

        self._more_menu = QMenu(self)
        self._record_action = self._more_menu.addAction("⏺ Gravar canal")
        self._record_action.setCheckable(True)
        self._record_action.triggered.connect(self._toggle_recording)

        self._overlay_action = self._more_menu.addAction("📊 Estatísticas da stream")
        self._overlay_action.setCheckable(True)
        if self._settings:
            self._overlay_action.setChecked(bool(self._settings.get("stream_overlay_enabled", False)))
        self._overlay_action.toggled.connect(self._toggle_overlay)

        self._pip_action = self._more_menu.addAction("🗗 Picture-in-Picture")
        self._pip_action.setCheckable(True)
        self._pip_action.toggled.connect(self._toggle_pip)

        # Fullscreen button
        self._fullscreen_btn = self._make_button("⛶", "Fullscreen")
        self._fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        btn_layout.addWidget(self._fullscreen_btn)

        # Channel info
        self._channel_info = QLabel("")
        self._channel_info.setStyleSheet(f"color: {Palette.TEXT_MUTED}; font-size: 11px; padding: 2px 10px;")
        controls_layout.addLayout(btn_layout)
        controls_layout.addWidget(self._channel_info)

        controls_container.setMaximumHeight(90)
        layout.addWidget(controls_container)

    def _make_button(self, text: str, tooltip: str) -> QPushButton:
        """Create a styled control button."""
        btn = QPushButton(text)
        btn.setToolTip(tooltip)
        btn.setFixedSize(36, 32)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {Palette.TEXT_SECONDARY};
                font-size: 16px;
                border-radius: {Palette.RADIUS_MD}px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.1);
                color: {Palette.TEXT_PRIMARY};
            }}
            QPushButton:pressed {{
                background: rgba(255, 255, 255, 0.2);
            }}
            QPushButton:checked {{
                background: {Palette.ACCENT};
                color: {Palette.TEXT_ON_ACCENT};
            }}
        """)
        return btn

    def _connect_signals(self):
        """Connect media player signals to UI updates."""
        self._media_player.position_changed.connect(self._on_position_changed)
        self._media_player.time_changed.connect(self._on_time_changed)
        self._media_player.state_changed.connect(self._on_state_changed)
        self._media_player.error_occurred.connect(self._on_error)
        self._media_player.recording_state_changed.connect(self._on_recording_state_changed)
        self._media_player.stats_changed.connect(self._on_stats_changed)

    def get_video_widget(self) -> QWidget:
        """Get the video frame widget for VLC output."""
        return self._video_frame

    def set_channel_info(self, channel_name: str):
        """Set the current channel name in the info bar."""
        self._channel_name = channel_name
        self._channel_info.setText(f"A reproduzir: {channel_name}")

    @Slot()
    def _toggle_play(self):
        """Toggle play/pause."""
        if self._media_player.is_playing:
            self._media_player.pause()
        else:
            self._media_player.play()

    @Slot()
    def _stop(self):
        """Stop playback."""
        self._media_player.stop()
        self._play_btn.setText("▶")
        self._channel_info.setText("Parado")

    @Slot(int)
    def _on_seek(self, value: int):
        """Handle seek slider movement (drag, click or release)."""
        if value == self._last_seek_value:
            return
        self._last_seek_value = value
        self._media_player.seek(value / 1000.0)

    @Slot(int)
    def _on_volume_change(self, value: int):
        """Handle volume slider change."""
        self._media_player.set_volume(value)

    def set_volume(self, value: int):
        """Sync the volume slider from outside (e.g. keyboard shortcuts)."""
        self._volume_slider.setValue(max(0, min(100, int(value))))

    def _show_audio_menu(self):
        menu = QMenu(self)
        tracks = self._media_player.get_audio_tracks()
        if not tracks:
            menu.addAction("Nenhuma faixa disponível").setEnabled(False)
        for track_id, label in tracks:
            menu.addAction(label, lambda checked=False, value=track_id: self._media_player.set_audio_track(value))
        menu.exec(self._audio_btn.mapToGlobal(self._audio_btn.rect().bottomLeft()))

    def _show_subtitle_menu(self):
        menu = QMenu(self)
        tracks = self._media_player.get_subtitle_tracks()
        selected_track = self._media_player.get_subtitle_track()
        disable = menu.addAction("Desativar")
        disable.setCheckable(True)
        disable.setChecked(selected_track < 0)
        disable.triggered.connect(lambda: self._media_player.set_subtitle_track(-1))
        if tracks:
            menu.addSeparator()
        for track_id, label in tracks:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(track_id == selected_track)
            action.triggered.connect(
                lambda checked=False, value=track_id: self._media_player.set_subtitle_track(value)
            )
        menu.addSeparator()
        add_file = menu.addAction("Adicionar ficheiro de legendas…")
        add_file.triggered.connect(self._add_subtitle_file)
        menu.exec(self._subtitle_btn.mapToGlobal(self._subtitle_btn.rect().bottomLeft()))

    def _add_subtitle_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Adicionar legendas",
            "",
            "Legendas (*.srt *.ass *.ssa *.sub *.vtt);;Todos os ficheiros (*)",
        )
        if file_path:
            self._media_player.add_subtitle_file(file_path)

    def _show_more_menu(self):
        self._more_menu.exec(self._more_btn.mapToGlobal(self._more_btn.rect().bottomLeft()))

    @Slot(float)
    def _on_position_changed(self, position: float):
        """Update progress slider."""
        if not self._progress_slider.isSliderDown():
            self._progress_slider.setValue(int(position * 1000))

    @Slot(int)
    def _on_time_changed(self, time_ms: int):
        """Update time labels."""
        length = self._media_player.get_length()
        current = format_duration(time_ms // 1000)
        total = format_duration(length // 1000) if length > 0 else "00:00"
        self._time_label.setText(f"{current} / {total}")

    @Slot(str)
    def _on_state_changed(self, state: str):
        """Update UI based on player state."""
        if state == "playing":
            self._play_btn.setText("⏸")
            if self._channel_name:
                self._channel_info.setText(f"A reproduzir: {self._channel_name}")
            self._channel_info.setStyleSheet(
                f"color: {Palette.TEXT_MUTED}; font-size: 11px; padding: 2px 10px;"
            )
        elif state in ("paused", "stopped"):
            self._play_btn.setText("▶")
        elif state == "buffering":
            self._channel_info.setText("A estabilizar a transmissão…")
        elif state == "reconnecting":
            self._channel_info.setText("A restabelecer a transmissão…")
            self._channel_info.setStyleSheet(
                f"color: {Palette.WARNING_AMBER}; font-size: 11px; padding: 2px 10px;"
            )

    @Slot(str)
    def _on_error(self, message: str):
        """Handle player errors."""
        self._channel_info.setText(f"⚠ Erro: {message}")
        self._play_btn.setText("▶")

    @Slot()
    def _toggle_fullscreen(self):
        """Toggle fullscreen mode. The actual window/layout changes are
        handled by MainWindow, which owns the panels that need to be
        hidden for a true fullscreen (video-only) view."""
        self._is_fullscreen = not self._is_fullscreen
        self.fullscreen_toggled.emit(self._is_fullscreen)

    def set_fullscreen_state(self, is_fullscreen: bool):
        """Sync internal state when fullscreen is exited externally (e.g. Esc)."""
        self._is_fullscreen = is_fullscreen

    @Slot()
    def _toggle_recording(self):
        if self._media_player.is_recording:
            self._media_player.stop_recording()
            return
        folder = Path(
            self._settings.get("recording_folder", "") if self._settings else ""
        ) or Path.home() / "Videos" / "IPTV Recordings"
        folder.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in self._channel_name) or "gravacao"
        filename = f"{safe_name}_{datetime.now():%Y%m%d_%H%M%S}.ts"
        self._media_player.start_recording(str(folder / filename))

    @Slot(bool, str)
    def _on_recording_state_changed(self, is_recording: bool, path: str):
        self._record_action.setChecked(is_recording)
        self._more_btn.setText("⏺" if is_recording else "⋯")
        self._record_action.setToolTip(f"A gravar para: {path}" if is_recording else "Gravar canal")

    @Slot(bool)
    def _toggle_overlay(self, checked: bool):
        if self._settings:
            self._settings.set("stream_overlay_enabled", checked)
        if not checked:
            self._media_player.clear_marquee()

    @Slot(dict)
    def _on_stats_changed(self, stats: dict):
        if not self._overlay_action.isChecked():
            return
        bitrate = stats.get("bitrate_kbps", 0)
        dropped = stats.get("dropped_frames", 0)
        buffering = stats.get("buffering_events", 0)
        text = f"{bitrate:.0f} kbps · {dropped} quebras · buffer x{buffering}"
        self._media_player.set_marquee_text(text)

    @Slot(bool)
    def _toggle_pip(self, checked: bool):
        if checked:
            size = QSize(*(self._settings.get("pip_window_size", [360, 202]) if self._settings else [360, 202]))
            self._pip_window = PiPWindow(size)
            self._pip_window.closed.connect(self._on_pip_closed)
            self._pip_window.show()
            self._media_player.set_video_widget(self._pip_window.video_frame)
        elif self._pip_window is not None:
            self._media_player.set_video_widget(self._video_frame)
            self._pip_window.close()
            self._pip_window = None

    @Slot()
    def _on_pip_closed(self):
        self._pip_window = None
        self._media_player.set_video_widget(self._video_frame)
        self._pip_action.setChecked(False)

    def close_pip(self):
        """Close any active PiP window (e.g. on application shutdown)."""
        if self._pip_window is not None:
            self._pip_window.close()
