from __future__ import annotations

from sqlalchemy import Engine, event, text
from sqlalchemy.engine import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import get_settings
from backend.models.base import Base


def _create_engine() -> Engine:
    settings = get_settings()
    engine = create_engine(
        settings.resolved_database_url,
        connect_args={"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        if settings.resolved_database_url.startswith("sqlite"):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.close()

    return engine


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)

    # lightweight sanity check (also warms up the connection)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

