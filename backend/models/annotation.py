from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base

if TYPE_CHECKING:
    from backend.models.image import Image


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String, nullable=False)
    bbox: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)  # [xmin,ymin,xmax,ymax] normalized
    mask_path: Mapped[str | None] = mapped_column(String, nullable=True)
    polygon: Mapped[list[list[float]] | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, server_default="manual")  # auto|manual|corrected
    is_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)

    extra: Mapped[str | None] = mapped_column(Text, nullable=True)

    image: Mapped["Image"] = relationship(back_populates="annotations")

