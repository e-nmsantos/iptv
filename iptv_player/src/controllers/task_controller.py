"""Concurrency limits and worker ownership for Qt background tasks."""

import threading


class TaskController:
    def __init__(self, max_connections: int):
        self.workers: list = []
        self.configure(max_connections)

    def configure(self, max_connections: int) -> None:
        self._semaphore = threading.BoundedSemaphore(max(1, int(max_connections)))

    def execute(self, task):
        with self._semaphore:
            return task()

    def add(self, worker) -> None:
        self.workers.append(worker)

    def remove(self, worker) -> None:
        if worker in self.workers:
            self.workers.remove(worker)

    def running(self) -> list:
        return [worker for worker in self.workers if worker.isRunning()]

    def cancel_all(self) -> None:
        for worker in self.running():
            worker.requestInterruption()
