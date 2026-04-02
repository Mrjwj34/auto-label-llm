from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api import AppError, ok
from backend.deps import get_db
from backend.models.evaluation_run import EvaluationRun
from backend.models.project import Project
from backend.services.evaluation_service import (
    create_evaluation_run,
    evaluation_run_to_dict,
    list_project_evaluations,
    read_evaluation_report,
)


router = APIRouter(prefix="/api", tags=["evaluations"])


class EvaluationStartIn(BaseModel):
    split: str | None = None
    image_ids: list[int] | None = None
    model_tag: str | None = None
    iou_threshold: float | None = None
    max_samples: int | None = None


@router.post("/projects/{project_id}/evaluate")
def start_evaluation(project_id: int, payload: EvaluationStartIn, db: Session = Depends(get_db)):
    run = create_evaluation_run(
        project_id,
        split=payload.split,
        image_ids=payload.image_ids,
        model_tag=payload.model_tag,
        iou_threshold=payload.iou_threshold,
        max_samples=payload.max_samples,
        db=db,
    )
    return ok({"run_id": run.id})


@router.get("/evaluations/{run_id}")
def get_evaluation(run_id: int, db: Session = Depends(get_db)):
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise AppError(404, "evaluation run not found")
    return ok(evaluation_run_to_dict(run))


@router.get("/evaluations/{run_id}/report")
def get_evaluation_report(run_id: int, db: Session = Depends(get_db)):
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise AppError(404, "evaluation run not found")
    report = read_evaluation_report(run)
    if report is None:
        raise AppError(404, "evaluation report not found")
    return ok(report)


@router.get("/projects/{project_id}/evaluations")
def get_project_evaluations(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")
    return ok(list_project_evaluations(project_id, db))
