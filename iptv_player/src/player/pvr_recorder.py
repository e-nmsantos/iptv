"""PVR Background stream recording engine for IPTV Player."""

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import requests

from ..utils.helpers import sanitize_filename

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
    ):
        self.stream_url = stream_url
        self.output_file = output_file
        self.duration_seconds = duration_seconds
        self.headers = headers or {}
        self.on_progress = on_progress
        self.on_complete = on_complete

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
        return time.time() - self._start_time

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
        if self._thread:
            self._thread.join(timeout=2.0)

    def _record_worker(self) -> None:
        self._start_time = time.time()
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        success = False
        error_msg = ""

        try:
            req_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) IPTVPlayer-PVR/1.0",
                **self.headers,
            }
            with requests.get(
                self.stream_url,
                headers=req_headers,
                stream=True,
                timeout=15,
            ) as response:
                response.raise_for_status()
                with open(self.output_file, "wb") as f:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if self._stop_event.is_set():
                            break
                        if chunk:
                            f.write(chunk)
                            self._bytes_written += len(chunk)
                            if self.on_progress:
                                self.on_progress(self._bytes_written, self.elapsed_seconds)

                        if self.duration_seconds > 0 and self.elapsed_seconds >= self.duration_seconds:
                            break
                success = True
        except Exception as e:
            error_msg = str(e)
            logger.warning("PVR recording error: %s", e)

        if self.on_complete:
            self.on_complete(success, error_msg)


class PvrRecorderManager:
    """Manages scheduled and instant background recordings."""

    def __init__(self, default_output_dir: Optional[Path] = None):
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
        )
        session.start()
        self._active_sessions.append(session)
        return session

    def stop_all(self) -> None:
        for s in self._active_sessions:
            s.stop()
        self._active_sessions.clear()

