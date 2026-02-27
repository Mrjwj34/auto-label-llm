from __future__ import annotations

import io
import time

from PIL import Image as PILImage


def _make_png_bytes(width: int = 120, height: int = 90) -> bytes:
    img = PILImage.new("RGB", (width, height), color=(30, 200, 120))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_annotate_task_progress_and_completion(client):
    p = client.post("/api/projects", json={"name": "p1", "task_type": "detection"})
    project_id = p.json()["data"]["id"]

    up = client.post(
        f"/api/projects/{project_id}/images/upload",
        files=[("files[]", ("a.png", _make_png_bytes(), "image/png"))],
    )
    image_id = up.json()["data"]["image_ids"][0]

    start = client.post(f"/api/images/{image_id}/annotate", json={"prompt": "stub"})
    assert start.status_code == 200
    task_id = start.json()["data"]["task_id"]
    assert isinstance(task_id, str) and task_id

    # Poll status until done
    last = None
    for _ in range(60):
        st = client.get(f"/api/tasks/{task_id}/status")
        assert st.status_code == 200
        payload = st.json()["data"]
        last = payload
        assert payload["status"] in ("PENDING", "STARTED", "SUCCESS", "FAILURE")
        assert 0 <= int(payload["progress"]) <= 100
        if payload["status"] in ("SUCCESS", "FAILURE"):
            break
        time.sleep(0.05)

    assert last is not None
    assert last["status"] == "SUCCESS"

    # Image status should become done
    lst = client.get(f"/api/projects/{project_id}/images")
    rows = lst.json()["data"]
    assert rows[0]["id"] == image_id
    assert rows[0]["status"] == "done"

