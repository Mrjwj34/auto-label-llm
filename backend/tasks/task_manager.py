from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from backend.services.redis_client import get_redis_client


TERMINAL_TASK_STATES = {"SUCCESS", "FAILURE"}
DEFAULT_TASK_QUEUE_BY_KIND = {
    "project_annotate": "annotation",
    "image_annotate": "annotation",
    "evaluation_run": "evaluation",
    "finetune_job": "finetune",
}


@dataclass
class TaskState:
    id: str
    kind: str
    queue: str
    status: str  # PENDING|STARTED|SUCCESS|FAILURE
    progress: int
    message: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    version: int = 0


@dataclass
class TaskEnvelope:
    task_id: str
    kind: str
    queue: str
    payload: dict[str, Any]


class TaskContext:
    def __init__(self, manager: "RedisTaskManager", task_id: str):
        self._manager = manager
        self.task_id = task_id

    def set_progress(self, progress: int, message: str | None = None) -> None:
        self._manager.update(self.task_id, progress=progress, message=message)


class RedisTaskManager:
    def __init__(self, *, key_prefix: str = "auto_labeling"):
        self._redis = get_redis_client()
        self._key_prefix = key_prefix

    def create(self, *, kind: str, payload: dict[str, Any], queue: str | None = None) -> str:
        task_id = uuid4().hex
        queue_name = queue or DEFAULT_TASK_QUEUE_BY_KIND.get(kind, "default")
        key = self._task_key(task_id)
        now = _utc_now_iso()
        self._redis.hset(
            key,
            mapping={
                "id": task_id,
                "kind": kind,
                "queue": queue_name,
                "status": "PENDING",
                "progress": 0,
                "message": "queued",
                "created_at": now,
                "started_at": "",
                "finished_at": "",
                "version": 0,
                "payload": json.dumps(payload, ensure_ascii=False),
            },
        )
        self._redis.lpush(self._queue_key(queue_name), task_id)
        return task_id

    def get(self, task_id: str) -> TaskState | None:
        payload = self._redis.hgetall(self._task_key(task_id))
        if not payload:
            return None
        return TaskState(
            id=str(payload.get("id") or task_id),
            kind=str(payload.get("kind") or ""),
            queue=str(payload.get("queue") or "default"),
            status=str(payload.get("status") or "PENDING"),
            progress=int(float(payload.get("progress") or 0)),
            message=_optional_text(payload.get("message")),
            created_at=_optional_text(payload.get("created_at")),
            started_at=_optional_text(payload.get("started_at")),
            finished_at=_optional_text(payload.get("finished_at")),
            version=int(float(payload.get("version") or 0)),
        )

    def get_payload(self, task_id: str) -> dict[str, Any]:
        raw = self._redis.hget(self._task_key(task_id), "payload")
        if not raw:
            return {}
        try:
            decoded = json.loads(raw)
        except Exception:
            return {}
        return decoded if isinstance(decoded, dict) else {}

    def to_dict(self, task_id: str) -> dict[str, Any] | None:
        state = self.get(task_id)
        if state is None:
            return None
        return {
            "task_id": state.id,
            "kind": state.kind,
            "queue": state.queue,
            "status": state.status,
            "progress": state.progress,
            "message": state.message,
            "version": state.version,
        }

    def get_with_version(self, task_id: str) -> TaskState | None:
        return self.get(task_id)

    def wait_for_update(self, task_id: str, *, after_version: int, timeout: float | None = None) -> TaskState | None:
        deadline = None if timeout is None else (time.monotonic() + max(0.0, timeout))
        while True:
            state = self.get(task_id)
            if state is None:
                return None
            if state.version > after_version or state.status in TERMINAL_TASK_STATES:
                return state
            if deadline is not None and time.monotonic() >= deadline:
                return state
            time.sleep(0.2)

    def dequeue(self, queues: list[str], *, timeout: float = 1.0) -> TaskEnvelope | None:
        keys = [self._queue_key(queue) for queue in queues]
        response = self._redis.brpop(keys, timeout=timeout)
        if response is None:
            return None
        queue_key, task_id = response
        queue_name = self._queue_name_from_key(queue_key)
        state = self.get(task_id)
        if state is None:
            return None
        return TaskEnvelope(
            task_id=task_id,
            kind=state.kind,
            queue=queue_name,
            payload=self.get_payload(task_id),
        )

    def mark_started(self, task_id: str, *, message: str | None = None) -> None:
        self.update(task_id, status="STARTED", message=message or "started", started_at=_utc_now_iso())

    def mark_success(self, task_id: str, *, message: str | None = None) -> None:
        final_state = self.get(task_id)
        final_message = message if message is not None else (final_state.message if final_state else "completed")
        self.update(task_id, status="SUCCESS", progress=100, message=final_message, finished_at=_utc_now_iso())

    def mark_failure(self, task_id: str, *, message: str | None = None) -> None:
        self.update(task_id, status="FAILURE", message=message or "failed", finished_at=_utc_now_iso())

    def update(
        self,
        task_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        key = self._task_key(task_id)
        if not self._redis.exists(key):
            return

        version = int(self._redis.hincrby(key, "version", 1))
        mapping: dict[str, Any] = {"version": version}
        if status is not None:
            mapping["status"] = status
        if progress is not None:
            mapping["progress"] = max(0, min(100, int(progress)))
        if message is not None:
            mapping["message"] = str(message)
        if started_at is not None:
            mapping["started_at"] = started_at
        if finished_at is not None:
            mapping["finished_at"] = finished_at
        self._redis.hset(key, mapping=mapping)

    def ping(self) -> None:
        self._redis.ping()

    def _task_key(self, task_id: str) -> str:
        return f"{self._key_prefix}:task:{task_id}"

    def _queue_key(self, queue: str) -> str:
        return f"{self._key_prefix}:queue:{queue}"

    def _queue_name_from_key(self, queue_key: str) -> str:
        prefix = f"{self._key_prefix}:queue:"
        if queue_key.startswith(prefix):
            return queue_key[len(prefix) :]
        return queue_key


_manager: RedisTaskManager | None = None


def get_task_manager() -> RedisTaskManager:
    global _manager
    if _manager is None:
        _manager = RedisTaskManager()
    return _manager


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
