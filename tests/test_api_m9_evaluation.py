from __future__ import annotations

import io
import time
from pathlib import Path

from PIL import Image as PILImage

from backend.services.auto_annotator import AutoAnnotationResult
from backend.services.vllm_client import GeneratedAnnotation, InferenceRoute
from backend.utils.storage import resolve_path


def _make_png_bytes(
    width: int = 128,
    height: int = 96,
    color: tuple[int, int, int] = (48, 120, 220),
) -> bytes:
    image = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _create_project_with_labels(client, labels: list[str], *, task_type: str = "detection") -> int:
    resp = client.post("/api/projects", json={"name": "m9-evaluation", "task_type": task_type})
    assert resp.status_code == 200
    project_id = resp.json()["data"]["id"]

    patch = client.patch(f"/api/projects/{project_id}/settings", json={"labels": labels})
    assert patch.status_code == 200
    return project_id


def _upload_image(
    client,
    project_id: int,
    filename: str,
    *,
    width: int = 128,
    height: int = 96,
    color: tuple[int, int, int] = (48, 120, 220),
) -> int:
    resp = client.post(
        f"/api/projects/{project_id}/images/upload",
        files=[("files[]", (filename, _make_png_bytes(width, height, color), "image/png"))],
    )
    assert resp.status_code == 200
    return resp.json()["data"]["image_ids"][0]


def _poll_task_until_finished(client, task_id: str, timeout: float = 10.0) -> dict:
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


def _poll_evaluation_run(client, run_id: int, timeout: float = 15.0) -> dict:
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


def _confirm_all_annotations(client, image_id: int) -> list[dict]:
    resp = client.get(f"/api/images/{image_id}/annotations")
    assert resp.status_code == 200
    annotations = resp.json()["data"]
    assert annotations

    for annotation in annotations:
        confirm = client.patch(f"/api/annotations/{annotation['id']}/confirm")
        assert confirm.status_code == 200

    confirmed = client.get(f"/api/images/{image_id}/annotations")
    assert confirmed.status_code == 200
    return confirmed.json()["data"]


def _make_route(model_tag: str = "base") -> InferenceRoute:
    return InferenceRoute(
        requested_model_tag=model_tag,
        effective_model_tag=model_tag,
        request_model_name="mock-model",
        base_model_name="mock-model",
        resolved_project_profile="default",
        route_kind="base",
    )


def _make_auto_result(
    annotations: list[GeneratedAnnotation],
    *,
    model_tag: str = "base",
    total_ms: float = 12.5,
    llm_ms: float | None = 8.1,
    sam_ms: float | None = None,
    postprocess_ms: float | None = None,
) -> AutoAnnotationResult:
    return AutoAnnotationResult(
        provider="stub",
        annotations=annotations,
        route=_make_route(model_tag),
        requested_backend="stub",
        runtime={
            "annotation_count": len(annotations),
            "total_ms": total_ms,
            "llm_ms": llm_ms,
            "sam_ms": sam_ms,
            "postprocess_ms": postprocess_ms,
            "segmentation_ms": sam_ms,
        },
    )


