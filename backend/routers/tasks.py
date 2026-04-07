from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from backend.api import AppError, ok
from backend.tasks.task_manager import get_task_manager


router = APIRouter(tags=["tasks"])


@router.get("/api/tasks/{task_id}/status")
def get_task_status(task_id: str):
    manager = get_task_manager()
    payload = manager.to_dict(task_id)
    if payload is None:
        raise AppError(404, "task not found")
    return ok(payload)


@router.websocket("/ws/tasks/{task_id}")
async def websocket_task_status(websocket: WebSocket, task_id: str):
    manager = get_task_manager()
    state = manager.get_with_version(task_id)
    if state is None:
        await websocket.close(code=4404, reason="task not found")
        return

    await websocket.accept()

    try:
        current = state
        while current is not None:
            await websocket.send_json(
                {
                    "task_id": current.id,
                    "status": current.status,
                    "progress": current.progress,
                    "message": current.message,
                }
            )
            if current.status in ("SUCCESS", "FAILURE"):
                break
            current = await run_in_threadpool(manager.wait_for_update, task_id, after_version=current.version, timeout=20.0)
    except WebSocketDisconnect:
        return
