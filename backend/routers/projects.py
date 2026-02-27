from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api import AppError, ok
from backend.config import DEFAULT_PROJECT_SETTINGS, deep_merge
from backend.deps import get_db
from backend.models.project import Project
from backend.utils.storage import delete_project_dirs, ensure_project_dirs


router = APIRouter(prefix="/api", tags=["projects"])


class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    task_type: Literal["detection", "segmentation"]


class ProjectOut(BaseModel):
    id: int
    name: str
    task_type: str
    created_at: datetime


def _project_to_dict(p: Project) -> dict[str, Any]:
    return {"id": p.id, "name": p.name, "task_type": p.task_type, "created_at": p.created_at}


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    projects = db.execute(select(Project).order_by(Project.id.desc())).scalars().all()
    return ok([_project_to_dict(p) for p in projects])


@router.post("/projects")
def create_project(payload: ProjectCreateIn, db: Session = Depends(get_db)):
    project = Project(name=payload.name, task_type=payload.task_type, config=None)
    db.add(project)
    db.commit()
    db.refresh(project)

    ensure_project_dirs(project.id)
    return ok({"id": project.id})


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")

    db.delete(project)
    db.commit()

    delete_project_dirs(project_id)
    return ok(None)


@router.get("/projects/{project_id}/settings")
def get_project_settings(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")

    stored: dict[str, Any] = {}
    if project.config:
        try:
            stored = json.loads(project.config)
        except Exception:
            stored = {}

    merged = deep_merge(DEFAULT_PROJECT_SETTINGS, stored)
    return ok(merged)


@router.patch("/projects/{project_id}/settings")
def patch_project_settings(
    project_id: int,
    patch: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")

    if not isinstance(patch, dict):
        raise AppError(400, "settings patch must be an object")

    stored: dict[str, Any] = {}
    if project.config:
        try:
            stored = json.loads(project.config)
        except Exception:
            stored = {}

    merged = deep_merge(stored, patch)
    project.config = json.dumps(merged, ensure_ascii=False)
    db.add(project)
    db.commit()
    return ok(None)

