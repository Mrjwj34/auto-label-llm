from __future__ import annotations

import copy
from typing import Any

from backend.api import AppError
from backend.config import DEFAULT_PROJECT_SETTINGS
from backend.models.project import Project


HOT_RELOAD_PATHS = (
    "labels",
    "quality.enable",
    "quality.threshold_review",
    "quality.threshold_ok",
    "quality.use_llm_confidence",
    "quality.use_sam_score",
    "quality.enable_consistency_check",
    "evaluation.split",
    "evaluation.iou_threshold",
    "evaluation.max_samples",
    "llm.max_tokens",
    "postprocess.enable_close",
    "postprocess.close_kernel",
    "postprocess.enable_dp_simplify",
    "postprocess.epsilon_ratio",
    "postprocess.min_area_ratio",
)
RELOAD_REQUIRED_PATHS = (
    "model_profile",
    "active_model_tag",
    "llm.base_model",
    "llm.auto_order",
    "sam.checkpoint",
    "sam.device",
    "sam.multimask_output",
)
MODEL_PROFILES = ("auto", "fixed", "dev_low_resource", "test_real_stack", "demo_prod")


def merged_project_settings(project: Project | None, stored: dict[str, Any] | None = None) -> dict[str, Any]:
    from backend.services.project_settings import load_project_settings, merge_project_settings

    if stored is not None:
        return merge_project_settings(stored, project=project)
    return load_project_settings(project)


def build_project_settings_response(project: Project | None, stored: dict[str, Any] | None = None) -> dict[str, Any]:
    from backend.services.project_settings import resolve_project_profile_name
    from backend.services.system_profiles import detect_active_profile

    merged = merged_project_settings(project, stored=stored)
    payload = copy.deepcopy(merged)
    payload["_meta"] = settings_metadata()
    payload["_meta"]["active_system_profile"] = detect_active_profile()
    payload["_meta"]["resolved_project_profile"] = resolve_project_profile_name(project, stored=stored)
    return payload


