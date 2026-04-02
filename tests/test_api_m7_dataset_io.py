from __future__ import annotations

import io
import json
import zipfile

from PIL import Image as PILImage


def _make_png_bytes(width: int = 96, height: int = 72, color: tuple[int, int, int] = (32, 96, 220)) -> bytes:
    img = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_project(client, *, name: str, task_type: str, labels: list[str] | None = None) -> int:
    resp = client.post("/api/projects", json={"name": name, "task_type": task_type})
    assert resp.status_code == 200
    project_id = resp.json()["data"]["id"]
    if labels is not None:
        patch = client.patch(f"/api/projects/{project_id}/settings", json={"labels": labels})
        assert patch.status_code == 200
    return project_id


def _upload_image(client, project_id: int, filename: str, *, width: int = 96, height: int = 72) -> int:
    resp = client.post(
        f"/api/projects/{project_id}/images/upload",
        files=[("files[]", (filename, _make_png_bytes(width, height), "image/png"))],
    )
    assert resp.status_code == 200
    return resp.json()["data"]["image_ids"][0]


def _confirm_annotation(client, annotation_id: int) -> None:
    resp = client.patch(f"/api/annotations/{annotation_id}/confirm")
    assert resp.status_code == 200


def _read_zip_map(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        return {name: zf.read(name) for name in zf.namelist() if not name.endswith("/")}


def test_export_yolo_contains_dataset_yaml_images_and_labels(client):
    project_id = _create_project(client, name="export-yolo", task_type="detection", labels=["crack", "scratch"])
    image_train = _upload_image(client, project_id, "train.png", width=100, height=80)
    image_val = _upload_image(client, project_id, "val.png", width=120, height=90)

    split_patch = client.patch(f"/api/images/{image_val}", json={"split": "val"})
    assert split_patch.status_code == 200

    ann_train = client.post(
        f"/api/images/{image_train}/annotations",
        json={"label": "crack", "bbox": [0.1, 0.2, 0.4, 0.6], "source": "manual"},
    )
    assert ann_train.status_code == 200
    _confirm_annotation(client, ann_train.json()["data"]["id"])

    ann_val = client.post(
        f"/api/images/{image_val}/annotations",
        json={"label": "scratch", "bbox": [0.25, 0.1, 0.7, 0.5], "source": "manual"},
    )
    assert ann_val.status_code == 200
    _confirm_annotation(client, ann_val.json()["data"]["id"])

    export = client.get(f"/api/projects/{project_id}/export", params={"format": "yolo"})
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("application/zip")

    files = _read_zip_map(export.content)
    names = set(files)
    assert "dataset.yaml" in names
    assert "manifest.json" in names
    assert any(name.startswith("images/train/") and name.endswith(".png") for name in names)
    assert any(name.startswith("images/val/") and name.endswith(".png") for name in names)
    assert any(name.startswith("labels/train/") and name.endswith(".txt") for name in names)
    assert any(name.startswith("labels/val/") and name.endswith(".txt") for name in names)

    dataset_yaml = files["dataset.yaml"].decode("utf-8")
    assert "names: [\"crack\", \"scratch\"]" in dataset_yaml

    train_label_name = next(name for name in names if name.startswith("labels/train/") and name.endswith(".txt"))
    val_label_name = next(name for name in names if name.startswith("labels/val/") and name.endswith(".txt"))
    assert files[train_label_name].decode("utf-8").strip().startswith("0 ")
    assert files[val_label_name].decode("utf-8").strip().startswith("1 ")


def test_export_coco_contains_split_json_and_segmentation(client):
    project_id = _create_project(client, name="export-coco", task_type="segmentation", labels=["crack"])
    image_id = _upload_image(client, project_id, "seg.png", width=200, height=120)

    create = client.post(
        f"/api/images/{image_id}/predict",
        json={"annotation_id": None, "label": "crack", "bbox": [0.2, 0.25, 0.6, 0.7]},
    )
    assert create.status_code == 200
    _confirm_annotation(client, create.json()["data"]["annotation_id"])

    export = client.get(f"/api/projects/{project_id}/export", params={"format": "coco"})
    assert export.status_code == 200

    files = _read_zip_map(export.content)
    names = set(files)
    assert "manifest.json" in names
    assert "annotations/instances_train.json" in names
    assert any(name.startswith("images/train/") and name.endswith(".png") for name in names)

    payload = json.loads(files["annotations/instances_train.json"].decode("utf-8"))
    assert payload["categories"] == [{"id": 1, "name": "crack", "supercategory": "object"}]
    assert len(payload["images"]) == 1
    assert len(payload["annotations"]) == 1
    annotation = payload["annotations"][0]
    assert annotation["bbox"] == [40.0, 30.0, 80.0, 54.0]
    assert annotation["segmentation"]


def test_import_yolo_creates_images_annotations_and_project_labels(client):
    project_id = _create_project(client, name="import-yolo", task_type="detection")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "dataset.yaml",
            "\n".join(
                [
                    "path: .",
                    "train: images/train",
                    "val: images/val",
                    "test: images/test",
                    "nc: 1",
                    "names: [\"crack\"]",
                    "",
                ]
            ),
        )
        zf.writestr("images/train/sample.png", _make_png_bytes(width=100, height=80))
        zf.writestr("labels/train/sample.txt", "0 0.500000 0.500000 0.400000 0.500000\n")

    resp = client.post(
        f"/api/projects/{project_id}/import",
        data={"format": "yolo"},
        files={"file": ("dataset.zip", archive.getvalue(), "application/zip")},
    )
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["imported_count"] == 1
    assert payload["annotation_count"] == 1
    assert payload["labels"] == ["crack"]

    settings = client.get(f"/api/projects/{project_id}/settings")
    assert settings.status_code == 200
    assert settings.json()["data"]["labels"] == ["crack"]

    images = client.get(f"/api/projects/{project_id}/images")
    rows = images.json()["data"]
    assert len(rows) == 1
    assert rows[0]["split"] == "train"
    image_id = rows[0]["id"]

    annotations = client.get(f"/api/images/{image_id}/annotations")
    ann_rows = annotations.json()["data"]
    assert len(ann_rows) == 1
    assert ann_rows[0]["label"] == "crack"
    assert ann_rows[0]["bbox"] == [0.3, 0.25, 0.7, 0.75]
    assert ann_rows[0]["is_confirmed"] is True
    assert ann_rows[0]["source"] == "manual"


