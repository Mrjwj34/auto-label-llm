from __future__ import annotations

import time
from contextlib import contextmanager
from uuid import uuid4

from backend.config import get_settings
from backend.services.redis_client import get_redis_client


class GPUBusyError(RuntimeError):
    pass


class GPULock:
    EXCLUSIVE_KEY = "auto_labeling:gpu:exclusive"
    SAM_ACTIVE_KEY = "auto_labeling:gpu:sam:active"
    SAM_TOKEN_KEY = "auto_labeling:gpu:sam:tokens"
    SAM_MUTEX_KEY = "auto_labeling:gpu:sam:mutex"

    @staticmethod
    @contextmanager
    def acquire_training(timeout: float | None = None, *, lock_timeout: int = 60 * 60):
        redis = get_redis_client()
        deadline = None if timeout is None else (time.monotonic() + max(0.0, timeout))
        blocking_timeout = None if deadline is None else max(0.0, timeout)
        lock = redis.lock(GPULock.EXCLUSIVE_KEY, timeout=lock_timeout)
        acquired = lock.acquire(blocking=True, blocking_timeout=blocking_timeout)
        if not acquired:
            raise GPUBusyError("GPU training lock is busy")
        try:
            while int(redis.get(GPULock.SAM_ACTIVE_KEY) or 0) > 0:
                if deadline is not None and time.monotonic() >= deadline:
                    raise GPUBusyError("GPU is busy with SAM tasks")
                time.sleep(0.1)
            yield
        finally:
            try:
                lock.release()
            except Exception:
                pass

    @staticmethod
    @contextmanager
    def acquire_model_reload(timeout: float | None = None):
        with GPULock.acquire_training(timeout=timeout):
            yield

    @staticmethod
    @contextmanager
    def acquire_sam(timeout: float | None = None):
        settings = get_settings()
        max_concurrency = max(1, int(settings.sam_max_concurrency))
        redis = get_redis_client()
        deadline = None if timeout is None else (time.monotonic() + max(0.0, timeout))
        token = uuid4().hex

        while True:
            with GPULock._sam_mutex(deadline):
                if redis.exists(GPULock.EXCLUSIVE_KEY):
                    acquired = False
                else:
                    active = int(redis.get(GPULock.SAM_ACTIVE_KEY) or 0)
                    if active < max_concurrency:
                        pipe = redis.pipeline()
                        pipe.incr(GPULock.SAM_ACTIVE_KEY)
                        pipe.sadd(GPULock.SAM_TOKEN_KEY, token)
                        pipe.execute()
                        acquired = True
                    else:
                        acquired = False

            if acquired:
                break
            if deadline is not None and time.monotonic() >= deadline:
                raise GPUBusyError("SAM GPU capacity is busy")
            time.sleep(0.1)

        try:
            yield
        finally:
            GPULock._release_sam_slot(redis, token)

    @staticmethod
    @contextmanager
    def _sam_mutex(deadline: float | None):
        redis = get_redis_client()
        blocking_timeout = 1.0
        if deadline is not None:
            blocking_timeout = max(0.0, min(1.0, deadline - time.monotonic()))
        lock = redis.lock(GPULock.SAM_MUTEX_KEY, timeout=1)
        acquired = lock.acquire(blocking=True, blocking_timeout=blocking_timeout)
        if not acquired:
            raise GPUBusyError("SAM GPU mutex is busy")
        try:
            yield
        finally:
            try:
                lock.release()
            except Exception:
                pass

    @staticmethod
    def _release_sam_slot(redis, token: str) -> None:
        deadline = time.monotonic() + 5.0
        while True:
            try:
                with GPULock._sam_mutex(deadline):
                    if redis.srem(GPULock.SAM_TOKEN_KEY, token):
                        active = max(0, int(redis.get(GPULock.SAM_ACTIVE_KEY) or 0) - 1)
                        pipe = redis.pipeline()
                        pipe.set(GPULock.SAM_ACTIVE_KEY, active)
                        if active == 0:
                            pipe.delete(GPULock.SAM_ACTIVE_KEY)
                        pipe.execute()
                    return
            except GPUBusyError:
                if time.monotonic() >= deadline:
                    return
                time.sleep(0.05)
