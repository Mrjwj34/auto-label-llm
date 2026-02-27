from __future__ import annotations

import io

from PIL import Image as PILImage


def _make_png_bytes(width: int = 64, height: int = 48) -> bytes:
    img = PILImage.new("RGB", (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_create_and_list_projects(client):
    resp = client.post("/api/projects", json={"name": "test", "task_type": "detection"})
    assert resp.status_code == 200
    project_id = resp.json()["data"]["id"]
    assert isinstance(project_id, int)

    resp2 = client.get("/api/projects")
    assert resp2.status_code == 200
    projects = resp2.json()["data"]
    assert any(p["id"] == project_id for p in projects)


def test_upload_and_list_images(client):
    resp = client.post("/api/projects", json={"name": "p1", "task_type": "detection"})
    project_id = resp.json()["data"]["id"]

    png_bytes = _make_png_bytes()
    files = [("files[]", ("a.png", png_bytes, "image/png"))]
    up = client.post(f"/api/projects/{project_id}/images/upload", files=files)
    assert up.status_code == 200
    payload = up.json()["data"]
    assert payload["uploaded"] == 1
    image_id = payload["image_ids"][0]

    lst = client.get(f"/api/projects/{project_id}/images")
    assert lst.status_code == 200
    rows = lst.json()["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == image_id
    assert rows[0]["width"] == 64
    assert rows[0]["height"] == 48
    assert rows[0]["file_url"].startswith("/api/images/")

    file_resp = client.get(rows[0]["file_url"])
    assert file_resp.status_code == 200
    assert file_resp.headers.get("content-type", "").startswith("image/")


def test_upload_rejects_non_image(client):
    resp = client.post("/api/projects", json={"name": "p1", "task_type": "detection"})
    project_id = resp.json()["data"]["id"]

    files = [("files[]", ("a.txt", b"not an image", "text/plain"))]
    up = client.post(f"/api/projects/{project_id}/images/upload", files=files)
    assert up.status_code == 400

