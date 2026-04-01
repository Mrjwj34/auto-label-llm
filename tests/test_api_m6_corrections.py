from __future__ import annotations

import io

from PIL import Image as PILImage


def _make_png_bytes(width: int = 200, height: int = 120, color: tuple[int, int, int] = (120, 80, 240)) -> bytes:
    img = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_project(client, *, task_type: str, labels: list[str]) -> int:
    project_resp = client.post("/api/projects", json={"name": f"{task_type}-project", "task_type": task_type})
    assert project_resp.status_code == 200
    project_id = project_resp.json()["data"]["id"]

    patch_resp = client.patch(f"/api/projects/{project_id}/settings", json={"labels": labels})
    assert patch_resp.status_code == 200
    return project_id


def _upload_image(client, project_id: int, filename: str = "sample.png") -> int:
    resp = client.post(
        f"/api/projects/{project_id}/images/upload",
        files=[("files[]", (filename, _make_png_bytes(), "image/png"))],
    )
    assert resp.status_code == 200
    return resp.json()["data"]["image_ids"][0]


def _list_annotations(client, image_id: int) -> list[dict]:
    resp = client.get(f"/api/images/{image_id}/annotations")
    assert resp.status_code == 200
    return resp.json()["data"]


def test_predict_bbox_creates_corrected_annotation(client):
    project_id = _create_project(client, task_type="detection", labels=["crack"])
    image_id = _upload_image(client, project_id)

    resp = client.post(
        f"/api/images/{image_id}/predict",
        json={"annotation_id": None, "label": "crack", "bbox": [0.15, 0.2, 0.55, 0.75]},
    )
    assert resp.status_code == 200

    payload = resp.json()["data"]
    assert isinstance(payload["annotation_id"], int)
    assert payload["bbox"] == [0.15, 0.2, 0.55, 0.75]
    assert payload["polygon"] is None

    annotations = _list_annotations(client, image_id)
    assert len(annotations) == 1
    assert annotations[0]["source"] == "corrected"
    assert annotations[0]["is_confirmed"] is False


def test_confirm_annotation_marks_confirmed(client):
    project_id = _create_project(client, task_type="detection", labels=["crack"])
    image_id = _upload_image(client, project_id)

    create = client.post(
        f"/api/images/{image_id}/annotations",
        json={"label": "crack", "bbox": [0.1, 0.2, 0.5, 0.7], "source": "manual"},
    )
    assert create.status_code == 200
    annotation_id = create.json()["data"]["id"]

    confirm = client.patch(f"/api/annotations/{annotation_id}/confirm")
    assert confirm.status_code == 200

    annotations = _list_annotations(client, image_id)
    assert len(annotations) == 1
    assert annotations[0]["id"] == annotation_id
    assert annotations[0]["is_confirmed"] is True


def test_segmentation_point_correction_updates_polygon_and_resets_confirmation(client):
    project_id = _create_project(client, task_type="segmentation", labels=["crack"])
    image_id = _upload_image(client, project_id, filename="seg.png")

    create = client.post(
        f"/api/images/{image_id}/predict",
        json={"annotation_id": None, "label": "crack", "bbox": [0.2, 0.2, 0.6, 0.7]},
    )
    assert create.status_code == 200
    annotation_id = create.json()["data"]["annotation_id"]
    original_bbox = create.json()["data"]["bbox"]
    original_polygon = create.json()["data"]["polygon"]
    assert original_polygon is not None

    confirm = client.patch(f"/api/annotations/{annotation_id}/confirm")
    assert confirm.status_code == 200

    update = client.post(
        f"/api/images/{image_id}/predict",
        json={
            "annotation_id": annotation_id,
            "points": [
                {"x": 0.75, "y": 0.75, "label": 1},
                {"x": 0.22, "y": 0.28, "label": 0},
            ],
        },
    )
    assert update.status_code == 200
    updated_payload = update.json()["data"]
    assert updated_payload["annotation_id"] == annotation_id
    assert updated_payload["polygon"] is not None
    assert updated_payload["bbox"] != original_bbox
    assert updated_payload["polygon"] != original_polygon

    annotations = _list_annotations(client, image_id)
    assert len(annotations) == 1
    annotation = annotations[0]
    assert annotation["source"] == "corrected"
    assert annotation["is_confirmed"] is False
    assert annotation["polygon"] == updated_payload["polygon"]


def test_point_correction_rejects_detection_project(client):
    project_id = _create_project(client, task_type="detection", labels=["crack"])
    image_id = _upload_image(client, project_id, filename="det.png")

    create = client.post(
        f"/api/images/{image_id}/predict",
        json={"annotation_id": None, "label": "crack", "bbox": [0.2, 0.25, 0.5, 0.65]},
    )
    annotation_id = create.json()["data"]["annotation_id"]

    bad = client.post(
        f"/api/images/{image_id}/predict",
        json={"annotation_id": annotation_id, "points": [{"x": 0.3, "y": 0.4, "label": 1}]},
    )
    assert bad.status_code == 400
    assert "segmentation" in bad.json()["message"]
