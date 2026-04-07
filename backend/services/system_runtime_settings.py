from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from backend.config import DEFAULT_PROJECT_SETTINGS, deep_merge, get_settings


SYSTEM_RUNTIME_FILENAME = "runtime_settings.json"
SYSTEM_RUNTIME_DIRNAME = "system"
SYSTEM_RUNTIME_KEYS = ("model_profile", "llm", "sam", "postprocess", "quality", "evaluation")


def system_runtime_settings_path() -> Path:
    settings = get_settings()
    return (settings.resolved_data_dir / SYSTEM_RUNTIME_DIRNAME / SYSTEM_RUNTIME_FILENAME).resolve()


def default_system_runtime_settings() -> dict[str, Any]:
    return copy.deepcopy({key: DEFAULT_PROJECT_SETTINGS[key] for key in SYSTEM_RUNTIME_KEYS})


def filter_system_runtime_settings(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {key: copy.deepcopy(value) for key, value in payload.items() if key in SYSTEM_RUNTIME_KEYS}


def load_stored_system_runtime_settings() -> dict[str, Any]:
    path = system_runtime_settings_path()
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return filter_system_runtime_settings(payload if isinstance(payload, dict) else {})


def resolve_system_runtime_profile_name(stored: dict[str, Any] | None = None) -> str:
    from backend.services.system_profiles import AVAILABLE_PROFILES, detect_active_profile

    source = stored if stored is not None else load_stored_system_runtime_settings()
    requested = str(source.get("model_profile") or DEFAULT_PROJECT_SETTINGS["model_profile"]).strip()
    if requested == "auto":
        return detect_active_profile()
    if requested in AVAILABLE_PROFILES:
        return requested
    return detect_active_profile()


def merge_system_runtime_settings(stored: dict[str, Any] | None = None) -> dict[str, Any]:
    from backend.services.system_profiles import read_system_profile

    stored_payload = filter_system_runtime_settings(
        stored if stored is not None else load_stored_system_runtime_settings()
    )
    resolved = default_system_runtime_settings()
    requested_profile = str(stored_payload.get("model_profile") or DEFAULT_PROJECT_SETTINGS["model_profile"]).strip()

    if requested_profile != "fixed":
        try:
            profile = read_system_profile(resolve_system_runtime_profile_name(stored_payload))
            profile_defaults = filter_system_runtime_settings(profile.get("project_defaults"))
            if profile_defaults:
                resolved = deep_merge(resolved, profile_defaults)
        except Exception:
            resolved = default_system_runtime_settings()

    return deep_merge(resolved, stored_payload)


def load_system_runtime_settings() -> dict[str, Any]:
    return merge_system_runtime_settings(load_stored_system_runtime_settings())


def build_system_runtime_settings_response(stored: dict[str, Any] | None = None) -> dict[str, Any]:
    from backend.services.settings_service import runtime_settings_metadata
    from backend.services.system_profiles import detect_active_profile

    payload = merge_system_runtime_settings(stored)
    payload["_meta"] = runtime_settings_metadata()
    payload["_meta"]["active_system_profile"] = detect_active_profile()
    payload["_meta"]["resolved_runtime_profile"] = resolve_system_runtime_profile_name(stored=stored)
    payload["_meta"]["storage_path"] = display_system_runtime_settings_path()
    return payload


def save_system_runtime_settings(stored: dict[str, Any]) -> Path:
    path = system_runtime_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(filter_system_runtime_settings(stored), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def display_system_runtime_settings_path() -> str:
    path = system_runtime_settings_path()
    settings = get_settings()
    try:
        return path.relative_to(settings.root_dir).as_posix()
    except Exception:
        return path.as_posix()
