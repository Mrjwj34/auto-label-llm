from __future__ import annotations

import io
import json
import time
from pathlib import Path

from PIL import Image as PILImage

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
    assert final_status["model_tag"] == f"lora:{job_id}"
    assert final_status["dataset_path"]
    assert final_status["lora_path"]
    assert final_status["log_path"]
    assert final_status["config"]["dataset"] == f"project_{project_id}_train"

    dataset_path = resolve_path(final_status["dataset_path"])
    assert dataset_path.exists()
    sample = json.loads(dataset_path.read_text(encoding="utf-8").splitlines()[0])
    assert sample["messages"][0]["role"] == "user"
    assert sample["messages"][1]["role"] == "assistant"
    assistant_payload = json.loads(sample["messages"][1]["content"])
    assert assistant_payload["objects"][0]["label"] == "crack"

    lora_dir = resolve_path(final_status["lora_path"])
    assert lora_dir.exists()
    assert (lora_dir / "adapter_config.json").exists()

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
