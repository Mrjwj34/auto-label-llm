from __future__ import annotations

import io

from PIL import Image as PILImage


def _make_png_bytes(width: int = 120, height: int = 90) -> bytes:
    image = PILImage.new("RGB", (width, height), color=(80, 170, 120))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_task_websocket_streams_progress_and_completion(client):
    project = client.post("/api/projects", json={"name": "m13-ws", "task_type": "detection"})
    assert project.status_code == 200
    project_id = int(project.json()["data"]["id"])

    labels = client.patch(f"/api/projects/{project_id}/settings", json={"labels": ["crack"]})
    assert labels.status_code == 200

    upload = client.post(
        f"/api/projects/{project_id}/images/upload",
        files=[("files[]", ("ws.png", _make_png_bytes(), "image/png"))],
    )
    assert upload.status_code == 200

    start = client.post(f"/api/projects/{project_id}/annotate", json={"only_pending": True})
    assert start.status_code == 200
    task_id = str(start.json()["data"]["task_id"])

    with client.websocket_connect(f"/ws/tasks/{task_id}") as websocket:
        messages: list[dict] = []
        for _ in range(20):
            payload = websocket.receive_json()
            messages.append(payload)
            if payload["status"] in ("SUCCESS", "FAILURE"):
                break

    assert messages
    assert all(message["task_id"] == task_id for message in messages)
    assert messages[-1]["status"] == "SUCCESS"
    assert 0 <= int(messages[-1]["progress"]) <= 100
