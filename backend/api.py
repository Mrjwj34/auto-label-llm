from __future__ import annotations

from typing import Any


def ok(data: Any = None, message: str = "ok", code: int = 200) -> dict[str, Any]:
    return {"code": code, "message": message, "data": data}


class AppError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message

