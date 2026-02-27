from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api import AppError, ok
from backend.config import get_settings
from backend.database import init_db
from backend.routers.health import router as health_router


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title="Auto Labeling System", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(_request, exc: AppError):  # type: ignore[no-untyped-def]
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code, "message": exc.message, "data": None},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_request, exc: StarletteHTTPException):  # type: ignore[no-untyped-def]
        code = int(getattr(exc, "status_code", 500))
        message = str(getattr(exc, "detail", "error"))
        return JSONResponse(status_code=code, content={"code": code, "message": message, "data": None})

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request, exc: RequestValidationError):  # type: ignore[no-untyped-def]
        return JSONResponse(
            status_code=400,
            content={"code": 400, "message": "invalid request", "data": {"detail": exc.errors()}},
        )

    @app.get("/healthz")
    async def healthz():
        return ok({"status": "ok"})

    app.include_router(health_router)

    @app.on_event("startup")
    async def _startup() -> None:
        init_db()

    return app

