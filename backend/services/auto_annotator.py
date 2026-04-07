from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.annotation import Annotation
from backend.models.image import Image
from backend.models.project import Project
from backend.services.postprocess import apply_project_postprocess
from backend.services.quality_service import refresh_image_quality
from backend.services.project_settings import get_project_labels, load_project_settings
from backend.services.sam_service import SAMService
from backend.services.vllm_client import (
    GeneratedAnnotation,
    InferenceRoute,
    resolve_inference_route,
    run_openai_compatible_annotation,
)
from backend.utils.storage import resolve_path


@dataclass
class AutoAnnotationResult:
    provider: str
    annotations: list[GeneratedAnnotation]
    route: InferenceRoute
    requested_backend: str
    fallback_used: bool = False
    warning: str | None = None

    def metadata(self) -> dict[str, Any]:
        payload = self.route.to_dict()
        payload["provider"] = self.provider
        payload["requested_backend"] = self.requested_backend
        payload["fallback_used"] = self.fallback_used
        payload["warning"] = self.warning
        return payload

    def runtime_label(self) -> str:
        text = f"{self.provider} [{self.route.short_label()}]"
        if self.fallback_used:
            return f"{text} (fallback)"
        return text


def _dedupe_annotations(annotations: list[GeneratedAnnotation]) -> list[GeneratedAnnotation]:
    unique: list[GeneratedAnnotation] = []
    seen: set[tuple[str, tuple[float, float, float, float]]] = set()
    for annotation in annotations:
        key = (annotation.label, tuple(round(v, 4) for v in annotation.bbox))
        if key in seen:
            continue
        seen.add(key)
        unique.append(annotation)
    return unique


def _stub_annotations(image: Image, labels: list[str], *, route: InferenceRoute) -> list[GeneratedAnnotation]:
    path = resolve_path(image.file_path)
    seed = (
        path.read_bytes()
        + route.effective_model_tag.encode("utf-8")
        + route.request_model_name.encode("utf-8")
        + route.resolved_project_profile.encode("utf-8")
    )
    digest = hashlib.sha512(seed).digest()

    max_objects = max(1, min(3, len(labels)))
    count = 1 + (digest[0] % max_objects)
    annotations: list[GeneratedAnnotation] = []

    aspect = 1.0
    if image.width and image.height and image.height > 0:
        aspect = image.width / image.height

    for idx in range(count):
        width = 0.2 + (digest[5 + idx] / 255.0) * 0.18
        height = 0.2 + (digest[11 + idx] / 255.0) * 0.18
        if aspect >= 1.5:
            width = min(0.42, width + 0.05)
            height = max(0.16, height - 0.03)
        elif aspect <= 0.8:
            width = max(0.16, width - 0.03)
            height = min(0.42, height + 0.05)

        margin = 0.04
        x_span = max(0.0, 1.0 - width - margin * 2)
        y_span = max(0.0, 1.0 - height - margin * 2)
        xmin = margin + (digest[19 + idx] / 255.0) * x_span
        ymin = margin + (digest[27 + idx] / 255.0) * y_span
        xmax = min(0.98, xmin + width)
        ymax = min(0.98, ymin + height)

        annotations.append(
            GeneratedAnnotation(
                label=labels[(digest[35 + idx] + idx) % len(labels)],
                bbox=[round(xmin, 6), round(ymin, 6), round(xmax, 6), round(ymax, 6)],
                confidence=round(0.58 + (digest[43 + idx] / 255.0) * 0.36, 4),
            )
        )

    return _dedupe_annotations(annotations)


def _openai_compatible_annotations(
    project: Project,
    image: Image,
    labels: list[str],
    *,
    route: InferenceRoute,
    project_settings: dict[str, Any],
) -> list[GeneratedAnnotation]:
    llm_settings = project_settings.get("llm", {}) if isinstance(project_settings.get("llm"), dict) else {}
    image_path = resolve_path(image.file_path)
    call = run_openai_compatible_annotation(
        project,
        image_path,
        labels=labels,
        route=route,
        max_tokens=int(llm_settings.get("max_tokens") or get_settings().llm_max_tokens),
    )
    return call.annotations


