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
from backend.config import DEFAULT_PROJECT_SETTINGS, deep_merge
from backend.database import get_session_factory
from backend.deps import get_db
from backend.models.image import Image
from backend.models.project import Project
from backend.services.auto_annotator import generate_auto_annotations, replace_auto_annotations
from backend.services.dataset_io import export_project_dataset, import_project_dataset
from backend.services.project_settings import get_project_labels
from backend.tasks.task_manager import TaskContext, get_task_manager
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


class ProjectAnnotateIn(BaseModel):
    image_ids: list[int] | None = None
    only_pending: bool = True


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

    if "labels" in patch:
        labels_value = patch.get("labels")
        if not isinstance(labels_value, list):
            raise AppError(400, "labels must be a list of strings")
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in labels_value:
            if not isinstance(item, str):
                raise AppError(400, "labels must be a list of strings")
            s = item.strip()
            if not s:
                continue
            if len(s) > 200:
                raise AppError(400, "label too long")
            if s in seen:
                continue
            cleaned.append(s)
            seen.add(s)
        patch["labels"] = cleaned

    merged = deep_merge(stored, patch)
    project.config = json.dumps(merged, ensure_ascii=False)
    db.add(project)
    db.commit()
    return ok(None)


@router.post("/projects/{project_id}/annotate")
def annotate_project(project_id: int, payload: ProjectAnnotateIn, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")
    if not get_project_labels(project):
        raise AppError(400, "project labels are empty; configure at least one label before auto annotation")

    image_ids: list[int]
    if payload.image_ids:
        rows = db.execute(
            select(Image.id).where(Image.project_id == project_id, Image.id.in_(payload.image_ids))
        ).all()
        image_ids = [int(r[0]) for r in rows]
        if len(image_ids) != len(set(payload.image_ids)):
            raise AppError(400, "some image_ids do not belong to the project")
    else:
        q = select(Image.id).where(Image.project_id == project_id)
        if payload.only_pending:
            q = q.where(Image.status == "pending")
        image_ids = [int(r[0]) for r in db.execute(q).all()]

    manager = get_task_manager()
    session_factory = get_session_factory()

    def _job(ctx: TaskContext) -> None:
        total = len(image_ids)
        if total == 0:
            ctx.set_progress(100, "no images to annotate")
            return

        success_count = 0
        failed_count = 0
        for idx, image_id in enumerate(image_ids, start=1):
            ctx.set_progress(int((idx - 1) / total * 100), f"image {idx}/{total}")

            try:
                with session_factory() as task_db:
                    img = task_db.get(Image, image_id)
                    if img is None:
                        continue
                    task_project = task_db.get(Project, img.project_id)
                    if task_project is None:
                        raise RuntimeError("project not found")

                    img.status = "annotating"
                    task_db.add(img)
                    task_db.commit()

                    result = generate_auto_annotations(task_project, img)
                    replace_auto_annotations(task_db, img, result)
                    img.status = "done"
                    task_db.add(img)
                    task_db.commit()

                    success_count += 1
                    provider_text = f" via {result.provider}"
                    if result.warning:
                        provider_text += " (fallback)"
            except Exception as exc:  # noqa: BLE001
                failed_count += 1
                provider_text = ""
                with session_factory() as task_db:
                    img = task_db.get(Image, image_id)
                    if img is not None:
                        img.status = "error"
                        task_db.add(img)
                        task_db.commit()
                ctx.set_progress(int(idx / total * 100), f"image {idx}/{total} failed: {exc}")
                continue

            ctx.set_progress(
                int(idx / total * 100),
                f"image {idx}/{total} done ({len(result.annotations)} boxes{provider_text})",
            )

        summary = f"completed {success_count}/{total} images"
        if failed_count:
            summary += f", failed {failed_count}"
        ctx.set_progress(100, summary)
        if failed_count == total and total > 0:
            raise RuntimeError(summary)

    task_id = manager.create(_job)
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
