from __future__ import annotations

import io
import json
import shutil
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from backend.api import AppError
from backend.app import create_app
from backend.config import get_settings
from backend.database import get_engine, get_session_factory
from backend.services import vllm_client
from backend.services.vllm_client import _extract_json_text, _normalize_response_payload


def _make_png_bytes(
    width: int = 128,
    height: int = 96,
    color: tuple[int, int, int] = (72, 140, 220),
) -> bytes:
    image = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _create_project(client: TestClient, *, name: str = "m11-project", task_type: str = "detection") -> int:
    resp = client.post("/api/projects", json={"name": name, "task_type": task_type})
    assert resp.status_code == 200
    return int(resp.json()["data"]["id"])


def _upload_image(client: TestClient, project_id: int, filename: str) -> int:
    resp = client.post(
        f"/api/projects/{project_id}/images/upload",
        files=[("files[]", (filename, _make_png_bytes(), "image/png"))],
    )
    assert resp.status_code == 200
    return int(resp.json()["data"]["image_ids"][0])


def _create_manual_confirmed_annotation(
    client: TestClient,
    image_id: int,
    *,
    bbox: list[float] | None = None,
) -> int:
    resp = client.post(
        f"/api/images/{image_id}/annotations",
        json={
            "label": "crack",
            "bbox": bbox or [0.2, 0.25, 0.65, 0.75],
            "source": "manual",
        },
    )
    assert resp.status_code == 200
    annotation_id = int(resp.json()["data"]["id"])

    confirm = client.patch(f"/api/annotations/{annotation_id}/confirm")
    assert confirm.status_code == 200
    return annotation_id


def _poll_task_until_finished(client: TestClient, task_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    last_payload: dict | None = None
    while time.time() < deadline:
        resp = client.get(f"/api/tasks/{task_id}/status")
        assert resp.status_code == 200
        last_payload = resp.json()["data"]
        if last_payload["status"] in ("SUCCESS", "FAILURE"):
            return last_payload
        time.sleep(0.05)
    raise AssertionError(f"task did not finish in time: {last_payload}")


def _poll_evaluation_run(client: TestClient, run_id: int, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    last_payload: dict | None = None
    while time.time() < deadline:
        resp = client.get(f"/api/evaluations/{run_id}")
        assert resp.status_code == 200
        last_payload = resp.json()["data"]
        if last_payload["status"] in ("done", "failed"):
            return last_payload
        time.sleep(0.05)
    raise AssertionError(f"evaluation run did not finish in time: {last_payload}")


def _poll_finetune_job(client: TestClient, job_id: int, timeout: float = 15.0) -> dict:
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


class _FakeVLLMResponse:
    def __init__(self, payload: dict, *, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://127.0.0.1:8001/v1/chat/completions")
            response = httpx.Response(self.status_code, request=request, json=self._payload)
            raise httpx.HTTPStatusError("fake error", request=request, response=response)

    def json(self) -> dict:
        return self._payload


class FakeVLLMClient:
    requests: list[dict] = []
    queued_payloads: list[dict] = []
    error: Exception | None = None

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url: str, json: dict, headers: dict):
        FakeVLLMClient.requests.append({"url": url, "json": json, "headers": headers})
        if FakeVLLMClient.error is not None:
            raise FakeVLLMClient.error
        payload = FakeVLLMClient.queued_payloads.pop(0) if FakeVLLMClient.queued_payloads else _default_vllm_payload()
        return _FakeVLLMResponse(payload)

    @classmethod
    def reset(cls, *, payloads: list[dict] | None = None, error: Exception | None = None) -> None:
        cls.requests = []
        cls.queued_payloads = list(payloads or [])
        cls.error = error


def _default_vllm_payload(*, bbox: list[float] | None = None) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"objects": [{"label": "crack", "bbox": %s, "confidence": 0.91}]}'
                        % str(bbox or [0.2, 0.25, 0.65, 0.75]).replace("'", '"')
                    )
                }
            }
        ]
    }