def sanitize_project_settings_patch(patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise AppError(400, "settings patch must be an object")

    cleaned: dict[str, Any] = {}
    for key, value in patch.items():
        if key not in DEFAULT_PROJECT_SETTINGS:
            raise AppError(400, f"unknown settings key: {key}")
        cleaned[key] = _sanitize_root_value(key, value)
    return cleaned


def settings_change_summary(patch: dict[str, Any]) -> dict[str, Any]:
    changed_paths = sorted(_leaf_paths(patch))
    hot_paths = [path for path in changed_paths if path in HOT_RELOAD_PATHS]
    reload_paths = [path for path in changed_paths if path in RELOAD_REQUIRED_PATHS]
    other_paths = [path for path in changed_paths if path not in HOT_RELOAD_PATHS and path not in RELOAD_REQUIRED_PATHS]
    return {
        "changed_paths": changed_paths,
        "hot_reload_paths": hot_paths,
        "reload_required_paths": reload_paths,
        "other_paths": other_paths,
        "reload_required": len(reload_paths) > 0,
        "message": _build_change_message(hot_paths, reload_paths),
    }


def settings_metadata() -> dict[str, Any]:
    return {
        "hot_reload_paths": list(HOT_RELOAD_PATHS),
        "reload_required_paths": list(RELOAD_REQUIRED_PATHS),
        "available_model_profiles": list(MODEL_PROFILES),
        "note": "Hot-reload fields affect new tasks immediately after save. Reload-required fields need explicit profile/model reload or service restart.",
    }


def _sanitize_root_value(key: str, value: Any) -> Any:
    if key == "labels":
        return _sanitize_labels(value)
    if key == "model_profile":
        return _sanitize_model_profile(value)
    if key == "active_model_tag":
        return _sanitize_string(value, field_name="active_model_tag", min_length=1, max_length=200)
    if key == "llm":
        return _sanitize_llm_settings(value)
    if key == "sam":
        return _sanitize_sam_settings(value)
    if key == "postprocess":
        return _sanitize_postprocess_settings(value)
    if key == "quality":
        return _sanitize_quality_settings(value)
    if key == "evaluation":
        return _sanitize_evaluation_settings(value)
    raise AppError(400, f"unsupported settings key: {key}")


def _sanitize_labels(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise AppError(400, "labels must be a list of strings")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise AppError(400, "labels must be a list of strings")
        label = item.strip()
        if not label:
            continue
        if len(label) > 200:
            raise AppError(400, "label too long")
        if label in seen:
            continue
        cleaned.append(label)
        seen.add(label)
    return cleaned


def _sanitize_model_profile(value: Any) -> str:
    text = _sanitize_string(value, field_name="model_profile", min_length=1, max_length=50)
    if text not in MODEL_PROFILES:
        raise AppError(400, f"model_profile must be one of: {', '.join(MODEL_PROFILES)}")
    return text


def _sanitize_llm_settings(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppError(400, "llm settings must be an object")
    allowed = {"base_model", "auto_order", "max_tokens"}
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if key not in allowed:
            raise AppError(400, f"unknown llm setting: {key}")
        if key == "base_model":
            cleaned[key] = _sanitize_string(item, field_name="llm.base_model", min_length=1, max_length=200)
        elif key == "auto_order":
            if not isinstance(item, list):
                raise AppError(400, "llm.auto_order must be a list of strings")
            cleaned[key] = [
                _sanitize_string(entry, field_name="llm.auto_order[]", min_length=1, max_length=100) for entry in item
            ]
        elif key == "max_tokens":
            cleaned[key] = _sanitize_int(item, field_name="llm.max_tokens", min_value=64, max_value=8192)
    return cleaned


def _sanitize_sam_settings(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppError(400, "sam settings must be an object")
    allowed = {"checkpoint", "device", "multimask_output"}
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if key not in allowed:
            raise AppError(400, f"unknown sam setting: {key}")
        if key == "checkpoint":
            cleaned[key] = _sanitize_string(item, field_name="sam.checkpoint", min_length=1, max_length=200)
        elif key == "device":
            text = _sanitize_string(item, field_name="sam.device", min_length=1, max_length=20)
            if text not in ("cpu", "cuda"):
                raise AppError(400, "sam.device must be one of cpu or cuda")
            cleaned[key] = text
        elif key == "multimask_output":
            cleaned[key] = _sanitize_bool(item, field_name="sam.multimask_output")
    return cleaned


def _sanitize_postprocess_settings(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppError(400, "postprocess settings must be an object")
    allowed = {"enable_close", "close_kernel", "enable_dp_simplify", "epsilon_ratio", "min_area_ratio"}
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if key not in allowed:
            raise AppError(400, f"unknown postprocess setting: {key}")
        if key in ("enable_close", "enable_dp_simplify"):
            cleaned[key] = _sanitize_bool(item, field_name=f"postprocess.{key}")
        elif key == "close_kernel":
            cleaned[key] = _sanitize_int(item, field_name="postprocess.close_kernel", min_value=1, max_value=31)
        elif key == "epsilon_ratio":
            cleaned[key] = _sanitize_float(item, field_name="postprocess.epsilon_ratio", min_value=0.0, max_value=1.0)
        elif key == "min_area_ratio":
            cleaned[key] = _sanitize_float(item, field_name="postprocess.min_area_ratio", min_value=0.0, max_value=1.0)
    return cleaned


def _sanitize_quality_settings(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppError(400, "quality settings must be an object")
    allowed = {
        "enable",
        "threshold_review",
        "threshold_ok",
        "use_llm_confidence",
        "use_sam_score",
        "enable_consistency_check",
    }
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if key not in allowed:
            raise AppError(400, f"unknown quality setting: {key}")
        if key in ("enable", "use_llm_confidence", "use_sam_score", "enable_consistency_check"):
            cleaned[key] = _sanitize_bool(item, field_name=f"quality.{key}")
        elif key in ("threshold_review", "threshold_ok"):
            cleaned[key] = _sanitize_float(item, field_name=f"quality.{key}", min_value=0.0, max_value=1.0)
    return cleaned


def _sanitize_evaluation_settings(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppError(400, "evaluation settings must be an object")
    allowed = {"split", "iou_threshold", "max_samples"}
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if key not in allowed:
            raise AppError(400, f"unknown evaluation setting: {key}")
        if key == "split":
            text = _sanitize_string(item, field_name="evaluation.split", min_length=1, max_length=20)
            if text not in ("train", "val", "test"):
                raise AppError(400, "evaluation.split must be one of train, val or test")
            cleaned[key] = text
        elif key == "iou_threshold":
            cleaned[key] = _sanitize_float(item, field_name="evaluation.iou_threshold", min_value=0.0, max_value=1.0)
        elif key == "max_samples":
            if item is None or item == "":
                cleaned[key] = None
            else:
                cleaned[key] = _sanitize_int(item, field_name="evaluation.max_samples", min_value=1, max_value=100000)
    return cleaned


def _sanitize_string(value: Any, *, field_name: str, min_length: int, max_length: int) -> str:
    if not isinstance(value, str):
        raise AppError(400, f"{field_name} must be a string")
    text = value.strip()
    if len(text) < min_length:
        raise AppError(400, f"{field_name} is too short")
    if len(text) > max_length:
        raise AppError(400, f"{field_name} is too long")
    return text


def _sanitize_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise AppError(400, f"{field_name} must be a boolean")


def _sanitize_int(value: Any, *, field_name: str, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception as exc:  # noqa: BLE001
        raise AppError(400, f"{field_name} must be an integer") from exc
    if parsed < min_value or parsed > max_value:
        raise AppError(400, f"{field_name} must be within {min_value}..{max_value}")
    return parsed


def _sanitize_float(value: Any, *, field_name: str, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except Exception as exc:  # noqa: BLE001
        raise AppError(400, f"{field_name} must be a number") from exc
    if parsed < min_value or parsed > max_value:
        raise AppError(400, f"{field_name} must be within {min_value}..{max_value}")
    return round(parsed, 6)


def _leaf_paths(obj: dict[str, Any], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, value in obj.items():
        current = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and value:
            paths.update(_leaf_paths(value, current))
        else:
            paths.add(current)
    return paths


def _build_change_message(hot_paths: list[str], reload_paths: list[str]) -> str:
    if hot_paths and reload_paths:
        return "Saved settings. Some fields apply immediately, and some require an explicit reload."
    if reload_paths:
        return "Saved settings. These fields require an explicit reload before they affect new tasks."
    return "Saved settings. Changes apply to new tasks immediately."
