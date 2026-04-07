from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image as PILImage
from PIL import ImageDraw
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from backend.api import AppError
from backend.config import get_settings
from backend.database import get_session_factory
from backend.models.annotation import Annotation
from backend.models.evaluation_run import EvaluationRun
from backend.models.image import Image
from backend.models.project import Project
from backend.services.auto_annotator import generate_auto_annotations
from backend.services.project_settings import load_project_settings
from backend.services.vllm_client import GeneratedAnnotation, resolve_inference_route
from backend.tasks.task_manager import TaskContext, get_task_manager


def _store_path(path: Path) -> str:
    settings = get_settings()
    try:
        return path.resolve().relative_to(settings.root_dir).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _resolve_path(stored_path: str) -> Path:
    if not stored_path:
        return get_settings().root_dir
    path = Path(stored_path)
    if path.is_absolute():
        return path
    return (get_settings().root_dir / path).resolve()


def _report_root(project_id: int) -> Path:
    root = Path(get_settings().resolved_data_dir) / "projects" / str(project_id) / "reports" / "evaluations"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _load_json_dict(raw_text: str | None) -> dict[str, Any]:
    if not raw_text:
        return {}
    try:
        data = json.loads(raw_text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, ratio)) * (len(ordered) - 1)
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _clamp_unit(value: Any) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = 0.0
    return min(1.0, max(0.0, numeric))


def _rasterize_polygon(
    polygon: list[list[float]] | None,
    *,
    width: int | None,
    height: int | None,
) -> PILImage.Image | None:
    if not polygon or len(polygon) < 3 or not width or not height:
        return None
    canvas_width = max(1, int(width))
    canvas_height = max(1, int(height))
    mask = PILImage.new("1", (canvas_width, canvas_height), 0)
    points = [
        (
            _clamp_unit(point[0]) * max(0, canvas_width - 1),
            _clamp_unit(point[1]) * max(0, canvas_height - 1),
        )
        for point in polygon
        if isinstance(point, (list, tuple)) and len(point) >= 2
    ]
    if len(points) < 3:
        return None
    ImageDraw.Draw(mask).polygon(points, fill=1)
    return mask


def _mask_overlap_scores(
    prediction_polygon: list[list[float]] | None,
    ground_truth_polygon: list[list[float]] | None,
    *,
    width: int | None,
    height: int | None,
) -> tuple[float | None, float | None]:
    pred_mask = _rasterize_polygon(prediction_polygon, width=width, height=height)
    gt_mask = _rasterize_polygon(ground_truth_polygon, width=width, height=height)
    if pred_mask is None or gt_mask is None:
        return None, None

    pred_bytes = pred_mask.tobytes()
    gt_bytes = gt_mask.tobytes()
    intersection = 0
    union = 0
    pred_area = 0
    gt_area = 0
    for left, right in zip(pred_bytes, gt_bytes):
        intersection += (left & right).bit_count()
        union += (left | right).bit_count()
        pred_area += left.bit_count()
        gt_area += right.bit_count()

    if union <= 0 or (pred_area + gt_area) <= 0:
        return None, None
    iou = intersection / union
    dice = (2.0 * intersection) / (pred_area + gt_area)
    return iou, dice


def bbox_iou(left: list[float], right: list[float]) -> float:
    lx1, ly1, lx2, ly2 = [float(v) for v in left]
    rx1, ry1, rx2, ry2 = [float(v) for v in right]

    inter_x1 = max(lx1, rx1)
    inter_y1 = max(ly1, ry1)
    inter_x2 = min(lx2, rx2)
    inter_y2 = min(ly2, ry2)

    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0.0:
        return 0.0

    left_area = max(0.0, lx2 - lx1) * max(0.0, ly2 - ly1)
    right_area = max(0.0, rx2 - rx1) * max(0.0, ry2 - ry1)
    union = left_area + right_area - inter_area
    if union <= 0.0:
        return 0.0
    return inter_area / union


