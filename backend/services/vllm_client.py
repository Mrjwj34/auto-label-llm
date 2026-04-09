from __future__ import annotations

import base64
import json
import mimetypes
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from backend.api import AppError
from backend.config import get_settings
from backend.database import get_session_factory
from backend.models.finetune_job import FinetuneJob
from backend.models.project import Project
from backend.services.local_vllm_runtime import (
    ensure_local_managed_vllm_started,
    is_local_vllm_managed_for_settings,
)
from backend.services.project_settings import (
    load_project_settings,
    load_stored_project_settings,
    resolve_project_profile_name,
)
from backend.utils.gpu_lock import GPULock
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


@dataclass(frozen=True)
class GeneratedAnnotation:
    label: str
    bbox: list[float]
    confidence: float | None = None
    polygon: list[list[float]] | None = None
    mask_path: str | None = None


@dataclass(frozen=True)
class InferenceRoute:
    requested_model_tag: str
    effective_model_tag: str
    request_model_name: str
    base_model_name: str
    resolved_project_profile: str
    route_kind: str
    adapter_path: str | None = None
    finetune_job_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_model_tag": self.requested_model_tag,
            "effective_model_tag": self.effective_model_tag,
            "request_model_name": self.request_model_name,
            "base_model_name": self.base_model_name,
            "resolved_project_profile": self.resolved_project_profile,
            "route_kind": self.route_kind,
            "adapter_path": self.adapter_path,
            "finetune_job_id": self.finetune_job_id,
        }

    def short_label(self) -> str:
        text = f"tag={self.effective_model_tag}, model={self.request_model_name}"
        if self.route_kind == "lora" and self.base_model_name:
            return f"{text}, base={self.base_model_name}"
        return text


@dataclass(frozen=True)
class VLLMCallResult:
    route: InferenceRoute
    annotations: list[GeneratedAnnotation]


def build_grounding_prompt(*, labels: list[str], task_type: str) -> str:
    labels_text = ", ".join(labels) if labels else "none"
    return (
        f"Task type: {task_type}. "
        f"Allowed labels: {labels_text}. "
        "Detect visible objects/defects and return only the JSON object."
    )


def resolve_inference_route(
    project: Project,
    *,
    requested_model_tag: str | None = None,
    db: Session | None = None,
    project_settings: dict[str, Any] | None = None,
) -> InferenceRoute:
    settings = get_settings()
    resolved_settings = project_settings or load_project_settings(project)
    llm_settings = resolved_settings.get("llm", {}) if isinstance(resolved_settings.get("llm"), dict) else {}
    base_model_name = str(llm_settings.get("base_model") or settings.vllm_model_name).strip()
    if not base_model_name:
        raise AppError(400, "no base LLM model configured")

    resolved_profile = resolve_project_profile_name(project, stored=resolved_settings)
    requested = str(requested_model_tag or resolved_settings.get("active_model_tag") or "base").strip() or "base"

    if requested == "base":
        return InferenceRoute(
            requested_model_tag=requested,
            effective_model_tag="base",
            request_model_name=base_model_name,
            base_model_name=base_model_name,
            resolved_project_profile=resolved_profile,
            route_kind="base",
        )

    if requested.startswith("lora:"):
        job_id = _parse_lora_job_id(requested)
        job = _load_finetune_job(job_id, db=db)
        if job.project_id != project.id:
            raise AppError(400, f"LoRA job {job_id} does not belong to project {project.id}")
        if job.status != "done":
            raise AppError(400, f"LoRA job {job_id} is not ready")
        if not job.lora_path:
            raise AppError(400, f"LoRA job {job_id} does not have an output directory")

        job_base_model = _resolve_job_base_model(job) or base_model_name
        return InferenceRoute(
            requested_model_tag=requested,
            effective_model_tag=requested,
            request_model_name=requested,
            base_model_name=job_base_model,
            resolved_project_profile=resolved_profile,
            route_kind="lora",
            adapter_path=str(job.lora_path),
            finetune_job_id=job_id,
        )

    return InferenceRoute(
        requested_model_tag=requested,
        effective_model_tag=requested,
        request_model_name=requested,
        base_model_name=requested,
        resolved_project_profile=resolved_profile,
        route_kind="direct",
    )


