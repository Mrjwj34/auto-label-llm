from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.annotation import Annotation
from backend.models.image import Image


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def estimate_annotation_quality(annotation: Annotation) -> float | None:
    if annotation.bbox is None:
        return None
    if bool(annotation.is_confirmed):
        return 1.0

    xmin, ymin, xmax, ymax = [float(v) for v in annotation.bbox]
    width = max(0.0, xmax - xmin)
    height = max(0.0, ymax - ymin)
    if width <= 0.0 or height <= 0.0:
        return 0.0

    if annotation.confidence is not None:
        score = 0.35 + 0.55 * _clamp01(annotation.confidence)
    elif annotation.source == "manual":
        score = 0.72
    elif annotation.source == "corrected":
        score = 0.68
    else:
        score = 0.58

    area = width * height
    if area < 0.001:
        score -= 0.28
    elif area < 0.005:
        score -= 0.14
    elif area > 0.8:
        score -= 0.18
    elif area > 0.55:
        score -= 0.08

    aspect = width / height if height > 0 else 99.0
    if aspect > 10.0 or aspect < 0.1:
        score -= 0.16
    elif aspect > 6.0 or aspect < 0.1667:
        score -= 0.08

    edge_distance = min(xmin, ymin, 1.0 - xmax, 1.0 - ymax)
    if edge_distance < 0.005:
        score -= 0.12
    elif edge_distance < 0.02:
        score -= 0.05

    if annotation.polygon:
        if len(annotation.polygon) < 4:
            score -= 0.05
        elif len(annotation.polygon) >= 6:
            score += 0.03

    if annotation.source == "manual":
        score += 0.08
    elif annotation.source == "corrected":
        score += 0.05

    return round(_clamp01(score), 4)


def refresh_image_quality(db: Session, image: Image) -> float | None:
    db.flush()
    annotations = db.execute(
        select(Annotation).where(Annotation.image_id == image.id).order_by(Annotation.id.asc())
    ).scalars().all()

    if not annotations:
        image.quality_score = None if image.status in ("pending", "annotating") else 0.0
        db.add(image)
        return image.quality_score

    scores: list[float] = []
    confirmed_count = 0
    for annotation in annotations:
        annotation.quality_score = estimate_annotation_quality(annotation)
        db.add(annotation)
        if annotation.quality_score is not None:
            scores.append(annotation.quality_score)
        if bool(annotation.is_confirmed):
            confirmed_count += 1

    base_score = (sum(scores) / len(scores)) if scores else 0.0
    if confirmed_count == len(annotations):
        image.quality_score = 1.0
    elif confirmed_count > 0:
        confirmed_ratio = confirmed_count / len(annotations)
        image.quality_score = round(_clamp01(base_score + confirmed_ratio * 0.1), 4)
    else:
        image.quality_score = round(_clamp01(base_score), 4)

    db.add(image)
    return image.quality_score


def refresh_project_quality_scores(db: Session, project_id: int) -> None:
    images = db.execute(select(Image).where(Image.project_id == project_id).order_by(Image.id.asc())).scalars().all()
    for image in images:
        refresh_image_quality(db, image)
