from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api import ok
from backend.services.system_profiles import (
    activate_system_model_profile,
    activate_system_profile,
    system_config_payload,
)


router = APIRouter(prefix="/api/system", tags=["system"])


class SystemProfileActivateIn(BaseModel):
    profile: str


@router.get("/config")
def get_system_config():
    return ok(system_config_payload())


@router.post("/profiles/activate")
def post_activate_system_profile(payload: SystemProfileActivateIn):
    result = activate_system_profile(payload.profile)
    return ok(result, message=result["message"])


@router.post("/model/activate")
def post_activate_model_profile(payload: SystemProfileActivateIn):
    result = activate_system_model_profile(payload.profile)
    return ok(result, message=result["message"])