def _attach_segmentation_shapes(
    project: Project,
    image: Image,
    annotations: list[GeneratedAnnotation],
    *,
    project_settings: dict[str, Any],
) -> list[GeneratedAnnotation]:
    if project.task_type != "segmentation":
        return annotations

    sam = SAMService()
    sam_settings = project_settings.get("sam", {}) if isinstance(project_settings.get("sam"), dict) else {}
    sam_lock_timeout = float(get_settings().sam_lock_timeout_seconds)
    enriched: list[GeneratedAnnotation] = []
    for annotation in annotations:
        prediction = sam.predict_polygon(
            image,
            annotation.bbox,
            checkpoint=str(sam_settings.get("checkpoint") or "sam3"),
            device=str(sam_settings.get("device") or "cuda"),
            multimask_output=bool(sam_settings.get("multimask_output", False)),
            lock_timeout=sam_lock_timeout,
        )
        processed = apply_project_postprocess(
            project,
            image,
            mask=prediction.mask,
            bbox=prediction.bbox,
            provider=prediction.provider,
            score=prediction.score,
        )
        enriched.append(
            GeneratedAnnotation(
                label=annotation.label,
                bbox=processed.bbox or prediction.bbox or annotation.bbox,
                confidence=annotation.confidence,
                polygon=processed.polygon,
                mask_path=processed.mask_path,
            )
        )
    return enriched


def generate_auto_annotations(
    project: Project,
    image: Image,
    *,
    db: Session | None = None,
    requested_model_tag: str | None = None,
    project_settings: dict[str, Any] | None = None,
) -> AutoAnnotationResult:
    labels = get_project_labels(project)
    if not labels:
        raise ValueError("project labels are empty; configure at least one label before auto annotation")

    resolved_settings = project_settings or load_project_settings(project)
    route = resolve_inference_route(
        project,
        requested_model_tag=requested_model_tag,
        db=db,
        project_settings=resolved_settings,
    )
    settings = get_settings()
    backend_name = settings.annotation_backend
    warning: str | None = None

    if backend_name == "openai_compatible":
        try:
            annotations = _openai_compatible_annotations(
                project,
                image,
                labels,
                route=route,
                project_settings=resolved_settings,
            )
            annotations = _attach_segmentation_shapes(
                project,
                image,
                annotations,
                project_settings=resolved_settings,
            )
            return AutoAnnotationResult(
                provider="openai_compatible",
                annotations=annotations,
                route=route,
                requested_backend=backend_name,
            )
        except Exception as exc:
            warning = str(exc)

    annotations = _stub_annotations(image, labels, route=route)
    annotations = _attach_segmentation_shapes(
        project,
        image,
        annotations,
        project_settings=resolved_settings,
    )
    return AutoAnnotationResult(
        provider="stub",
        annotations=annotations,
        route=route,
        requested_backend=backend_name,
        fallback_used=backend_name == "openai_compatible",
        warning=warning,
    )


def replace_auto_annotations(db: Session, image: Image, result: AutoAnnotationResult) -> None:
    db.execute(
        delete(Annotation).where(
            Annotation.image_id == image.id,
            Annotation.source == "auto",
            Annotation.is_confirmed.is_(False),
        )
    )

    extra_text = json.dumps(result.metadata(), ensure_ascii=False)

    for generated in result.annotations:
        ann = Annotation(
            image_id=image.id,
            label=generated.label,
            bbox=generated.bbox,
            polygon=generated.polygon,
            mask_path=generated.mask_path,
            confidence=generated.confidence,
            source="auto",
            extra=extra_text,
        )
        db.add(ann)

    refresh_image_quality(db, image)
