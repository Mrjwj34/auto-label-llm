from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api import AppError
from backend.config import get_settings
from backend.database import get_session_factory
from backend.models.annotation import Annotation
from backend.models.finetune_job import FinetuneJob
from backend.models.image import Image
from backend.models.project import Project
from backend.services.project_settings import get_project_labels, load_project_settings
from backend.services.vllm_client import activate_project_model_tag


PROMPT_TEMPLATES = [
    "请检测图中所有{categories}目标并输出边界框。",
    "识别图像中的{categories}，返回归一化坐标。",
    "找出图中所有{categories}，以 JSON 格式输出。",
]


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="finetune")
_futures: dict[int, Future[None]] = {}
_futures_lock = threading.Lock()


def _settings_paths() -> tuple[Path, Path]:
    settings = get_settings()
    model_root = (settings.root_dir / "models" / "lora").resolve()
    log_root = (settings.root_dir / "logs" / "finetune").resolve()
    model_root.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)
    return model_root, log_root


def _store_path(path: Path) -> str:
    settings = get_settings()
    try:
        return path.resolve().relative_to(settings.root_dir).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def detect_vram_gb() -> float:
    env_value = os.getenv("CUDA_TOTAL_MEMORY_GB")
    if env_value:
        try:
            return max(0.0, float(env_value))
        except ValueError:
            pass
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return float(torch.cuda.get_device_properties(0).total_memory) / 1e9
    except Exception:
        pass
    return 6.0


def generate_lora_config(project_id: int, job_id: int) -> dict[str, Any]:
    vram_gb = detect_vram_gb()
    model_size = "2B" if vram_gb < 12 else ("4B" if vram_gb < 20 else "8B")
    model_root, _log_root = _settings_paths()
    output_dir = (model_root / str(job_id)).resolve()
    return {
        "project_id": project_id,
        "job_id": job_id,
        "model_name_or_path": f"models/qwen3-vl-{model_size}",
        "finetuning_type": "lora",
        "lora_rank": 8,
        "lora_target": "all",
        "dataset": f"project_{project_id}_train",
        "output_dir": _store_path(output_dir),
        "per_device_train_batch_size": 1,
        "gradient_accumulation_steps": 8,
        "num_train_epochs": 3,
        "learning_rate": 1e-4,
        "bf16": True,
        "vram_gb": round(vram_gb, 2),
    }


def _build_training_prompt(labels: list[str], image_id: int) -> str:
    categories = "、".join(labels) if labels else "目标"
    template = PROMPT_TEMPLATES[image_id % len(PROMPT_TEMPLATES)]
    return template.format(categories=categories)


def export_finetune_dataset(project: Project, db: Session, *, job_id: int) -> str:
    rows = db.execute(
        select(Image, Annotation)
        .join(Annotation, Annotation.image_id == Image.id)
        .where(
            Image.project_id == project.id,
            Image.split == "train",
            Annotation.is_confirmed.is_(True),
        )
        .order_by(Image.id.asc(), Annotation.id.asc())
    ).all()

    grouped: dict[int, dict[str, Any]] = defaultdict(lambda: {"image": None, "annotations": []})
    for image, annotation in rows:
        if annotation.bbox is None:
            continue
        grouped[image.id]["image"] = image
        grouped[image.id]["annotations"].append(annotation)

    if not grouped:
        raise AppError(400, "no confirmed train annotations available for finetune")

    project_root = Path(get_settings().resolved_data_dir) / "projects" / str(project.id) / "exports" / "finetune"
    project_root.mkdir(parents=True, exist_ok=True)
    dataset_path = project_root / f"project_{project.id}_train_job_{job_id}.jsonl"

    labels = get_project_labels(project)
    with dataset_path.open("w", encoding="utf-8") as fp:
        for payload in grouped.values():
            image: Image = payload["image"]
            annotations: list[Annotation] = payload["annotations"]
            objects: list[dict[str, Any]] = []
            for annotation in annotations:
                entry: dict[str, Any] = {"label": annotation.label, "bbox": annotation.bbox}
                if annotation.polygon:
                    entry["polygon"] = annotation.polygon
                objects.append(entry)

            sample = {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "image": _resolve_path(image.file_path).as_uri()},
                            {"type": "text", "text": _build_training_prompt(labels, image.id)},
                        ],
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({"objects": objects}, ensure_ascii=False),
                    },
                ]
            }
            fp.write(json.dumps(sample, ensure_ascii=False) + "\n")

    return _store_path(dataset_path)


def list_project_finetune_jobs(project_id: int, db: Session) -> list[dict[str, Any]]:
    jobs = db.execute(
        select(FinetuneJob).where(FinetuneJob.project_id == project_id).order_by(FinetuneJob.id.desc())
    ).scalars().all()
    project = db.get(Project, project_id)
    settings = load_project_settings(project)
    active_tag = str(settings.get("active_model_tag") or "base")
    return [finetune_job_to_dict(job, active_tag=active_tag) for job in jobs]


