from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api import AppError, ok
from backend.deps import get_db
from backend.models.annotation import Annotation
from backend.models.image import Image
from backend.services.quality_service import refresh_image_quality


router = APIRouter(prefix="/api", tags=["annotations"])


@router.delete("/annotations/{annotation_id}")
def delete_annotation(annotation_id: int, db: Session = Depends(get_db)):
    ann = db.get(Annotation, annotation_id)
    if ann is None:
        raise AppError(404, "annotation not found")
    image = db.get(Image, ann.image_id)
    db.delete(ann)
    db.flush()
    if image is not None:
        refresh_image_quality(db, image)
    db.commit()
    return ok(None)


@router.patch("/annotations/{annotation_id}/confirm")
def confirm_annotation(annotation_id: int, db: Session = Depends(get_db)):
    ann = db.get(Annotation, annotation_id)
    if ann is None:
        raise AppError(404, "annotation not found")
    ann.is_confirmed = True
    db.add(ann)
    image = db.get(Image, ann.image_id)
    if image is not None:
        refresh_image_quality(db, image)
    db.commit()
    return ok(None)
