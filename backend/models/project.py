from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base

if TYPE_CHECKING:
    from backend.models.evaluation_run import EvaluationRun
    from backend.models.finetune_job import FinetuneJob
    from backend.models.image import Image


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    task_type: Mapped[str] = mapped_column(String, nullable=False)  # 'detection' | 'segmentation'
    config: Mapped[str] = mapped_column(Text, nullable=True)  # JSON string
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)

    images: Mapped[list["Image"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    evaluation_runs: Mapped[list["EvaluationRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    finetune_jobs: Mapped[list["FinetuneJob"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
