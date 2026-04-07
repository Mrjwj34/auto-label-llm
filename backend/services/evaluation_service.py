from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _compute_metrics(per_image: list[dict[str, Any]], *, iou_threshold: float) -> dict[str, Any]:
    tp = sum(int(row["tp"]) for row in per_image)
    fp = sum(int(row["fp"]) for row in per_image)
    fn = sum(int(row["fn"]) for row in per_image)
    matched_ious = [float(match["iou"]) for row in per_image for match in row["matches"]]

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    miou_bbox = (sum(matched_ious) / len(matched_ious)) if matched_ious else 0.0

    per_label_totals: dict[str, dict[str, Any]] = {}
    for row in per_image:
        for label in row["labels_seen"]:
            per_label_totals.setdefault(label, {"tp": 0, "fp": 0, "fn": 0, "matched_ious": []})
        for match in row["matches"]:
            label = str(match["label"])
            bucket = per_label_totals.setdefault(label, {"tp": 0, "fp": 0, "fn": 0, "matched_ious": []})
            bucket["tp"] += 1
            bucket["matched_ious"].append(float(match["iou"]))
        for label in row["unmatched_prediction_labels"]:
            bucket = per_label_totals.setdefault(label, {"tp": 0, "fp": 0, "fn": 0, "matched_ious": []})
            bucket["fp"] += 1
        for label in row["unmatched_ground_truth_labels"]:
            bucket = per_label_totals.setdefault(label, {"tp": 0, "fp": 0, "fn": 0, "matched_ious": []})
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
        }

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "miou_bbox": round(miou_bbox, 4),
        "iou_threshold": round(iou_threshold, 4),
        "images_evaluated": len(per_image),
        "predictions": sum(int(row["pred_count"]) for row in per_image),
        "ground_truth": sum(int(row["gt_count"]) for row in per_image),
        "tp": tp,
        "fp": fp,
        "fn": fn,
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
                matched_prediction_indices = {int(match["prediction_index"]) for match in matches}
                matched_ground_truth_indices = {int(match["ground_truth_index"]) for match in matches}

                per_image.append(
                    {
                        "image_id": image.id,
                        "filename": image.filename,
                        "split": image.split,
                        "pred_count": len(predictions),
                        "gt_count": len(gt_annotations),
                        "tp": tp,
                        "fp": fp,
                        "fn": fn,
                        "matches": matches,
                        "labels_seen": sorted(
                            {prediction.label for prediction in predictions} | {annotation.label for annotation in gt_annotations}
                        ),
                        "unmatched_prediction_labels": [
                            prediction.label
                            for idx, prediction in enumerate(predictions)
                            if idx not in matched_prediction_indices
                        ],
                        "unmatched_ground_truth_labels": [
                            annotation.label
                            for idx, annotation in enumerate(gt_annotations)
                            if idx not in matched_ground_truth_indices
                        ],
                        "inference": result.metadata(),
                    }
                )

            if not per_image:
                raise RuntimeError("no evaluation images contained confirmed bbox annotations")

            metrics = _compute_metrics(per_image, iou_threshold=iou_threshold)
            report_payload = {
                "run_id": run.id,
                "project_id": project.id,
                "split": run.split,
                "model_tag": run.model_tag,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "inference": config_inference or per_image[0].get("inference"),
                "metrics": metrics,
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
