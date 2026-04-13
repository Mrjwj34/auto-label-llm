from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from backend.app import create_app
from backend.config import get_settings
from backend.database import get_engine, get_session_factory


def _make_png_bytes(
    width: int = 160,
    height: int = 120,
    color: tuple[int, int, int] = (60, 140, 220),
) -> bytes:
    image = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _create_project(client: TestClient, *, task_type: str = "detection", name: str = "m10-project") -> int:
    resp = client.post("/api/projects", json={"name": name, "task_type": task_type})
    assert resp.status_code == 200
    return int(resp.json()["data"]["id"])


def _upload_image(client: TestClient, project_id: int, filename: str = "sample.png") -> int:
    resp = client.post(
        f"/api/projects/{project_id}/images/upload",
        files=[("files[]", (filename, _make_png_bytes(), "image/png"))],
    )
    assert resp.status_code == 200
    return int(resp.json()["data"]["image_ids"][0])


@pytest.fixture()
def profile_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root_dir = tmp_path / "runtime-root"
    data_dir = root_dir / "data"
    db_path = data_dir / "test.db"

    target_profiles = root_dir / "configs" / "profiles"
    target_profiles.mkdir(parents=True, exist_ok=True)
    for source in (Path(__file__).resolve().parents[1] / "configs" / "profiles").glob("*.json"):
        shutil.copy2(source, target_profiles / source.name)
    (root_dir / "frontend").mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("ROOT_DIR", str(root_dir))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("REDIS_URL", f"fakeredis://{root_dir.as_posix()}/0")
    monkeypatch.setenv("TASK_EMBEDDED_WORKER", "true")
    monkeypatch.setenv("TASK_WORKER_CONCURRENCY", "1")
    for env_name in (
        "APP_PROFILE",
        "ANNOTATION_BACKEND",
        "VLLM_BASE_URL",
        "VLLM_MODEL_NAME",
        "LLM_REQUEST_TIMEOUT_SECONDS",
        "LLM_MAX_RETRIES",
        "LLM_MAX_TOKENS",
    ):
        monkeypatch.delenv(env_name, raising=False)

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    app = create_app()
    with TestClient(app) as client:
        yield client, root_dir


def test_project_settings_patch_returns_change_summary_and_metadata(client: TestClient):
    project_id = _create_project(client)

    before = client.get(f"/api/projects/{project_id}/settings")
    assert before.status_code == 200
    before_payload = before.json()["data"]
    assert before_payload["_meta"]["active_system_profile"] == "dev_low_resource"
    assert "labels" in before_payload["_meta"]["project_editable_paths"]

    patch = client.patch(
        f"/api/projects/{project_id}/settings",
        json={"labels": ["crack", "scratch"]},
    )
    assert patch.status_code == 200

    after = client.get(f"/api/projects/{project_id}/settings")
    assert after.status_code == 200
    after_payload = after.json()["data"]
    assert after_payload["labels"] == ["crack", "scratch"]

    invalid = client.patch(f"/api/projects/{project_id}/settings", json={"unknown": True})
    assert invalid.status_code == 400
    assert "unknown settings key" in invalid.json()["message"]

    runtime_invalid = client.patch(f"/api/projects/{project_id}/settings", json={"sam": {"checkpoint": "sam2.1"}})
    assert runtime_invalid.status_code == 400
    assert "/api/system/settings" in runtime_invalid.json()["message"]


def test_system_runtime_settings_patch_returns_change_summary_and_metadata(client: TestClient):
    before = client.get("/api/system/settings")
    assert before.status_code == 200
    before_payload = before.json()["data"]
    assert "quality.threshold_review" in before_payload["_meta"]["hot_reload_paths"]
    assert "sam.checkpoint" in before_payload["_meta"]["reload_required_paths"]

    patch = client.patch(
        "/api/system/settings",
        json={
            "quality": {"threshold_review": 0.72},
            "sam": {"checkpoint": "sam2.1"},
        },
    )
    assert patch.status_code == 200
    payload = patch.json()
    assert "Saved settings." in payload["message"]
    change = payload["data"]["change"]
    assert "quality.threshold_review" in change["hot_reload_paths"]
    assert "sam.checkpoint" in change["reload_required_paths"]
    assert change["reload_required"] is True

    after = client.get("/api/system/settings")
    assert after.status_code == 200
    after_payload = after.json()["data"]
    assert after_payload["quality"]["threshold_review"] == 0.72
    assert after_payload["sam"]["checkpoint"] == "sam2.1"