@pytest.fixture()
def openai_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
    monkeypatch.setenv("APP_PROFILE", "test_real_stack")
    monkeypatch.setenv("ANNOTATION_BACKEND", "openai_compatible")
    monkeypatch.setenv("REDIS_URL", f"fakeredis://{root_dir.as_posix()}/0")
    monkeypatch.setenv("TASK_EMBEDDED_WORKER", "true")
    monkeypatch.setenv("TASK_WORKER_CONCURRENCY", "1")
    monkeypatch.setenv("FINETUNE_BACKEND", "mock")
    monkeypatch.setenv("VLLM_BASE_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("VLLM_MODEL_NAME", "qwen3-vl-4b")
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    monkeypatch.setenv("LLM_MAX_TOKENS", "2048")

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    app = create_app()
    with TestClient(app) as client:
        yield client


def test_openai_annotation_uses_profile_resolved_model_and_records_inference_metadata(
    openai_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("backend.services.vllm_client.httpx.Client", FakeVLLMClient)
    FakeVLLMClient.reset(payloads=[_default_vllm_payload(bbox=[0.12, 0.2, 0.66, 0.8])])

    project_id = _create_project(openai_client, name="m11-openai")
    labels_patch = openai_client.patch(f"/api/projects/{project_id}/settings", json={"labels": ["crack"]})
    assert labels_patch.status_code == 200
    system_patch = openai_client.patch("/api/system/settings", json={"model_profile": "demo_prod"})
    assert system_patch.status_code == 200

    image_id = _upload_image(openai_client, project_id, "demo.png")
    annotate = openai_client.post(f"/api/images/{image_id}/annotate")
    assert annotate.status_code == 200

    task_id = str(annotate.json()["data"]["task_id"])
    final_task = _poll_task_until_finished(openai_client, task_id)
    assert final_task["status"] == "SUCCESS"
    assert "openai_compatible" in str(final_task["message"])
    assert "qwen3-vl-8b" in str(final_task["message"])

    assert len(FakeVLLMClient.requests) == 1
    request_payload = FakeVLLMClient.requests[0]["json"]
    assert request_payload["model"] == "qwen3-vl-8b"
    assert request_payload["guided_json"]["required"] == ["objects"]
    assert request_payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert request_payload["messages"][1]["content"][0]["text"].startswith("/no_think\n")

    annotations = openai_client.get(f"/api/images/{image_id}/annotations")
    assert annotations.status_code == 200
    rows = annotations.json()["data"]
    assert len(rows) == 1
    inference = rows[0]["inference"]
    assert inference is not None
    assert inference["provider"] == "openai_compatible"
    assert inference["requested_backend"] == "openai_compatible"
    assert inference["effective_model_tag"] == "base"
    assert inference["request_model_name"] == "qwen3-vl-8b"
    assert inference["resolved_project_profile"] == "demo_prod"
    assert inference["fallback_used"] is False


def test_qwen_array_payload_is_normalized_into_annotations():
    payload = json.loads(
        _extract_json_text(
            """```json
[
  {"label": "cat", "bbox_2d": [12, 111, 497, 985], "confidence": 0.99},
  {"label": "couch", "bbox": [0, 0, 1000, 1000], "confidence": 0.88}
]
```"""
        )
    )

    annotations = _normalize_response_payload(payload, ["cat", "couch"])

    assert len(annotations) == 2
    assert annotations[0].label == "cat"
    assert annotations[0].bbox == [0.012, 0.111, 0.497, 0.985]
    assert annotations[0].confidence == 0.99
    assert annotations[1].label == "couch"
    assert annotations[1].bbox == [0.0, 0.0, 1.0, 1.0]


def test_qwen_bbox_aliases_are_normalized_into_annotations():
    payload = {
        "objects": [
            {"label": "cat", "box_2d": [20, 40, 220, 440], "confidence": 0.75},
            {"label": "couch", "bounding_box": [0, 0, 1000, 1000], "confidence": 0.88},
        ]
    }

    annotations = _normalize_response_payload(payload, ["cat", "couch"])

    assert len(annotations) == 2
    assert annotations[0].label == "cat"
    assert annotations[0].bbox == [0.02, 0.04, 0.22, 0.44]
    assert annotations[1].label == "couch"
    assert annotations[1].bbox == [0.0, 0.0, 1.0, 1.0]


def test_openai_failure_falls_back_to_stub_and_keeps_route_metadata(
    openai_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("backend.services.vllm_client.httpx.Client", FakeVLLMClient)
    FakeVLLMClient.reset(error=httpx.ConnectError("vllm offline"))

    project_id = _create_project(openai_client, name="m11-fallback")
    patch = openai_client.patch(f"/api/projects/{project_id}/settings", json={"labels": ["crack"]})
    assert patch.status_code == 200

    image_id = _upload_image(openai_client, project_id, "fallback.png")
    annotate = openai_client.post(f"/api/images/{image_id}/annotate")
    assert annotate.status_code == 200

    task_id = str(annotate.json()["data"]["task_id"])
    final_task = _poll_task_until_finished(openai_client, task_id)
    assert final_task["status"] == "SUCCESS"
    assert "fallback" in str(final_task["message"])

    assert len(FakeVLLMClient.requests) == 1
    assert FakeVLLMClient.requests[0]["json"]["model"] == "qwen3-vl-4b"

    annotations = openai_client.get(f"/api/images/{image_id}/annotations")
    assert annotations.status_code == 200
    rows = annotations.json()["data"]
    assert len(rows) >= 1
    inference = rows[0]["inference"]
    assert inference is not None
    assert inference["provider"] == "stub"
    assert inference["requested_backend"] == "openai_compatible"
    assert inference["effective_model_tag"] == "base"
    assert inference["request_model_name"] == "qwen3-vl-4b"
    assert inference["fallback_used"] is True
    assert "vllm offline" in str(inference["warning"])


def test_lora_openai_failure_marks_task_failed_instead_of_falling_back_to_stub(
    openai_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("backend.services.vllm_client.httpx.Client", FakeVLLMClient)

    project_id = _create_project(openai_client, name="m11-lora-failure")
    patch = openai_client.patch(f"/api/projects/{project_id}/settings", json={"labels": ["crack"]})
    assert patch.status_code == 200

    train_image_id = _upload_image(openai_client, project_id, "train.png")
    _create_manual_confirmed_annotation(openai_client, train_image_id)

    start = openai_client.post("/api/finetune/start", json={"project_id": project_id})
    assert start.status_code == 200
    job_id = int(start.json()["data"]["job_id"])

    finetune_status = _poll_finetune_job(openai_client, job_id)
    assert finetune_status["status"] == "done"

    activate_lora = openai_client.post(
        f"/api/projects/{project_id}/models/activate",
        json={"model_tag": f"lora:{job_id}"},
    )
    assert activate_lora.status_code == 200

    FakeVLLMClient.reset(error=httpx.ReadTimeout("timed out"))

    image_id = _upload_image(openai_client, project_id, "lora-timeout.png")
    annotate = openai_client.post(f"/api/images/{image_id}/annotate")
    assert annotate.status_code == 200

    task_id = str(annotate.json()["data"]["task_id"])
    final_task = _poll_task_until_finished(openai_client, task_id)
    assert final_task["status"] == "FAILURE"
    assert f"lora:{job_id}" in str(final_task["message"])
    assert "openai-compatible annotation failed" in str(final_task["message"])

    image = openai_client.get(f"/api/images/{image_id}")
    assert image.status_code == 200
    assert image.json()["data"]["status"] == "error"

    annotations = openai_client.get(f"/api/images/{image_id}/annotations")
    assert annotations.status_code == 200
    assert annotations.json()["data"] == []


def test_project_model_activation_switches_base_and_lora_and_evaluation_uses_active_tag(
    openai_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("backend.services.vllm_client.httpx.Client", FakeVLLMClient)
    FakeVLLMClient.reset(payloads=[_default_vllm_payload()])

    project_id = _create_project(openai_client, name="m11-routing")
    patch = openai_client.patch(f"/api/projects/{project_id}/settings", json={"labels": ["crack"]})
    assert patch.status_code == 200

    train_image_id = _upload_image(openai_client, project_id, "train.png")
    _create_manual_confirmed_annotation(openai_client, train_image_id)

    val_image_id = _upload_image(openai_client, project_id, "val.png")
    _create_manual_confirmed_annotation(openai_client, val_image_id)
    mark_val = openai_client.patch(f"/api/images/{val_image_id}", json={"split": "val"})
    assert mark_val.status_code == 200

    start = openai_client.post("/api/finetune/start", json={"project_id": project_id})
    assert start.status_code == 200
    job_id = int(start.json()["data"]["job_id"])

    finetune_status = _poll_finetune_job(openai_client, job_id)
    assert finetune_status["status"] == "done"

    activate_lora = openai_client.post(
        f"/api/projects/{project_id}/models/activate",
        json={"model_tag": f"lora:{job_id}"},
    )
    assert activate_lora.status_code == 200
    assert activate_lora.json()["data"]["activation"]["active_model_tag"] == f"lora:{job_id}"

    activate_base = openai_client.post(
        f"/api/projects/{project_id}/models/activate",
        json={"model_tag": "base"},
    )
    assert activate_base.status_code == 200
    assert activate_base.json()["data"]["activation"]["active_model_tag"] == "base"

    activate_lora_again = openai_client.post(
        f"/api/projects/{project_id}/models/activate",
        json={"model_tag": f"lora:{job_id}"},
    )
    assert activate_lora_again.status_code == 200

    start_eval = openai_client.post(f"/api/projects/{project_id}/evaluate", json={"split": "val"})
    assert start_eval.status_code == 200
    run_id = int(start_eval.json()["data"]["run_id"])

    final_run = _poll_evaluation_run(openai_client, run_id)
    assert final_run["status"] == "done"
    assert final_run["model_tag"] == f"lora:{job_id}"

    assert len(FakeVLLMClient.requests) == 1
    assert FakeVLLMClient.requests[0]["json"]["model"] == "qwen3-vl-4b"
    assert FakeVLLMClient.requests[0]["json"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert FakeVLLMClient.requests[0]["json"]["messages"][1]["content"][0]["text"].startswith("/no_think\n")

    report = openai_client.get(f"/api/evaluations/{run_id}/report")
    assert report.status_code == 200
    payload = report.json()["data"]
    assert payload["model_tag"] == f"lora:{job_id}"
    assert payload["inference"]["effective_model_tag"] == f"lora:{job_id}"
    assert payload["images"][0]["image_id"] == val_image_id
    assert payload["images"][0]["inference"]["provider"] == "openai_compatible"
    assert payload["images"][0]["inference"]["request_model_name"] == "qwen3-vl-4b"
    assert FakeVLLMClient.requests[0]["json"]["max_tokens"] == 128


def test_project_model_activation_can_sync_vllm_runtime_lora(openai_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VLLM_ENABLE_RUNTIME_LORA_UPDATE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("backend.services.vllm_client.httpx.Client", FakeVLLMClient)
    FakeVLLMClient.reset()

    project_id = _create_project(openai_client, name="m14-runtime-sync")
    patch = openai_client.patch(f"/api/projects/{project_id}/settings", json={"labels": ["crack"]})
    assert patch.status_code == 200

    train_image_id = _upload_image(openai_client, project_id, "train.png")
    _create_manual_confirmed_annotation(openai_client, train_image_id)

    start = openai_client.post("/api/finetune/start", json={"project_id": project_id})
    assert start.status_code == 200
    job_id = int(start.json()["data"]["job_id"])

    finetune_status = _poll_finetune_job(openai_client, job_id)
    assert finetune_status["status"] == "done"

    activate_lora = openai_client.post(
        f"/api/projects/{project_id}/models/activate",
        json={"model_tag": f"lora:{job_id}"},
    )
    assert activate_lora.status_code == 200
    runtime_sync = activate_lora.json()["data"]["activation"]["runtime_sync"]
    assert runtime_sync["status"] == "synced"
    assert runtime_sync["actions"] == []
    assert activate_lora.json()["data"]["activation"]["route"]["route_kind"] == "mock_lora"

    activate_base = openai_client.post(
        f"/api/projects/{project_id}/models/activate",
        json={"model_tag": "base"},
    )
    assert activate_base.status_code == 200
    base_sync = activate_base.json()["data"]["activation"]["runtime_sync"]
    assert base_sync["status"] == "synced"
    assert base_sync["actions"] == []

    assert FakeVLLMClient.requests == []


def test_runtime_lora_route_404_has_actionable_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VLLM_BASE_URL", "http://127.0.0.1:8001")
    get_settings.cache_clear()

    class Fake404Client:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, json: dict, headers: dict):
            return _FakeVLLMResponse({"detail": "Not Found"}, status_code=404)

    monkeypatch.setattr("backend.services.vllm_client.httpx.Client", Fake404Client)

    with pytest.raises(AppError, match="VLLM_ALLOW_RUNTIME_LORA_UPDATING=1"):
        vllm_client._post_vllm_runtime("/v1/load_lora_adapter", {"lora_name": "lora:8"})


def test_annotation_token_cap_is_conservative_for_base_and_lora(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VLLM_MAX_MODEL_LEN", "2048")
    get_settings.cache_clear()

    base_route = vllm_client.InferenceRoute(
        requested_model_tag="base",
        effective_model_tag="base",
        request_model_name="qwen3-vl-8b",
        base_model_name="qwen3-vl-8b",
        resolved_project_profile="test_real_stack",
        route_kind="base",
    )
    lora_route = vllm_client.InferenceRoute(
        requested_model_tag="lora:9",
        effective_model_tag="lora:9",
        request_model_name="lora:9",
        base_model_name="qwen3-vl-8b",
        resolved_project_profile="test_real_stack",
        route_kind="lora",
        adapter_path="models/lora/9",
        finetune_job_id=9,
    )

    assert vllm_client._cap_annotation_max_tokens(2048, route=base_route) == 256
    assert vllm_client._cap_annotation_max_tokens(2048, route=lora_route) == 128


def test_annotation_chat_template_kwargs_disable_qwen3_thinking():
    qwen3_route = vllm_client.InferenceRoute(
        requested_model_tag="lora:10",
        effective_model_tag="lora:10",
        request_model_name="lora:10",
        base_model_name="qwen3-vl-8b",
        resolved_project_profile="test_real_stack",
        route_kind="lora",
        adapter_path="models/lora/10",
        finetune_job_id=10,
    )
    non_qwen_route = vllm_client.InferenceRoute(
        requested_model_tag="base",
        effective_model_tag="base",
        request_model_name="internvl",
        base_model_name="internvl",
        resolved_project_profile="fixed",
        route_kind="base",
    )

    assert vllm_client._annotation_chat_template_kwargs(qwen3_route) == {"enable_thinking": False}
    assert vllm_client._annotation_chat_template_kwargs(non_qwen_route) is None
    assert vllm_client._annotation_user_text(labels=["crack"], task_type="detection", route=qwen3_route).startswith(
        "/no_think\n"
    )
    assert not vllm_client._annotation_user_text(
        labels=["crack"], task_type="detection", route=non_qwen_route
    ).startswith("/no_think\n")


def test_annotation_timeout_extends_lora_route(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "180")
    get_settings.cache_clear()

    base_route = vllm_client.InferenceRoute(
        requested_model_tag="base",
        effective_model_tag="base",
        request_model_name="qwen3-vl-8b",
        base_model_name="qwen3-vl-8b",
        resolved_project_profile="test_real_stack",
        route_kind="base",
    )
    lora_route = vllm_client.InferenceRoute(
        requested_model_tag="lora:10",
        effective_model_tag="lora:10",
        request_model_name="lora:10",
        base_model_name="qwen3-vl-8b",
        resolved_project_profile="test_real_stack",
        route_kind="lora",
        adapter_path="models/lora/10",
        finetune_job_id=10,
    )

    assert vllm_client._annotation_timeout_seconds(base_route) == 180.0
    assert vllm_client._annotation_timeout_seconds(lora_route) == 600.0