def _match_annotations(
    predictions: list[GeneratedAnnotation],
    ground_truth: list[Annotation],
    *,
    iou_threshold: float,
) -> tuple[list[dict[str, Any]], int, int, int]:
    candidates: list[tuple[float, int, int]] = []
    for pred_idx, prediction in enumerate(predictions):
        if prediction.bbox is None:
            continue
        for gt_idx, annotation in enumerate(ground_truth):
            if annotation.bbox is None or annotation.label != prediction.label:
                continue
            iou = bbox_iou(prediction.bbox, annotation.bbox)
            if iou >= iou_threshold:
                candidates.append((iou, pred_idx, gt_idx))

    candidates.sort(key=lambda item: item[0], reverse=True)
    matched_pred: set[int] = set()
    matched_gt: set[int] = set()
    matches: list[dict[str, Any]] = []

    for iou, pred_idx, gt_idx in candidates:
        if pred_idx in matched_pred or gt_idx in matched_gt:
            continue
        matched_pred.add(pred_idx)
        matched_gt.add(gt_idx)
        matches.append(
            {
                "prediction_index": pred_idx,
                "ground_truth_index": gt_idx,
                "label": predictions[pred_idx].label,
                "iou": round(iou, 4),
            }
        )

    tp = len(matches)
    fp = len(predictions) - tp
    fn = len(ground_truth) - tp
    return matches, tp, fp, fn


def _build_image_row(
    *,
    image: Image,
    predictions: list[GeneratedAnnotation],
    ground_truth: list[Annotation],
    matches: list[dict[str, Any]],
    tp: int,
    fp: int,
    fn: int,
    inference: dict[str, Any] | None,
) -> dict[str, Any]:
    matched_prediction_indices = {int(match["prediction_index"]) for match in matches}
    matched_ground_truth_indices = {int(match["ground_truth_index"]) for match in matches}

    bbox_ious: list[float] = []
    mask_ious: list[float] = []
    dice_scores: list[float] = []
    match_rows: list[dict[str, Any]] = []

    for match in matches:
        prediction = predictions[int(match["prediction_index"])]
        annotation = ground_truth[int(match["ground_truth_index"])]
        bbox_ious.append(float(match["iou"]))
        mask_iou, dice = _mask_overlap_scores(
            prediction.polygon,
            annotation.polygon,
            width=image.width,
            height=image.height,
        )
        if mask_iou is not None:
            mask_ious.append(mask_iou)
        if dice is not None:
            dice_scores.append(dice)

        match_rows.append(
            {
                **match,
                "mask_iou": _round_or_none(mask_iou),
                "dice": _round_or_none(dice),
            }
        )

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "image_id": image.id,
        "filename": image.filename,
        "split": image.split,
        "width": image.width,
        "height": image.height,
        "pred_count": len(predictions),
        "gt_count": len(ground_truth),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "error_count": fp + fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "miou_bbox": round(_safe_mean(bbox_ious) or 0.0, 4),
        "miou_mask": _round_or_none(_safe_mean(mask_ious)),
        "dice": _round_or_none(_safe_mean(dice_scores)),
        "mask_pairs": len(mask_ious),
        "matches": match_rows,
        "labels_seen": sorted({prediction.label for prediction in predictions} | {annotation.label for annotation in ground_truth}),
        "unmatched_prediction_labels": [
            prediction.label for idx, prediction in enumerate(predictions) if idx not in matched_prediction_indices
        ],
        "unmatched_ground_truth_labels": [
            annotation.label for idx, annotation in enumerate(ground_truth) if idx not in matched_ground_truth_indices
        ],
        "inference": inference or {},
    }