def test_system_profile_activation_updates_runtime_and_auto_project_defaults(profile_client):
    client, root_dir = profile_client

    initial = client.get("/api/system/config")
    assert initial.status_code == 200
    initial_payload = initial.json()["data"]
    assert initial_payload["active_profile"] == "dev_low_resource"
    assert initial_payload["runtime"]["annotation_backend"] == "stub"
    assert initial_payload["runtime"]["vllm_model_name"] in ("", "qwen3-vl-2b")

    activate = client.post("/api/system/model/activate", json={"profile": "test_real_stack"})
    assert activate.status_code == 200
    activated = activate.json()["data"]
    assert activated["active_profile"] == "test_real_stack"
    assert activated["runtime"]["annotation_backend"] == "openai_compatible"
    assert activated["runtime"]["vllm_model_name"] == "qwen3-vl-8b"
    assert (root_dir / ".env.active").exists()
    assert (root_dir / "frontend" / ".env.local").exists()

    refreshed = client.get("/api/system/config")
    assert refreshed.status_code == 200
    refreshed_payload = refreshed.json()["data"]
    assert refreshed_payload["active_profile"] == "test_real_stack"
    assert refreshed_payload["runtime"]["annotation_backend"] == "openai_compatible"
    assert refreshed_payload["runtime"]["vllm_model_name"] == "qwen3-vl-8b"

    project_id = _create_project(client, name="profile-aware")
    settings_resp = client.get(f"/api/projects/{project_id}/settings")
    assert settings_resp.status_code == 200
    settings_payload = settings_resp.json()["data"]
    assert settings_payload["model_profile"] == "auto"
    assert settings_payload["llm"]["base_model"] == "qwen3-vl-8b"
    assert settings_payload["sam"]["checkpoint"] == "sam2.1"
    assert settings_payload["_meta"]["resolved_project_profile"] == "test_real_stack"

    patch = client.patch("/api/system/settings", json={"model_profile": "demo_prod"})
    assert patch.status_code == 200
    assert patch.json()["data"]["change"]["reload_required"] is True

    demo_settings = client.get(f"/api/projects/{project_id}/settings")
    assert demo_settings.status_code == 200
    demo_payload = demo_settings.json()["data"]
    assert demo_payload["llm"]["base_model"] == "qwen3-vl-8b"
    assert demo_payload["sam"]["checkpoint"] == "sam2.1"
    assert demo_payload["_meta"]["resolved_project_profile"] == "demo_prod"


def test_postprocess_and_quality_settings_affect_new_segmentation_predictions(client: TestClient):
    project_id = _create_project(client, task_type="segmentation", name="m10-seg")
    image_id = _upload_image(client, project_id, filename="seg.png")

    labels_settings = client.patch(f"/api/projects/{project_id}/settings", json={"labels": ["crack"]})
    assert labels_settings.status_code == 200

    first_settings = client.patch(
        "/api/system/settings",
        json={
            "quality": {"enable": False},
            "sam": {"checkpoint": "sam2.1", "multimask_output": True},
            "postprocess": {"enable_close": False, "enable_dp_simplify": False},
        },
    )
    assert first_settings.status_code == 200

    first_prediction = client.post(
        f"/api/images/{image_id}/predict",
        json={"annotation_id": None, "label": "crack", "bbox": [0.12, 0.18, 0.78, 0.86]},
    )
    assert first_prediction.status_code == 200
    first_annotation_id = int(first_prediction.json()["data"]["annotation_id"])

    first_annotations = client.get(f"/api/images/{image_id}/annotations")
    assert first_annotations.status_code == 200
    first_row = next(row for row in first_annotations.json()["data"] if int(row["id"]) == first_annotation_id)
    first_polygon_len = len(first_row["polygon"])
    assert first_polygon_len >= 8
    assert first_row["quality_score"] is None

    second_settings = client.patch(
        "/api/system/settings",
        json={
            "quality": {
                "enable": True,
                "threshold_review": 0.61,
                "use_llm_confidence": True,
                "use_sam_score": True,
            },
            "sam": {"checkpoint": "sam2", "multimask_output": False},
            "postprocess": {"enable_close": True, "enable_dp_simplify": True, "epsilon_ratio": 0.2},
        },
    )
    assert second_settings.status_code == 200

    second_prediction = client.post(
        f"/api/images/{image_id}/predict",
        json={"annotation_id": None, "label": "crack", "bbox": [0.2, 0.22, 0.7, 0.74]},
    )
    assert second_prediction.status_code == 200
    second_annotation_id = int(second_prediction.json()["data"]["annotation_id"])

    second_annotations = client.get(f"/api/images/{image_id}/annotations")
    assert second_annotations.status_code == 200
    second_row = next(row for row in second_annotations.json()["data"] if int(row["id"]) == second_annotation_id)
    assert second_row["quality_score"] is not None
    assert len(second_row["polygon"]) < first_polygon_len