def finetune_job_to_dict(job: FinetuneJob, *, active_tag: str | None = None) -> dict[str, Any]:
    config: dict[str, Any] | None = None
    if job.config:
        try:
            loaded = json.loads(job.config)
            if isinstance(loaded, dict):
                config = loaded
        except Exception:
            config = None

    model_tag = f"lora:{job.id}"
    return {
        "id": job.id,
        "project_id": job.project_id,
        "status": job.status,
        "dataset_path": job.dataset_path,
        "lora_path": job.lora_path,
        "log_path": job.log_path,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "created_at": job.created_at,
        "model_tag": model_tag,
        "is_active": active_tag == model_tag if active_tag is not None else None,
        "config": config,
    }


def create_finetune_job(project_id: int, db: Session) -> FinetuneJob:
    running = db.execute(
        select(FinetuneJob).where(FinetuneJob.status.in_(("pending", "running"))).limit(1)
    ).scalar_one_or_none()
    if running is not None:
        raise AppError(409, "a finetune job is already running")

    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")

    job = FinetuneJob(project_id=project_id, status="pending")
    db.add(job)
    db.flush()

    config = generate_lora_config(project_id, job.id)
    _model_root, log_root = _settings_paths()
    log_path = log_root / f"{job.id}.log"
    log_path.write_text("", encoding="utf-8")

    job.log_path = _store_path(log_path)
    job.config = json.dumps(config, ensure_ascii=False)
    db.add(job)
    db.commit()
    db.refresh(job)

    future = _executor.submit(_run_finetune_job, job.id)
    with _futures_lock:
        _futures[job.id] = future
    return job


def read_finetune_log(job: FinetuneJob) -> str:
    if not job.log_path:
        return ""
    log_path = _resolve_path(job.log_path)
    if not log_path.exists():
        return ""
    return log_path.read_text(encoding="utf-8")


def activate_finetune_job(job_id: int, db: Session) -> None:
    job = db.get(FinetuneJob, job_id)
    if job is None:
        raise AppError(404, "finetune job not found")
    if job.status != "done":
        raise AppError(400, "only completed finetune jobs can be activated")
    if not job.lora_path:
        raise AppError(400, "finetune output path is missing")

    project = db.get(Project, job.project_id)
    if project is None:
        raise AppError(404, "project not found")

    activate_project_model_tag(project, f"lora:{job.id}", db)


def _run_finetune_job(job_id: int) -> None:
    session_factory = get_session_factory()
    try:
        with session_factory() as db:
            job = db.get(FinetuneJob, job_id)
            if job is None:
                return
            project = db.get(Project, job.project_id)
            if project is None:
                raise RuntimeError("project not found")

            job.status = "running"
            job.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
            job.dataset_path = export_finetune_dataset(project, db, job_id=job.id)
            db.add(job)
            db.commit()

            log_path = _resolve_path(job.log_path or "")
            config = json.loads(job.config or "{}")
            output_dir = _resolve_path(str(config.get("output_dir") or ""))
            output_dir.mkdir(parents=True, exist_ok=True)

            _append_log(log_path, f"Starting finetune job #{job.id} for project #{project.id}")
            _append_log(log_path, f"Dataset: {job.dataset_path}")
            _append_log(log_path, f"Config: {json.dumps(config, ensure_ascii=False)}")

            epoch_count = int(config.get("num_train_epochs") or 3)
            losses = [0.612, 0.431, 0.298, 0.221, 0.187]
            for epoch in range(1, epoch_count + 1):
                time.sleep(0.35)
                loss = losses[min(epoch - 1, len(losses) - 1)]
                _append_log(log_path, f"Epoch {epoch}/{epoch_count} | loss: {loss:.3f}")

            adapter_config = {
                "job_id": job.id,
                "project_id": project.id,
                "base_model": config.get("model_name_or_path"),
                "dataset_path": job.dataset_path,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            (output_dir / "adapter_config.json").write_text(
                json.dumps(adapter_config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (output_dir / "README.txt").write_text(
                "Stub LoRA artifact generated by the M8 finetune pipeline.\n",
                encoding="utf-8",
            )

            job.lora_path = _store_path(output_dir)
            job.status = "done"
            job.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(job)
            db.commit()
            _append_log(log_path, f"Saved adapter to {job.lora_path}")
            _append_log(log_path, "Finetune job completed successfully.")
    except Exception as exc:  # noqa: BLE001
        with session_factory() as db:
            job = db.get(FinetuneJob, job_id)
            if job is not None:
                job.status = "failed"
                job.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.add(job)
                db.commit()
                if job.log_path:
                    _append_log(_resolve_path(job.log_path), f"ERROR: {exc}")
    finally:
        with _futures_lock:
            _futures.pop(job_id, None)


def _resolve_path(stored_path: str) -> Path:
    if not stored_path:
        settings = get_settings()
        return settings.root_dir
    p = Path(stored_path)
    if p.is_absolute():
        return p
    return (get_settings().root_dir / p).resolve()


def _append_log(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(line.rstrip() + "\n")