def _compute_performance_summary(per_image: list[dict[str, Any]]) -> dict[str, Any]:
    total_ms_values: list[float] = []
    llm_ms_values: list[float] = []
    sam_ms_values: list[float] = []
    postprocess_ms_values: list[float] = []
    segmentation_ms_values: list[float] = []
    providers: dict[str, int] = {}
    route_kinds: dict[str, int] = {}
    fallback_images = 0
    generated_annotations = 0

    for row in per_image:
        inference = row.get("inference", {})
        if not isinstance(inference, dict):
            continue
        provider = str(inference.get("provider") or "unknown")
        route_kind = str(inference.get("route_kind") or "unknown")
        providers[provider] = providers.get(provider, 0) + 1
        route_kinds[route_kind] = route_kinds.get(route_kind, 0) + 1
        if bool(inference.get("fallback_used")):
            fallback_images += 1

        generated_annotations += int(
            _as_float(inference.get("annotation_count")) or row.get("pred_count") or 0
        )

        total_ms = _as_float(inference.get("total_ms"))
        llm_ms = _as_float(inference.get("llm_ms"))
        sam_ms = _as_float(inference.get("sam_ms"))
        postprocess_ms = _as_float(inference.get("postprocess_ms"))
        segmentation_ms = _as_float(inference.get("segmentation_ms"))

        if total_ms is not None:
            total_ms_values.append(total_ms)
        if llm_ms is not None:
            llm_ms_values.append(llm_ms)
        if sam_ms is not None:
            sam_ms_values.append(sam_ms)
        if postprocess_ms is not None:
            postprocess_ms_values.append(postprocess_ms)
        if segmentation_ms is not None:
            segmentation_ms_values.append(segmentation_ms)

    return {
        "images_profiled": len(per_image),
        "generated_annotations": generated_annotations,
        "fallback_images": fallback_images,
        "providers": dict(sorted(providers.items())),
        "route_kinds": dict(sorted(route_kinds.items())),
        "total_elapsed_ms": _round_or_none(sum(total_ms_values), digits=2) if total_ms_values else None,
        "avg_total_ms": _round_or_none(_safe_mean(total_ms_values), digits=2),
        "p95_total_ms": _round_or_none(_percentile(total_ms_values, 0.95), digits=2),
        "max_total_ms": _round_or_none(max(total_ms_values), digits=2) if total_ms_values else None,
        "avg_llm_ms": _round_or_none(_safe_mean(llm_ms_values), digits=2),
        "avg_sam_ms": _round_or_none(_safe_mean(sam_ms_values), digits=2),
        "avg_postprocess_ms": _round_or_none(_safe_mean(postprocess_ms_values), digits=2),
        "avg_segmentation_ms": _round_or_none(_safe_mean(segmentation_ms_values), digits=2),
    }


