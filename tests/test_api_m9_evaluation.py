from __future__ import annotations

import io
import time
from pathlib import Path

from PIL import Image as PILImage


def _make_png_bytes(
    width: int = 128,
    height: int = 96,
    color: tuple[int, int, int] = (48, 120, 220),
) -> bytes:
    image = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _create_project_with_labels(client, labels: list[str]) -> int:
    resp = client.post("/api/projects", json={"name": "m9-evaluation", "task_type": "detection"})
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
    report_path = Path(final_run["report_path"])
    assert report_path.exists()

    report = client.get(f"/api/evaluations/{run_id}/report")
    assert report.status_code == 200
    report_payload = report.json()["data"]
    assert report_payload["run_id"] == run_id
    assert report_payload["project_id"] == project_id
    assert report_payload["metrics"]["f1"] == 1.0
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
