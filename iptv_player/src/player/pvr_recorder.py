"""PVR Background stream recording engine for IPTV Player."""

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from ..utils.helpers import sanitize_filename
from .recording_engine import record_stream

logger = logging.getLogger(__name__)


class RecordingSession:
    """Manages an active background stream recording."""

    def __init__(
        self,
        stream_url: str,
        output_file: Path,
        duration_seconds: int = 0,
        headers: Optional[dict] = None,
        on_progress: Optional[Callable[[int, float], None]] = None,
        on_complete: Optional[Callable[[bool, str], None]] = None,
        on_started: Optional[Callable[[], None]] = None,
    ):
        self.stream_url = stream_url
        self.output_file = output_file
        self.duration_seconds = duration_seconds
        self.headers = headers or {}
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.on_started = on_started

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._bytes_written = 0
        self._start_time: float = 0.0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def bytes_written(self) -> int:
        return self._bytes_written

    @property
    def elapsed_seconds(self) -> float:
        if self._start_time <= 0:
            return 0.0
        return time.monotonic() - self._start_time

    def start(self) -> None:
        """Start capturing the stream in a background thread."""
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._record_worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the recording thread to finish gracefully."""
        self._stop_event.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)

    def _record_worker(self) -> None:
        self._start_time = time.monotonic()
        success = False
        error_msg = ""
        try:
            record_stream(self)
            success = True
        except Exception as exc:
            error_msg = str(exc) if isinstance(exc, RuntimeError) else "Não foi possível gravar o canal. Verifica a ligação e a pasta de gravações."
            logger.warning("PVR recording failed (%s)", type(exc).__name__)
        finally:
            try:
                self._bytes_written = self.output_file.stat().st_size if self.output_file.exists() else 0
                if not self._bytes_written:
                    self.output_file.unlink(missing_ok=True)
                    success = False
                    error_msg = error_msg or "Não foram recebidos dados de vídeo."
            except OSError:
                success = False
                error_msg = "Não foi possível verificar o ficheiro gravado."
            if self.on_complete:
                self.on_complete(success, error_msg)


class PvrRecorderManager(QObject):
    """Manages scheduled and instant background recordings."""

    recording_started = Signal(str)
    recording_finished = Signal(str, bool, str)

    def __init__(self, default_output_dir: Optional[Path] = None):
        super().__init__()
        if default_output_dir is None:
            default_output_dir = Path.home() / "Videos" / "IPTV Recordings"
        self.output_dir = Path(default_output_dir)
        self._active_sessions: list[RecordingSession] = []

    def start_recording(
        self,
        channel_name: str,
        stream_url: str,
        duration_seconds: int = 0,
        headers: Optional[dict] = None,
    ) -> RecordingSession:
        """Create and start a new background recording session."""
        self._active_sessions = [
            session for session in self._active_sessions
            if session._thread is None or session.is_running
        ]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_name = sanitize_filename(channel_name) or "stream"
        out_path = self.output_dir / f"{safe_name}_{timestamp}.ts"
        taken = {s.output_file for s in self._active_sessions}
        suffix = 1
        while out_path in taken or out_path.exists():
            out_path = self.output_dir / f"{safe_name}_{timestamp}_{suffix}.ts"
            suffix += 1

        session = RecordingSession(
            stream_url=stream_url,
            output_file=out_path,
            duration_seconds=duration_seconds,
            headers=headers,
            on_started=lambda: self.recording_started.emit(channel_name),
            on_complete=lambda ok, message: self.recording_finished.emit(channel_name, ok, message),
        )
        self._active_sessions.append(session)
        session.start()
        return session

    def stop_all(self) -> None:
        for s in self._active_sessions:
            s.stop()
        self._active_sessions.clear()