def test_import_coco_creates_segmentation_annotations(client):
    project_id = _create_project(client, name="import-coco", task_type="segmentation")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("images/train/sample.png", _make_png_bytes(width=100, height=80, color=(180, 30, 30)))
        zf.writestr(
            "annotations/instances_train.json",
            json.dumps(
                {
                    "images": [{"id": 7, "file_name": "train/sample.png", "width": 100, "height": 80, "split": "train"}],
                    "categories": [{"id": 1, "name": "crack"}],
                    "annotations": [
                        {
                            "id": 1,
                            "image_id": 7,
                            "category_id": 1,
                            "bbox": [10, 8, 30, 24],
                            "area": 720,
                            "iscrowd": 0,
                            "segmentation": [[10, 8, 40, 8, 40, 32, 10, 32]],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )

    resp = client.post(
        f"/api/projects/{project_id}/import",
        data={"format": "coco"},
        files={"file": ("dataset.zip", archive.getvalue(), "application/zip")},
    )
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["imported_count"] == 1
    assert payload["annotation_count"] == 1
    assert payload["labels"] == ["crack"]

    images = client.get(f"/api/projects/{project_id}/images")
    rows = images.json()["data"]
    assert len(rows) == 1
    image_id = rows[0]["id"]

    annotations = client.get(f"/api/images/{image_id}/annotations")
    ann_rows = annotations.json()["data"]
    assert len(ann_rows) == 1
    assert ann_rows[0]["label"] == "crack"
    assert ann_rows[0]["bbox"] == [0.1, 0.1, 0.4, 0.4]
    assert ann_rows[0]["polygon"] == [[0.1, 0.1], [0.4, 0.1], [0.4, 0.4], [0.1, 0.4]]
    assert ann_rows[0]["is_confirmed"] is True
