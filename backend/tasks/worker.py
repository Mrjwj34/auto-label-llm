from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from backend.config import get_settings
from backend.database import get_session_factory
from backend.models.image import Image
from backend.tasks.task_manager import TERMINAL_TASK_STATES, TaskContext, TaskEnvelope, get_task_manager


TaskHandler = Callable[[TaskContext, dict], None]


class RedisTaskWorker:
    def __init__(self, *, handlers: dict[str, TaskHandler], queues: list[str] | None = None, concurrency: int | None = None):
        settings = get_settings()
        self._manager = get_task_manager()
        self._handlers = handlers
        self._queues = queues or ["annotation", "evaluation", "finetune"]
        self._concurrency = max(1, int(concurrency or settings.task_worker_concurrency))
        self._stop_event = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=self._concurrency, thread_name_prefix="redis-task-worker")
        self._thread: threading.Thread | None = None

    def start_in_background(self) -> "RedisTaskWorker":
        if self._thread is not None and self._thread.is_alive():
            return self
        self._thread = threading.Thread(target=self.run_forever, name="redis-task-dispatcher", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self._executor.shutdown(wait=True, cancel_futures=False)

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            envelope = self._manager.dequeue(self._queues, timeout=1.0)
            if envelope is None:
                continue
            self._executor.submit(self._run_one, envelope)

    def _run_one(self, envelope: TaskEnvelope) -> None:
        handler = self._handlers.get(envelope.kind)
        if handler is None:
            self._manager.mark_failure(envelope.task_id, message=f"no task handler registered for {envelope.kind}")
            return

        self._manager.mark_started(envelope.task_id)
        ctx = TaskContext(self._manager, envelope.task_id)
        try:
            handler(ctx, envelope.payload)
            final_state = self._manager.get(envelope.task_id)
            if final_state is None:
                return
            if final_state.status not in TERMINAL_TASK_STATES:
                self._manager.mark_success(envelope.task_id, message=final_state.message or "completed")
        except Exception as exc:  # noqa: BLE001
            self._mark_task_failure_side_effects(envelope)
            self._manager.mark_failure(envelope.task_id, message=str(exc))

    def _mark_task_failure_side_effects(self, envelope: TaskEnvelope) -> None:
        if envelope.kind != "image_annotate":
            return

        image_id = int(envelope.payload.get("image_id") or 0)
        if image_id <= 0:
            return

        session_factory = get_session_factory()
        with session_factory() as db:
            image = db.get(Image, image_id)
            if image is None:
                return
            image.status = "error"
            db.add(image)
            db.commit()
