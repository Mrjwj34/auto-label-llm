from __future__ import annotations

from math import fabs

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.annotation import Annotation
from backend.models.image import Image
from backend.models.project import Project
from backend.services.project_settings import load_project_settings


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _polygon_area(polygon: list[list[float]]) -> float:
    if len(polygon) < 3:
        return 0.0
    area = 0.0
    for idx, point in enumerate(polygon):
        next_point = polygon[(idx + 1) % len(polygon)]
        area += point[0] * next_point[1] - next_point[0] * point[1]
    return fabs(area) / 2.0


def estimate_annotation_quality(annotation: Annotation, *, quality_settings: dict[str, object]) -> float | None:
    if not bool(quality_settings.get("enable", True)):
        return None
    if annotation.bbox is None:
        return None
    if bool(annotation.is_confirmed):
        return 1.0

    xmin, ymin, xmax, ymax = [float(v) for v in annotation.bbox]
    width = max(0.0, xmax - xmin)
    height = max(0.0, ymax - ymin)
    if width <= 0.0 or height <= 0.0:
        return 0.0

    use_llm_confidence = bool(quality_settings.get("use_llm_confidence", True))
    use_sam_score = bool(quality_settings.get("use_sam_score", True))
    use_consistency_check = bool(quality_settings.get("enable_consistency_check", False))

    if annotation.confidence is not None and use_llm_confidence:
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
        if use_sam_score:
            polygon_area = _polygon_area(annotation.polygon)
            bbox_area = max(1e-6, area)
            coverage = polygon_area / bbox_area
            if 0.55 <= coverage <= 1.02:
                score += 0.05
            elif coverage < 0.35 or coverage > 1.1:
                score -= 0.08
        if use_consistency_check:
            polygon_area = _polygon_area(annotation.polygon)
            bbox_area = max(1e-6, area)
            coverage = polygon_area / bbox_area
            if 0.45 <= coverage <= 1.0:
                score += 0.02
            else:
                score -= 0.04

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
    project = db.get(Project, image.project_id)
    project_settings = load_project_settings(project)
    quality_settings = project_settings.get("quality", {}) if isinstance(project_settings.get("quality"), dict) else {}

    if not annotations:
        if not bool(quality_settings.get("enable", True)):
            image.quality_score = None
        else:
            image.quality_score = None if image.status in ("pending", "annotating") else 0.0
        db.add(image)
        return image.quality_score

    scores: list[float] = []
    confirmed_count = 0
    for annotation in annotations:
        annotation.quality_score = estimate_annotation_quality(annotation, quality_settings=quality_settings)
        db.add(annotation)
        if annotation.quality_score is not None:
            scores.append(annotation.quality_score)
        if bool(annotation.is_confirmed):
            confirmed_count += 1

    if not bool(quality_settings.get("enable", True)):
        image.quality_score = None
        db.add(image)
        return image.quality_score

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