def activate_project_model_tag(project: Project, model_tag: str, db: Session) -> dict[str, Any]:
    cleaned_tag = str(model_tag).strip()
    if not cleaned_tag:
        raise AppError(400, "model_tag is required")

    route = resolve_inference_route(project, requested_model_tag=cleaned_tag, db=db)
    stored = load_stored_project_settings(project)
    previous_tag = str(stored.get("active_model_tag") or "base").strip() or "base"
    runtime_sync = sync_vllm_serving_runtime(project, previous_model_tag=previous_tag, target_route=route, db=db)
    stored["active_model_tag"] = route.effective_model_tag
    project.config = json.dumps(stored, ensure_ascii=False)
    db.add(project)
    db.commit()
    db.refresh(project)

    return {
        "active_model_tag": route.effective_model_tag,
        "route": route.to_dict(),
        "runtime_sync": runtime_sync,
        "message": f"Activated {route.short_label()}",
    }


def sync_vllm_serving_runtime(
    project: Project,
    *,
    previous_model_tag: str,
    target_route: InferenceRoute,
    db: Session | None = None,
) -> dict[str, Any]:
    local_result = _sync_local_managed_vllm_runtime(
        project,
        previous_model_tag=previous_model_tag,
        target_route=target_route,
        db=db,
    )
    if local_result is not None:
        return local_result
    return sync_vllm_runtime(project, previous_model_tag=previous_model_tag, target_route=target_route, db=db)


def _sync_local_managed_vllm_runtime(
    project: Project,
    *,
    previous_model_tag: str,
    target_route: InferenceRoute,
    db: Session | None = None,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not is_local_vllm_managed_for_settings(settings):
        return None
    if settings.annotation_backend != "openai_compatible":
        return None

    actions: list[dict[str, Any]] = []
    previous_tag = str(previous_model_tag or "base").strip() or "base"
    needs_lora_sync = previous_tag.startswith("lora:") or target_route.route_kind == "lora"

    with GPULock.acquire_model_reload():
        started = ensure_local_managed_vllm_started(enable_lora=target_route.route_kind == "lora")
        if started["status"] in {"started", "already_running"}:
            actions.append(
                {
                    "action": "start" if started["status"] == "started" else "reuse",
                    "pid": started.get("pid"),
                    "enable_lora": target_route.route_kind == "lora",
                }
            )

        if needs_lora_sync:
            runtime_result = _sync_vllm_runtime_actions(
                project,
                previous_model_tag=previous_tag,
                target_route=target_route,
                db=db,
                force_runtime_update=True,
                skip_previous_unload=started["status"] == "started",
            )
            actions.extend(runtime_result["actions"])

    message = "Local managed vLLM is ready for the requested route."
    if target_route.route_kind == "lora":
        message = f"Local managed vLLM is ready for {target_route.effective_model_tag}."
    return {
        "status": "synced",
        "mode": "local_managed_vllm",
        "actions": actions,
        "message": message,
    }


def run_openai_compatible_annotation(
    project: Project,
    image_path: Path,
    *,
    labels: list[str],
    route: InferenceRoute,
    max_tokens: int | None = None,
) -> VLLMCallResult:
    settings = get_settings()
    requested_max_tokens = int(max_tokens or settings.llm_max_tokens)
    payload = {
        "model": route.request_model_name,
        "temperature": 0,
        # Bounding-box JSON should stay terse, especially for LoRA adapters.
        "max_tokens": _cap_annotation_max_tokens(requested_max_tokens, route=route),
        "guided_json": ANNOTATION_SCHEMA,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": _annotation_user_text(labels=labels, task_type=project.task_type, route=route),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": _data_url_for_path(image_path)},
                    },
                ],
            },
        ],
    }
    chat_template_kwargs = _annotation_chat_template_kwargs(route)
    if chat_template_kwargs is not None:
        payload["chat_template_kwargs"] = chat_template_kwargs

    headers = {"Content-Type": "application/json"}
    api_key = settings.vllm_api_key.strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    timeout = _annotation_timeout_seconds(route)
    retries = max(0, int(settings.llm_max_retries))
    last_error: Exception | None = None

    for _attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(_chat_completions_url(settings.vllm_base_url), json=payload, headers=headers)
                response.raise_for_status()

            body = response.json()
            content = body["choices"][0]["message"]["content"]
            text = _extract_json_text(content)
            decoded = json.loads(text)
            annotations = _normalize_response_payload(decoded, labels)
            if annotations:
                return VLLMCallResult(route=route, annotations=annotations)
            raise RuntimeError("model returned no usable annotations")
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    raise RuntimeError(f"openai-compatible annotation failed: {last_error}")


