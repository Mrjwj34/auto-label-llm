from __future__ import annotations

import uvicorn

from backend.app import create_app
from backend.config import get_settings


app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=True)


if __name__ == "__main__":
    main()

