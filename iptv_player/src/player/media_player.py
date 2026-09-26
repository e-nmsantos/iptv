"""VLC-based media player for IPTV stream playback."""

import logging
import os
import socket
import sys
from pathlib import Path
from typing import Optional

import vlc
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

# Watchdog timing (polled every 500ms by _update_timer).
_LIVE_BUFFER_WATCHDOG_TICKS = 30     # ~15s of continuous VLC buffering -> retry
_LIVE_STALL_WATCHDOG_TICKS = 30      # ~15s of frozen picture while "Playing" -> retry
_STABLE_RESET_TICKS = 30             # ~15s of stable playback -> restore retry budget
_SEEK_TOLERANCE_MS = 2500
_MAX_SEEK_RETRIES = 6
_MAX_SUBTITLE_RETRIES = 6

# Port VLC serves the stream on for a Chromecast. VLC's default (8010) often
# falls inside ranges Windows reserves for Hyper-V/WSL, where binding fails
# with "Access denied" and casting silently does nothing.
CHROMECAST_HTTP_PORTS = (8010, 18010, 28010, 38010)


def pick_chromecast_http_port(candidates=CHROMECAST_HTTP_PORTS) -> int:
    """Return the first candidate port this machine lets us listen on."""
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("0.0.0.0", port))
            except OSError:
                continue
        return port
    return candidates[0]