def _parse_lora_job_id(model_tag: str) -> int:
    _, _, suffix = model_tag.partition(":")
    try:
        job_id = int(suffix)
    except Exception as exc:  # noqa: BLE001
        raise AppError(400, f"invalid LoRA model tag: {model_tag}") from exc
    if job_id <= 0:
        raise AppError(400, f"invalid LoRA model tag: {model_tag}")
    return job_id


def _load_finetune_job(job_id: int, *, db: Session | None = None) -> FinetuneJob:
    session_ctx = nullcontext(db) if db is not None else get_session_factory()()
    with session_ctx as lookup_db:
        job = lookup_db.get(FinetuneJob, job_id)
        if job is None:
            raise AppError(404, f"LoRA job {job_id} not found")
        return job


def _resolve_job_base_model(job: FinetuneJob) -> str | None:
    config = _load_json_dict(job.config)
    candidate = str(
        config.get("serving_base_model")
        or config.get("requested_base_model")
        or config.get("base_model")
        or config.get("model_name_or_path")
        or ""
    ).strip()
    if candidate:
        return candidate

    if not job.lora_path:
        return None
    adapter_config = resolve_path(str(Path(job.lora_path) / "adapter_config.json"))
    payload = _load_json_dict(adapter_config.read_text(encoding="utf-8")) if adapter_config.exists() else {}
    text = str(payload.get("base_model") or "").strip()
    return text or None


def _annotation_chat_template_kwargs(route: InferenceRoute) -> dict[str, Any] | None:
    # Qwen3 family defaults to thinking mode unless it is explicitly disabled.
    # For annotation JSON, long reasoning traces only add latency and can cause
    # LoRA routes to time out before returning a usable response.
    if _route_uses_qwen3_family(route):
        return {"enable_thinking": False}
    return None


def _annotation_user_text(*, labels: list[str], task_type: str, route: InferenceRoute) -> str:
    prompt = build_grounding_prompt(labels=labels, task_type=task_type)
    if _route_uses_qwen3_family(route):
        # Qwen3 also supports a prompt-level soft switch; keeping it alongside
        # chat_template_kwargs makes non-thinking mode more robust across routes.
        return f"/no_think\n{prompt}"
    return prompt


def _annotation_timeout_seconds(route: InferenceRoute) -> float:
    settings = get_settings()
    timeout = max(1.0, float(settings.llm_request_timeout_seconds))
    if route.route_kind == "lora":
        # Runtime LoRA on the 8B FP8 vision model is substantially slower than
        # the base route on 16GB cards; keep the task alive long enough for the
        # adapter request to finish instead of failing at the base-route timeout.
        return max(timeout, 600.0)
    return timeout


def _route_uses_qwen3_family(route: InferenceRoute) -> bool:
    for candidate in (
        route.request_model_name,
        route.base_model_name,
        route.effective_model_tag,
        route.requested_model_tag,
    ):
        text = str(candidate or "").strip().lower()
        if "qwen3" in text:
            return True
    return False


def _load_json_dict(raw_text: str | None) -> dict[str, Any]:
    if not raw_text:
        return {}
    try:
        loaded = json.loads(raw_text)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _canonicalize_bbox(raw_bbox: Any) -> list[float] | None:
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return None

    try:
        xmin, ymin, xmax, ymax = [float(x) for x in raw_bbox]
    except Exception:
        return None

    max_coordinate = max(abs(xmin), abs(ymin), abs(xmax), abs(ymax))
    if max_coordinate > 1.0:
        if max_coordinate <= 1000.0:
            xmin /= 1000.0
            ymin /= 1000.0
            xmax /= 1000.0
            ymax /= 1000.0
        else:
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
            if item.get("type") in {"text", "output_text"} and isinstance(item.get("text"), str):
                parts.append(item["text"])
        text = "\n".join(parts).strip()
    else:
        raise ValueError("unexpected model response content")

    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return text


def _normalize_response_payload(payload: Any, allowed_labels: list[str]) -> list[GeneratedAnnotation]:
    raw_objects: list[Any] | None = None
    if isinstance(payload, list):
        raw_objects = payload
    elif isinstance(payload, dict):
        maybe_objects = payload.get("objects")
        if isinstance(maybe_objects, list):
            raw_objects = maybe_objects

    if raw_objects is None:
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


