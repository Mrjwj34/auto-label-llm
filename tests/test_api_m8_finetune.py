from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from PIL import Image as PILImage

from backend.config import get_settings
from backend.services import finetune_service
from backend.services import local_vllm_runtime
from backend.utils.storage import resolve_path


def _make_png_bytes(width: int = 120, height: int = 80, color: tuple[int, int, int] = (64, 140, 220)) -> bytes:
    img = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_confirmed_train_annotation(client, *, task_type: str = "detection") -> tuple[int, int]:
    project = client.post("/api/projects", json={"name": f"{task_type}-project", "task_type": task_type})
    assert project.status_code == 200
    project_id = project.json()["data"]["id"]

    patch = client.patch(f"/api/projects/{project_id}/settings", json={"labels": ["crack"]})
    assert patch.status_code == 200

    upload = client.post(
        f"/api/projects/{project_id}/images/upload",
        files=[("files[]", ("sample.png", _make_png_bytes(), "image/png"))],
    )
    assert upload.status_code == 200
    image_id = upload.json()["data"]["image_ids"][0]

    if task_type == "segmentation":
        create = client.post(
            f"/api/images/{image_id}/predict",
            json={"annotation_id": None, "label": "crack", "bbox": [0.2, 0.25, 0.65, 0.75]},
        )
        assert create.status_code == 200
        annotation_id = create.json()["data"]["annotation_id"]
    else:
        create = client.post(
            f"/api/images/{image_id}/annotations",
            json={"label": "crack", "bbox": [0.2, 0.25, 0.65, 0.75], "source": "manual"},
        )
        assert create.status_code == 200
        annotation_id = create.json()["data"]["id"]

    confirm = client.patch(f"/api/annotations/{annotation_id}/confirm")
    assert confirm.status_code == 200
    return project_id, image_id


