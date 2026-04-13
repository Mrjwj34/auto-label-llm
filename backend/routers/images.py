from __future__ import annotations

import io
import json
import mimetypes
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from PIL import Image as PILImage
from pydantic import BaseModel, Field
from pydantic import field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api import AppError, ok
from backend.deps import get_db
from backend.models.annotation import Annotation
from backend.models.image import Image
from backend.models.project import Project
from backend.services.postprocess import apply_project_postprocess
from backend.services.project_settings import get_project_labels, get_project_workflow, load_project_settings
from backend.services.quality_service import refresh_image_quality
from backend.services.sam_service import SAMService
from backend.tasks.task_manager import get_task_manager
from backend.utils.gpu_lock import GPUBusyError
from backend.utils.storage import resolve_path, save_project_image_bytes


router = APIRouter(prefix="/api", tags=["images"])


def _normalize_bbox_input(value: list[float]) -> list[float]:
    if len(value) != 4:
        raise ValueError("bbox must have 4 numbers")
    xmin, ymin, xmax, ymax = [float(x) for x in value]
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
        return _normalize_bbox_input(v)


class PredictPointIn(BaseModel):
    x: float
    y: float
    label: Literal[0, 1]

    @field_validator("x", "y")
    @classmethod
    def validate_coordinate(cls, value: float) -> float:
        num = float(value)
        if num < 0.0 or num > 1.0:
            raise ValueError("point values must be within 0..1")
        return num


class ImagePredictIn(BaseModel):
    annotation_id: int | None = None
    label: str | None = Field(default=None, max_length=200)
    bbox: list[float] | None = None
    points: list[PredictPointIn] | None = None

    @field_validator("label")
    @classmethod
    def validate_optional_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("label must be non-empty")
        return stripped

    @field_validator("bbox")
    @classmethod
    def validate_optional_bbox(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return None
        return _normalize_bbox_input(value)

    @field_validator("points")
    @classmethod
    def validate_points(cls, value: list[PredictPointIn] | None) -> list[PredictPointIn] | None:
        if value is None:
            return None
        if len(value) == 0:
            raise ValueError("points must not be empty")
        return value


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
    inference_payload = _annotation_inference_payload(a)
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
        "inference": inference_payload,
    }


def _annotation_inference_payload(annotation: Annotation) -> dict[str, Any] | None:
    if not annotation.extra:
        return None
    try:
        payload = json.loads(annotation.extra)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _validate_project_label(project: Project | None, label: str | None) -> None:
    if label is None:
        return
    labels = get_project_labels(project)
    if labels and label not in labels:
        raise AppError(400, "label must be one of project's labels")


def _project_sam_kwargs(project: Project | None) -> dict[str, Any]:
    settings = load_project_settings(project)
    sam_settings = settings.get("sam", {}) if isinstance(settings.get("sam"), dict) else {}
    return {
        "checkpoint": str(sam_settings.get("checkpoint") or "sam2"),
        "device": str(sam_settings.get("device") or "cuda"),
        "multimask_output": bool(sam_settings.get("multimask_output", False)),
    }


def _interactive_sam_kwargs(project: Project | None) -> dict[str, Any]:
    payload = _project_sam_kwargs(project)
    payload["lock_timeout"] = 0.0
    return payload


def _project_workflow(project: Project | None):
    return get_project_workflow(project)


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
    _validate_project_label(project, payload.label)
    workflow = _project_workflow(project)

    polygon: list[list[float]] | None = None
    mask_path: str | None = None
    processed = None
    if project is not None and workflow.has_capability("sam_refine"):
        prediction = SAMService().predict_polygon(image, payload.bbox, **_project_sam_kwargs(project))
        processed = apply_project_postprocess(
            project,
            image,
            mask=prediction.mask,
            bbox=prediction.bbox,
            provider=prediction.provider,
            score=prediction.score,
        )
        polygon = processed.polygon
        mask_path = processed.mask_path

    ann = Annotation(
        image_id=image_id,
        label=payload.label,
        bbox=processed.bbox if processed is not None else payload.bbox,
        polygon=polygon,
        mask_path=mask_path,
        confidence=payload.confidence,
        source=payload.source,
    )
    db.add(ann)
    db.flush()
    refresh_image_quality(db, image)
    db.commit()
    db.refresh(ann)
    return ok({"id": ann.id})


