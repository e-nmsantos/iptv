"""Qt worker primitives shared by background application services."""

from typing import Callable

from PySide6.QtCore import QThread, Signal


class TaskWorker(QThread):
    """Run one callable and expose result, failure and progress signals."""

    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(str)

    def __init__(self, task: Callable, *args, **kwargs):
        super().__init__()
        self._task = task
        self._args = args
        self._kwargs = kwargs

    def run(self):
        if self.isInterruptionRequested():
            self.cancelled.emit()
            return
        try:
            result = self._task(*self._args, **self._kwargs)
            if self.isInterruptionRequested():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)
        except Exception as exc:
            if self.isInterruptionRequested():
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc))


def report_progress(message: str):
    """Emit progress from code currently running inside a TaskWorker."""
    worker = QThread.currentThread()
    if isinstance(worker, TaskWorker):
        worker.progress.emit(message)