def _poll_finetune_job(client, job_id: int, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    last_payload: dict | None = None
    while time.time() < deadline:
        resp = client.get(f"/api/finetune/{job_id}/status")
        assert resp.status_code == 200
        last_payload = resp.json()["data"]
        if last_payload["status"] in ("done", "failed"):
            return last_payload
        time.sleep(0.1)
    raise AssertionError(f"finetune job did not finish in time: {last_payload}")


def test_finetune_job_runs_exports_dataset_and_can_activate(client):
    project_id, _image_id = _create_confirmed_train_annotation(client, task_type="detection")

    start = client.post("/api/finetune/start", json={"project_id": project_id})
    assert start.status_code == 200
    job_id = start.json()["data"]["job_id"]

    final_status = _poll_finetune_job(client, job_id)
    assert final_status["status"] == "done"
    if final_status["config"]["runner_backend"] == "pending":
        status_resp = client.get(f"/api/finetune/{job_id}/status")
        assert status_resp.status_code == 200
        final_status = status_resp.json()["data"]

    assert final_status["model_tag"] == f"lora:{job_id}"
    assert final_status["dataset_path"]
    assert final_status["lora_path"]
    assert final_status["log_path"]
    assert final_status["config"]["dataset"] == f"project_{project_id}_train"
    assert final_status["config"]["runner_backend"] == "mock"
    assert final_status["config"]["dataset_info_path"]
    assert final_status["config"]["train_config_path"]
    assert len(final_status["metrics"]) >= 1

    dataset_path = resolve_path(final_status["dataset_path"])
    assert dataset_path.exists()
    sample = json.loads(dataset_path.read_text(encoding="utf-8").splitlines()[0])
    assert sample["conversations"][0]["from"] == "human"
    assert sample["conversations"][1]["from"] == "gpt"
    assert sample["images"]
    assistant_payload = json.loads(sample["conversations"][1]["value"])
    assert assistant_payload["objects"][0]["label"] == "crack"

    lora_dir = resolve_path(final_status["lora_path"])
    assert lora_dir.exists()
    assert (lora_dir / "adapter_config.json").exists()
    assert (lora_dir / "trainer_state.json").exists()

    log_resp = client.get(f"/api/finetune/{job_id}/log")
    assert log_resp.status_code == 200
    log_text = log_resp.json()["data"]["log"]
    assert "Epoch 1/3" in log_text
    assert "completed successfully" in log_text

    jobs_resp = client.get(f"/api/projects/{project_id}/finetune-jobs")
    assert jobs_resp.status_code == 200
    jobs = jobs_resp.json()["data"]
    assert len(jobs) == 1
    assert jobs[0]["id"] == job_id
    assert jobs[0]["is_active"] is False

    activate = client.post(f"/api/finetune/{job_id}/activate")
    assert activate.status_code == 200

    settings = client.get(f"/api/projects/{project_id}/settings")
    assert settings.status_code == 200
    assert settings.json()["data"]["active_model_tag"] == f"lora:{job_id}"

    jobs_after = client.get(f"/api/projects/{project_id}/finetune-jobs")
    assert jobs_after.status_code == 200
    assert jobs_after.json()["data"][0]["is_active"] is True


def test_finetune_job_fails_without_confirmed_train_annotations(client):
    project = client.post("/api/projects", json={"name": "empty-project", "task_type": "detection"})
    assert project.status_code == 200
    project_id = project.json()["data"]["id"]

    start = client.post("/api/finetune/start", json={"project_id": project_id})
    assert start.status_code == 200
    job_id = start.json()["data"]["job_id"]

    final_status = _poll_finetune_job(client, job_id)
    assert final_status["status"] == "failed"

    log_resp = client.get(f"/api/finetune/{job_id}/log")
    assert log_resp.status_code == 200
    assert "no confirmed train annotations available for finetune" in log_resp.json()["data"]["log"]


def test_cannot_start_second_finetune_while_first_is_running(client):
    project_id, _image_id = _create_confirmed_train_annotation(client, task_type="detection")

    first = client.post("/api/finetune/start", json={"project_id": project_id})
    assert first.status_code == 200
    running_job_id = first.json()["data"]["job_id"]

    second = client.post("/api/finetune/start", json={"project_id": project_id})
    assert second.status_code == 409
    assert "already running" in second.json()["message"]

    final_status = _poll_finetune_job(client, running_job_id)
    assert final_status["status"] == "done"


def test_finetune_job_acquires_gpu_training_lock(client, monkeypatch):
    project_id, _image_id = _create_confirmed_train_annotation(client, task_type="detection")
    events: list[str] = []
    original_acquire_training = finetune_service.GPULock.acquire_training

    @contextmanager
    def tracked_training_lock(*args, **kwargs):
        events.append("requested")
        with original_acquire_training(*args, **kwargs):
            events.append("entered")
            yield
        events.append("released")

    monkeypatch.setattr(finetune_service.GPULock, "acquire_training", tracked_training_lock)

    start = client.post("/api/finetune/start", json={"project_id": project_id})
    assert start.status_code == 200
    job_id = start.json()["data"]["job_id"]

    final_status = _poll_finetune_job(client, job_id)
    assert final_status["status"] == "done"
    assert events[:2] == ["requested", "entered"]
    assert events[-1] == "released"


def test_finetune_job_pauses_local_managed_vllm_before_training(client, monkeypatch):
    project_id, _image_id = _create_confirmed_train_annotation(client, task_type="detection")

    monkeypatch.setattr(
        finetune_service,
        "stop_local_managed_vllm",
        lambda: {"status": "stopped", "pid": 2468, "message": "stopped"},
    )

    start = client.post("/api/finetune/start", json={"project_id": project_id})
    assert start.status_code == 200
    job_id = start.json()["data"]["job_id"]

    final_status = _poll_finetune_job(client, job_id)
    assert final_status["status"] == "done"

    log_resp = client.get(f"/api/finetune/{job_id}/log")
    assert log_resp.status_code == 200
    assert "Paused local managed vLLM" in log_resp.json()["data"]["log"]


def test_finetune_job_restores_local_managed_vllm_after_failure(client, monkeypatch):
    project_id, _image_id = _create_confirmed_train_annotation(client, task_type="detection")

    monkeypatch.setattr(
        finetune_service,
        "stop_local_managed_vllm",
        lambda: {"status": "stopped", "pid": 2468, "message": "stopped"},
    )
    restore_calls: list[bool] = []
    monkeypatch.setattr(
        finetune_service,
        "ensure_local_managed_vllm_started",
        lambda *, enable_lora, timeout=None: (
            restore_calls.append(enable_lora) or {"status": "started", "pid": 1357, "message": "started"}
        ),
    )
    monkeypatch.setattr(
        finetune_service,
        "_run_mock_training",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    start = client.post("/api/finetune/start", json={"project_id": project_id})
    assert start.status_code == 200
    job_id = start.json()["data"]["job_id"]

    final_status = _poll_finetune_job(client, job_id)
    assert final_status["status"] == "failed"
    assert restore_calls == [False]

    log_resp = client.get(f"/api/finetune/{job_id}/log")
    assert log_resp.status_code == 200
    log_text = log_resp.json()["data"]["log"]
    assert "Restored local managed vLLM" in log_text
    assert "ERROR: boom" in log_text


def test_restore_local_managed_vllm_reclaims_training_cache_for_serving_restart(tmp_path, monkeypatch):
    root_dir = tmp_path / "runtime-root"
    root_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ROOT_DIR", str(root_dir))
    hf_home = tmp_path / "hf-home"
    monkeypatch.setenv("HF_HOME", str(hf_home))
    get_settings.cache_clear()

    train_repo = hf_home / "hub" / "models--Qwen--Qwen3-VL-8B-Instruct"
    train_repo.mkdir(parents=True, exist_ok=True)
    (train_repo / "weights.bin").write_bytes(b"train-cache")

    local_vllm_runtime.write_local_vllm_state(
        {
            "version": 1,
            "managed_by": "scripts/start-linux.sh",
            "repo_root": root_dir.as_posix(),
            "cwd": root_dir.as_posix(),
            "base_url": "http://127.0.0.1:8001",
            "host": "127.0.0.1",
            "port": 8001,
            "model_source": "Qwen/Qwen3-VL-8B-Instruct-FP8",
            "served_model_name": "qwen3-vl-8b",
            "pid": None,
            "log_path": (root_dir / "logs" / "vllm.log").as_posix(),
            "env_unset": [],
            "env_set": {"PYTHONUNBUFFERED": "1"},
            "command": [sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", "demo"],
            "supports_enable_lora": True,
        },
        root_dir=root_dir,
    )

    restore_calls: list[bool] = []
    monkeypatch.setattr(
        finetune_service,
        "ensure_local_managed_vllm_started",
        lambda *, enable_lora, timeout=None: (
            restore_calls.append(enable_lora) or {"status": "started", "pid": 1357, "message": "started"}
        ),
    )
    free_values = iter([2 * finetune_service.GIB, 12 * finetune_service.GIB])
    monkeypatch.setattr(finetune_service, "_free_disk_bytes", lambda path: next(free_values))

    log_path = root_dir / "logs" / "finetune.log"
    finetune_service._restore_local_managed_vllm(
        {"model_name_or_path": "Qwen/Qwen3-VL-8B-Instruct"},
        log_path,
    )

    assert restore_calls == [False]
    assert not train_repo.exists()

    log_text = log_path.read_text(encoding="utf-8")
    assert "Removed cached finetune training base model" in log_text
    assert "Restored local managed vLLM" in log_text


def test_finetune_job_can_run_llamafactory_subprocess(client, monkeypatch):
    project_id, _image_id = _create_confirmed_train_annotation(client, task_type="detection")
    mock_cli = (Path(__file__).resolve().parent / "helpers" / "mock_llamafactory_cli.py").resolve()
    cli_value = subprocess.list2cmdline([str(Path(sys.executable).resolve()), str(mock_cli)])

    monkeypatch.setenv("FINETUNE_BACKEND", "llamafactory")
    monkeypatch.setenv("LLAMAFACTORY_CLI", cli_value)
    monkeypatch.setattr(finetune_service, "_prepare_finetune_storage", lambda *args, **kwargs: {})
    get_settings.cache_clear()

    start = client.post("/api/finetune/start", json={"project_id": project_id})
    assert start.status_code == 200
    job_id = start.json()["data"]["job_id"]

    final_status = _poll_finetune_job(client, job_id)
    assert final_status["status"] == "done"
    assert final_status["config"]["runner_backend"] == "llamafactory"

    dataset_info_path = resolve_path(final_status["config"]["dataset_info_path"])
    train_config_path = resolve_path(final_status["config"]["train_config_path"])
    assert dataset_info_path.exists()
    assert train_config_path.exists()

    lora_dir = resolve_path(final_status["lora_path"])
    assert lora_dir.exists()
    assert (lora_dir / "adapter_model.safetensors").exists()

    log_resp = client.get(f"/api/finetune/{job_id}/log")
    assert log_resp.status_code == 200
    log_text = log_resp.json()["data"]["log"]
    assert "Launching LLaMA-Factory subprocess" in log_text
    assert "train completed" in log_text

    metrics = final_status["metrics"]
    assert len(metrics) >= 3
    assert metrics[-1]["loss"] is not None


def test_finetune_start_rejects_real_profile_when_llamafactory_is_missing(client, monkeypatch):
    project_id, _image_id = _create_confirmed_train_annotation(client, task_type="detection")

    monkeypatch.setenv("APP_PROFILE", "test_real_stack")
    monkeypatch.setenv("FINETUNE_BACKEND", "auto")
    monkeypatch.setenv("LLAMAFACTORY_CLI", "definitely-missing-llamafactory-cli")
    get_settings.cache_clear()

    start = client.post("/api/finetune/start", json={"project_id": project_id})
    assert start.status_code == 400
    assert "requires real LLaMA-Factory finetune" in start.json()["message"]


def test_build_train_runtime_config_excludes_internal_metadata():
    runtime = finetune_service._build_train_runtime_config(
        {
            "project_id": 7,
            "job_id": 11,
            "runner_backend": "llamafactory",
            "model_name_or_path": "Qwen/Qwen3-VL-8B-Instruct",
            "requested_base_model": "qwen3-vl-8b",
            "serving_base_model": "qwen3-vl-8b",
            "template": "qwen3_vl_nothink",
            "dataset": "project_7_train",
            "dataset_dir": "data/projects/7/exports/finetune/job_11",
            "dataset_info_path": "data/projects/7/exports/finetune/job_11/dataset_info.json",
            "train_config_path": "data/projects/7/exports/finetune/job_11/llamafactory-train.yaml",
            "dataset_path": "data/projects/7/exports/finetune/job_11/project_7_train.jsonl",
            "output_dir": "models/lora/11",
            "precision": "bf16",
            "quantization_bit": 4,
            "quantization_type": "nf4",
            "double_quantization": True,
        }
    )

    assert runtime["model_name_or_path"] == "Qwen/Qwen3-VL-8B-Instruct"
    assert runtime["template"] == "qwen3_vl_nothink"
    assert runtime["bf16"] is True
    assert runtime["fp16"] is False
    assert runtime["quantization_bit"] == 4
    assert runtime["quantization_type"] == "nf4"
    assert runtime["double_quantization"] is True
    assert "dataset_info_path" not in runtime
    assert "dataset_path" not in runtime
    assert "train_config_path" not in runtime
    assert "project_id" not in runtime
    assert "job_id" not in runtime
    assert "serving_base_model" not in runtime


def test_resolve_finetune_model_name_prefers_vllm_model_source(monkeypatch):
    monkeypatch.setenv("VLLM_MODEL_NAME", "qwen3-vl-8b")
    monkeypatch.setenv("VLLM_MODEL_SOURCE", "Qwen/Qwen3-VL-8B-Instruct-FP8")
    get_settings.cache_clear()

    assert finetune_service._resolve_finetune_model_name("qwen3-vl-8b") == "Qwen/Qwen3-VL-8B-Instruct"
    assert finetune_service._resolve_llamafactory_template("Qwen/Qwen3-VL-8B-Instruct-FP8") == "qwen3_vl_nothink"


def test_generate_lora_config_prefers_trainable_source_on_low_vram(monkeypatch, client):
    monkeypatch.setenv("VLLM_MODEL_NAME", "qwen3-vl-8b")
    monkeypatch.setenv("VLLM_MODEL_SOURCE", "Qwen/Qwen3-VL-8B-Instruct-FP8")
    get_settings.cache_clear()
    monkeypatch.setattr(finetune_service, "detect_vram_gb", lambda: 16.6)

    system_patch = client.patch("/api/system/settings", json={"llm": {"base_model": "qwen3-vl-8b"}})
    assert system_patch.status_code == 200

    project = client.post("/api/projects", json={"name": "cfg-project", "task_type": "detection"})
    assert project.status_code == 200
    project_id = project.json()["data"]["id"]
    patch = client.patch(f"/api/projects/{project_id}/settings", json={"labels": ["crack"]})
    assert patch.status_code == 200

    with finetune_service.get_session_factory()() as db:
        project_row = db.get(finetune_service.Project, project_id)
        config = finetune_service.generate_lora_config(project_row, job_id=99)

    assert config["requested_base_model"] == "qwen3-vl-8b"
    assert config["serving_base_model"] == "qwen3-vl-8b"
    assert config["model_name_or_path"] == "Qwen/Qwen3-VL-8B-Instruct"
    assert config["cutoff_len"] == 2048
    assert config["quantization_bit"] == 4
    assert config["quantization_type"] == "nf4"
    assert config["double_quantization"] is True


def test_prepare_finetune_storage_purges_inactive_serving_cache_when_train_cache_not_ready(tmp_path, monkeypatch):
    root_dir = tmp_path / "runtime-root"
    root_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ROOT_DIR", str(root_dir))
    hf_home = tmp_path / "hf-home"
    monkeypatch.setenv("HF_HOME", str(hf_home))
    get_settings.cache_clear()

    serving_repo = hf_home / "hub" / "models--Qwen--Qwen3-VL-8B-Instruct-FP8"
    serving_repo.mkdir(parents=True, exist_ok=True)
    (serving_repo / "weights.bin").write_bytes(b"fp8-cache")

    train_repo = hf_home / "hub" / "models--Qwen--Qwen3-VL-8B-Instruct" / "blobs"
    train_repo.mkdir(parents=True, exist_ok=True)
    (train_repo / "part.incomplete").write_bytes(b"partial")

    local_vllm_runtime.write_local_vllm_state(
        {
            "version": 1,
            "managed_by": "scripts/start-linux.sh",
            "repo_root": root_dir.as_posix(),
            "cwd": root_dir.as_posix(),
            "base_url": "http://127.0.0.1:8001",
            "host": "127.0.0.1",
            "port": 8001,
            "model_source": "Qwen/Qwen3-VL-8B-Instruct-FP8",
            "served_model_name": "qwen3-vl-8b",
            "pid": None,
            "log_path": (root_dir / "logs" / "vllm.log").as_posix(),
            "env_unset": [],
            "env_set": {"PYTHONUNBUFFERED": "1"},
            "command": [sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", "demo"],
            "supports_enable_lora": True,
        },
        root_dir=root_dir,
    )

    free_values = iter([2 * finetune_service.GIB, 12 * finetune_service.GIB])
    monkeypatch.setattr(finetune_service, "_free_disk_bytes", lambda path: next(free_values))

    log_path = root_dir / "logs" / "finetune.log"
    env_updates = finetune_service._prepare_finetune_storage(
        {"model_name_or_path": "Qwen/Qwen3-VL-8B-Instruct"},
        log_path,
    )

    assert env_updates["HF_HOME"] == hf_home.resolve().as_posix()
    assert not serving_repo.exists()
    assert "Removed cached serving base model" in log_path.read_text(encoding="utf-8")