def _build_failure_samples(per_image: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    ranked = sorted(
        per_image,
        key=lambda row: (
            -int(row.get("error_count", 0)),
            float(row.get("f1", 0.0)),
            float(row.get("miou_bbox", 0.0)),
            int(row.get("image_id", 0)),
        ),
    )
    rows: list[dict[str, Any]] = []
    for row in ranked:
        if int(row.get("error_count", 0)) <= 0:
            continue
        inference = row.get("inference", {})
        total_ms = _as_float(inference.get("total_ms")) if isinstance(inference, dict) else None
        rows.append(
            {
                "image_id": row["image_id"],
                "filename": row["filename"],
                "split": row["split"],
                "tp": row["tp"],
                "fp": row["fp"],
                "fn": row["fn"],
                "error_count": row["error_count"],
                "precision": row["precision"],
                "recall": row["recall"],
                "f1": row["f1"],
                "miou_bbox": row["miou_bbox"],
                "miou_mask": row.get("miou_mask"),
                "dice": row.get("dice"),
                "unmatched_prediction_labels": row["unmatched_prediction_labels"],
                "unmatched_ground_truth_labels": row["unmatched_ground_truth_labels"],
                "inference_total_ms": _round_or_none(total_ms, digits=2),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _compute_metrics(per_image: list[dict[str, Any]], *, iou_threshold: float) -> dict[str, Any]:
    tp = sum(int(row["tp"]) for row in per_image)
    fp = sum(int(row["fp"]) for row in per_image)
    fn = sum(int(row["fn"]) for row in per_image)
    matched_ious = [float(match["iou"]) for row in per_image for match in row["matches"]]
    mask_ious = [
        float(match["mask_iou"])
        for row in per_image
        for match in row["matches"]
        if match.get("mask_iou") is not None
    ]
    dice_scores = [
        float(match["dice"])
        for row in per_image
        for match in row["matches"]
        if match.get("dice") is not None
    ]

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    miou_bbox = (sum(matched_ious) / len(matched_ious)) if matched_ious else 0.0

    per_label_totals: dict[str, dict[str, Any]] = {}
    for row in per_image:
        for label in row["labels_seen"]:
            per_label_totals.setdefault(
                label,
                {"tp": 0, "fp": 0, "fn": 0, "matched_ious": [], "mask_ious": [], "dice_scores": []},
            )
        for match in row["matches"]:
            label = str(match["label"])
            bucket = per_label_totals.setdefault(
                label,
                {"tp": 0, "fp": 0, "fn": 0, "matched_ious": [], "mask_ious": [], "dice_scores": []},
            )
            bucket["tp"] += 1
            bucket["matched_ious"].append(float(match["iou"]))
            if match.get("mask_iou") is not None:
                bucket["mask_ious"].append(float(match["mask_iou"]))
            if match.get("dice") is not None:
                bucket["dice_scores"].append(float(match["dice"]))
        for label in row["unmatched_prediction_labels"]:
            bucket = per_label_totals.setdefault(
                label,
                {"tp": 0, "fp": 0, "fn": 0, "matched_ious": [], "mask_ious": [], "dice_scores": []},
            )
            bucket["fp"] += 1
        for label in row["unmatched_ground_truth_labels"]:
            bucket = per_label_totals.setdefault(
                label,
                {"tp": 0, "fp": 0, "fn": 0, "matched_ious": [], "mask_ious": [], "dice_scores": []},
            )
            bucket["fn"] += 1

    per_label: dict[str, Any] = {}
    for label, bucket in sorted(per_label_totals.items()):
        label_precision = bucket["tp"] / (bucket["tp"] + bucket["fp"]) if (bucket["tp"] + bucket["fp"]) else 0.0
        label_recall = bucket["tp"] / (bucket["tp"] + bucket["fn"]) if (bucket["tp"] + bucket["fn"]) else 0.0
        label_f1 = (
            2 * label_precision * label_recall / (label_precision + label_recall)
            if (label_precision + label_recall)
            else 0.0
        )
        label_iou = (
            sum(bucket["matched_ious"]) / len(bucket["matched_ious"]) if bucket["matched_ious"] else 0.0
        )
        per_label[label] = {
            "tp": int(bucket["tp"]),
            "fp": int(bucket["fp"]),
            "fn": int(bucket["fn"]),
            "precision": round(label_precision, 4),
            "recall": round(label_recall, 4),
            "f1": round(label_f1, 4),
            "miou_bbox": round(label_iou, 4),
            "miou_mask": _round_or_none(_safe_mean(bucket["mask_ious"])),
            "dice": _round_or_none(_safe_mean(bucket["dice_scores"])),
        }

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "miou_bbox": round(miou_bbox, 4),
        "miou_mask": _round_or_none(_safe_mean(mask_ious)),
        "dice": _round_or_none(_safe_mean(dice_scores)),
        "iou_threshold": round(iou_threshold, 4),
        "images_evaluated": len(per_image),
        "perfect_images": sum(1 for row in per_image if int(row["error_count"]) == 0),
        "images_with_failures": sum(1 for row in per_image if int(row["error_count"]) > 0),
        "predictions": sum(int(row["pred_count"]) for row in per_image),
        "ground_truth": sum(int(row["gt_count"]) for row in per_image),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "mask_pairs": len(mask_ious),
        "per_label": per_label,
    }


def evaluation_run_to_dict(run: EvaluationRun) -> dict[str, Any]:
    metrics = _load_json_dict(run.metrics)
    config = _load_json_dict(run.config)
    return {
        "id": run.id,
        "project_id": run.project_id,
        "status": run.status,
        "split": run.split,
        "model_tag": run.model_tag,
        "metrics": metrics or None,
        "report_path": run.report_path,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "created_at": run.created_at,
        "task_id": config.get("task_id"),
        "config": config or None,
    }


def list_project_evaluations(project_id: int, db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(EvaluationRun).where(EvaluationRun.project_id == project_id).order_by(EvaluationRun.id.desc())
    ).scalars().all()
    return [evaluation_run_to_dict(row) for row in rows]


def read_evaluation_report(run: EvaluationRun) -> dict[str, Any] | None:
    if not run.report_path:
        return None
    report_path = _resolve_path(run.report_path)
    if not report_path.exists():
        return None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _resolve_baseline_run(current_run: EvaluationRun, *, baseline_run_id: int | None, db: Session) -> EvaluationRun:
    if baseline_run_id is not None:
        baseline_run = db.get(EvaluationRun, baseline_run_id)
        if baseline_run is None:
            raise AppError(404, "baseline evaluation run not found")
        if baseline_run.project_id != current_run.project_id:
            raise AppError(400, "baseline evaluation run must belong to the same project")
        if baseline_run.status != "done":
            raise AppError(400, "baseline evaluation run is not completed")
        return baseline_run

    baseline_run = (
        db.execute(
            select(EvaluationRun)
            .where(
                EvaluationRun.project_id == current_run.project_id,
                EvaluationRun.status == "done",
                EvaluationRun.id != current_run.id,
            )
            .order_by(EvaluationRun.id.desc())
        )
        .scalars()
        .first()
    )
    if baseline_run is None:
        raise AppError(404, "baseline evaluation run not found")
    return baseline_run


def _compare_metric_block(
    current: dict[str, Any],
    baseline: dict[str, Any],
    *,
    keys: tuple[str, ...],
    digits: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in keys:
        current_value = _as_float(current.get(key))
        baseline_value = _as_float(baseline.get(key))
        if current_value is None and baseline_value is None:
            continue
        payload[key] = {
            "current": _round_or_none(current_value, digits=digits),
            "baseline": _round_or_none(baseline_value, digits=digits),
            "delta": (
                _round_or_none(current_value - baseline_value, digits=digits)
                if current_value is not None and baseline_value is not None
                else None
            ),
        }
    return payload


def _compare_per_label(
    current_metrics: dict[str, Any],
    baseline_metrics: dict[str, Any],
) -> dict[str, Any]:
    current_labels = current_metrics.get("per_label", {})
    baseline_labels = baseline_metrics.get("per_label", {})
    if not isinstance(current_labels, dict):
        current_labels = {}
    if not isinstance(baseline_labels, dict):
        baseline_labels = {}

    labels = sorted(set(current_labels) | set(baseline_labels))
    payload: dict[str, Any] = {}
    for label in labels:
        current_row = current_labels.get(label, {})
        baseline_row = baseline_labels.get(label, {})
        if not isinstance(current_row, dict):
            current_row = {}
        if not isinstance(baseline_row, dict):
            baseline_row = {}
        payload[label] = _compare_metric_block(
            current_row,
            baseline_row,
            keys=("tp", "fp", "fn", "precision", "recall", "f1", "miou_bbox", "miou_mask", "dice"),
            digits=4,
        )
    return payload


def _extract_image_compare_summary(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {
            "f1": None,
            "fp": 0,
            "fn": 0,
            "error_count": 0,
            "miou_bbox": None,
            "miou_mask": None,
            "dice": None,
        }
    return {
        "f1": _as_float(row.get("f1")),
        "fp": int(row.get("fp", 0) or 0),
        "fn": int(row.get("fn", 0) or 0),
        "error_count": int(row.get("error_count", 0) or 0),
        "miou_bbox": _as_float(row.get("miou_bbox")),
        "miou_mask": _as_float(row.get("miou_mask")),
        "dice": _as_float(row.get("dice")),
    }


def _compare_image_rows(
    current_report: dict[str, Any],
    baseline_report: dict[str, Any],
    *,
    limit: int = 5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current_rows = current_report.get("images", [])
    baseline_rows = baseline_report.get("images", [])
    if not isinstance(current_rows, list):
        current_rows = []
    if not isinstance(baseline_rows, list):
        baseline_rows = []

    current_index = {
        int(row["image_id"]): row for row in current_rows if isinstance(row, dict) and row.get("image_id") is not None
    }
    baseline_index = {
        int(row["image_id"]): row for row in baseline_rows if isinstance(row, dict) and row.get("image_id") is not None
    }

    changes: list[dict[str, Any]] = []
    for image_id in sorted(set(current_index) | set(baseline_index)):
        current_row = current_index.get(image_id)
        baseline_row = baseline_index.get(image_id)
        current_summary = _extract_image_compare_summary(current_row)
        baseline_summary = _extract_image_compare_summary(baseline_row)
        f1_delta = (
            _round_or_none(float(current_summary["f1"]) - float(baseline_summary["f1"]))
            if current_summary["f1"] is not None and baseline_summary["f1"] is not None
            else None
        )
        error_delta = int(current_summary["error_count"]) - int(baseline_summary["error_count"])
        miou_bbox_delta = (
            _round_or_none(float(current_summary["miou_bbox"]) - float(baseline_summary["miou_bbox"]))
            if current_summary["miou_bbox"] is not None and baseline_summary["miou_bbox"] is not None
            else None
        )
        if error_delta == 0 and (f1_delta is None or f1_delta == 0.0) and (miou_bbox_delta is None or miou_bbox_delta == 0.0):
            continue
        source = current_row or baseline_row or {}
        changes.append(
            {
                "image_id": image_id,
                "filename": source.get("filename"),
                "split": source.get("split"),
                "current": current_summary,
                "baseline": baseline_summary,
                "delta": {
                    "error_count": error_delta,
                    "f1": f1_delta,
                    "miou_bbox": miou_bbox_delta,
                },
            }
        )

    regressions = sorted(
        changes,
        key=lambda row: (
            -int(row["delta"]["error_count"]),
            float(row["delta"]["f1"]) if row["delta"]["f1"] is not None else 0.0,
            row["image_id"],
        ),
    )
    improvements = sorted(
        changes,
        key=lambda row: (
            int(row["delta"]["error_count"]),
            -(float(row["delta"]["f1"]) if row["delta"]["f1"] is not None else 0.0),
            row["image_id"],
        ),
    )
    return regressions[:limit], improvements[:limit]


def compare_evaluation_runs(run_id: int, *, baseline_run_id: int | None, db: Session) -> dict[str, Any]:
    current_run = db.get(EvaluationRun, run_id)
    if current_run is None:
        raise AppError(404, "evaluation run not found")
    if current_run.status != "done":
        raise AppError(400, "evaluation run is not completed")

    baseline_run = _resolve_baseline_run(current_run, baseline_run_id=baseline_run_id, db=db)
    current_report = read_evaluation_report(current_run)
    baseline_report = read_evaluation_report(baseline_run)
    if current_report is None:
        raise AppError(404, "evaluation report not found")
    if baseline_report is None:
        raise AppError(404, "baseline evaluation report not found")

    current_metrics = current_report.get("metrics", {})
    baseline_metrics = baseline_report.get("metrics", {})
    if not isinstance(current_metrics, dict):
        current_metrics = {}
    if not isinstance(baseline_metrics, dict):
        baseline_metrics = {}

    current_performance = current_report.get("performance", {})
    baseline_performance = baseline_report.get("performance", {})
    if not isinstance(current_performance, dict):
        current_performance = {}
    if not isinstance(baseline_performance, dict):
        baseline_performance = {}

    regressions, improvements = _compare_image_rows(current_report, baseline_report)
    return {
        "current_run": evaluation_run_to_dict(current_run),
        "baseline_run": evaluation_run_to_dict(baseline_run),
        "delta": {
            "metrics": _compare_metric_block(
                current_metrics,
                baseline_metrics,
                keys=("precision", "recall", "f1", "miou_bbox", "miou_mask", "dice", "tp", "fp", "fn"),
                digits=4,
            ),
            "performance": _compare_metric_block(
                current_performance,
                baseline_performance,
                keys=("avg_total_ms", "p95_total_ms", "avg_llm_ms", "avg_sam_ms", "avg_postprocess_ms"),
                digits=2,
            ),
        },
        "per_label": _compare_per_label(current_metrics, baseline_metrics),
        "current_failure_samples": current_report.get("summary", {}).get("failure_samples", []),
        "baseline_failure_samples": baseline_report.get("summary", {}).get("failure_samples", []),
        "top_regressions": regressions,
        "top_improvements": improvements,
    }


def _resolve_image_ids(
    project_id: int,
    *,
    split: str | None,
    image_ids: list[int] | None,
    db: Session,
) -> list[int]:
    query = (
        select(distinct(Image.id))
        .join(Annotation, Annotation.image_id == Image.id)
        .where(
            Image.project_id == project_id,
            Annotation.is_confirmed.is_(True),
            Annotation.bbox.is_not(None),
        )
        .order_by(Image.id.asc())
    )

    if image_ids:
        query = query.where(Image.id.in_(image_ids))
    elif split:
        query = query.where(Image.split == split)

    resolved = [int(row[0]) for row in db.execute(query).all()]
    if image_ids:
        requested = {int(image_id) for image_id in image_ids}
        if requested != set(resolved):
            raise AppError(400, "some image_ids do not have confirmed bbox annotations in the project")
    return resolved


def create_evaluation_run(
    project_id: int,
    *,
    split: str | None,
    image_ids: list[int] | None,
    model_tag: str | None,
    iou_threshold: float | None,
    max_samples: int | None,
    db: Session,
) -> tuple[EvaluationRun, str]:
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project not found")
    if split and image_ids:
        raise AppError(400, "split and image_ids cannot be used together")
    if split and split not in ("train", "val", "test"):
        raise AppError(400, "split must be one of train, val or test")

    project_settings = load_project_settings(project)
    evaluation_settings = (
        project_settings.get("evaluation", {}) if isinstance(project_settings.get("evaluation"), dict) else {}
    )
    resolved_split = split or str(evaluation_settings.get("split") or "val")
    resolved_iou_threshold = float(iou_threshold if iou_threshold is not None else evaluation_settings.get("iou_threshold") or 0.5)
    if resolved_iou_threshold <= 0.0 or resolved_iou_threshold > 1.0:
        raise AppError(400, "iou_threshold must be within 0..1")

    resolved_max_samples = max_samples if max_samples is not None else evaluation_settings.get("max_samples")
    if resolved_max_samples is not None:
        try:
            resolved_max_samples = max(1, int(resolved_max_samples))
        except Exception as exc:  # noqa: BLE001
            raise AppError(400, f"invalid max_samples: {exc}") from exc

    selected_image_ids = _resolve_image_ids(project_id, split=resolved_split, image_ids=image_ids, db=db)
    if resolved_max_samples is not None:
        selected_image_ids = selected_image_ids[:resolved_max_samples]
    if not selected_image_ids:
        raise AppError(400, "no confirmed evaluation annotations available for the requested split")

    resolved_route = resolve_inference_route(
        project,
        requested_model_tag=model_tag,
        db=db,
        project_settings=project_settings,
    )
    config = {
        "image_ids": selected_image_ids,
        "iou_threshold": resolved_iou_threshold,
        "max_samples": resolved_max_samples,
        "project_settings": project_settings,
        "inference": resolved_route.to_dict(),
    }
    run = EvaluationRun(
        project_id=project_id,
        status="pending",
        split="custom" if image_ids else resolved_split,
        model_tag=resolved_route.effective_model_tag,
        config=json.dumps(config, ensure_ascii=False),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    task_id = get_task_manager().create(
        kind="evaluation_run",
        payload={"run_id": run.id},
        queue="evaluation",
    )
    config["task_id"] = task_id
    run.config = json.dumps(config, ensure_ascii=False)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run, task_id


def run_evaluation_task(run_id: int, *, ctx: TaskContext | None = None) -> None:
    session_factory = get_session_factory()
    try:
        with session_factory() as db:
            run = db.get(EvaluationRun, run_id)
            if run is None:
                return
            project = db.get(Project, run.project_id)
            if project is None:
                raise RuntimeError("project not found")

            config = _load_json_dict(run.config)
            image_ids = [int(image_id) for image_id in config.get("image_ids", []) if int(image_id) > 0]
            iou_threshold = float(config.get("iou_threshold") or 0.5)
            project_settings = (
                config.get("project_settings", {})
                if isinstance(config.get("project_settings"), dict)
                else load_project_settings(project)
            )
            config_inference = config.get("inference", {}) if isinstance(config.get("inference"), dict) else {}
            requested_model_tag = str(
                config_inference.get("effective_model_tag")
                or config_inference.get("requested_model_tag")
                or run.model_tag
                or "base"
            )

            run.status = "running"
            run.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(run)
            db.commit()
            if ctx is not None:
                ctx.set_progress(5, f"evaluation run #{run.id} started")

            images = db.execute(
                select(Image).where(Image.project_id == project.id, Image.id.in_(image_ids)).order_by(Image.id.asc())
            ).scalars().all()
            if not images:
                raise RuntimeError("evaluation images not found")

            per_image: list[dict[str, Any]] = []
            total_images = len(images)
            for index, image in enumerate(images, start=1):
                if ctx is not None:
                    ctx.set_progress(
                        min(90, int(10 + ((index - 1) / max(1, total_images)) * 75)),
                        f"evaluating image {index}/{total_images}",
                    )
                gt_annotations = db.execute(
                    select(Annotation)
                    .where(
                        Annotation.image_id == image.id,
                        Annotation.is_confirmed.is_(True),
                        Annotation.bbox.is_not(None),
                    )
                    .order_by(Annotation.id.asc())
                ).scalars().all()
                if not gt_annotations:
                    continue

                result = generate_auto_annotations(
                    project,
                    image,
                    db=db,
                    requested_model_tag=requested_model_tag,
                    project_settings=project_settings,
                )
                predictions = result.annotations
                matches, tp, fp, fn = _match_annotations(predictions, gt_annotations, iou_threshold=iou_threshold)
                per_image.append(
                    _build_image_row(
                        image=image,
                        predictions=predictions,
                        ground_truth=gt_annotations,
                        matches=matches,
                        tp=tp,
                        fp=fp,
                        fn=fn,
                        inference=result.metadata(),
                    )
                )

            if not per_image:
                raise RuntimeError("no evaluation images contained confirmed bbox annotations")

            metrics = _compute_metrics(per_image, iou_threshold=iou_threshold)
            performance = _compute_performance_summary(per_image)
            summary = {
                "perfect_images": metrics["perfect_images"],
                "images_with_failures": metrics["images_with_failures"],
                "failure_samples": _build_failure_samples(per_image),
            }
            report_payload = {
                "run_id": run.id,
                "project_id": project.id,
                "split": run.split,
                "model_tag": run.model_tag,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "inference": config_inference or per_image[0].get("inference"),
                "metrics": metrics,
                "performance": performance,
                "summary": summary,
                "images": per_image,
            }
            report_path = (_report_root(project.id) / f"evaluation_run_{run.id}.json").resolve()
            report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            run.metrics = json.dumps(metrics, ensure_ascii=False)
            run.report_path = _store_path(report_path)
            run.status = "done"
            run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(run)
            db.commit()
            if ctx is not None:
                ctx.set_progress(100, f"evaluation run #{run.id} completed")
    except Exception as exc:  # noqa: BLE001
        with session_factory() as db:
            run = db.get(EvaluationRun, run_id)
            if run is not None:
                run.status = "failed"
                run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                run.metrics = json.dumps({"error": str(exc)}, ensure_ascii=False)
                db.add(run)
                db.commit()
        if ctx is not None:
            ctx.set_progress(100, f"evaluation run failed: {exc}")
