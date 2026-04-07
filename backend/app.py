from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api import AppError, ok
from backend.config import get_settings
from backend.database import init_db
from backend.routers.health import router as health_router
from backend.routers.annotations import router as annotations_router
from backend.routers.evaluations import router as evaluations_router
from backend.routers.finetune import router as finetune_router
from backend.routers.images import router as images_router
from backend.routers.projects import router as projects_router
from backend.routers.system import router as system_router
from backend.routers.tasks import router as tasks_router
from backend.services.redis_client import ping_redis
from backend.tasks.job_handlers import TASK_HANDLERS
from backend.tasks.worker import RedisTaskWorker


def _json_safe(value):  # type: ignore[no-untyped-def]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # noqa: ANN001
        init_db()
        ping_redis()
        worker: RedisTaskWorker | None = None
        if settings.task_embedded_worker:
            worker = RedisTaskWorker(handlers=TASK_HANDLERS).start_in_background()
        yield
        if worker is not None:
            worker.stop()

    app = FastAPI(title="Auto Labeling System", version="0.1.0", lifespan=lifespan)

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
            content={"code": 400, "message": "invalid request", "data": {"detail": _json_safe(exc.errors())}},
        )

    @app.get("/healthz")
    async def healthz():
        return ok({"status": "ok"})

    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(images_router)
    app.include_router(annotations_router)
    app.include_router(evaluations_router)
    app.include_router(finetune_router)
    app.include_router(system_router)
    app.include_router(tasks_router)

    return app
