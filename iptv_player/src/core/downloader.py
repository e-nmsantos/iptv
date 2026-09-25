"""Asynchronous chunked VOD download manager with resume support."""

import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


@dataclass
class DownloadTask:
    task_id: str
    title: str
    url: str
    target_path: Path
    headers: dict[str, str]
    total_bytes: int = 0
    downloaded_bytes: int = 0
    speed_bps: float = 0.0
    status: str = "pending"  # pending, downloading, paused, completed, error
    error_message: str = ""
    _stop_event: Optional[threading.Event] = None
    _thread: Optional[threading.Thread] = None


class VODDownloader(QObject):
    """Global manager for offline VOD downloads."""

    progress_updated = Signal(str, int, int, float)  # task_id, downloaded, total, speed_bps
    task_completed = Signal(str, str)  # task_id, file_path
    task_failed = Signal(str, str)  # task_id, error_message
    task_status_changed = Signal(str, str)  # task_id, status

    _instance: Optional["VODDownloader"] = None

    @classmethod
    def get_instance(cls, download_dir: Optional[Path] = None) -> "VODDownloader":
        if cls._instance is None:
            cls._instance = VODDownloader(download_dir)
        return cls._instance

    def __init__(self, download_dir: Optional[Path] = None):
        super().__init__()
        if download_dir is None:
            download_dir = Path.home() / "Downloads" / "IPTV Downloads"
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, DownloadTask] = {}
        self._lock = threading.Lock()

    def list_tasks(self) -> list[DownloadTask]:
        with self._lock:
            return list(self._tasks.values())

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def start_download(
        self,
        title: str,
        url: str,
        headers: Optional[dict[str, str]] = None,
        custom_folder: Optional[Path] = None,
    ) -> DownloadTask:
        """Start or enqueue a new video download."""
        safe_name = re.sub(r'[\W_]+', '_', title).strip('_') or "video"

        # Determine extension from url or default to .mp4
        ext = ".mp4"
        if ".mkv" in url.lower():
            ext = ".mkv"
        elif ".avi" in url.lower():
            ext = ".avi"
        elif ".ts" in url.lower():
            ext = ".ts"

        folder = custom_folder or self.download_dir
        folder.mkdir(parents=True, exist_ok=True)

        with self._lock:
            existing_paths = {t.target_path for t in self._tasks.values() if t.status != "cancelled"}
            base_target = folder / f"{safe_name}{ext}"
            target_path = base_target
            counter = 1
            while target_path in existing_paths or target_path.exists():
                target_path = folder / f"{safe_name}_{counter}{ext}"
                counter += 1

            task_id = f"{safe_name}_{int(time.time())}_{counter}"
            task = DownloadTask(
                task_id=task_id,
                title=title,
                url=url,
                target_path=target_path,
                headers=headers or {},
                _stop_event=threading.Event(),
            )
            self._tasks[task_id] = task

        thread = threading.Thread(
            target=self._download_worker, args=(task,), daemon=True
        )
        task._thread = thread
        thread.start()
        return task

    def pause_download(self, task_id: str):
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.status == "downloading" and task._stop_event:
                task.status = "paused"
                task._stop_event.set()
                self.task_status_changed.emit(task_id, "paused")

    def resume_download(self, task_id: str):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.status not in ("paused", "error"):
                return

            if task._thread and task._thread.is_alive():
                if task._stop_event:
                    task._stop_event.set()
                task._thread.join(timeout=2.0)
                if task._thread.is_alive():
                    logger.warning("Previous download thread still terminating for task %s", task_id)
                    return

            task.status = "pending"
            task.error_message = ""
            task._stop_event = threading.Event()
            thread = threading.Thread(
                target=self._download_worker, args=(task,), daemon=True
            )
            task._thread = thread
            thread.start()
            self.task_status_changed.emit(task_id, "pending")

    def cancel_download(self, task_id: str, delete_file: bool = True):
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                if task._stop_event:
                    task._stop_event.set()
                task.status = "cancelled"
                self.task_status_changed.emit(task_id, "cancelled")
                if delete_file and task.target_path.exists():
                    try:
                        task.target_path.unlink()
                    except Exception as e:
                        logger.warning(f"Failed to delete cancelled file: {e}")

    def _download_worker(self, task: DownloadTask):
        task.status = "downloading"
        self.task_status_changed.emit(task.task_id, "downloading")

        # Check existing file size for resume
        existing_size = 0
        if task.target_path.exists():
            existing_size = task.target_path.stat().st_size
            task.downloaded_bytes = existing_size

        req_headers = dict(task.headers)
        if existing_size > 0:
            req_headers["Range"] = f"bytes={existing_size}-"

        try:
            resp = requests.get(
                task.url,
                headers=req_headers,
                stream=True,
                timeout=15,
            )

            if resp.status_code not in (200, 206):
                raise RuntimeError(f"HTTP {resp.status_code} {resp.reason}")

            content_len = resp.headers.get("Content-Length")
            if content_len:
                if resp.status_code == 206:
                    task.total_bytes = existing_size + int(content_len)
                else:
                    task.total_bytes = int(content_len)
                    existing_size = 0

            mode = "ab" if resp.status_code == 206 else "wb"
            chunk_size = 64 * 1024  # 64 KB

            bytes_since_last_tick = 0
            last_tick_time = time.time()

            with open(task.target_path, mode) as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if task._stop_event and task._stop_event.is_set():
                        return

                    if chunk:
                        f.write(chunk)
                        task.downloaded_bytes += len(chunk)
                        bytes_since_last_tick += len(chunk)

                        now = time.time()
                        elapsed = now - last_tick_time
                        if elapsed >= 0.5:
                            task.speed_bps = bytes_since_last_tick / elapsed
                            bytes_since_last_tick = 0
                            last_tick_time = now
                            self.progress_updated.emit(
                                task.task_id,
                                task.downloaded_bytes,
                                task.total_bytes,
                                task.speed_bps,
                            )

            task.status = "completed"
            task.speed_bps = 0
            self.task_status_changed.emit(task.task_id, "completed")
            self.task_completed.emit(task.task_id, str(task.target_path))

        except Exception as exc:
            if task._stop_event and task._stop_event.is_set():
                return
            task.status = "error"
            task.error_message = str(exc)
            logger.error(f"Download failed for {task.title}: {exc}")
            self.task_status_changed.emit(task.task_id, "error")
            self.task_failed.emit(task.task_id, str(exc))

