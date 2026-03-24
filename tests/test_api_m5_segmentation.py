from __future__ import annotations

import io
import time

from PIL import Image as PILImage


def _make_png_bytes(width: int = 180, height: int = 120, color: tuple[int, int, int] = (90, 120, 240)) -> bytes:
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


def _create_segmentation_project(client) -> int:
    project_resp = client.post("/api/projects", json={"name": "seg", "task_type": "segmentation"})
    assert project_resp.status_code == 200
    project_id = project_resp.json()["data"]["id"]

    patch_resp = client.patch(f"/api/projects/{project_id}/settings", json={"labels": ["crack", "scratch"]})
    assert patch_resp.status_code == 200
    return project_id


def _upload_single_image(client, project_id: int, filename: str = "seg.png") -> int:
    resp = client.post(
        f"/api/projects/{project_id}/images/upload",
        files=[("files[]", (filename, _make_png_bytes(), "image/png"))],
    )
    assert resp.status_code == 200
    return resp.json()["data"]["image_ids"][0]


def _assert_polygon(polygon: list[list[float]]) -> None:
    assert len(polygon) >= 4
    for point in polygon:
        assert len(point) == 2
        assert 0.0 <= point[0] <= 1.0
        assert 0.0 <= point[1] <= 1.0


def test_segmentation_auto_annotation_generates_polygon(client):
    project_id = _create_segmentation_project(client)
    image_id = _upload_single_image(client, project_id)

    start = client.post(f"/api/projects/{project_id}/annotate", json={"image_ids": [image_id]})
    assert start.status_code == 200

    final_status = _poll_task_until_finished(client, start.json()["data"]["task_id"])
    assert final_status["status"] == "SUCCESS"

    anns_resp = client.get(f"/api/images/{image_id}/annotations")
    assert anns_resp.status_code == 200
    annotations = anns_resp.json()["data"]
    assert len(annotations) >= 1

    for annotation in annotations:
        assert annotation["bbox"] is not None
        assert annotation["polygon"] is not None
        _assert_polygon(annotation["polygon"])


def test_segmentation_manual_annotation_generates_polygon(client):
    project_id = _create_segmentation_project(client)
    image_id = _upload_single_image(client, project_id, filename="manual.png")

    create = client.post(
        f"/api/images/{image_id}/annotations",
        json={"label": "crack", "bbox": [0.1, 0.15, 0.7, 0.8], "source": "manual"},
    )
    assert create.status_code == 200

    anns_resp = client.get(f"/api/images/{image_id}/annotations")
    assert anns_resp.status_code == 200
    annotations = anns_resp.json()["data"]
    assert len(annotations) == 1
    annotation = annotations[0]
    assert annotation["source"] == "manual"
    assert annotation["bbox"] == [0.1, 0.15, 0.7, 0.8]
    assert annotation["polygon"] is not None
    _assert_polygon(annotation["polygon"])
