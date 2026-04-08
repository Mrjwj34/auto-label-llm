from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections import defaultdict
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
from backend.tasks.task_manager import TaskContext, get_task_manager
from backend.utils.gpu_lock import GPULock


PROMPT_TEMPLATES = [
    "Detect all objects that belong to: {categories}. Return JSON with normalized bbox coordinates only.",
    "Find every visible instance of {categories}. Respond with JSON objects using [xmin, ymin, xmax, ymax].",
    "Annotate the image for categories {categories}. Output a JSON object with an objects array.",
]
TRAIN_PROGRESS_START = 25
TRAIN_PROGRESS_END = 95
TERMINAL_JOB_STATES = {"done", "failed"}


def _settings_paths() -> tuple[Path, Path]:
    settings = get_settings()
    model_root = (settings.root_dir / "models" / "lora").resolve()
    log_root = (settings.root_dir / "logs" / "finetune").resolve()
    model_root.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)
    return model_root, log_root


def _job_workspace_root(project_id: int, job_id: int) -> Path:
    root = Path(get_settings().resolved_data_dir) / "projects" / str(project_id) / "exports" / "finetune" / f"job_{job_id}"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


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


def generate_lora_config(project: Project, job_id: int) -> dict[str, Any]:
    vram_gb = detect_vram_gb()
    model_root, _log_root = _settings_paths()
    project_settings = load_project_settings(project)
    llm_settings = project_settings.get("llm", {}) if isinstance(project_settings.get("llm"), dict) else {}
    requested_base_model = str(llm_settings.get("base_model") or get_settings().vllm_model_name).strip()
    if not requested_base_model:
        raise AppError(400, "no base LLM model configured for finetune")
    model_name_or_path = _resolve_finetune_model_name(requested_base_model)

    workspace_dir = _job_workspace_root(project.id, job_id)
    output_dir = (model_root / str(job_id)).resolve()
    dataset_name = f"project_{project.id}_train"
    template = _resolve_llamafactory_template(model_name_or_path)
    precision = _resolve_training_precision(vram_gb)

    return {
        "project_id": project.id,
        "job_id": job_id,
        "runner_backend": "pending",
        "model_name_or_path": model_name_or_path,
        "requested_base_model": requested_base_model,
        "template": template,
        "finetuning_type": "lora",
        "stage": "sft",
        "do_train": True,
        "dataset": dataset_name,
        "dataset_dir": _store_path(workspace_dir),
        "dataset_info_path": _store_path(workspace_dir / "dataset_info.json"),
        "train_config_path": _store_path(workspace_dir / "llamafactory-train.yaml"),
        "output_dir": _store_path(output_dir),
        "per_device_train_batch_size": 1,
        "gradient_accumulation_steps": 8,
        "num_train_epochs": 3,
        "learning_rate": 1e-4,
        "cutoff_len": 4096,
        "logging_steps": 1,
        "save_steps": 50,
        "plot_loss": True,
        "report_to": "none",
        "warmup_ratio": 0.0,
        "lr_scheduler_type": "cosine",
        "preprocessing_num_workers": 1,
        "overwrite_cache": True,
        "overwrite_output_dir": True,
        "vram_gb": round(vram_gb, 2),
        "precision": precision,
        "runtime_lora_update": bool(get_settings().vllm_enable_runtime_lora_update),
    }


def _build_training_prompt(labels: list[str], image_id: int) -> str:
    categories = ", ".join(labels) if labels else "the configured labels"
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

    workspace_dir = _job_workspace_root(project.id, job_id)
    dataset_path = workspace_dir / f"project_{project.id}_train.jsonl"

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
                "conversations": [
                    {
                        "from": "human",
                        "value": f"<image>\n{_build_training_prompt(labels, image.id)}",
                    },
                    {
                        "from": "gpt",
                        "value": json.dumps({"objects": objects}, ensure_ascii=False),
                    },
                ],
                "images": [_resolve_path(image.file_path).as_posix()],
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
    log_text = read_finetune_log(job)
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
        "task_id": (config or {}).get("task_id"),
        "config": config,
        "metrics": parse_finetune_metrics(log_text),
    }


