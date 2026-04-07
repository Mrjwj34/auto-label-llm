from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api import ok
from backend.services.settings_service import sanitize_system_settings_patch, settings_change_summary
from backend.services.system_profiles import (
    activate_system_model_profile,
    activate_system_profile,
    system_config_payload,
)
from backend.services.system_runtime_settings import (
    build_system_runtime_settings_response,
    load_stored_system_runtime_settings,
    save_system_runtime_settings,
)


router = APIRouter(prefix="/api/system", tags=["system"])


class SystemProfileActivateIn(BaseModel):
    profile: str


@router.get("/config")
def get_system_config():
    return ok(system_config_payload())


@router.get("/settings")
def get_system_settings():
    return ok(build_system_runtime_settings_response())


@router.patch("/settings")
def patch_system_settings(patch: dict):
    cleaned_patch = sanitize_system_settings_patch(patch)
    stored = load_stored_system_runtime_settings()
    merged = dict(stored)
    for key, value in cleaned_patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value

    save_system_runtime_settings(merged)
    summary = settings_change_summary(cleaned_patch)
    settings_payload = build_system_runtime_settings_response(stored=merged)
    return ok({"settings": settings_payload, "change": summary}, message=summary["message"])


@router.post("/profiles/activate")
def post_activate_system_profile(payload: SystemProfileActivateIn):
    result = activate_system_profile(payload.profile)
    return ok(result, message=result["message"])


@router.post("/model/activate")
def post_activate_model_profile(payload: SystemProfileActivateIn):
    result = activate_system_model_profile(payload.profile)
    return ok(result, message=result["message"])
