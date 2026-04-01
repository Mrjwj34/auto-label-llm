from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api import AppError, ok
from backend.deps import get_db
from backend.models.annotation import Annotation


router = APIRouter(prefix="/api", tags=["annotations"])


@router.delete("/annotations/{annotation_id}")
def delete_annotation(annotation_id: int, db: Session = Depends(get_db)):
    ann = db.get(Annotation, annotation_id)
    if ann is None:
        raise AppError(404, "annotation not found")
    db.delete(ann)
    db.commit()
    return ok(None)


@router.patch("/annotations/{annotation_id}/confirm")
def confirm_annotation(annotation_id: int, db: Session = Depends(get_db)):
    ann = db.get(Annotation, annotation_id)
    if ann is None:
        raise AppError(404, "annotation not found")
    ann.is_confirmed = True
    db.add(ann)
    db.commit()
    return ok(None)