def create_finetune_job(project_id: int, db: Session) -> tuple[FinetuneJob, str]:
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

    config = generate_lora_config(project, job.id)
    _model_root, log_root = _settings_paths()
    log_path = log_root / f"{job.id}.log"
    log_path.write_text("", encoding="utf-8")

    job.log_path = _store_path(log_path)
    job.config = json.dumps(config, ensure_ascii=False)
    db.add(job)
    db.commit()
    db.refresh(job)

    task_id = get_task_manager().create(
        kind="finetune_job",
        payload={"job_id": job.id},
        queue="finetune",
    )
    config["task_id"] = task_id
    job.config = json.dumps(config, ensure_ascii=False)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job, task_id


def read_finetune_log(job: FinetuneJob) -> str:
    if not job.log_path:
        return ""
    log_path = _resolve_path(job.log_path)
    if not log_path.exists():
        return ""
    return log_path.read_text(encoding="utf-8")


def activate_finetune_job(job_id: int, db: Session) -> dict[str, Any]:
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

    return activate_project_model_tag(project, f"lora:{job.id}", db)


def run_finetune_job_task(job_id: int, *, ctx: TaskContext | None = None) -> None:
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

            config = _load_job_config(job)
            config["dataset_path"] = job.dataset_path
            config = _prepare_training_assets(project, job, config)
            runner_backend = _resolve_finetune_backend()
            config["runner_backend"] = runner_backend

            if runner_backend == "llamafactory":
                command = _resolve_llamafactory_command(required=True)
                config["runner_command"] = _display_command(command + ["train", str(_resolve_path(config["train_config_path"]))])
            else:
                config["runner_command"] = "mock-runner"

            job.config = json.dumps(config, ensure_ascii=False)
            db.add(job)
            db.commit()

            if ctx is not None:
                ctx.set_progress(15, f"finetune job #{job.id} dataset exported")

            log_path = _resolve_path(job.log_path or "")
            output_dir = _resolve_path(str(config.get("output_dir") or ""))
            output_dir.mkdir(parents=True, exist_ok=True)

            _append_log(log_path, f"Starting finetune job #{job.id} for project #{project.id}")
            _append_log(log_path, f"Dataset: {job.dataset_path}")
            _append_log(log_path, f"Train config: {config.get('train_config_path')}")
            _append_log(log_path, f"Runner backend: {runner_backend}")
            _append_log(log_path, "Waiting for exclusive GPU training lock.")
            if ctx is not None:
                ctx.set_progress(20, f"finetune job #{job.id} waiting for GPU lock")

            with GPULock.acquire_training():
                _append_log(log_path, "GPU training lock acquired.")
                if runner_backend == "llamafactory":
                    _run_llamafactory_training(job, project, config, log_path, ctx=ctx)
                else:
                    _run_mock_training(job, project, config, log_path, ctx=ctx)
                _append_log(log_path, "GPU training lock released.")

            _assert_finetune_output(output_dir, backend=runner_backend)
            _write_adapter_metadata(
                output_dir,
                {
                    "job_id": job.id,
                    "project_id": project.id,
                    "base_model": config.get("model_name_or_path"),
                    "dataset_path": job.dataset_path,
                    "train_config_path": config.get("train_config_path"),
                    "runner_backend": runner_backend,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            job.lora_path = _store_path(output_dir)
            job.status = "done"
            job.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(job)
            db.commit()
            _append_log(log_path, f"Saved adapter to {job.lora_path}")
            _append_log(log_path, "Finetune job completed successfully.")
            if ctx is not None:
                ctx.set_progress(100, f"finetune job #{job.id} completed")
    except Exception as exc:  # noqa: BLE001
        with session_factory() as db:
            job = db.get(FinetuneJob, job_id)
            if job is not None and job.status not in TERMINAL_JOB_STATES:
                job.status = "failed"
                job.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.add(job)
                db.commit()
            if job is not None and job.log_path:
                _append_log(_resolve_path(job.log_path), f"ERROR: {exc}")
        if ctx is not None:
            ctx.set_progress(100, f"finetune job failed: {exc}")


def parse_finetune_metrics(log_text: str) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for line in log_text.splitlines():
        point = _extract_metric_point(line)
        if point is None:
            continue
        key = (
            point.get("epoch"),
            point.get("epoch_total"),
            point.get("step"),
            point.get("loss"),
            point.get("learning_rate"),
        )
        if key in seen:
            continue
        seen.add(key)
        points.append(point)
    return points


def _prepare_training_assets(project: Project, job: FinetuneJob, config: dict[str, Any]) -> dict[str, Any]:
    dataset_path = _resolve_path(job.dataset_path or "")
    workspace_dir = _resolve_path(str(config.get("dataset_dir") or ""))
    dataset_info_path = _resolve_path(str(config.get("dataset_info_path") or ""))
    train_config_path = _resolve_path(str(config.get("train_config_path") or ""))
    output_dir = _resolve_path(str(config.get("output_dir") or ""))

    workspace_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset_info_payload = {
        str(config.get("dataset") or f"project_{project.id}_train"): {
            "file_name": dataset_path.name,
            "formatting": "sharegpt",
            "columns": {
                "messages": "conversations",
                "images": "images",
            },
            "tags": {
                "role_tag": "from",
                "content_tag": "value",
                "user_tag": "human",
                "assistant_tag": "gpt",
            },
        }
    }
    dataset_info_path.write_text(json.dumps(dataset_info_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    train_config_payload = _build_train_runtime_config(config)
    train_config_path.write_text(json.dumps(train_config_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    config["dataset_info_path"] = _store_path(dataset_info_path)
    config["train_config_path"] = _store_path(train_config_path)
    return config


def _build_train_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    precision = str(config.get("precision") or "fp16")
    return {
        "model_name_or_path": str(config.get("model_name_or_path") or ""),
        "template": str(config.get("template") or "default"),
        "finetuning_type": str(config.get("finetuning_type") or "lora"),
        "stage": str(config.get("stage") or "sft"),
        "do_train": True,
        "dataset": str(config.get("dataset") or ""),
        # LLaMA-Factory discovers dataset_info.json under dataset_dir automatically.
        "dataset_dir": _resolve_path(str(config.get("dataset_dir") or "")).as_posix(),
        "output_dir": _resolve_path(str(config.get("output_dir") or "")).as_posix(),
        "per_device_train_batch_size": int(config.get("per_device_train_batch_size") or 1),
        "gradient_accumulation_steps": int(config.get("gradient_accumulation_steps") or 8),
        "num_train_epochs": int(config.get("num_train_epochs") or 3),
        "learning_rate": float(config.get("learning_rate") or 1e-4),
        "cutoff_len": int(config.get("cutoff_len") or 4096),
        "logging_steps": int(config.get("logging_steps") or 1),
        "save_steps": int(config.get("save_steps") or 50),
        "plot_loss": bool(config.get("plot_loss", True)),
        "report_to": str(config.get("report_to") or "none"),
        "warmup_ratio": float(config.get("warmup_ratio") or 0.0),
        "lr_scheduler_type": str(config.get("lr_scheduler_type") or "cosine"),
        "preprocessing_num_workers": int(config.get("preprocessing_num_workers") or 1),
        "overwrite_output_dir": bool(config.get("overwrite_output_dir", True)),
        "overwrite_cache": bool(config.get("overwrite_cache", True)),
        "bf16": precision == "bf16",
        "fp16": precision == "fp16",
    }


def _load_job_config(job: FinetuneJob) -> dict[str, Any]:
    if not job.config:
        return {}
    try:
        payload = json.loads(job.config)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_finetune_backend() -> str:
    settings = get_settings()
    requested = settings.finetune_backend
    if requested == "mock":
        return "mock"
    if requested == "llamafactory":
        _resolve_llamafactory_command(required=True)
        return "llamafactory"
    return "llamafactory" if _resolve_llamafactory_command(required=False) else "mock"


def _resolve_llamafactory_command(*, required: bool) -> list[str] | None:
    settings = get_settings()
    raw = str(settings.llamafactory_cli or "").strip()
    if not raw:
        if required:
            raise RuntimeError("LLAMAFACTORY_CLI is empty")
        return None

    parts = shlex.split(raw, posix=os.name != "nt")
    if not parts:
        if required:
            raise RuntimeError("LLAMAFACTORY_CLI is empty")
        return None

    executable = parts[0]
    if Path(executable).exists():
        parts[0] = str(Path(executable).resolve())
        return parts

    resolved = shutil.which(executable)
    if resolved:
        parts[0] = resolved
        return parts

    venv_sibling = Path(sys.executable).resolve().parent / executable
    if venv_sibling.exists():
        parts[0] = str(venv_sibling)
        return parts

    if required:
        raise RuntimeError(f"LLaMA-Factory CLI was not found: {executable}")
    return None


def _run_mock_training(
    job: FinetuneJob,
    project: Project,
    config: dict[str, Any],
    log_path: Path,
    *,
    ctx: TaskContext | None,
) -> None:
    output_dir = _resolve_path(str(config.get("output_dir") or ""))
    epoch_count = int(config.get("num_train_epochs") or 3)
    losses = [0.612, 0.431, 0.298, 0.221, 0.187]
    trainer_history: list[dict[str, Any]] = []

    _append_log(log_path, "Mock finetune runner selected. Set FINETUNE_BACKEND=llamafactory to use real subprocess training.")
    if ctx is not None:
        ctx.set_progress(TRAIN_PROGRESS_START, f"finetune job #{job.id} training started")

    for epoch in range(1, epoch_count + 1):
        time.sleep(0.35)
        loss = losses[min(epoch - 1, len(losses) - 1)]
        lr = round(float(config.get("learning_rate") or 1e-4), 8)
        _append_log(log_path, f"Epoch {epoch}/{epoch_count} | loss: {loss:.3f} | lr: {lr:.6f}")
        trainer_history.append({"epoch": epoch, "loss": loss, "learning_rate": lr, "step": epoch})
        if ctx is not None:
            progress = _progress_from_epoch(epoch, epoch_count)
            ctx.set_progress(progress, f"epoch {epoch}/{epoch_count} loss={loss:.3f}")

    (output_dir / "adapter_config.json").write_text(
        json.dumps(
            {
                "job_id": job.id,
                "project_id": project.id,
                "base_model": config.get("model_name_or_path"),
                "peft_type": "LORA",
                "r": 8,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "adapter_model.safetensors").write_text("mock lora weights\n", encoding="utf-8")
    (output_dir / "trainer_state.json").write_text(
        json.dumps({"log_history": trainer_history}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_llamafactory_training(
    job: FinetuneJob,
    project: Project,
    config: dict[str, Any],
    log_path: Path,
    *,
    ctx: TaskContext | None,
) -> None:
    command = _resolve_llamafactory_command(required=True)
    if command is None:
        raise RuntimeError("LLaMA-Factory CLI is unavailable")

    config_path = _resolve_path(str(config.get("train_config_path") or ""))
    full_command = [*command, "train", str(config_path)]
    env = os.environ.copy()
    env["AUTO_LABELING_FINETUNE_JOB_ID"] = str(job.id)
    env["AUTO_LABELING_PROJECT_ID"] = str(project.id)
    env["AUTO_LABELING_OUTPUT_DIR"] = _resolve_path(str(config.get("output_dir") or "")).as_posix()
    env["AUTO_LABELING_DATASET_PATH"] = _resolve_path(str(config.get("dataset_path") or "")).as_posix()

    timeout_seconds = max(0, int(get_settings().finetune_timeout_seconds))
    started = time.monotonic()
    current_progress = TRAIN_PROGRESS_START
    _append_log(log_path, f"Launching LLaMA-Factory subprocess: {_display_command(full_command)}")
    if ctx is not None:
        ctx.set_progress(current_progress, f"finetune job #{job.id} training started")

    process = subprocess.Popen(  # noqa: S603
        full_command,
        cwd=str(get_settings().root_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if timeout_seconds and time.monotonic() - started > timeout_seconds:
                process.kill()
                process.wait(timeout=5.0)
                raise RuntimeError(f"LLaMA-Factory training timed out after {timeout_seconds} seconds")

            _append_log(log_path, line)
            metric = _extract_metric_point(line)
            if metric is None or ctx is None:
                continue

            next_progress = _progress_from_metric(metric, epoch_count=int(config.get("num_train_epochs") or 3))
            if next_progress > current_progress:
                current_progress = next_progress
            message = _trim_log_line(line)
            if next_progress > current_progress or message:
                ctx.set_progress(current_progress, message)

        return_code = process.wait()
    finally:
        if process.stdout is not None:
            process.stdout.close()

    if return_code != 0:
        raise RuntimeError(f"LLaMA-Factory subprocess exited with code {return_code}")


def _assert_finetune_output(output_dir: Path, *, backend: str) -> None:
    if not output_dir.exists():
        raise RuntimeError(f"{backend} finetune output directory was not created: {output_dir}")

    contents = list(output_dir.iterdir())
    if not contents:
        raise RuntimeError(f"{backend} finetune output directory is empty: {output_dir}")


def _write_adapter_metadata(output_dir: Path, payload: dict[str, Any]) -> None:
    metadata_path = output_dir / "auto_labeling_metadata.json"
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    adapter_config_path = output_dir / "adapter_config.json"
    if not adapter_config_path.exists():
        adapter_config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_llamafactory_template(base_model_name: str) -> str:
    lowered = base_model_name.casefold()
    if "qwen3" in lowered and "vl" in lowered:
        return "qwen3_vl"
    if "qwen" in lowered and "vl" in lowered:
        return "qwen2_vl"
    if "qwen" in lowered:
        return "qwen"
    return "default"


def _resolve_finetune_model_name(base_model_name: str) -> str:
    settings = get_settings()
    requested = str(base_model_name or "").strip()
    if not requested:
        return ""

    served_name = str(settings.vllm_model_name or "").strip()
    source_name = str(settings.vllm_model_source or "").strip()
    if source_name and served_name and requested == served_name:
        return source_name
    return requested


def _resolve_training_precision(vram_gb: float) -> str:
    return "bf16" if vram_gb >= 10 else "fp16"


def _progress_from_epoch(epoch: int, epoch_count: int) -> int:
    ratio = max(0.0, min(1.0, epoch / max(1, epoch_count)))
    return min(TRAIN_PROGRESS_END, int(TRAIN_PROGRESS_START + ratio * (TRAIN_PROGRESS_END - TRAIN_PROGRESS_START)))


def _extract_metric_point(line: str) -> dict[str, Any] | None:
    text = line.strip()
    if not text:
        return None

    epoch_match = re.search(
        r"Epoch\s+(?P<current>\d+(?:\.\d+)?)\s*/\s*(?P<total>\d+(?:\.\d+)?)(?:.*?loss\s*[:=]\s*(?P<loss>[0-9.]+))?",
        text,
        re.IGNORECASE,
    )
    if epoch_match:
        point: dict[str, Any] = {
            "epoch": float(epoch_match.group("current")),
            "epoch_total": float(epoch_match.group("total")),
            "raw": text,
        }
        if epoch_match.group("loss"):
            point["loss"] = round(float(epoch_match.group("loss")), 6)
        lr_value = _search_float(text, r"lr\s*[:=]\s*([0-9.eE+-]+)")
        if lr_value is not None:
            point["learning_rate"] = lr_value
        return point

    epoch_value = _search_float(text, r"(?:^|[{'\", ])epoch['\"]?\s*[:=]\s*([0-9.]+)")
    loss_value = _search_float(text, r"(?:^|[{'\", ])loss['\"]?\s*[:=]\s*([0-9.eE+-]+)")
    step_value = _search_int(text, r"(?:^|[{'\", ])step['\"]?\s*[:=]\s*(\d+)")
    lr_value = _search_float(text, r"(?:^|[{'\", ])learning_rate['\"]?\s*[:=]\s*([0-9.eE+-]+)")

    if epoch_value is None and loss_value is None and step_value is None and lr_value is None:
        return None

    point = {"raw": text}
    if epoch_value is not None:
        point["epoch"] = epoch_value
    if loss_value is not None:
        point["loss"] = loss_value
    if step_value is not None:
        point["step"] = step_value
    if lr_value is not None:
        point["learning_rate"] = lr_value
    return point


def _progress_from_metric(metric: dict[str, Any], *, epoch_count: int) -> int:
    epoch_value = float(metric.get("epoch") or 0.0)
    epoch_total = float(metric.get("epoch_total") or epoch_count or max(epoch_value, 1.0))
    if epoch_value > 0 and epoch_total > 0:
        ratio = max(0.0, min(1.0, epoch_value / epoch_total))
        return min(TRAIN_PROGRESS_END, int(TRAIN_PROGRESS_START + ratio * (TRAIN_PROGRESS_END - TRAIN_PROGRESS_START)))
    if metric.get("step") is not None:
        return min(TRAIN_PROGRESS_END - 2, TRAIN_PROGRESS_START + 5)
    return TRAIN_PROGRESS_START


def _trim_log_line(line: str, *, limit: int = 180) -> str:
    text = line.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _display_command(command: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return " ".join(shlex.quote(part) for part in command)


def _search_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    try:
        return round(float(match.group(1)), 6)
    except Exception:
        return None


def _search_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


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
