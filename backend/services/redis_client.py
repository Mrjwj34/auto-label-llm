from __future__ import annotations

from functools import lru_cache
from typing import Any

import redis

from backend.config import get_settings


_FAKE_SERVERS: dict[str, Any] = {}


@lru_cache
def _get_redis_client(redis_url: str) -> redis.Redis:
    if redis_url.startswith("fakeredis://"):
        import fakeredis

        server = _FAKE_SERVERS.setdefault(redis_url, fakeredis.FakeServer())
        return fakeredis.FakeRedis(server=server, decode_responses=True)

    return redis.Redis.from_url(redis_url, decode_responses=True)


def get_redis_client() -> redis.Redis:
    return _get_redis_client(get_settings().redis_url)


def ping_redis() -> None:
    get_redis_client().ping()