@router.post("/images/{image_id}/predict")
def predict_annotation(image_id: int, payload: ImagePredictIn, db: Session = Depends(get_db)):
    image = db.get(Image, image_id)
    if image is None:
        raise AppError(404, "image not found")

    project = db.get(Project, image.project_id)
    if project is None:
        raise AppError(404, "project not found")
    workflow = _project_workflow(project)

    has_bbox = payload.bbox is not None
    has_points = payload.points is not None
    if has_bbox == has_points:
        raise AppError(400, "exactly one of bbox or points is required")

    annotation: Annotation | None = None
    if payload.annotation_id is not None:
        annotation = db.get(Annotation, payload.annotation_id)
        if annotation is None or annotation.image_id != image_id:
            raise AppError(404, "annotation not found")

    if has_bbox:
        if annotation is None:
            if payload.label is None:
                raise AppError(400, "label is required when creating a new annotation")
            _validate_project_label(project, payload.label)
            created = Annotation(
                image_id=image_id,
                label=payload.label,
                bbox=payload.bbox,
                source="corrected",
                is_confirmed=False,
            )
            if workflow.has_capability("sam_refine") and payload.bbox is not None:
                prediction = SAMService().predict_polygon(image, payload.bbox, **_project_sam_kwargs(project))
                processed = apply_project_postprocess(
                    project,
                    image,
                    mask=prediction.mask,
                    bbox=prediction.bbox,
                    provider=prediction.provider,
                    score=prediction.score,
                )
                created.bbox = processed.bbox or prediction.bbox or payload.bbox
                created.polygon = processed.polygon
                created.mask_path = processed.mask_path
            db.add(created)
            db.flush()
            refresh_image_quality(db, image)
            db.commit()
            db.refresh(created)
            return ok(
                {
                    "annotation_id": created.id,
                    "bbox": created.bbox,
                    "polygon": created.polygon,
                    "mask_path": created.mask_path,
                }
            )

        if payload.label is not None:
            _validate_project_label(project, payload.label)
            annotation.label = payload.label
        annotation.bbox = payload.bbox
        annotation.source = "corrected"
        annotation.is_confirmed = False
        if workflow.has_capability("sam_refine") and payload.bbox is not None:
            prediction = SAMService().predict_polygon(image, payload.bbox, **_project_sam_kwargs(project))
            processed = apply_project_postprocess(
                project,
                image,
                mask=prediction.mask,
                bbox=prediction.bbox,
                provider=prediction.provider,
                score=prediction.score,
            )
            annotation.bbox = processed.bbox or prediction.bbox or payload.bbox
            annotation.polygon = processed.polygon
            annotation.mask_path = processed.mask_path
        db.add(annotation)
        db.flush()
        refresh_image_quality(db, image)
        db.commit()
        db.refresh(annotation)
        return ok(
            {
                "annotation_id": annotation.id,
                "bbox": annotation.bbox,
                "polygon": annotation.polygon,
                "mask_path": annotation.mask_path,
            }
        )

    if annotation is None:
        raise AppError(400, "annotation_id is required for point correction")
    if not workflow.supports_point_refine:
        raise AppError(400, "point correction is only available for segmentation projects")

    prediction = SAMService().refine_annotation(
        image=image,
        annotation=annotation,
        points=[{"x": point.x, "y": point.y, "label": point.label} for point in payload.points or []],
        **_project_sam_kwargs(project),
    )
    processed = apply_project_postprocess(
        project,
        image,
        mask=prediction.mask,
        bbox=prediction.bbox,
        provider=prediction.provider,
        score=prediction.score,
    )
    annotation.bbox = processed.bbox or prediction.bbox or annotation.bbox
    annotation.polygon = processed.polygon
    annotation.mask_path = processed.mask_path
    annotation.source = "corrected"
    annotation.is_confirmed = False
    db.add(annotation)
    db.flush()
    refresh_image_quality(db, image)
    db.commit()
    db.refresh(annotation)
    return ok(
        {
            "annotation_id": annotation.id,
            "bbox": annotation.bbox,
            "polygon": annotation.polygon,
            "mask_path": annotation.mask_path,
        }
    )


@router.post("/images/{image_id}/annotate")
def annotate_image(image_id: int, db: Session = Depends(get_db)):
    image = db.get(Image, image_id)
    if image is None:
        raise AppError(404, "image not found")
    project = db.get(Project, image.project_id)
    if project is None:
        raise AppError(404, "project not found")
    if not get_project_labels(project):
        raise AppError(400, "project labels are empty; configure at least one label before auto annotation")

    manager = get_task_manager()
    task_id = manager.create(
        kind="image_annotate",
        payload={"image_id": image_id},
        queue="annotation",
    )
    return ok({"task_id": task_id})
