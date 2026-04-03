from __future__ import annotations

import ast
import io
import json
import re
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api import AppError
from backend.models.annotation import Annotation
from backend.models.image import Image
from backend.models.project import Project
from backend.services.postprocess import apply_project_postprocess, save_polygon_mask
from backend.services.project_settings import get_project_labels, load_project_settings
from backend.services.quality_service import refresh_project_quality_scores
from backend.services.sam_service import SAMService
from backend.utils.storage import ensure_project_dirs, project_dir, resolve_path, safe_filename, save_project_image_bytes


DatasetFormat = Literal["yolo", "coco"]

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VALID_SPLITS = {"train", "val", "test"}


@dataclass
class DatasetImportResult:
    imported_count: int
    annotation_count: int
    labels: list[str]


def export_project_dataset(project: Project, db: Session, format_name: DatasetFormat) -> Path:
    rows = db.execute(
        select(Image, Annotation)
        .join(Annotation, Annotation.image_id == Image.id)
        .where(Image.project_id == project.id, Annotation.is_confirmed.is_(True))
        .order_by(Image.id.asc(), Annotation.id.asc())
    ).all()

    grouped: dict[int, dict[str, Any]] = {}
    ordered_annotations: list[Annotation] = []
    for image, annotation in rows:
        if annotation.bbox is None:
            continue
        bucket = grouped.setdefault(image.id, {"image": image, "annotations": []})
        bucket["annotations"].append(annotation)
        ordered_annotations.append(annotation)

    if not grouped:
        raise AppError(400, "no confirmed annotations available for export")

    labels = _build_label_list(project, ordered_annotations)
    if not labels:
        raise AppError(400, "no labels available for export")

    ensure_project_dirs(project.id)
    export_root = project_dir(project.id) / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = export_root / f"project_{project.id}_{format_name}_{timestamp}.zip"

    with tempfile.TemporaryDirectory(prefix=f"export-{format_name}-") as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        if format_name == "yolo":
            _write_yolo_export(tmp_dir, grouped, labels)
        elif format_name == "coco":
            _write_coco_export(tmp_dir, grouped, labels)
        else:
            raise AppError(400, f"unsupported export format: {format_name}")
        _zip_directory(tmp_dir, zip_path)

    return zip_path


def import_project_dataset(
    project: Project,
    db: Session,
    *,
    format_name: DatasetFormat,
    archive_name: str,
    archive_bytes: bytes,
) -> DatasetImportResult:
    if not archive_bytes:
        raise AppError(400, "empty archive")

    ensure_project_dirs(project.id)
    created_files: list[Path] = []

    try:
        with tempfile.TemporaryDirectory(prefix=f"import-{format_name}-") as tmp_dir_name:
            archive_path = Path(tmp_dir_name) / safe_filename(archive_name or f"dataset_{format_name}.zip")
            archive_path.write_bytes(archive_bytes)

            try:
                with zipfile.ZipFile(archive_path) as zf:
                    zf.extractall(Path(tmp_dir_name) / "unzipped")
            except zipfile.BadZipFile as exc:
                raise AppError(400, f"invalid zip file: {exc}") from exc

            extracted_root = Path(tmp_dir_name) / "unzipped"
            if format_name == "yolo":
                result = _import_yolo_dataset(project, db, extracted_root, created_files)
            elif format_name == "coco":
                result = _import_coco_dataset(project, db, extracted_root, created_files)
            else:
                raise AppError(400, f"unsupported import format: {format_name}")

        db.commit()
        return result
    except AppError:
        db.rollback()
        _cleanup_files(created_files)
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _cleanup_files(created_files)
        raise AppError(400, f"failed to import dataset: {exc}") from exc


