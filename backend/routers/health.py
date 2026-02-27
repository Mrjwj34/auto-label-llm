from __future__ import annotations

from fastapi import APIRouter

from backend.api import ok


router = APIRouter()


@router.get("/api/health")
async def api_health():
    return ok({"status": "ok"})

