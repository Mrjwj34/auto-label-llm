from __future__ import annotations

import io
import time

from PIL import Image as PILImage


def _make_png_bytes(width: int = 160, height: int = 120, color: tuple[int, int, int] = (40, 160, 240)) -> bytes:
    img = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _poll_task_until_finished(client, task_id: str) -> dict:
    last_payload: dict | None = None
    for _ in range(80):
        resp = client.get(f"/api/tasks/{task_id}/status")
        assert resp.status_code == 200
        last_payload = resp.json()["data"]
        if last_payload["status"] in ("SUCCESS", "FAILURE"):
            break
        time.sleep(0.05)

    assert last_payload is not None
    return last_payload


def _create_project_with_labels(client, labels: list[str]) -> int:
    project_resp = client.post("/api/projects", json={"name": "auto-label", "task_type": "detection"})
    assert project_resp.status_code == 200
    project_id = project_resp.json()["data"]["id"]

    patch_resp = client.patch(f"/api/projects/{project_id}/settings", json={"labels": labels})
    assert patch_resp.status_code == 200
    return project_id


def _upload_images(client, project_id: int, image_specs: list[tuple[str, bytes]]) -> list[int]:
    files = [("files[]", (filename, content, "image/png")) for filename, content in image_specs]
    resp = client.post(f"/api/projects/{project_id}/images/upload", files=files)
    assert resp.status_code == 200
    return resp.json()["data"]["image_ids"]


def _assert_normalized_bbox(bbox: list[float]) -> None:
    assert len(bbox) == 4
    xmin, ymin, xmax, ymax = bbox
    assert 0.0 <= xmin < xmax <= 1.0
    assert 0.0 <= ymin < ymax <= 1.0


def test_batch_annotate_generates_bbox_annotations(client):
    labels = ["crack", "scratch"]
    project_id = _create_project_with_labels(client, labels)
    image_ids = _upload_images(
        client,
        project_id,
        [
            ("a.png", _make_png_bytes(160, 120, (10, 120, 240))),
            ("b.png", _make_png_bytes(120, 160, (220, 80, 90))),
        ],
    )

    start = client.post(f"/api/projects/{project_id}/annotate", json={"only_pending": True})
    assert start.status_code == 200
    task_id = start.json()["data"]["task_id"]

    final_status = _poll_task_until_finished(client, task_id)
    assert final_status["status"] == "SUCCESS"

    images_resp = client.get(f"/api/projects/{project_id}/images")
    assert images_resp.status_code == 200
    images = sorted(images_resp.json()["data"], key=lambda row: row["id"])
    assert [row["id"] for row in images] == sorted(image_ids)
    assert all(row["status"] == "done" for row in images)
    assert all(row["quality_score"] is None or 0.0 <= row["quality_score"] <= 1.0 for row in images)

    for image_id in image_ids:
        anns_resp = client.get(f"/api/images/{image_id}/annotations")
        assert anns_resp.status_code == 200
        annotations = anns_resp.json()["data"]
        assert len(annotations) >= 1
        assert all(ann["source"] == "auto" for ann in annotations)
        assert all(ann["label"] in labels for ann in annotations)
        assert all(ann["confidence"] is None or 0.0 <= ann["confidence"] <= 1.0 for ann in annotations)
        for ann in annotations:
            _assert_normalized_bbox(ann["bbox"])


def test_batch_annotate_replaces_existing_unconfirmed_auto_annotations(client):
    project_id = _create_project_with_labels(client, ["crack", "scratch"])
    image_id = _upload_images(client, project_id, [("a.png", _make_png_bytes())])[0]

    first = client.post(f"/api/projects/{project_id}/annotate", json={"image_ids": [image_id]})
    assert first.status_code == 200
    assert _poll_task_until_finished(client, first.json()["data"]["task_id"])["status"] == "SUCCESS"

    anns_first = client.get(f"/api/images/{image_id}/annotations").json()["data"]
    first_signature = [(ann["label"], ann["bbox"]) for ann in anns_first]
    assert len(first_signature) >= 1

    second = client.post(f"/api/projects/{project_id}/annotate", json={"image_ids": [image_id]})
    assert second.status_code == 200
    assert _poll_task_until_finished(client, second.json()["data"]["task_id"])["status"] == "SUCCESS"

    anns_second = client.get(f"/api/images/{image_id}/annotations").json()["data"]
    second_signature = [(ann["label"], ann["bbox"]) for ann in anns_second]

    assert second_signature == first_signature
    assert len(anns_second) == len(anns_first)


def test_batch_annotate_requires_labels(client):
    project_resp = client.post("/api/projects", json={"name": "no-labels", "task_type": "detection"})
    project_id = project_resp.json()["data"]["id"]
    _upload_images(client, project_id, [("a.png", _make_png_bytes())])

    resp = client.post(f"/api/projects/{project_id}/annotate", json={"only_pending": True})
    assert resp.status_code == 400
    assert "labels" in resp.json()["message"]


def test_single_image_annotate_generates_annotations(client):
    project_id = _create_project_with_labels(client, ["crack"])
    image_id = _upload_images(client, project_id, [("single.png", _make_png_bytes(200, 120))])[0]

    start = client.post(f"/api/images/{image_id}/annotate")
    assert start.status_code == 200
    task_id = start.json()["data"]["task_id"]

    final_status = _poll_task_until_finished(client, task_id)
    assert final_status["status"] == "SUCCESS"

    anns_resp = client.get(f"/api/images/{image_id}/annotations")
    annotations = anns_resp.json()["data"]
    assert len(annotations) >= 1
    assert all(ann["label"] == "crack" for ann in annotations)