def _build_label_list(project: Project, annotations: list[Annotation]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()

    for label in get_project_labels(project):
        if label in seen:
            continue
        labels.append(label)
        seen.add(label)

    for annotation in annotations:
        label = annotation.label.strip()
        if not label or label in seen:
            continue
        labels.append(label)
        seen.add(label)

    return labels


def _write_yolo_export(
    root_dir: Path,
    grouped: dict[int, dict[str, Any]],
    labels: list[str],
) -> None:
    image_dirs = {split: root_dir / "images" / split for split in VALID_SPLITS}
    label_dirs = {split: root_dir / "labels" / split for split in VALID_SPLITS}
    for path in [*image_dirs.values(), *label_dirs.values()]:
        path.mkdir(parents=True, exist_ok=True)

    label_to_index = {label: idx for idx, label in enumerate(labels)}

    for payload in grouped.values():
        image: Image = payload["image"]
        annotations: list[Annotation] = payload["annotations"]
        split = _normalize_split(image.split)
        export_name = _export_image_name(image)
        image_dst = image_dirs[split] / export_name
        image_dst.write_bytes(resolve_path(image.file_path).read_bytes())

        label_dst = label_dirs[split] / f"{Path(export_name).stem}.txt"
        lines: list[str] = []
        for annotation in annotations:
            class_id = label_to_index[annotation.label]
            xmin, ymin, xmax, ymax = [float(v) for v in annotation.bbox or []]
            cx = (xmin + xmax) / 2
            cy = (ymin + ymax) / 2
            width = xmax - xmin
            height = ymax - ymin
            lines.append(
                f"{class_id} {cx:.6f} {cy:.6f} {width:.6f} {height:.6f}"
            )
        label_dst.write_text("\n".join(lines) + "\n", encoding="utf-8")

    manifest = {
        "project_id": next(iter(grouped.values()))["image"].project_id,
        "format": "yolo",
        "confirmed_only": True,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
    }
    (root_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    names_repr = ", ".join(json.dumps(label, ensure_ascii=False) for label in labels)
    dataset_yaml = "\n".join(
        [
            "path: .",
            "train: images/train",
            "val: images/val",
            "test: images/test",
            f"nc: {len(labels)}",
            f"names: [{names_repr}]",
            "",
        ]
    )
    (root_dir / "dataset.yaml").write_text(dataset_yaml, encoding="utf-8")


def _write_coco_export(
    root_dir: Path,
    grouped: dict[int, dict[str, Any]],
    labels: list[str],
) -> None:
    label_to_category_id = {label: idx + 1 for idx, label in enumerate(labels)}
    annotations_dir = root_dir / "annotations"
    annotations_dir.mkdir(parents=True, exist_ok=True)

    split_payloads: dict[str, dict[str, Any]] = {
        split: {
            "images": [],
            "annotations": [],
            "categories": [{"id": idx + 1, "name": label, "supercategory": "object"} for idx, label in enumerate(labels)],
        }
        for split in VALID_SPLITS
    }

    for payload in grouped.values():
        image: Image = payload["image"]
        annotations: list[Annotation] = payload["annotations"]
        split = _normalize_split(image.split)
        export_name = _export_image_name(image)
        image_dst = root_dir / "images" / split / export_name
        image_dst.parent.mkdir(parents=True, exist_ok=True)
        image_dst.write_bytes(resolve_path(image.file_path).read_bytes())

        image_w = int(image.width or 1)
        image_h = int(image.height or 1)
        split_payloads[split]["images"].append(
            {
                "id": image.id,
                "file_name": f"{split}/{export_name}",
                "width": image_w,
                "height": image_h,
                "split": split,
            }
        )

        for annotation in annotations:
            bbox = annotation.bbox or [0.0, 0.0, 0.0, 0.0]
            xmin, ymin, xmax, ymax = [float(v) for v in bbox]
            bbox_px = [
                round(xmin * image_w, 2),
                round(ymin * image_h, 2),
                round((xmax - xmin) * image_w, 2),
                round((ymax - ymin) * image_h, 2),
            ]
            payload_ann: dict[str, Any] = {
                "id": annotation.id,
                "image_id": image.id,
                "category_id": label_to_category_id[annotation.label],
                "bbox": bbox_px,
                "area": round(max(bbox_px[2], 0.0) * max(bbox_px[3], 0.0), 2),
                "iscrowd": 0,
            }
            segmentation = _annotation_polygon_to_coco(annotation.polygon, image_w, image_h)
            if segmentation:
                payload_ann["segmentation"] = [segmentation]
            split_payloads[split]["annotations"].append(payload_ann)

    manifest = {
        "project_id": next(iter(grouped.values()))["image"].project_id,
        "format": "coco",
        "confirmed_only": True,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
    }
    (root_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    for split, payload in split_payloads.items():
        if not payload["images"]:
            continue
        json_path = annotations_dir / f"instances_{split}.json"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _annotation_polygon_to_coco(polygon: list[list[float]] | None, width: int, height: int) -> list[float] | None:
    if not polygon or len(polygon) < 3:
        return None
    coords: list[float] = []
    for point in polygon:
        if len(point) != 2:
            continue
        coords.extend([round(float(point[0]) * width, 2), round(float(point[1]) * height, 2)])
    return coords or None


def _zip_directory(source_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_dir():
                continue
            zf.write(path, arcname=path.relative_to(source_dir).as_posix())


def _import_yolo_dataset(
    project: Project,
    db: Session,
    extracted_root: Path,
    created_files: list[Path],
) -> DatasetImportResult:
    yaml_path = _find_first(extracted_root, ("dataset.yaml", "data.yaml"))
    labels_from_yaml = _parse_yolo_names(yaml_path.read_text(encoding="utf-8")) if yaml_path else []

    image_files = [path for path in extracted_root.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES]
    if not image_files:
        raise AppError(400, "no image files found in YOLO archive")

    annotation_count = 0
    imported_images = 0
    seen_labels: list[str] = []
    seen_set: set[str] = set()
    existing_labels = get_project_labels(project)

    for image_path in sorted(image_files):
        if "labels" in image_path.parts:
            continue
        split = _infer_split_from_path(image_path)
        image_bytes = image_path.read_bytes()
        width, height = _image_size_from_bytes(image_bytes)

        image = Image(
            project_id=project.id,
            filename=image_path.name,
            file_path="",
            width=width,
            height=height,
            split=split,
            status="done",
        )
        db.add(image)
        db.flush()
        stored_path = save_project_image_bytes(project.id, image.id, image.filename, image_bytes)
        image.file_path = stored_path
        created_files.append(resolve_path(stored_path))
        imported_images += 1

        label_path = _guess_yolo_label_path(image_path)
        if not label_path.exists():
            continue

        for line in label_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            annotation = _parse_yolo_annotation_line(
                stripped,
                project=project,
                labels_from_yaml=labels_from_yaml,
                project_labels=existing_labels,
                width=width,
                height=height,
                task_type=project.task_type,
                image=image,
            )
            db.add(annotation)
            annotation_count += 1
            if annotation.label not in seen_set:
                seen_labels.append(annotation.label)
                seen_set.add(annotation.label)

    if imported_images == 0:
        raise AppError(400, "no images were imported from YOLO archive")

    _merge_project_labels(project, [*existing_labels, *seen_labels])
    refresh_project_quality_scores(db, project.id)
    db.add(project)
    return DatasetImportResult(imported_count=imported_images, annotation_count=annotation_count, labels=get_project_labels(project))


def _parse_yolo_annotation_line(
    line: str,
    *,
    project: Project,
    labels_from_yaml: list[str],
    project_labels: list[str],
    width: int,
    height: int,
    task_type: str,
    image: Image,
) -> Annotation:
    parts = line.split()
    if len(parts) < 5:
        raise AppError(400, f"invalid YOLO annotation line: {line}")

    try:
        class_id = int(parts[0])
    except ValueError as exc:
        raise AppError(400, f"invalid class id in YOLO annotation: {line}") from exc

    label_candidates = labels_from_yaml or project_labels
    if 0 <= class_id < len(label_candidates):
        label = label_candidates[class_id]
    else:
        label = f"class_{class_id}"

    polygon: list[list[float]] | None = None
    if len(parts) >= 7 and len(parts[1:]) % 2 == 0:
        coords = [float(v) for v in parts[1:]]
        polygon = []
        for idx in range(0, len(coords), 2):
            polygon.append([_clamp01(coords[idx]), _clamp01(coords[idx + 1])])
        bbox = _bbox_from_polygon(polygon)
    else:
        cx, cy, box_w, box_h = [float(v) for v in parts[1:5]]
        bbox = _normalize_bbox(
            [
                cx - box_w / 2,
                cy - box_h / 2,
                cx + box_w / 2,
                cy + box_h / 2,
            ]
        )

    mask_path: str | None = None
    if task_type == "segmentation":
        sam_settings = load_project_settings(project).get("sam", {})
        sam_kwargs = {
            "checkpoint": str(sam_settings.get("checkpoint") or "sam3"),
            "device": str(sam_settings.get("device") or "cuda"),
            "multimask_output": bool(sam_settings.get("multimask_output", False)),
        }
        if polygon is None:
            prediction = SAMService().predict_polygon(image, bbox, **sam_kwargs)
            processed = apply_project_postprocess(
                project,
                image,
                mask=prediction.mask,
                bbox=prediction.bbox or bbox,
                provider=prediction.provider,
                score=prediction.score,
            )
            bbox = processed.bbox or bbox
            polygon = processed.polygon
            mask_path = processed.mask_path
        else:
            bbox = _normalize_bbox(_bbox_from_polygon(polygon))
            mask_path = save_polygon_mask(image, polygon, stem="import_polygon")

    return Annotation(
        image_id=image.id,
        label=label,
        bbox=bbox,
        polygon=polygon if task_type == "segmentation" else None,
        mask_path=mask_path if task_type == "segmentation" else None,
        source="manual",
        is_confirmed=True,
    )


def _guess_yolo_label_path(image_path: Path) -> Path:
    parts = list(image_path.parts)
    if "images" in parts:
        idx = parts.index("images")
        candidate_parts = parts[:]
        candidate_parts[idx] = "labels"
        candidate = Path(*candidate_parts).with_suffix(".txt")
        if candidate.exists():
            return candidate
    return image_path.with_suffix(".txt")


def _import_coco_dataset(
    project: Project,
    db: Session,
    extracted_root: Path,
    created_files: list[Path],
) -> DatasetImportResult:
    annotation_files = [path for path in extracted_root.rglob("*.json") if _looks_like_coco_file(path)]
    if not annotation_files:
        raise AppError(400, "no COCO annotation json found in archive")

    annotation_count = 0
    imported_images = 0
    seen_labels: list[str] = []
    seen_set: set[str] = set()
    existing_labels = get_project_labels(project)

    for json_path in sorted(annotation_files):
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        images = payload.get("images")
        annotations = payload.get("annotations")
        categories = payload.get("categories")
        if not isinstance(images, list) or not isinstance(annotations, list) or not isinstance(categories, list):
            continue

        category_map = {
            int(item["id"]): str(item["name"]).strip()
            for item in categories
            if isinstance(item, dict) and "id" in item and "name" in item and str(item["name"]).strip()
        }
        annotations_by_image: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for item in annotations:
            if isinstance(item, dict) and item.get("image_id") is not None:
                annotations_by_image[int(item["image_id"])].append(item)

        for image_payload in images:
            if not isinstance(image_payload, dict):
                continue
            image_id = int(image_payload.get("id", 0))
            file_name = str(image_payload.get("file_name", "")).strip()
            if not file_name:
                raise AppError(400, f"COCO image entry missing file_name in {json_path.name}")
            image_file = _locate_coco_image_file(extracted_root, json_path, file_name)
            if image_file is None or not image_file.exists():
                raise AppError(400, f"image file not found for COCO entry: {file_name}")

            image_bytes = image_file.read_bytes()
            width = int(image_payload.get("width") or _image_size_from_bytes(image_bytes)[0])
            height = int(image_payload.get("height") or _image_size_from_bytes(image_bytes)[1])
            split = _normalize_split(
                str(image_payload.get("split") or _infer_split_from_path(image_file) or _infer_split_from_name(json_path.name))
            )

            image = Image(
                project_id=project.id,
                filename=Path(file_name).name,
                file_path="",
                width=width,
                height=height,
                split=split,
                status="done",
            )
            db.add(image)
            db.flush()
            stored_path = save_project_image_bytes(project.id, image.id, image.filename, image_bytes)
            image.file_path = stored_path
            created_files.append(resolve_path(stored_path))
            imported_images += 1

            for ann_payload in annotations_by_image.get(image_id, []):
                annotation = _parse_coco_annotation(
                    ann_payload,
                    project=project,
                    category_map=category_map,
                    width=width,
                    height=height,
                    task_type=project.task_type,
                    image=image,
                )
                db.add(annotation)
                annotation_count += 1
                if annotation.label not in seen_set:
                    seen_labels.append(annotation.label)
                    seen_set.add(annotation.label)

    if imported_images == 0:
        raise AppError(400, "no images were imported from COCO archive")

    _merge_project_labels(project, [*existing_labels, *seen_labels])
    refresh_project_quality_scores(db, project.id)
    db.add(project)
    return DatasetImportResult(imported_count=imported_images, annotation_count=annotation_count, labels=get_project_labels(project))


def _parse_coco_annotation(
    ann_payload: dict[str, Any],
    *,
    project: Project,
    category_map: dict[int, str],
    width: int,
    height: int,
    task_type: str,
    image: Image,
) -> Annotation:
    category_id = ann_payload.get("category_id")
    if category_id is None:
        raise AppError(400, "COCO annotation missing category_id")
    label = category_map.get(int(category_id))
    if not label:
        raise AppError(400, f"COCO category not found: {category_id}")

    bbox_raw = ann_payload.get("bbox")
    if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
        raise AppError(400, "COCO annotation bbox must contain 4 numbers")
    xmin, ymin, box_w, box_h = [float(v) for v in bbox_raw]
    bbox = _normalize_bbox([xmin / width, ymin / height, (xmin + box_w) / width, (ymin + box_h) / height])

    polygon = _coco_segmentation_to_polygon(ann_payload.get("segmentation"), width, height)
    mask_path: str | None = None
    if task_type == "segmentation" and polygon is None:
        sam_settings = load_project_settings(project).get("sam", {})
        prediction = SAMService().predict_polygon(
            image,
            bbox,
            checkpoint=str(sam_settings.get("checkpoint") or "sam3"),
            device=str(sam_settings.get("device") or "cuda"),
            multimask_output=bool(sam_settings.get("multimask_output", False)),
        )
        processed = apply_project_postprocess(
            project,
            image,
            mask=prediction.mask,
            bbox=prediction.bbox or bbox,
            provider=prediction.provider,
            score=prediction.score,
        )
        bbox = processed.bbox or bbox
        polygon = processed.polygon
        mask_path = processed.mask_path
    elif task_type == "segmentation" and polygon is not None:
        mask_path = save_polygon_mask(image, polygon, stem="import_polygon")

    return Annotation(
        image_id=image.id,
        label=label,
        bbox=bbox,
        polygon=polygon if task_type == "segmentation" else None,
        mask_path=mask_path if task_type == "segmentation" else None,
        source="manual",
        is_confirmed=True,
    )


def _coco_segmentation_to_polygon(segmentation: Any, width: int, height: int) -> list[list[float]] | None:
    if not isinstance(segmentation, list) or not segmentation:
        return None
    first = segmentation[0]
    if not isinstance(first, list) or len(first) < 6 or len(first) % 2 != 0:
        return None
    polygon: list[list[float]] = []
    for idx in range(0, len(first), 2):
        polygon.append([_clamp01(float(first[idx]) / width), _clamp01(float(first[idx + 1]) / height)])
    return polygon


def _locate_coco_image_file(extracted_root: Path, json_path: Path, file_name: str) -> Path | None:
    normalized = PurePosixPath(file_name)
    candidates = [
        extracted_root / normalized.as_posix(),
        extracted_root / "images" / normalized.as_posix(),
        json_path.parent / normalized.as_posix(),
        json_path.parent.parent / "images" / normalized.as_posix(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    matching = list(extracted_root.rglob(Path(file_name).name))
    if matching:
        return matching[0]
    return None


def _find_first(root: Path, names: tuple[str, ...]) -> Path | None:
    lowered = {name.lower() for name in names}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name.lower() in lowered:
            return path
    return None


def _parse_yolo_names(text: str) -> list[str]:
    names: list[str] = []
    in_block = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("names:"):
            rest = stripped[len("names:") :].strip()
            if rest:
                parsed = _parse_yolo_names_inline(rest)
                if parsed:
                    return parsed
            in_block = True
            continue
        if in_block:
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*:", stripped):
                break
            list_match = re.match(r"^-\s*(.+)$", stripped)
            dict_match = re.match(r"^(\d+)\s*:\s*(.+)$", stripped)
            if list_match:
                label = _strip_yaml_scalar(list_match.group(1))
                if label:
                    names.append(label)
                continue
            if dict_match:
                label = _strip_yaml_scalar(dict_match.group(2))
                if label:
                    index = int(dict_match.group(1))
                    while len(names) <= index:
                        names.append("")
                    names[index] = label
                continue
            if names:
                break
    return [label for label in names if label]


def _parse_yolo_names_inline(raw: str) -> list[str]:
    candidate = raw.strip()
    try:
        parsed = ast.literal_eval(candidate)
    except Exception:
        return []
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    if isinstance(parsed, dict):
        items = sorted((int(key), str(value).strip()) for key, value in parsed.items() if str(value).strip())
        return [value for _key, value in items]
    return []


def _strip_yaml_scalar(value: str) -> str:
    cleaned = value.strip().strip("'").strip('"')
    return cleaned


def _looks_like_coco_file(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return isinstance(payload, dict) and all(key in payload for key in ("images", "annotations", "categories"))


def _image_size_from_bytes(content: bytes) -> tuple[int, int]:
    try:
        image = PILImage.open(io.BytesIO(content))
        image.load()
        return int(image.size[0]), int(image.size[1])
    except Exception as exc:  # noqa: BLE001
        raise AppError(400, f"invalid image file: {exc}") from exc


def _merge_project_labels(project: Project, labels: list[str]) -> None:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in labels:
        label = str(item).strip()
        if not label or label in seen:
            continue
        cleaned.append(label)
        seen.add(label)

    stored: dict[str, Any] = {}
    if project.config:
        try:
            loaded = json.loads(project.config)
            if isinstance(loaded, dict):
                stored = loaded
        except Exception:
            stored = {}
    stored["labels"] = cleaned
    project.config = json.dumps(stored, ensure_ascii=False)


def _cleanup_files(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            continue


def _normalize_split(value: str | None) -> str:
    if not value:
        return "train"
    text = str(value).strip().lower()
    return text if text in VALID_SPLITS else "train"


def _infer_split_from_name(name: str) -> str | None:
    lowered = name.lower()
    for split in ("train", "val", "test"):
        if split in lowered:
            return split
    return None


def _infer_split_from_path(path: Path) -> str:
    lowered_parts = [part.lower() for part in path.parts]
    for split in ("train", "val", "test"):
        if split in lowered_parts:
            return split
    return "train"


def _export_image_name(image: Image) -> str:
    return f"{image.id}_{safe_filename(image.filename)}"


def _normalize_bbox(values: list[float]) -> list[float]:
    xmin, ymin, xmax, ymax = [float(v) for v in values]
    if xmin > xmax:
        xmin, xmax = xmax, xmin
    if ymin > ymax:
        ymin, ymax = ymax, ymin
    xmin = _clamp01(xmin)
    ymin = _clamp01(ymin)
    xmax = _clamp01(xmax)
    ymax = _clamp01(ymax)
    if xmax <= xmin:
        xmax = min(1.0, xmin + 0.001)
    if ymax <= ymin:
        ymax = min(1.0, ymin + 0.001)
    return [round(xmin, 6), round(ymin, 6), round(xmax, 6), round(ymax, 6)]


def _bbox_from_polygon(polygon: list[list[float]]) -> list[float]:
    xs = [float(point[0]) for point in polygon]
    ys = [float(point[1]) for point in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