class MediaPlayer(QObject):
    """
    Wrapper around python-vlc for IPTV stream playback.
    
    Features:
    - Play/Pause/Stop
    - Volume control
    - Stream buffering
    - Error handling
    - Hardware acceleration support
    """

    # Signals
    position_changed = Signal(float)  # 0.0 to 1.0
    time_changed = Signal(int)  # milliseconds
    length_changed = Signal(int)  # milliseconds
    state_changed = Signal(str)  # playing, paused, stopped, error
    error_occurred = Signal(str)
    media_ended = Signal()
    recording_state_changed = Signal(bool, str)  # is_recording, path
    stats_changed = Signal(dict)  # bitrate_kbps, dropped_frames, buffering_events

    def __init__(
        self,
        video_widget: Optional[QWidget] = None,
        vlc_path: str = "",
        buffer_size_ms: int = 5000,
        deinterlace: bool = True,
        normalize_audio: bool = True,
    ):
        super().__init__()
        self._video_widget = video_widget
        self._instance: Optional[vlc.Instance] = None
        self._player: Optional[vlc.MediaPlayer] = None
        self._dll_directory_handle = None
        self._current_url: str = ""
        self._is_playing = False
        self._volume = 80
        self._muted = False
        self._retry_count = 0
        self._max_retries = 12
        self._retrying = False
        self._retry_scheduled = False
        self._stable_playback_ticks = 0
        self._buffering_ticks = 0
        # Live stall watchdog state.
        self._live_has_advanced = False
        self._last_read_bytes = 0
        self._stall_ticks = 0
        self._current_headers: dict = {}
        self._current_is_live = False
        self._buffer_size_ms = max(300, min(10000, int(buffer_size_ms)))
        self._deinterlace = bool(deinterlace)
        self._normalize_audio = bool(normalize_audio)
        self._is_recording = False
        self._recording_path = ""
        self._buffering_events = 0
        self._pending_seek_ms: Optional[int] = None
        self._seek_retry_count = 0
        self._requested_subtitle_track: Optional[int] = None
        self._subtitle_retry_count = 0
        self._current_renderer = None
        self._active_cast_ip = None
        self._active_cast_sout = None

        # Auto-detect VLC installation path
        if not vlc_path:
            common_paths = [
                r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
            ]
            for path in common_paths:
                if os.path.isfile(path):
                    vlc_path = path
                    vlc_dir = os.path.dirname(path)
                    if vlc_dir not in os.environ.get("PATH", ""):
                        os.environ["PATH"] = vlc_dir + os.pathsep + os.environ.get("PATH", "")
                    break

        # Timer for position updates
        self._update_timer = QTimer()
        self._update_timer.setInterval(500)  # 500ms updates
        self._update_timer.timeout.connect(self._update_position)

        # Reopening an input inside the polling callback can create rapid
        # stop/start loops. Recover later on the Qt event loop instead.
        self._retry_timer = QTimer()
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._retry_current_stream)

        # Initialize VLC
        self._init_vlc(vlc_path)

    def _init_vlc(self, vlc_path: str = ""):
        """Initialize VLC instance with appropriate options."""
        cast_port = pick_chromecast_http_port()
        logger.info("Chromecast HTTP port: %d", cast_port)
        vlc_args = [
            "--no-xlib",
            "--quiet",
            "--no-video-title-show",
            f"--network-caching={self._buffer_size_ms}",
            f"--live-caching={self._buffer_size_ms}",
            f"--file-caching={self._buffer_size_ms}",
            "--rtsp-tcp",
            "--http-reconnect",
            # IPTV sources send irregular PCR/timestamps; the default clock
            # sync treats that jitter as a desync and stalls the picture.
            # Disabling it and widening the bitrate-averaging window is the
            # standard VLC fix for network streams that "freeze" a lot.
            "--clock-synchro=0",
            "--cr-average=1000",
            f"--sout-chromecast-http-port={cast_port}",
        ]
        if getattr(self, "_normalize_audio", True):
            vlc_args.extend(["--audio-filter=normvol", "--norm-max-level=2.0"])

        try:
            if vlc_path and os.path.isfile(vlc_path):
                vlc_path_dir = os.path.dirname(vlc_path)
                if vlc_path_dir:
                    os.environ["PATH"] = vlc_path_dir + os.pathsep + os.environ.get("PATH", "")
                    if sys.platform.startswith("win") and hasattr(os, "add_dll_directory"):
                        if self._dll_directory_handle is not None:
                            self._dll_directory_handle.close()
                        self._dll_directory_handle = os.add_dll_directory(vlc_path_dir)
                self._instance = vlc.Instance(vlc_args)
            else:
                self._instance = vlc.Instance(vlc_args)
        except Exception as e:
            logger.warning("VLC initialization warning: %s", e)
            try:
                self._instance = vlc.Instance(["--quiet", "--no-video-title-show"])
            except Exception:
                try:
                    self._instance = vlc.Instance()
                except Exception as e3:
                    raise RuntimeError(f"Failed to initialize VLC: {e3}") from e3

        if self._instance:
            self._player = self._instance.media_player_new()
            if self._video_widget:
                self._embed_video_widget(self._video_widget)

    def _embed_video_widget(self, widget: QWidget):
        """Bind the VLC video output to a Qt widget for the current platform."""
        window_id = int(widget.winId())
        if sys.platform.startswith("win"):
            self._player.set_hwnd(window_id)
        elif sys.platform == "darwin":
            self._player.set_nsobject(window_id)
        else:
            self._player.set_xwindow(window_id)

    def set_video_widget(self, widget: QWidget):
        """Set the video output widget."""
        self._video_widget = widget
        if self._player:
            self._embed_video_widget(widget)

    def set_deinterlace(self, enabled: bool, mode: str = "yadif"):
        """Enable or disable deinterlacing at runtime."""
        self._deinterlace = bool(enabled)
        if self._player:
            try:
                self._player.video_set_deinterlace(mode if enabled else "")
            except Exception:
                pass

    def is_deinterlace_enabled(self) -> bool:
        return self._deinterlace

    def is_normalize_audio_enabled(self) -> bool:
        return self._normalize_audio

    @property
    def vlc_instance(self) -> Optional[vlc.Instance]:
        """Return the underlying VLC Instance (for casting and renderer discovery)."""
        return self._instance

    def set_renderer(self, renderer_item) -> bool:
        """Direct playback output to a Chromecast / DLNA renderer."""
        if not (self._player and renderer_item):
            return False
        if not self._apply_renderer(renderer_item):
            return False
        self._current_renderer = renderer_item
        return True

    def clear_renderer(self) -> bool:
        """Reset playback output to the local PC display."""
        if not self._player:
            return False
        had_renderer = getattr(self, "_current_renderer", None) is not None
        self._current_renderer = None
        return self._apply_renderer(None) if had_renderer else True

    def _apply_renderer(self, renderer_item) -> bool:
        """Switch VLC's output and reopen the current stream so it takes effect.

        libVLC only honours set_renderer() before playback starts; on media that
        is already playing it returns success but keeps rendering locally.
        """
        # Reopening restarts the input, so carry over what the user had chosen.
        resume_ms = None
        if not self._current_is_live:
            try:
                resume_ms = int(self._player.get_time())
            except Exception:
                resume_ms = None
        subtitle_track = self._requested_subtitle_track
        if subtitle_track is None:
            current = self.get_subtitle_track()
            subtitle_track = current if current > 0 else None
        subtitle_file = getattr(self, "_external_subtitle_path", None)

        try:
            self._player.stop()
            res = self._player.set_renderer(renderer_item)
        except Exception as ex:
            logger.warning("Failed to set renderer: %s", ex)
            return False
        logger.info("Set renderer on VLC player (%s), result=%s", bool(renderer_item), res)
        if res != 0:
            return False
        if self._current_url:
            self.play(
                url=self._current_url,
                custom_headers=self._current_headers,
                is_live=self._current_is_live,
            )
            if subtitle_file:
                self.add_subtitle_file(subtitle_file)
            elif subtitle_track is not None:
                self.set_subtitle_track(subtitle_track)
            if resume_ms and resume_ms > 1000:
                self.set_time(resume_ms)
        return True

    def get_renderer(self):
        """Return the currently attached VLC renderer, if any."""
        return getattr(self, "_current_renderer", None)

    def has_renderer(self) -> bool:
        """Return True if playback is currently directed to a renderer."""
        return getattr(self, "_current_renderer", None) is not None

    def set_cast_target(self, host_ip: str) -> bool:
        """Stream playback directly to a Chromecast via VLC sout."""
        clean_ip = host_ip.split(":")[0].strip()
        if not clean_ip:
            return False
        self._active_cast_ip = clean_ip
        self._active_cast_sout = f":sout=#chromecast{{ip={clean_ip}}}"
        logger.info("Directing playback to Chromecast at %s", clean_ip)
        if self._current_url and self._player:
            self.play(
                url=self._current_url,
                custom_headers=self._current_headers,
                is_live=self._current_is_live,
                extra_sout=self._active_cast_sout,
            )
        return True

    def clear_cast_target(self) -> bool:
        """Return playback from Chromecast back to local PC screen."""
        if not getattr(self, "_active_cast_sout", None):
            return False
        self._active_cast_ip = None
        self._active_cast_sout = None
        logger.info("Cleared Chromecast cast target, returning to local display")
        if self._current_url and self._player:
            self.play(
                url=self._current_url,
                custom_headers=self._current_headers,
                is_live=self._current_is_live,
            )
        return True

    def is_casting_active(self) -> bool:
        return bool(getattr(self, "_active_cast_sout", None))

    def play(
        self,
        url: str = "",
        custom_headers: Optional[dict] = None,
        is_live: bool = False,
        extra_sout: Optional[str] = None,
    ):
        """
        Play a media URL.

        Args:
            url: Stream URL to play. Empty string resumes current media.
            custom_headers: Optional HTTP headers for the stream.
            extra_sout: Optional raw VLC `:sout=...` input option, used to
                duplicate the live stream to a local recording file. VLC only
                applies sout chains when a Media is (re)opened, so toggling
                a recording re-plays the current URL with/without this set.
        """
        if not self._player:
            self._on_error("Player not initialized")
            return

        if url:
            if url != self._current_url:
                # A subtitle file belongs to the item it was loaded for.
                self._external_subtitle_path = None
            self._current_url = url
            if not self._retrying:
                self._retry_scheduled = False
                self._retry_count = 0
                self._stable_playback_ticks = 0
                self._buffering_ticks = 0
                self._buffering_events = 0
                self._live_has_advanced = False
                self._last_read_bytes = 0
                self._stall_ticks = 0
                self._current_headers = dict(custom_headers or {})
                self._current_is_live = bool(is_live)
                self._pending_seek_ms = None
                self._seek_retry_count = 0
                self._requested_subtitle_track = None
                self._subtitle_retry_count = 0

            # Create media with custom headers if needed
            try:
                headers = custom_headers if custom_headers is not None else self._current_headers
                options = []
                if headers:
                    # Build VLC input options for headers.
                    for key, value in headers.items():
                        normalized_key = key.lower()
                        if normalized_key == "user-agent":
                            options.append(f":http-user-agent={value}")
                        elif normalized_key in ("referer", "referrer"):
                            options.append(f":http-referrer={value}")
                        elif normalized_key == "cookie":
                            options.append(f":http-cookie={value}")

                if url.lower().startswith(("http://", "https://")):
                    cache_ms = self._effective_cache_ms()
                    options.extend([":http-reconnect", f":network-caching={cache_ms}"])
                    if self._current_is_live:
                        # Continuous mode is appropriate for endless broadcasts,
                        # but prevents reliable HTTP range seeking in VOD/episodes.
                        options.extend([":http-continuous", f":live-caching={cache_ms}"])
                    else:
                        options.append(f":file-caching={cache_ms}")

                # Keep an active Chromecast sout across channel changes.
                sout = extra_sout or getattr(self, "_active_cast_sout", None)
                if sout:
                    options.append(sout)

                media = self._instance.media_new(url)
                for opt in (option for option in options if option):
                    media.add_option(opt)

                self._player.set_media(media)
            except Exception as e:
                self._on_error(f"Failed to load media: {e}")
                return

        # Play
        result = self._player.play()
        if result == -1:
            self._on_error("Failed to start playback")
            return

        self._is_playing = True
        self._update_timer.start()
        self.state_changed.emit("playing")

    def pause(self):
        """Toggle pause state."""
        if self._player and self._is_playing:
            self._player.pause()
            self._is_playing = False
            self.state_changed.emit("paused")

    def stop(self):
        """Stop playback."""
        self._update_timer.stop()
        retry_timer = getattr(self, "_retry_timer", None)
        if retry_timer:
            retry_timer.stop()
        self._retry_scheduled = False
        self._retrying = False
        if self._player:
            self._player.stop()
            self._is_playing = False
            self.state_changed.emit("stopped")

    def start_recording(self, output_path: str) -> bool:
        """Start duplicating the current live stream to a local file.

        Re-opens the current media with a VLC `sout=#duplicate{...}` chain,
        which causes a brief re-buffer — the same accepted tradeoff as a
        channel switch, not a bug.
        """
        if not self._current_url or self._is_recording:
            return False
        escaped_path = output_path.replace("\\", "/").replace(",", "\\,")
        sout_option = (
            f":sout=#duplicate{{s,dst=std{{access=file,mux=ts,dst={escaped_path}}}}}"
            ":sout-keep"
        )
        self._is_recording = True
        self._recording_path = output_path
        self.play(
            self._current_url, self._current_headers,
            is_live=self._current_is_live, extra_sout=sout_option,
        )
        self.recording_state_changed.emit(True, output_path)
        return True

    def stop_recording(self):
        """Stop the active recording by re-opening the media without sout."""
        if not self._is_recording:
            return
        self._is_recording = False
        path = self._recording_path
        self._recording_path = ""
        if self._current_url:
            self.play(self._current_url, self._current_headers, is_live=self._current_is_live)
        self.recording_state_changed.emit(False, path)

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def set_marquee_text(self, text: str):
        """Show a small on-screen text overlay via VLC's own OSD marquee.

        Used instead of a Qt child widget: on Windows the video widget is
        bound via set_hwnd(), so VLC paints directly into that native
        surface and a Qt overlay isn't reliably guaranteed to composite
        above it. The marquee is guaranteed to render on every platform.
        """
        if not self._player:
            return
        self._player.video_set_marquee_string(vlc.VideoMarqueeOption.Text, text)
        self._player.video_set_marquee_int(vlc.VideoMarqueeOption.Enable, 1)
        self._player.video_set_marquee_int(vlc.VideoMarqueeOption.Position, 8)  # bottom-right
        self._player.video_set_marquee_int(vlc.VideoMarqueeOption.Size, 14)
        self._player.video_set_marquee_int(vlc.VideoMarqueeOption.Opacity, 200)

    def clear_marquee(self):
        if self._player:
            self._player.video_set_marquee_int(vlc.VideoMarqueeOption.Enable, 0)

    def set_volume(self, volume: int):
        """Set volume (0-100)."""
        self._volume = max(0, min(100, volume))
        if self._player:
            self._player.audio_set_volume(self._volume)

    def toggle_mute(self) -> bool:
        """Toggle mute on/off; returns the new muted state."""
        self._muted = not self._muted
        if self._player:
            self._player.audio_set_mute(1 if self._muted else 0)
        return self._muted

    @property
    def is_muted(self) -> bool:
        """Whether the audio is currently muted."""
        return self._muted

    def set_buffer_size(self, buffer_size_ms: int):
        """Apply the cache size to subsequently opened media."""
        self._buffer_size_ms = max(300, min(10000, int(buffer_size_ms)))

    def _effective_cache_ms(self) -> int:
        """Live streams respect configured buffer setting with a sensible floor."""
        if self._current_is_live:
            return max(500, self._buffer_size_ms)
        return self._buffer_size_ms

    def reinitialize(self, vlc_path: str = "", buffer_size_ms: Optional[int] = None):
        """Recreate VLC so changed settings take effect immediately."""
        widget = self._video_widget
        volume = self._volume
        self.cleanup()
        if buffer_size_ms is not None:
            self.set_buffer_size(buffer_size_ms)
        self._init_vlc(vlc_path)
        if widget and self._player:
            self._embed_video_widget(widget)
        self.set_volume(volume)

    def get_volume(self) -> int:
        """Get current volume."""
        return self._volume

    def get_length(self) -> int:
        """Get media length in milliseconds (0 when unavailable)."""
        if self._player:
            try:
                return int(self._player.get_length())
            except Exception:
                return 0
        return 0

    def seek(self, position: float) -> bool:
        """Seek to a fraction of a finite item using an absolute timestamp.

        VLC's ``set_position`` is unreliable for HTTP VOD and may reopen the
        input at byte zero. Converting the fraction to milliseconds preserves
        normal HTTP range requests and also lets us verify that VLC applied it.
        """
        length = self.get_length()
        if not self._player or length <= 0 or self._current_is_live:
            return False
        fraction = max(0.0, min(1.0, float(position)))
        return self.set_time(round(length * fraction))

    def seek_relative(self, seconds: int) -> bool:
        """Seek relative to current position."""
        if not self._player or self._current_is_live:
            return False
        current_time = max(0, int(self._player.get_time()))
        return self.set_time(current_time + (seconds * 1000))

    def set_time(self, time_ms: int) -> bool:
        if not self._player or self._current_is_live:
            return False
        length = self.get_length()
        target = max(0, int(time_ms))
        if length > 0:
            target = min(target, max(0, length - 500))
        self._pending_seek_ms = target
        self._seek_retry_count = 0
        return self._apply_pending_seek()

    def _apply_pending_seek(self) -> bool:
        if not self._player or self._pending_seek_ms is None:
            return False
        result = self._player.set_time(self._pending_seek_ms)
        self._seek_retry_count += 1
        return result in (None, 0)

    @staticmethod
    def _track_descriptions(raw_tracks) -> list[tuple[int, str]]:
        tracks = []
        for track_id, label in raw_tracks or []:
            if isinstance(label, bytes):
                label = label.decode("utf-8", errors="replace")
            tracks.append((int(track_id), str(label or track_id)))
        return tracks

    def get_audio_tracks(self) -> list[tuple[int, str]]:
        if not self._player:
            return []
        return self._track_descriptions(self._player.audio_get_track_description())

    def set_audio_track(self, track_id: int) -> bool:
        return bool(self._player and self._player.audio_set_track(int(track_id)) == 0)

    def get_subtitle_tracks(self) -> list[tuple[int, str]]:
        if not self._player:
            return []
        # VLC exposes its synthetic "Disable" entry as track -1. The UI has a
        # dedicated action for it, so only return actual subtitle tracks here.
        return [
            track for track in self._track_descriptions(
                self._player.video_get_spu_description()
            ) if track[0] >= 0
        ]

    def get_subtitle_track(self) -> int:
        if not self._player:
            return -1
        try:
            return int(self._player.video_get_spu())
        except Exception:
            return -1

    def set_subtitle_track(self, track_id: int) -> bool:
        if not self._player:
            return False
        self._requested_subtitle_track = int(track_id)
        self._subtitle_retry_count = 0
        return self._apply_requested_subtitle()

    def _apply_requested_subtitle(self) -> bool:
        if not self._player or self._requested_subtitle_track is None:
            return False
        result = self._player.video_set_spu(self._requested_subtitle_track)
        self._subtitle_retry_count += 1
        return result in (None, 0)

    def add_subtitle_file(self, file_path: str) -> bool:
        if not self._player:
            return False
        resolved_path = str(Path(file_path).resolve())
        uri = Path(file_path).resolve().as_uri()
        added = False
        if hasattr(self._player, "video_set_subtitle_file"):
            try:
                res = self._player.video_set_subtitle_file(resolved_path)
                if res in (0, 1, True, None):
                    added = True
            except Exception as e:
                logger.debug("video_set_subtitle_file error: %s", e)
        if not added and hasattr(self._player, "add_slave"):
            try:
                added = self._player.add_slave(vlc.MediaSlaveType.subtitle, uri, True) == 0
            except Exception as e:
                logger.debug("add_slave error: %s", e)
        if added:
            self._external_subtitle_path = resolved_path
            self._requested_subtitle_track = None
            self._subtitle_retry_count = 0
            try:
                tracks = self._player.video_get_spu_description() or []
                if tracks:
                    last_id = tracks[-1][0]
                    if last_id > 0:
                        self._player.video_set_spu(last_id)
            except Exception:
                pass
        return added

    def set_subtitle_delay(self, delay_ms: int) -> bool:
        """Set subtitle synchronization offset in milliseconds."""
        self._subtitle_delay_ms = int(delay_ms)
        if not self._player:
            return False
        try:
            # LibVLC takes delay in microseconds (int64_t)
            ret = self._player.video_set_spu_delay(int(self._subtitle_delay_ms * 1000))
            return ret in (0, None)
        except Exception as e:
            logger.debug("video_set_spu_delay error: %s", e)
            return False

    def get_subtitle_delay(self) -> int:
        """Get current subtitle synchronization offset in milliseconds."""
        if self._player:
            try:
                vlc_delay = self._player.video_get_spu_delay()
                if vlc_delay is not None and vlc_delay != 0:
                    return int(vlc_delay / 1000)
            except Exception:
                pass
        return getattr(self, "_subtitle_delay_ms", 0)

    def set_night_mode(self, enabled: bool) -> None:
        """Enable speech clarity / night mode equalizer boost on vocal frequencies."""
        self._night_mode_enabled = bool(enabled)
        if self._player and hasattr(vlc, "AudioEqualizer"):
            try:
                eq = vlc.AudioEqualizer()
                if self._night_mode_enabled:
                    eq.set_amp_at_index(0, -4.0)
                    eq.set_amp_at_index(1, -2.0)
                    eq.set_amp_at_index(4, 3.0)
                    eq.set_amp_at_index(5, 5.0)
                    eq.set_amp_at_index(6, 4.0)
                self._player.set_equalizer(eq)
            except Exception:
                pass

    def is_night_mode_enabled(self) -> bool:
        return getattr(self, "_night_mode_enabled", False)

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    def _update_position(self):
        """Update position tracking (called by timer)."""
        if not self._player:
            return

        state = self._player.get_state()
        if state == vlc.State.Ended:
            if self._current_is_live:
                self._on_error("A transmissão Live foi interrompida")
                return
            self.stop()
            self.media_ended.emit()
            return
        elif state == vlc.State.Error:
            self._on_error("Playback error occurred")
            return
        elif state == vlc.State.Playing:
            self._is_playing = True
            self._buffering_ticks = 0
            self._stable_playback_ticks += 1
            # The retry budget belongs to one interruption. Restore it after
            # 15 seconds of stable playback so a long-running channel can
            # recover again later.
            if self._stable_playback_ticks >= _STABLE_RESET_TICKS:
                self._retry_count = 0
                self._stable_playback_ticks = _STABLE_RESET_TICKS

            # Live sources can stall silently (connection stays open but no
            # new data arrives). VLC keeps reporting "Playing" on a frozen
            # picture, so a byte-based watchdog catches it where the state
            # machine cannot.
            if self._current_is_live and self._update_live_stall_detection():
                return
        elif state == vlc.State.Buffering:
            self._stable_playback_ticks = 0
            if self._buffering_ticks == 0:
                self._buffering_events += 1
            self._buffering_ticks += 1
            self.state_changed.emit("buffering")
            # Recover from a prolonged VLC buffering state. MPEG-TS playback
            # timestamps are deliberately not used as a watchdog: many healthy
            # Live sources legitimately keep them at zero.
            if self._current_is_live and self._buffering_ticks >= _LIVE_BUFFER_WATCHDOG_TICKS:
                self._on_error("A transmissão ficou sem dados")
                return
        else:
            self._stable_playback_ticks = 0

        # Emit position updates
        length = self._player.get_length()
        position = self._player.get_position()
        current_time = self._player.get_time()

        if self._pending_seek_ms is not None and current_time >= 0:
            if abs(current_time - self._pending_seek_ms) <= _SEEK_TOLERANCE_MS:
                self._pending_seek_ms = None
                self._seek_retry_count = 0
            elif (
                state in (vlc.State.Playing, vlc.State.Paused)
                and self._seek_retry_count < _MAX_SEEK_RETRIES
            ):
                self._apply_pending_seek()

        if (
            self._requested_subtitle_track is not None
            and state == vlc.State.Playing
        ):
            selected = self.get_subtitle_track()
            if selected == self._requested_subtitle_track:
                self._subtitle_retry_count = 0
            elif self._subtitle_retry_count < _MAX_SUBTITLE_RETRIES:
                # VLC can recreate SPU tracks while the decoder starts. Reapply
                # the user's selection until the active track confirms it.
                self._apply_requested_subtitle()

        if length > 0:
            self.length_changed.emit(length)
        if position >= 0:
            self.position_changed.emit(position)
        if current_time >= 0:
            self.time_changed.emit(current_time)

        self._poll_stats()

    def _poll_stats(self):
        """Emit a compact health snapshot (bitrate/dropped frames/buffering)."""
        media = self._player.get_media() if self._player else None
        if not media:
            return
        stats = vlc.MediaStats()
        if not media.get_stats(stats):
            return
        self.stats_changed.emit({
            "bitrate_kbps": round((stats.demux_bitrate or 0.0) * 8, 0),
            "dropped_frames": int(stats.lost_pictures or 0),
            "buffering_events": self._buffering_events,
        })

    def _update_live_stall_detection(self) -> bool:
        """Detect a live picture frozen while VLC still reports 'Playing'.

        Many IPTV sources stall silently (the server keeps the connection
        open but stops sending data), so VLC never transitions to Buffering
        or Error and the normal watchdog never fires. We use the input byte
        counter instead: while the stream really is playing, VLC keeps reading
        bytes from the network, so `read_bytes` grows; a picture frozen on its
        last frame has a flat counter.

        Returns True when a stall was detected and recovery was scheduled.
        """
        media = self._player.get_media() if self._player else None
        if not media:
            return False
        stats = vlc.MediaStats()
        if not media.get_stats(stats):
            return False

        current_bytes = int(getattr(stats, "read_bytes", 0) or 0)
        if not self._live_has_advanced:
            # Arm the watchdog only after we have seen the stream advance, so
            # the very first frames of a new stream can't false-trigger it.
            if current_bytes > self._last_read_bytes:
                self._live_has_advanced = True
                self._last_read_bytes = current_bytes
            return False

        if current_bytes > self._last_read_bytes:
            self._stall_ticks = 0
            self._last_read_bytes = current_bytes
            return False

        self._stall_ticks += 1
        if self._stall_ticks >= _LIVE_STALL_WATCHDOG_TICKS:
            logger.warning("Live stream picture stalled; recovering")
            self._on_error("A transmissão parou (imagem congelada)")
            return True
        return False

    def _on_error(self, message: str):
        """Handle playback errors."""
        self._update_timer.stop()
        self._is_playing = False

        if getattr(self, "_retry_scheduled", False):
            return

        if (
            not self._current_is_live
            and self._player
            and getattr(self, "_pending_seek_ms", None) is None
        ):
            current_time = max(0, int(self._player.get_time()))
            if current_time >= 10_000:
                self._pending_seek_ms = current_time
                self._seek_retry_count = 0

        max_retries = 12 if self._current_is_live else self._max_retries
        if self._retry_count < max_retries and self._current_url:
            self._retry_count += 1
            delay_ms = min(8000, 1000 * (2 ** min(self._retry_count - 1, 3)))
            logger.warning(
                "Retrying playback (%s/%s) in %s ms",
                self._retry_count,
                max_retries,
                delay_ms,
            )
            self._retry_scheduled = True
            self.state_changed.emit("reconnecting")
            retry_timer = getattr(self, "_retry_timer", None)
            if retry_timer:
                retry_timer.start(delay_ms)
            else:
                # Compatibility for lightweight/headless player instances.
                self._retry_current_stream()
        else:
            self.state_changed.emit("error")
            self.error_occurred.emit(message)

    def _retry_current_stream(self):
        """Rebuild the current VLC media after a real input failure."""
        self._retry_scheduled = False
        if not self._current_url or not self._player:
            return
        self._retrying = True
        self._stable_playback_ticks = 0
        self._buffering_ticks = 0
        self._live_has_advanced = False
        self._last_read_bytes = 0
        self._stall_ticks = 0
        try:
            if hasattr(self._player, "stop"):
                self._player.stop()
            self.play(
                self._current_url,
                self._current_headers,
                is_live=self._current_is_live,
            )
        finally:
            self._retrying = False

    def get_current_state(self) -> str:
        """Get current player state as string."""
        if not self._player:
            return "stopped"
        state = self._player.get_state()
        state_map = {
            vlc.State.NothingSpecial: "idle",
            vlc.State.Opening: "opening",
            vlc.State.Buffering: "buffering",
            vlc.State.Playing: "playing",
            vlc.State.Paused: "paused",
            vlc.State.Stopped: "stopped",
            vlc.State.Ended: "ended",
            vlc.State.Error: "error",
        }
        return state_map.get(state, "unknown")

    def cleanup(self):
        """Clean up VLC resources."""
        self.stop()
        if self._player:
            self._player.release()
        if self._instance:
            self._instance.release()
        self._player = None
        self._instance = None
        if self._dll_directory_handle is not None:
            self._dll_directory_handle.close()
            self._dll_directory_handle = None
