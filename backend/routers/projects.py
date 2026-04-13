from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api import AppError, ok
from backend.database import get_session_factory
from backend.deps import get_db
from backend.models.image import Image
from backend.models.project import Project
from backend.services.auto_annotator import generate_auto_annotations, replace_auto_annotations
from backend.services.annotation_tasks import resolve_project_image_ids
from backend.services.dataset_io import export_project_dataset, import_project_dataset
from backend.services.project_settings import get_project_labels, load_stored_project_settings, merge_project_settings
from backend.services.settings_service import (
    build_project_settings_response,
    sanitize_project_settings_patch,
    settings_change_summary,
)
from backend.services.vllm_client import activate_project_model_tag, resolve_inference_route
from backend.tasks.task_manager import get_task_manager
from backend.utils.storage import delete_project_dirs, ensure_project_dirs
from backend.workflows.registry import (
    default_workflow_key_for_task_type,
    list_available_workflows,
    resolve_project_workflow,
    validate_workflow_key_for_task_type,
)


router = APIRouter(prefix="/api", tags=["projects"])


class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    task_type: Literal["detection", "segmentation"]
    workflow_key: str | None = Field(default=None, min_length=1, max_length=100)


class ProjectOut(BaseModel):
    id: int
    name: str
    task_type: str
    created_at: datetime


class ProjectAnnotateIn(BaseModel):
    image_ids: list[int] | None = None
    only_pending: bool = True


class ProjectModelActivateIn(BaseModel):
    model_tag: str = Field(min_length=1, max_length=200)


def _project_to_dict(p: Project) -> dict[str, Any]:
    workflow = resolve_project_workflow(p)
    return {
        "id": p.id,
        "name": p.name,
        "task_type": p.task_type,
        "workflow_key": workflow.key,
        "task_family": workflow.task_family,
        "created_at": p.created_at,
    }


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    projects = db.execute(select(Project).order_by(Project.id.desc())).scalars().all()
    return ok([_project_to_dict(p) for p in projects])


@router.get("/projects/meta")
def get_project_meta():
    workflows = [workflow.to_dict() for workflow in list_available_workflows()]
    return ok(
        {
            "task_types": ["detection", "segmentation"],
            "default_workflows": {
                "detection": default_workflow_key_for_task_type("detection"),
                "segmentation": default_workflow_key_for_task_type("segmentation"),
            },
            "workflows": workflows,
        }
    )


@router.post("/projects")
def create_project(payload: ProjectCreateIn, db: Session = Depends(get_db)):
    workflow_key = payload.workflow_key or default_workflow_key_for_task_type(payload.task_type)
    try:
        workflow = validate_workflow_key_for_task_type(workflow_key, payload.task_type)
    except ValueError as exc:
        raise AppError(400, str(exc)) from exc

    project = Project(
        name=payload.name,
        task_type=payload.task_type,
        config=json.dumps({"workflow_key": workflow.key}, ensure_ascii=False),
    )
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
    return ok(build_project_settings_response(project))


@router.patch("/projects/{project_id}/settings")
def patch_project_settings(
    project_id: int,
    patch: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")

    cleaned_patch = sanitize_project_settings_patch(patch)
    stored = load_stored_project_settings(project)
    merged = dict(stored)
    for key, value in cleaned_patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value

    workflow_key = str(merged.get("workflow_key") or default_workflow_key_for_task_type(project.task_type))
    try:
        validate_workflow_key_for_task_type(workflow_key, project.task_type)
    except ValueError as exc:
        raise AppError(400, str(exc)) from exc

    resolved_settings = merge_project_settings(merged, project=project)
    resolve_inference_route(
        project,
        requested_model_tag=str(merged.get("active_model_tag") or resolved_settings.get("active_model_tag") or "base"),
        db=db,
        project_settings=resolved_settings,
    )

    summary = settings_change_summary(cleaned_patch)
    project.config = json.dumps(merged, ensure_ascii=False)
    db.add(project)
    db.commit()
    return ok(
        {
            "settings": build_project_settings_response(project, stored=merged),
            "change": summary,
        },
        message=summary["message"],
    )


@router.post("/projects/{project_id}/models/activate")
def activate_project_model(project_id: int, payload: ProjectModelActivateIn, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")

    activation = activate_project_model_tag(project, payload.model_tag, db)
    return ok(
        {
            "settings": build_project_settings_response(project),
            "activation": activation,
        },
        message=activation["message"],
    )


@router.post("/projects/{project_id}/annotate")
def annotate_project(project_id: int, payload: ProjectAnnotateIn, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")
    if not get_project_labels(project):
        raise AppError(400, "project labels are empty; configure at least one label before auto annotation")

    try:
        image_ids = resolve_project_image_ids(
            project_id=project_id,
            image_ids=payload.image_ids,
            only_pending=payload.only_pending,
        )
    except RuntimeError as exc:
        raise AppError(400, str(exc)) from exc

    manager = get_task_manager()
    task_id = manager.create(
        kind="project_annotate",
        payload={"project_id": project_id, "image_ids": image_ids},
        queue="annotation",
    )
    return ok({"task_id": task_id, "total": len(image_ids)})


@router.get("/projects/{project_id}/export")
def export_dataset(
    project_id: int,
    format: Literal["yolo", "coco"],
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")

    archive_path = export_project_dataset(project, db, format)
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=archive_path.name,
    )


@router.post("/projects/{project_id}/import")
async def import_dataset(
    project_id: int,
    format: Literal["yolo", "coco"] = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")

    content = await file.read()
    result = import_project_dataset(
        project,
        db,
        format_name=format,
        archive_name=file.filename or f"{format}.zip",
        archive_bytes=content,
    )
    return ok(
        {
            "imported_count": result.imported_count,
            "annotation_count": result.annotation_count,
            "labels": result.labels,
        }
    )
