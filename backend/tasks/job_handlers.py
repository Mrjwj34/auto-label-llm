from __future__ import annotations

from backend.services.annotation_tasks import run_image_annotation_task, run_project_annotation_task
from backend.services.evaluation_service import run_evaluation_task
from backend.services.finetune_service import run_finetune_job_task
from backend.tasks.task_manager import TaskContext


def handle_project_annotate(ctx: TaskContext, payload: dict) -> None:
    run_project_annotation_task(ctx, payload)


def handle_image_annotate(ctx: TaskContext, payload: dict) -> None:
    run_image_annotation_task(ctx, payload)


def handle_evaluation_run(ctx: TaskContext, payload: dict) -> None:
    run_id = int(payload.get("run_id") or 0)
    if run_id <= 0:
        raise RuntimeError("run_id is required")
    run_evaluation_task(run_id, ctx=ctx)


def handle_finetune_job(ctx: TaskContext, payload: dict) -> None:
    job_id = int(payload.get("job_id") or 0)
    if job_id <= 0:
        raise RuntimeError("job_id is required")
    run_finetune_job_task(job_id, ctx=ctx)


TASK_HANDLERS = {
    "project_annotate": handle_project_annotate,
    "image_annotate": handle_image_annotate,
    "evaluation_run": handle_evaluation_run,
    "finetune_job": handle_finetune_job,
}
