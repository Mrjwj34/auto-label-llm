from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api import AppError, ok
from backend.deps import get_db
from backend.models.finetune_job import FinetuneJob
from backend.models.project import Project
from backend.services.finetune_service import (
    activate_finetune_job,
    create_finetune_job,
    finetune_job_to_dict,
    list_project_finetune_jobs,
    read_finetune_log,
)
from backend.services.project_settings import load_project_settings


router = APIRouter(prefix="/api", tags=["finetune"])


class FinetuneStartIn(BaseModel):
    project_id: int


@router.post("/finetune/start")
def start_finetune(payload: FinetuneStartIn, db: Session = Depends(get_db)):
    job, task_id = create_finetune_job(payload.project_id, db)
    return ok({"job_id": job.id, "task_id": task_id})


@router.get("/finetune/{job_id}/status")
def get_finetune_status(job_id: int, db: Session = Depends(get_db)):
    job = db.get(FinetuneJob, job_id)
    if job is None:
        raise AppError(404, "finetune job not found")

    project = db.get(Project, job.project_id)
    active_tag = "base"
    if project is not None:
        active_tag = str(load_project_settings(project).get("active_model_tag") or "base")
    return ok(finetune_job_to_dict(job, active_tag=active_tag))


@router.get("/finetune/{job_id}/log")
def get_finetune_log(job_id: int, db: Session = Depends(get_db)):
    job = db.get(FinetuneJob, job_id)
    if job is None:
        raise AppError(404, "finetune job not found")
    return ok({"log": read_finetune_log(job)})


@router.post("/finetune/{job_id}/activate")
def activate_finetune(job_id: int, db: Session = Depends(get_db)):
    result = activate_finetune_job(job_id, db)
    return ok(result, message=result["message"])


@router.get("/projects/{project_id}/finetune-jobs")
def get_project_finetune_jobs(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")
    return ok(list_project_finetune_jobs(project_id, db))
