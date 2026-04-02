from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.annotation import Annotation
from backend.models.image import Image
from backend.models.project import Project
from backend.services.quality_service import refresh_image_quality
from backend.services.project_settings import get_project_labels, load_project_settings
from backend.services.sam_service import SAMService
from backend.utils.storage import resolve_path


ANNOTATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "confidence": {"type": "number"},
                    "bbox": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                },
                "required": ["label", "bbox"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["objects"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are an image annotation assistant for object detection. "
    "Return JSON only. Use only the provided labels. "
    "Each object must include a label, a normalized bbox [xmin, ymin, xmax, ymax] in 0..1, "
    "and an optional confidence in 0..1."
)


@dataclass
class GeneratedAnnotation:
    label: str
    bbox: list[float]
    confidence: float | None = None
    polygon: list[list[float]] | None = None
    mask_path: str | None = None


@dataclass
class AutoAnnotationResult:
    provider: str
    annotations: list[GeneratedAnnotation]
    warning: str | None = None


def _canonicalize_bbox(raw_bbox: Any) -> list[float] | None:
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return None

    try:
        xmin, ymin, xmax, ymax = [float(x) for x in raw_bbox]
    except Exception:
        return None

    if xmin > xmax:
        xmin, xmax = xmax, xmin
    if ymin > ymax:
        ymin, ymax = ymax, ymin

    xmin = max(0.0, min(1.0, xmin))
    ymin = max(0.0, min(1.0, ymin))
    xmax = max(0.0, min(1.0, xmax))
    ymax = max(0.0, min(1.0, ymax))

    if xmax - xmin < 1e-4 or ymax - ymin < 1e-4:
        return None

    return [round(xmin, 6), round(ymin, 6), round(xmax, 6), round(ymax, 6)]


def _normalize_confidence(raw_confidence: Any) -> float | None:
    if raw_confidence is None:
        return None
    try:
        value = float(raw_confidence)
    except Exception:
        return None
    return round(max(0.0, min(1.0, value)), 4)


def _normalize_label(raw_label: Any, allowed_labels: list[str]) -> str | None:
    if not isinstance(raw_label, str):
        return None

    cleaned = raw_label.strip()
    if not cleaned:
        return None

    allowed_map = {label.casefold(): label for label in allowed_labels}
    return allowed_map.get(cleaned.casefold())


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


def _extract_json_text(content: Any) -> str:
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        text = "\n".join(parts).strip()
    else:
        raise ValueError("unexpected model response content")

    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return text


def _normalize_response_payload(payload: Any, allowed_labels: list[str]) -> list[GeneratedAnnotation]:
    if not isinstance(payload, dict):
        return []

    raw_objects = payload.get("objects")
    if not isinstance(raw_objects, list):
        return []

    annotations: list[GeneratedAnnotation] = []
    for raw_object in raw_objects:
        if not isinstance(raw_object, dict):
            continue

        label = _normalize_label(raw_object.get("label"), allowed_labels)
        bbox = _canonicalize_bbox(raw_object.get("bbox"))
        if label is None or bbox is None:
            continue

        annotations.append(
            GeneratedAnnotation(
                label=label,
                bbox=bbox,
                confidence=_normalize_confidence(raw_object.get("confidence")),
            )
        )

    return _dedupe_annotations(annotations)


def _data_url_for_path(path: Path) -> str:
    content = path.read_bytes()
    mime_type, _ = mimetypes.guess_type(str(path))
    media_type = mime_type or "application/octet-stream"
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _chat_completions_url(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        return f"{root}/chat/completions"
    return f"{root}/v1/chat/completions"


def _stub_annotations(image: Image, labels: list[str]) -> list[GeneratedAnnotation]:
    path = resolve_path(image.file_path)
    digest = hashlib.sha512(path.read_bytes()).digest()

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


def _openai_compatible_annotations(project: Project, image: Image, labels: list[str]) -> list[GeneratedAnnotation]:
    settings = get_settings()
    project_settings = load_project_settings(project)
    llm_settings = project_settings.get("llm", {}) if isinstance(project_settings.get("llm"), dict) else {}

    model_name = str(llm_settings.get("base_model") or settings.vllm_model_name).strip()
    if not model_name:
        raise RuntimeError("no vLLM model configured")

    image_path = resolve_path(image.file_path)
    url = _chat_completions_url(settings.vllm_base_url)
    payload = {
        "model": model_name,
        "temperature": 0,
        "max_tokens": int(llm_settings.get("max_tokens") or settings.llm_max_tokens),
        "guided_json": ANNOTATION_SCHEMA,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Task type: {project.task_type}. "
                            f"Allowed labels: {', '.join(labels)}. "
                            "Detect visible objects/defects and return only the JSON object."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": _data_url_for_path(image_path)},
                    },
                ],
            },
        ],
    }

    headers = {"Content-Type": "application/json"}
    api_key = settings.vllm_api_key.strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    timeout = max(1.0, float(settings.llm_request_timeout_seconds))
    retries = max(0, int(settings.llm_max_retries))
    last_error: Exception | None = None

    for _attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()

            body = response.json()
            content = body["choices"][0]["message"]["content"]
            text = _extract_json_text(content)
            decoded = json.loads(text)
            annotations = _normalize_response_payload(decoded, labels)
            if annotations:
                return annotations
            raise RuntimeError("model returned no usable annotations")
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"openai-compatible annotation failed: {last_error}")


def _attach_segmentation_shapes(project: Project, image: Image, annotations: list[GeneratedAnnotation]) -> list[GeneratedAnnotation]:
    if project.task_type != "segmentation":
        return annotations

    sam = SAMService()
    enriched: list[GeneratedAnnotation] = []
    for annotation in annotations:
        prediction = sam.predict_polygon(image, annotation.bbox)
        enriched.append(
            GeneratedAnnotation(
                label=annotation.label,
                bbox=annotation.bbox,
                confidence=annotation.confidence,
                polygon=prediction.polygon,
                mask_path=prediction.mask_path,
            )
        )
    return enriched


def generate_auto_annotations(project: Project, image: Image) -> AutoAnnotationResult:
    labels = get_project_labels(project)
    if not labels:
        raise ValueError("project labels are empty; configure at least one label before auto annotation")

    settings = get_settings()
    backend_name = settings.annotation_backend
    warning: str | None = None

    if backend_name == "openai_compatible":
        try:
            annotations = _openai_compatible_annotations(project, image, labels)
            annotations = _attach_segmentation_shapes(project, image, annotations)
            return AutoAnnotationResult(provider="openai_compatible", annotations=annotations)
        except Exception as exc:
            warning = str(exc)

    annotations = _stub_annotations(image, labels)
    annotations = _attach_segmentation_shapes(project, image, annotations)
    return AutoAnnotationResult(provider="stub", annotations=annotations, warning=warning)


def replace_auto_annotations(db: Session, image: Image, result: AutoAnnotationResult) -> None:
    db.execute(
        delete(Annotation).where(
            Annotation.image_id == image.id,
            Annotation.source == "auto",
            Annotation.is_confirmed.is_(False),
        )
    )

    extra_payload = {"provider": result.provider}
    if result.warning:
        extra_payload["warning"] = result.warning
    extra_text = json.dumps(extra_payload, ensure_ascii=False)

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
