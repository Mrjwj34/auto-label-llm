from __future__ import annotations

import io
import mimetypes
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from PIL import Image as PILImage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api import AppError, ok
from backend.deps import get_db
from backend.models.image import Image
from backend.models.project import Project
from backend.utils.storage import resolve_path, save_project_image_bytes


router = APIRouter(prefix="/api", tags=["images"])


class ImagePatchIn(BaseModel):
    split: Literal["train", "val", "test"] | None = None


def _image_to_dict(img: Image) -> dict[str, Any]:
    return {
        "id": img.id,
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
