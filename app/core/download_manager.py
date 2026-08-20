"""Queue + concurrency control for DownloadTask instances."""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QObject, Signal

from app.core.download_task import DownloadTask, TaskStatus
from app.core.settings import AppSettings


class DownloadManager(QObject):
    task_added = Signal(str)      # task_id
    task_updated = Signal(str)    # task_id
    task_finished = Signal(str)   # task_id

    def __init__(self, settings: AppSettings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._tasks: dict[str, DownloadTask] = {}
        self._order: list[str] = []
        self._waiting: deque[str] = deque()

    # ----------------------------------------------------------- accessors

    def tasks(self) -> list[DownloadTask]:
        return [self._tasks[tid] for tid in self._order if tid in self._tasks]

    def get(self, task_id: str) -> DownloadTask | None:
        return self._tasks.get(task_id)

    def active_count(self) -> int:
        return sum(
            1 for t in self._tasks.values() if t.state.status == TaskStatus.RUNNING
        )

    # ------------------------------------------------------------- enqueue

    def add(self, task: DownloadTask) -> str:
        task.updated.connect(self._on_updated)
        task.finished.connect(self._on_finished)
        self._tasks[task.state.task_id] = task
        self._order.append(task.state.task_id)
        self._waiting.append(task.state.task_id)
        self.task_added.emit(task.state.task_id)
        self._pump()
        return task.state.task_id

    def pause(self, task_id: str) -> None:
        t = self._tasks.get(task_id)
        if t and t.state.status == TaskStatus.RUNNING:
            t.pause()
            # A slot opened, launch next.
            self._pump()

    def resume(self, task_id: str) -> None:
        t = self._tasks.get(task_id)
        if not t or t.state.status not in (TaskStatus.PAUSED, TaskStatus.FAILED):
            return
        t.state.status = TaskStatus.QUEUED
        if task_id not in self._waiting:
            self._waiting.append(task_id)
        self._pump()

    def cancel(self, task_id: str) -> None:
        t = self._tasks.get(task_id)
        if not t:
            return
        try:
            self._waiting.remove(task_id)
        except ValueError:
            pass
        t.cancel()
        self._pump()

    def remove(self, task_id: str) -> None:
        self.cancel(task_id)
        self._tasks.pop(task_id, None)
        try:
            self._order.remove(task_id)
        except ValueError:
            pass

    def clear_finished(self) -> None:
        gone = [
            tid for tid, t in self._tasks.items()
            if t.state.status in (TaskStatus.DONE, TaskStatus.CANCELED, TaskStatus.FAILED)
        ]
        for tid in gone:
            self._tasks.pop(tid, None)
            try:
                self._order.remove(tid)
            except ValueError:
                pass

    # -------------------------------------------------------------- pump

    def _pump(self) -> None:
        while self.active_count() < self._settings.max_concurrent and self._waiting:
            tid = self._waiting.popleft()
            t = self._tasks.get(tid)
            if not t:
                continue
            if t.state.status in (TaskStatus.QUEUED, TaskStatus.PAUSED):
                t.start()

    # ------------------------------------------------------------ slots

    def _on_updated(self, task_id: str) -> None:
        self.task_updated.emit(task_id)

    def _on_finished(self, task_id: str) -> None:
        self.task_finished.emit(task_id)
        self._pump()