def _cap_annotation_max_tokens(
    requested_max_tokens: int,
    *,
    route: InferenceRoute | None = None,
) -> int:
    settings = get_settings()
    requested = max(64, int(requested_max_tokens))
    route_cap = 128 if route is not None and route.route_kind != "base" else 256
    capped = min(requested, route_cap)
    context_window = max(0, int(settings.vllm_max_model_len or 0))
    if context_window <= 0:
        return capped
    # Leave room for prompt and image tokens; annotation JSON should be short.
    return min(capped, max(64, context_window // 8))


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


def sync_vllm_runtime(
    project: Project,
    *,
    previous_model_tag: str,
    target_route: InferenceRoute,
    db: Session | None = None,
) -> dict[str, Any]:
    return _sync_vllm_runtime_actions(
        project,
        previous_model_tag=previous_model_tag,
        target_route=target_route,
        db=db,
        force_runtime_update=False,
        skip_previous_unload=False,
    )


def _sync_vllm_runtime_actions(
    project: Project,
    *,
    previous_model_tag: str,
    target_route: InferenceRoute,
    db: Session | None = None,
    force_runtime_update: bool,
    skip_previous_unload: bool,
) -> dict[str, Any]:
    settings = get_settings()
    if not force_runtime_update and not settings.vllm_enable_runtime_lora_update:
        return {
            "status": "skipped",
            "mode": "disabled",
            "actions": [],
            "message": "Runtime LoRA sync is disabled; only project routing metadata was updated.",
        }

    if settings.annotation_backend != "openai_compatible":
        return {
            "status": "skipped",
            "mode": "annotation_backend",
            "actions": [],
            "message": "Runtime LoRA sync requires ANNOTATION_BACKEND=openai_compatible.",
        }

    actions: list[dict[str, Any]] = []
    previous_tag = str(previous_model_tag or "base").strip() or "base"

    if (
        not skip_previous_unload
        and previous_tag.startswith("lora:")
        and previous_tag != target_route.effective_model_tag
    ):
        previous_route: InferenceRoute | None
        try:
            previous_route = resolve_inference_route(project, requested_model_tag=previous_tag, db=db)
        except AppError:
            previous_route = None
        if previous_route is not None and previous_route.route_kind == "lora":
            _post_vllm_runtime(
                "/v1/unload_lora_adapter",
                {"lora_name": previous_route.effective_model_tag},
            )
            actions.append({"action": "unload", "model_tag": previous_route.effective_model_tag})

    if target_route.route_kind == "lora":
        if not target_route.adapter_path:
            raise AppError(400, f"LoRA route {target_route.effective_model_tag} is missing adapter_path")
        _post_vllm_runtime(
            "/v1/load_lora_adapter",
            {
                "lora_name": target_route.effective_model_tag,
                "lora_path": resolve_path(target_route.adapter_path).as_posix(),
                "base_model_name": target_route.base_model_name,
                "load_inplace": True,
            },
        )
        actions.append(
            {
                "action": "load",
                "model_tag": target_route.effective_model_tag,
                "adapter_path": target_route.adapter_path,
            }
        )

    return {
        "status": "synced",
        "mode": "vllm_runtime_api",
        "actions": actions,
        "message": "Runtime LoRA sync finished.",
    }


def _post_vllm_runtime(path: str, payload: dict[str, Any]) -> None:
    settings = get_settings()
    timeout = max(5.0, float(settings.llm_request_timeout_seconds))
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(_vllm_api_url(settings.vllm_base_url, path), json=payload, headers=_vllm_headers())
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if response.status_code == 404 and path in {"/v1/load_lora_adapter", "/v1/unload_lora_adapter"}:
                    raise AppError(
                        502,
                        "vLLM runtime LoRA routes are unavailable. Restart vLLM with "
                        "--enable-lora and VLLM_ALLOW_RUNTIME_LORA_UPDATING=1.",
                    ) from exc
                raise
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AppError(502, f"vLLM runtime sync failed: {exc}") from exc


def _vllm_headers() -> dict[str, str]:
    settings = get_settings()
    headers = {"Content-Type": "application/json"}
    api_key = settings.vllm_api_key.strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _vllm_api_url(base_url: str, path: str) -> str:
    root = base_url.rstrip("/")
    normalized_path = path if path.startswith("/") else f"/{path}"
    if root.endswith("/v1") and normalized_path.startswith("/v1/"):
        normalized_path = normalized_path[3:]
    return f"{root}{normalized_path}"
