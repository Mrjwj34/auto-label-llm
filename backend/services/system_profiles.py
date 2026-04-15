from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.api import AppError
from backend.config import get_settings


ACTIVE_ENV_FILENAME = ".env.active"
FRONTEND_ENV_FILENAME = ".env.local"
PROFILE_DIRNAME = "configs/profiles"
AVAILABLE_PROFILES = ("dev_low_resource", "test_real_stack", "demo_prod")
SYSTEM_HOT_RELOAD_FIELDS = (
    "annotation_backend",
    "vllm_base_url",
    "vllm_model_name",
    "llm_request_timeout_seconds",
    "llm_max_retries",
    "llm_max_tokens",
)
SYSTEM_RESTART_REQUIRED_FIELDS = (
    "frontend.vite_env",
    "host",
    "port",
    "cors_allow_origins",
)


def profile_dir(root_dir: Path | None = None) -> Path:
    root = root_dir or get_settings().root_dir
    return (root / PROFILE_DIRNAME).resolve()


def active_backend_env_path(root_dir: Path | None = None) -> Path:
    root = root_dir or get_settings().root_dir
    return (root / ACTIVE_ENV_FILENAME).resolve()


def active_frontend_env_path(root_dir: Path | None = None) -> Path:
    root = root_dir or get_settings().root_dir
    return (root / "frontend" / FRONTEND_ENV_FILENAME).resolve()


def list_system_profiles(root_dir: Path | None = None) -> list[dict[str, Any]]:
    return [read_system_profile(name, root_dir=root_dir) for name in AVAILABLE_PROFILES]


def read_system_profile(name: str, *, root_dir: Path | None = None) -> dict[str, Any]:
    if name not in AVAILABLE_PROFILES:
        raise AppError(404, f"unknown profile: {name}")

    path = profile_dir(root_dir) / f"{name}.json"
    if not path.exists():
        raise AppError(500, f"profile definition missing: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AppError(500, f"invalid profile json: {exc}") from exc

    if not isinstance(payload, dict):
        raise AppError(500, f"invalid profile payload for {name}")

    backend_values = payload.get("backend")
    frontend_values = payload.get("frontend")
    project_defaults = payload.get("project_defaults")
    if not isinstance(backend_values, dict) or not isinstance(frontend_values, dict):
        raise AppError(500, f"profile sections missing for {name}")
    if project_defaults is not None and not isinstance(project_defaults, dict):
        raise AppError(500, f"invalid project_defaults for {name}")

    return {
        "name": str(payload.get("name") or name),
        "description": str(payload.get("description") or ""),
        "backend": backend_values,
        "frontend": frontend_values,
        "project_defaults": project_defaults or {},
    }


def detect_active_profile(root_dir: Path | None = None) -> str:
    env_path = active_backend_env_path(root_dir)
    if env_path.exists():
        parsed = parse_env_file(env_path)
        profile = str(parsed.get("APP_PROFILE") or "").strip()
        if profile in AVAILABLE_PROFILES:
            return profile

    return str(get_settings().app_profile or "dev_low_resource")


def activate_system_profile(name: str, *, root_dir: Path | None = None) -> dict[str, Any]:
    from backend.services.finetune_service import finetune_runtime_status

    profile = read_system_profile(name, root_dir=root_dir)
    backend_env = active_backend_env_path(root_dir)
    frontend_env = active_frontend_env_path(root_dir)

    write_env_file(backend_env, profile["backend"], header=f"Generated from profile: {name}")
    write_env_file(frontend_env, profile["frontend"], header=f"Generated from profile: {name}")

    get_settings.cache_clear()
    settings = get_settings()

    return {
        "active_profile": name,
        "backend_env_path": _display_path(backend_env, root_dir=root_dir),
        "frontend_env_path": _display_path(frontend_env, root_dir=root_dir),
        "backend_hot_reloaded_fields": list(SYSTEM_HOT_RELOAD_FIELDS),
        "restart_required_targets": ["frontend"],
        "runtime": {
            "app_profile": settings.app_profile,
            "annotation_backend": settings.annotation_backend,
            "vllm_base_url": settings.vllm_base_url,
            "vllm_model_name": settings.vllm_model_name,
            "llm_request_timeout_seconds": settings.llm_request_timeout_seconds,
            "llm_max_retries": settings.llm_max_retries,
            "llm_max_tokens": settings.llm_max_tokens,
            "finetune": finetune_runtime_status(),
        },
        "message": "Profile files updated. Backend settings cache cleared; restart frontend if Vite env values changed.",
    }


def activate_system_model_profile(name: str, *, root_dir: Path | None = None) -> dict[str, Any]:
    result = activate_system_profile(name, root_dir=root_dir)
    result["message"] = (
        "Base model profile switched. New backend runtime settings are active; frontend Vite env values still need a restart."
    )
    return result


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_env_file(path: Path, values: dict[str, Any], *, header: str | None = None) -> None:
    lines: list[str] = []
    if header:
        lines.append(f"# {header}")
    for key, value in values.items():
        lines.append(f"{key}={_format_env_value(value)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def system_config_payload(root_dir: Path | None = None) -> dict[str, Any]:
    from backend.services.finetune_service import finetune_runtime_status
    from backend.services.system_runtime_settings import build_system_runtime_settings_response

    settings = get_settings()
    return {
        "active_profile": detect_active_profile(root_dir=root_dir),
        "profiles": list_system_profiles(root_dir=root_dir),
        "settings": build_system_runtime_settings_response(),
        "env_files": {
            "backend": _display_path(active_backend_env_path(root_dir), root_dir=root_dir),
            "frontend": _display_path(active_frontend_env_path(root_dir), root_dir=root_dir),
        },
        "runtime": {
            "app_profile": settings.app_profile,
            "annotation_backend": settings.annotation_backend,
            "vllm_base_url": settings.vllm_base_url,
            "vllm_model_name": settings.vllm_model_name,
            "llm_request_timeout_seconds": settings.llm_request_timeout_seconds,
            "llm_max_retries": settings.llm_max_retries,
            "llm_max_tokens": settings.llm_max_tokens,
            "finetune": finetune_runtime_status(),
        },
        "metadata": {
            "hot_reload_fields": list(SYSTEM_HOT_RELOAD_FIELDS),
            "restart_required_fields": list(SYSTEM_RESTART_REQUIRED_FIELDS),
            "note": "Backend runtime fields can be refreshed after profile activation; frontend Vite env values need a restart.",
        },
    }


def _format_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _display_path(path: Path, *, root_dir: Path | None = None) -> str:
    root = root_dir or get_settings().root_dir
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return path.resolve().as_posix()
