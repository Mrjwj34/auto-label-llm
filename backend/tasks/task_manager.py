from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable
from uuid import uuid4

from concurrent.futures import Future, ThreadPoolExecutor


TaskFn = Callable[["TaskContext"], Any]


@dataclass
class TaskState:
    id: str
    status: str  # PENDING|STARTED|SUCCESS|FAILURE
    progress: int
    message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TaskContext:
    def __init__(self, manager: "TaskManager", task_id: str):
        self._manager = manager
        self.task_id = task_id

    def set_progress(self, progress: int, message: str | None = None) -> None:
        p = max(0, min(100, int(progress)))
        self._manager._update(self.task_id, progress=p, message=message)


class TaskManager:
    def __init__(self, max_workers: int = 4):
        self._lock = Lock()
        self._states: dict[str, TaskState] = {}
        self._futures: dict[str, Future[Any]] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tasks")

    def create(self, fn: TaskFn) -> str:
        task_id = uuid4().hex
        with self._lock:
            self._states[task_id] = TaskState(id=task_id, status="PENDING", progress=0)

        ctx = TaskContext(self, task_id)
        fut = self._executor.submit(self._run, task_id, fn, ctx)
        with self._lock:
            self._futures[task_id] = fut
        return task_id

    def get(self, task_id: str) -> TaskState | None:
        with self._lock:
            st = self._states.get(task_id)
            if st is None:
                return None
            return TaskState(**asdict(st))

    def to_dict(self, task_id: str) -> dict[str, Any] | None:
        st = self.get(task_id)
        if st is None:
            return None
        return {
            "task_id": st.id,
            "status": st.status,
            "progress": st.progress,
            "message": st.message,
        }

    def _update(self, task_id: str, *, status: str | None = None, progress: int | None = None, message: str | None = None):
        with self._lock:
            st = self._states.get(task_id)
            if st is None:
                return
            if status is not None:
                st.status = status
                if status == "STARTED" and st.started_at is None:
                    st.started_at = datetime.now(timezone.utc)
                if status in ("SUCCESS", "FAILURE"):
                    st.finished_at = datetime.now(timezone.utc)
            if progress is not None:
                st.progress = max(0, min(100, int(progress)))
            if message is not None:
                st.message = message

    def _run(self, task_id: str, fn: TaskFn, ctx: TaskContext) -> None:
        self._update(task_id, status="STARTED", progress=0)
        try:
            fn(ctx)
            self._update(task_id, status="SUCCESS", progress=100)
        except Exception as exc:  # noqa: BLE001
            self._update(task_id, status="FAILURE", message=str(exc))


_manager: TaskManager | None = None


def get_task_manager() -> TaskManager:
    global _manager
    if _manager is None:
        _manager = TaskManager(max_workers=4)
    return _manager