def test_evaluation_run_generates_report_and_perfect_metrics_from_confirmed_auto_annotations(client):
    project_id = _create_project_with_labels(client, ["crack", "scratch"])
    image_id = _upload_image(client, project_id, "eval.png", color=(80, 140, 220))

    annotate = client.post(f"/api/images/{image_id}/annotate")
    assert annotate.status_code == 200
    task_id = annotate.json()["data"]["task_id"]

    final_task = _poll_task_until_finished(client, task_id)
    assert final_task["status"] == "SUCCESS"

    confirmed_annotations = _confirm_all_annotations(client, image_id)
    assert all(row["is_confirmed"] is True for row in confirmed_annotations)

    split_patch = client.patch(f"/api/images/{image_id}", json={"split": "val"})
    assert split_patch.status_code == 200

    start = client.post(
        f"/api/projects/{project_id}/evaluate",
        json={"split": "val", "model_tag": "base"},
    )
    assert start.status_code == 200
    run_id = start.json()["data"]["run_id"]

    final_run = _poll_evaluation_run(client, run_id)
    assert final_run["status"] == "done"
    assert final_run["split"] == "val"
    assert final_run["model_tag"] == "base"
    assert final_run["metrics"] is not None

    metrics = final_run["metrics"]
    assert metrics["images_evaluated"] == 1
    assert metrics["predictions"] == len(confirmed_annotations)
    assert metrics["ground_truth"] == len(confirmed_annotations)
    assert metrics["tp"] == len(confirmed_annotations)
    assert metrics["fp"] == 0
    assert metrics["fn"] == 0
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 1.0
    assert metrics["miou_bbox"] == 1.0
    assert set(metrics["per_label"]) <= {"crack", "scratch"}

    assert final_run["report_path"]
    report_path = resolve_path(final_run["report_path"])
    assert report_path.exists()

    report = client.get(f"/api/evaluations/{run_id}/report")
    assert report.status_code == 200
    report_payload = report.json()["data"]
    assert report_payload["run_id"] == run_id
    assert report_payload["project_id"] == project_id
    assert report_payload["metrics"]["f1"] == 1.0
    assert report_payload["performance"]["images_profiled"] == 1
    assert report_payload["summary"]["perfect_images"] == 1
    assert report_payload["summary"]["images_with_failures"] == 0
    assert report_payload["summary"]["failure_samples"] == []
    assert len(report_payload["images"]) == 1
    assert report_payload["images"][0]["image_id"] == image_id
    assert report_payload["images"][0]["tp"] == len(confirmed_annotations)
    assert report_payload["images"][0]["fp"] == 0
    assert report_payload["images"][0]["fn"] == 0

    listing = client.get(f"/api/projects/{project_id}/evaluations")
    assert listing.status_code == 200
    rows = listing.json()["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == run_id
    assert rows[0]["status"] == "done"


def test_segmentation_evaluation_reports_mask_metrics(client, monkeypatch):
    project_id = _create_project_with_labels(client, ["crack"], task_type="segmentation")
    image_id = _upload_image(client, project_id, "segmentation.png", color=(60, 110, 190))

    create = client.post(
        f"/api/images/{image_id}/annotations",
        json={"label": "crack", "bbox": [0.2, 0.2, 0.75, 0.82], "source": "manual"},
    )
    assert create.status_code == 200
    annotation_id = create.json()["data"]["id"]
    created_annotation_resp = client.get(f"/api/images/{image_id}/annotations")
    assert created_annotation_resp.status_code == 200
    created_annotation = next(
        row for row in created_annotation_resp.json()["data"] if int(row["id"]) == int(annotation_id)
    )
    assert created_annotation["polygon"] is not None

    confirm = client.patch(f"/api/annotations/{annotation_id}/confirm")
    assert confirm.status_code == 200

    split_patch = client.patch(f"/api/images/{image_id}", json={"split": "val"})
    assert split_patch.status_code == 200

    def fake_generate_auto_annotations(*args, **kwargs):
        return _make_auto_result(
            [
                GeneratedAnnotation(
                    label="crack",
                    bbox=created_annotation["bbox"],
                    polygon=created_annotation["polygon"],
                    confidence=0.95,
                )
            ],
            total_ms=18.2,
            llm_ms=6.2,
            sam_ms=9.4,
            postprocess_ms=2.1,
        )

    monkeypatch.setattr("backend.services.evaluation_service.generate_auto_annotations", fake_generate_auto_annotations)

    start = client.post(
        f"/api/projects/{project_id}/evaluate",
        json={"split": "val", "model_tag": "base"},
    )
    assert start.status_code == 200
    run_id = start.json()["data"]["run_id"]

    final_run = _poll_evaluation_run(client, run_id)
    assert final_run["status"] == "done"
    assert final_run["metrics"]["miou_mask"] == 1.0
    assert final_run["metrics"]["dice"] == 1.0
    assert final_run["metrics"]["mask_pairs"] == 1

    report = client.get(f"/api/evaluations/{run_id}/report")
    assert report.status_code == 200
    report_payload = report.json()["data"]
    assert report_payload["performance"]["avg_total_ms"] == 18.2
    assert report_payload["performance"]["avg_sam_ms"] == 9.4
    assert report_payload["summary"]["failure_samples"] == []
    assert report_payload["images"][0]["miou_mask"] == 1.0
    assert report_payload["images"][0]["dice"] == 1.0


def test_evaluation_compare_endpoint_returns_metric_delta_and_regressions(client, monkeypatch):
    project_id = _create_project_with_labels(client, ["crack"])
    image_id = _upload_image(client, project_id, "compare.png", color=(90, 150, 200))

    create = client.post(
        f"/api/images/{image_id}/annotations",
        json={"label": "crack", "bbox": [0.2, 0.25, 0.72, 0.78], "source": "manual"},
    )
    assert create.status_code == 200
    annotation_id = create.json()["data"]["id"]
    created_annotation_resp = client.get(f"/api/images/{image_id}/annotations")
    assert created_annotation_resp.status_code == 200
    created_annotation = next(
        row for row in created_annotation_resp.json()["data"] if int(row["id"]) == int(annotation_id)
    )

    confirm = client.patch(f"/api/annotations/{annotation_id}/confirm")
    assert confirm.status_code == 200

    split_patch = client.patch(f"/api/images/{image_id}", json={"split": "val"})
    assert split_patch.status_code == 200

    call_count = {"value": 0}

    def fake_generate_auto_annotations(*args, **kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return _make_auto_result(
                [GeneratedAnnotation(label="crack", bbox=created_annotation["bbox"], confidence=0.97)],
                total_ms=11.0,
            )
        return _make_auto_result(
            [GeneratedAnnotation(label="crack", bbox=[0.01, 0.01, 0.12, 0.12], confidence=0.42)],
            total_ms=23.0,
        )

    monkeypatch.setattr("backend.services.evaluation_service.generate_auto_annotations", fake_generate_auto_annotations)

    first = client.post(f"/api/projects/{project_id}/evaluate", json={"split": "val", "model_tag": "base"})
    assert first.status_code == 200
    first_run_id = first.json()["data"]["run_id"]
    assert _poll_evaluation_run(client, first_run_id)["status"] == "done"

    second = client.post(f"/api/projects/{project_id}/evaluate", json={"split": "val", "model_tag": "base"})
    assert second.status_code == 200
    second_run_id = second.json()["data"]["run_id"]
    final_run = _poll_evaluation_run(client, second_run_id)
    assert final_run["status"] == "done"
    assert final_run["metrics"]["f1"] == 0.0

    compare = client.get(f"/api/evaluations/{second_run_id}/compare", params={"baseline_run_id": first_run_id})
    assert compare.status_code == 200
    payload = compare.json()["data"]
    assert payload["current_run"]["id"] == second_run_id
    assert payload["baseline_run"]["id"] == first_run_id
    assert payload["delta"]["metrics"]["f1"] == {"current": 0.0, "baseline": 1.0, "delta": -1.0}
    assert payload["delta"]["metrics"]["fp"]["delta"] == 1.0
    assert payload["delta"]["metrics"]["fn"]["delta"] == 1.0
    assert payload["current_failure_samples"][0]["image_id"] == image_id
    assert payload["baseline_failure_samples"] == []
    assert payload["top_regressions"][0]["image_id"] == image_id
    assert payload["top_regressions"][0]["delta"]["error_count"] == 2

    compare_default = client.get(f"/api/evaluations/{second_run_id}/compare")
    assert compare_default.status_code == 200
    assert compare_default.json()["data"]["baseline_run"]["id"] == first_run_id


def test_evaluation_start_fails_without_confirmed_annotations_for_requested_split(client):
    project_id = _create_project_with_labels(client, ["crack"])
    image_id = _upload_image(client, project_id, "no-gt.png", color=(180, 80, 80))

    split_patch = client.patch(f"/api/images/{image_id}", json={"split": "val"})
    assert split_patch.status_code == 200

    start = client.post(f"/api/projects/{project_id}/evaluate", json={"split": "val"})
    assert start.status_code == 400
    assert "no confirmed evaluation annotations available" in start.json()["message"]


def test_quality_scores_refresh_for_manual_annotations_and_confirmation(client):
    project_id = _create_project_with_labels(client, ["crack"])
    image_id = _upload_image(client, project_id, "quality.png", color=(60, 180, 120))

    create = client.post(
        f"/api/images/{image_id}/annotations",
        json={"label": "crack", "bbox": [0.2, 0.25, 0.7, 0.8], "source": "manual"},
    )
    assert create.status_code == 200
    annotation_id = create.json()["data"]["id"]

    annotations_before = client.get(f"/api/images/{image_id}/annotations")
    assert annotations_before.status_code == 200
    annotation_row = annotations_before.json()["data"][0]
    assert annotation_row["id"] == annotation_id
    assert annotation_row["is_confirmed"] is False
    assert annotation_row["quality_score"] is not None
    assert 0.0 < annotation_row["quality_score"] < 1.0

    image_before = client.get(f"/api/images/{image_id}")
    assert image_before.status_code == 200
    image_before_row = image_before.json()["data"]
    assert image_before_row["quality_score"] is not None
    assert 0.0 < image_before_row["quality_score"] < 1.0

    confirm = client.patch(f"/api/annotations/{annotation_id}/confirm")
    assert confirm.status_code == 200

    annotations_after = client.get(f"/api/images/{image_id}/annotations")
    assert annotations_after.status_code == 200
    confirmed_annotation = annotations_after.json()["data"][0]
    assert confirmed_annotation["is_confirmed"] is True
    assert confirmed_annotation["quality_score"] == 1.0

    image_after = client.get(f"/api/images/{image_id}")
    assert image_after.status_code == 200
    assert image_after.json()["data"]["quality_score"] == 1.0
