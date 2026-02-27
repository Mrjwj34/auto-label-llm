from __future__ import annotations

import io

from PIL import Image as PILImage


def _make_png_bytes(width: int = 80, height: int = 60) -> bytes:
    img = PILImage.new("RGB", (width, height), color=(0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_project_with_image(client) -> int:
    p = client.post("/api/projects", json={"name": "p1", "task_type": "detection"})
    project_id = p.json()["data"]["id"]
    up = client.post(
        f"/api/projects/{project_id}/images/upload",
        files=[("files[]", ("a.png", _make_png_bytes(), "image/png"))],
    )
    image_id = up.json()["data"]["image_ids"][0]
    return image_id


def test_get_image_detail(client):
    image_id = _create_project_with_image(client)
    resp = client.get(f"/api/images/{image_id}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == image_id
    assert data["file_url"].endswith(f"/api/images/{image_id}/file")


def test_create_and_list_annotations_bbox(client):
    image_id = _create_project_with_image(client)

    create = client.post(
        f"/api/images/{image_id}/annotations",
        json={"label": "螺丝孔缺陷", "bbox": [0.4, 0.5, 0.1, 0.2], "source": "manual"},
    )
    assert create.status_code == 200
    ann_id = create.json()["data"]["id"]
    assert isinstance(ann_id, int)

    lst = client.get(f"/api/images/{image_id}/annotations")
    assert lst.status_code == 200
    anns = lst.json()["data"]
    assert len(anns) == 1
    assert anns[0]["id"] == ann_id
    assert anns[0]["label"] == "螺丝孔缺陷"
    assert anns[0]["bbox"] == [0.1, 0.2, 0.4, 0.5]  # server canonicalizes min/max


def test_create_annotation_rejects_out_of_range_bbox(client):
    image_id = _create_project_with_image(client)

    bad = client.post(
        f"/api/images/{image_id}/annotations",
        json={"label": "obj", "bbox": [-0.1, 0.2, 0.4, 0.5]},
    )
    assert bad.status_code == 400


def test_delete_annotation(client):
    image_id = _create_project_with_image(client)

    create = client.post(
        f"/api/images/{image_id}/annotations",
        json={"label": "obj", "bbox": [0.1, 0.1, 0.4, 0.4]},
    )
    ann_id = create.json()["data"]["id"]

    resp = client.delete(f"/api/annotations/{ann_id}")
    assert resp.status_code == 200

    lst = client.get(f"/api/images/{image_id}/annotations")
    assert lst.status_code == 200
    assert lst.json()["data"] == []
