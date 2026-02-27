from __future__ import annotations

import json
import io
import mimetypes
from datetime import datetime
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from PIL import Image as PILImage
from pydantic import BaseModel, Field
from pydantic import field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api import AppError, ok
from backend.database import get_session_factory
from backend.deps import get_db
from backend.models.annotation import Annotation
from backend.models.image import Image
from backend.models.project import Project
from backend.tasks.task_manager import TaskContext, get_task_manager
from backend.utils.storage import resolve_path, save_project_image_bytes


router = APIRouter(prefix="/api", tags=["images"])


class ImagePatchIn(BaseModel):
    split: Literal["train", "val", "test"] | None = None


class AnnotationCreateIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    bbox: list[float] = Field(min_length=4, max_length=4)
    confidence: float | None = None
    source: Literal["auto", "manual", "corrected"] = "manual"

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("label must be non-empty")
        return s

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, v: list[float]) -> list[float]:
        if len(v) != 4:
            raise ValueError("bbox must have 4 numbers")
        xmin, ymin, xmax, ymax = [float(x) for x in v]
        if xmin > xmax:
            xmin, xmax = xmax, xmin
        if ymin > ymax:
            ymin, ymax = ymax, ymin
        for n in (xmin, ymin, xmax, ymax):
            if n < 0.0 or n > 1.0:
                raise ValueError("bbox values must be within 0..1")
        if xmin == xmax or ymin == ymax:
            raise ValueError("bbox must have non-zero area")
        return [xmin, ymin, xmax, ymax]


def _image_to_dict(img: Image) -> dict[str, Any]:
    return {
        "id": img.id,
        "project_id": img.project_id,
        "filename": img.filename,
        "width": img.width,
        "height": img.height,
        "split": img.split,
        "status": img.status,
        "quality_score": img.quality_score,
        "file_url": f"/api/images/{img.id}/file",
    }


def _get_image_size(content: bytes) -> tuple[int, int]:
    try:
        pil = PILImage.open(io.BytesIO(content))
        pil.load()
        width, height = pil.size
        return int(width), int(height)
    except Exception as exc:  # noqa: BLE001
        raise AppError(400, f"invalid image file: {exc}") from exc


@router.post("/projects/{project_id}/images/upload")
async def upload_images(
    project_id: int,
    files: list[UploadFile] | None = File(None),
    files_array: list[UploadFile] | None = File(None, alias="files[]"),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")

    incoming_files = files_array or files or []
    if len(incoming_files) == 0:
        raise AppError(400, "no files uploaded")

    uploaded_ids: list[int] = []

    for f in incoming_files:
        content = await f.read()
        if not content:
            continue

        width, height = _get_image_size(content)
        image = Image(
            project_id=project_id,
            filename=f.filename or "image",
            file_path="",
            width=width,
            height=height,
            split="train",
            status="pending",
        )
        db.add(image)
        db.flush()  # allocate image.id

        image.file_path = save_project_image_bytes(project_id, image.id, image.filename, content)
        uploaded_ids.append(image.id)

    db.commit()

    return ok({"uploaded": len(uploaded_ids), "image_ids": uploaded_ids})


@router.get("/projects/{project_id}/images")
def list_images(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")

    images = db.execute(select(Image).where(Image.project_id == project_id).order_by(Image.id.desc())).scalars().all()
    return ok([_image_to_dict(img) for img in images])


@router.get("/images/{image_id}")
def get_image(image_id: int, db: Session = Depends(get_db)):
    image = db.get(Image, image_id)
    if image is None:
        raise AppError(404, "image not found")
    return ok(_image_to_dict(image))


@router.patch("/images/{image_id}")
def patch_image(image_id: int, payload: ImagePatchIn, db: Session = Depends(get_db)):
    image = db.get(Image, image_id)
    if image is None:
        raise AppError(404, "image not found")
    if payload.split is not None:
        image.split = payload.split
    db.add(image)
    db.commit()
    return ok(None)


@router.delete("/images/{image_id}")
def delete_image(image_id: int, db: Session = Depends(get_db)):
    image = db.get(Image, image_id)
    if image is None:
        raise AppError(404, "image not found")
    db.delete(image)
    db.commit()
    return ok(None)


@router.get("/images/{image_id}/file")
def get_image_file(image_id: int, db: Session = Depends(get_db)):
    image = db.get(Image, image_id)
    if image is None:
        raise AppError(404, "image not found")

    path = resolve_path(image.file_path)
    if not path.exists():
        raise AppError(404, "image file not found on disk")

    media_type, _encoding = mimetypes.guess_type(str(path))
    return FileResponse(path, media_type=media_type or "application/octet-stream", filename=image.filename)


def _annotation_to_dict(a: Annotation) -> dict[str, Any]:
    return {
        "id": a.id,
        "image_id": a.image_id,
        "label": a.label,
        "bbox": a.bbox,
        "polygon": a.polygon,
        "mask_path": a.mask_path,
        "confidence": a.confidence,
        "quality_score": a.quality_score,
        "source": a.source,
        "is_confirmed": bool(a.is_confirmed),
        "created_at": a.created_at,
    }


@router.get("/images/{image_id}/annotations")
def list_annotations(image_id: int, db: Session = Depends(get_db)):
    image = db.get(Image, image_id)
    if image is None:
        raise AppError(404, "image not found")

    anns = db.execute(select(Annotation).where(Annotation.image_id == image_id).order_by(Annotation.id.asc())).scalars()
    return ok([_annotation_to_dict(a) for a in anns])


@router.post("/images/{image_id}/annotations")
def create_annotation(image_id: int, payload: AnnotationCreateIn, db: Session = Depends(get_db)):
    image = db.get(Image, image_id)
    if image is None:
        raise AppError(404, "image not found")

    project = db.get(Project, image.project_id)
    labels: list[str] = []
    if project is not None and project.config:
        try:
            cfg = json.loads(project.config)
            raw = cfg.get("labels")
            if isinstance(raw, list) and all(isinstance(x, str) for x in raw):
                labels = [x.strip() for x in raw if x and x.strip()]
        except Exception:
            labels = []

    if labels and payload.label not in labels:
        raise AppError(400, "label must be one of project's labels")

    ann = Annotation(
        image_id=image_id,
        label=payload.label,
        bbox=payload.bbox,
        confidence=payload.confidence,
        source=payload.source,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return ok({"id": ann.id})


@router.post("/images/{image_id}/annotate")
def annotate_image(image_id: int, db: Session = Depends(get_db)):
    image = db.get(Image, image_id)
    if image is None:
        raise AppError(404, "image not found")

    manager = get_task_manager()
    session_factory = get_session_factory()

    def _job(ctx: TaskContext) -> None:
        ctx.set_progress(5, "queued")
        with session_factory() as task_db:
            img = task_db.get(Image, image_id)
            if img is None:
                raise RuntimeError("image not found")
            img.status = "annotating"
            task_db.add(img)
            task_db.commit()

        # MVP: just simulate a long-running pipeline (LLM/SAM will be added in M4/M5)
        ctx.set_progress(25, "running")
        time.sleep(0.2)
        ctx.set_progress(60, "running")
        time.sleep(0.2)
        ctx.set_progress(90, "finalizing")
        time.sleep(0.1)

        with session_factory() as task_db:
            img = task_db.get(Image, image_id)
            if img is not None:
                img.status = "done"
                task_db.add(img)
                task_db.commit()

    task_id = manager.create(_job)
    return ok({"task_id": task_id})
