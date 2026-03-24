from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    root_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    data_dir: Path | None = None
    database_url: str | None = None

    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    annotation_backend: Literal["stub", "openai_compatible"] = "stub"
    vllm_base_url: str = "http://127.0.0.1:8001"
    vllm_api_key: str = ""
    vllm_model_name: str = ""
    llm_request_timeout_seconds: float = 30.0
    llm_max_retries: int = 1
    llm_max_tokens: int = 2048

    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def resolved_data_dir(self) -> Path:
        return (self.data_dir or (self.root_dir / "data")).resolve()

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_path = self.resolved_data_dir / "app.db"
        # SQLAlchemy sqlite URL uses forward slashes; Path.as_posix() works on Windows too.
        return f"sqlite:///{db_path.as_posix()}"


DEFAULT_PROJECT_SETTINGS: dict[str, Any] = {
    # User-defined label list (fixed prompt; no free-form prompting by users)
    "labels": [],
    "model_profile": "auto",
    "llm": {"base_model": "qwen3-vl-2b", "auto_order": ["2b", "4b", "8b"], "max_tokens": 2048},
    "sam": {"checkpoint": "sam2_hiera_tiny", "device": "cuda", "multimask_output": False},
    "postprocess": {
        "enable_close": True,
        "close_kernel": 5,
        "enable_dp_simplify": True,
        "epsilon_ratio": 0.002,
        "min_area_ratio": 0.0005,
    },
    "quality": {
        "enable": True,
        "threshold_review": 0.6,
        "threshold_ok": 0.8,
        "use_llm_confidence": True,
        "use_sam_score": True,
        "enable_consistency_check": False,
    },
    "evaluation": {"split": "val", "iou_threshold": 0.5, "max_samples": None},
}


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)  # type: ignore[arg-type]
        else:
            merged[key] = value
    return merged


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    return settings
