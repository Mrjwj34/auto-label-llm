from __future__ import annotations

from fastapi import APIRouter

from backend.api import AppError, ok
from backend.tasks.task_manager import get_task_manager


router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/tasks/{task_id}/status")
def get_task_status(task_id: str):
    manager = get_task_manager()
    payload = manager.to_dict(task_id)
    if payload is None:
        raise AppError(404, "task not found")
    return ok(payload)

