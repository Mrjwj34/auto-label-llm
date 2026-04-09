from __future__ import annotations

import argparse
import io
import json
import mimetypes
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run end-to-end design_doc verification against a real backend/vLLM stack."
    )
    parser.add_argument("--backend-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--image-path", default="/tmp/verify-real-model.jpg")
    parser.add_argument("--yolo-import-zip", default="data/external/coco8.zip")
    parser.add_argument("--context-path", default="/tmp/design_doc_context.json")
    parser.add_argument("--request-timeout", type=float, default=600.0)
    parser.add_argument("--task-timeout", type=float, default=900.0)
    parser.add_argument("--project-id", type=int, default=0)
    parser.add_argument("--finetune-job-id", type=int, default=0)
    parser.add_argument(
        "--phase",
        choices=("phase1", "phase2"),
        default="phase1",
        help="Verification phase to run.",
    )
    return parser.parse_args()


def unwrap_ok(response: httpx.Response) -> Any:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 200:
        raise RuntimeError(f"unexpected response payload: {payload!r}")
    return payload.get("data")


def poll_task(client: httpx.Client, base_url: str, task_id: str, *, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        payload = unwrap_ok(client.get(f"{base_url}/api/tasks/{task_id}/status"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"unexpected task payload: {payload!r}")
        status = str(payload.get("status") or "")
        if status == "SUCCESS":
            return payload
        if status == "FAILURE":
            raise RuntimeError(f"task failed: {payload!r}")
        time.sleep(2.0)
    raise RuntimeError(f"task timeout: {task_id}")


def create_project(client: httpx.Client, base_url: str, *, name: str, task_type: str) -> int:
    payload = unwrap_ok(client.post(f"{base_url}/api/projects", json={"name": name, "task_type": task_type}))
    return int(payload["id"])


def patch_project_labels(client: httpx.Client, base_url: str, project_id: int, labels: list[str]) -> None:
    unwrap_ok(client.patch(f"{base_url}/api/projects/{project_id}/settings", json={"labels": labels}))


def upload_image(client: httpx.Client, base_url: str, project_id: int, image_path: Path, filename: str) -> int:
    media_type = mimetypes.guess_type(filename)[0] or "image/jpeg"
    files = [("files[]", (filename, image_path.read_bytes(), media_type))]
    payload = unwrap_ok(client.post(f"{base_url}/api/projects/{project_id}/images/upload", files=files))
    image_ids = payload.get("image_ids") if isinstance(payload, dict) else None
    if not isinstance(image_ids, list) or not image_ids:
        raise RuntimeError(f"upload did not return image_ids: {payload!r}")
    return int(image_ids[0])


def patch_image_split(client: httpx.Client, base_url: str, image_id: int, split: str) -> None:
    unwrap_ok(client.patch(f"{base_url}/api/images/{image_id}", json={"split": split}))


def list_annotations(client: httpx.Client, base_url: str, image_id: int) -> list[dict[str, Any]]:
    payload = unwrap_ok(client.get(f"{base_url}/api/images/{image_id}/annotations"))
    return [row for row in payload if isinstance(row, dict)]


def confirm_annotation(client: httpx.Client, base_url: str, annotation_id: int) -> None:
    unwrap_ok(client.patch(f"{base_url}/api/annotations/{annotation_id}/confirm"))


def confirm_all_annotations(client: httpx.Client, base_url: str, image_id: int) -> list[dict[str, Any]]:
    rows = list_annotations(client, base_url, image_id)
    for row in rows:
        confirm_annotation(client, base_url, int(row["id"]))
    return list_annotations(client, base_url, image_id)


def trigger_single_image_annotation(client: httpx.Client, base_url: str, image_id: int, *, timeout_seconds: float) -> dict[str, Any]:
    payload = unwrap_ok(client.post(f"{base_url}/api/images/{image_id}/annotate"))
    task_id = str(payload["task_id"])
    return poll_task(client, base_url, task_id, timeout_seconds=timeout_seconds)


def export_zip_entries(client: httpx.Client, base_url: str, project_id: int, format_name: str) -> list[str]:
    response = client.get(f"{base_url}/api/projects/{project_id}/export", params={"format": format_name})
    response.raise_for_status()
    return sorted(zipfile.ZipFile(io.BytesIO(response.content)).namelist())


def run_evaluation(
    client: httpx.Client,
    base_url: str,
    project_id: int,
    *,
    split: str,
    model_tag: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    payload = unwrap_ok(
        client.post(
            f"{base_url}/api/projects/{project_id}/evaluate",
            json={"split": split, "model_tag": model_tag},
        )
    )
    run_id = int(payload["run_id"])
    task_payload = poll_task(client, base_url, str(payload["task_id"]), timeout_seconds=timeout_seconds)
    run_payload = unwrap_ok(client.get(f"{base_url}/api/evaluations/{run_id}"))
    report_payload = unwrap_ok(client.get(f"{base_url}/api/evaluations/{run_id}/report"))
    return {
        "run_id": run_id,
        "task": task_payload,
        "run": run_payload,
        "report": report_payload,
    }


def get_project_settings(client: httpx.Client, base_url: str, project_id: int) -> dict[str, Any]:
    payload = unwrap_ok(client.get(f"{base_url}/api/projects/{project_id}/settings"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected project settings payload: {payload!r}")
    return payload


def get_finetune_status(client: httpx.Client, base_url: str, job_id: int) -> dict[str, Any]:
    payload = unwrap_ok(client.get(f"{base_url}/api/finetune/{job_id}/status"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected finetune payload: {payload!r}")
    return payload


def poll_finetune_job(
    client: httpx.Client,
    base_url: str,
    job_id: int,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        payload = get_finetune_status(client, base_url, job_id)
        status = str(payload.get("status") or "")
        if status == "done":
            return payload
        if status == "failed":
            raise RuntimeError(f"finetune job failed: {payload!r}")
        time.sleep(5.0)
    raise RuntimeError(f"finetune job timeout: {job_id}")


def start_finetune(client: httpx.Client, base_url: str, project_id: int) -> dict[str, Any]:
    payload = unwrap_ok(client.post(f"{base_url}/api/finetune/start", json={"project_id": project_id}))
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected finetune start payload: {payload!r}")
    return payload


def activate_finetune_job(client: httpx.Client, base_url: str, job_id: int) -> dict[str, Any]:
    payload = unwrap_ok(client.post(f"{base_url}/api/finetune/{job_id}/activate"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected finetune activation payload: {payload!r}")
    return payload


def compare_evaluation(
    client: httpx.Client,
    base_url: str,
    run_id: int,
    *,
    baseline_run_id: int,
) -> dict[str, Any]:
    payload = unwrap_ok(client.get(f"{base_url}/api/evaluations/{run_id}/compare", params={"baseline_run_id": baseline_run_id}))
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected evaluation compare payload: {payload!r}")
    return payload


def import_yolo_zip(
    client: httpx.Client,
    base_url: str,
    project_id: int,
    *,
    archive_path: Path,
) -> dict[str, Any]:
    files = {
        "format": (None, "yolo"),
        "file": (archive_path.name, archive_path.read_bytes(), "application/zip"),
    }
    payload = unwrap_ok(client.post(f"{base_url}/api/projects/{project_id}/import", files=files))
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected import payload: {payload!r}")
    return payload


def run_phase1(
    client: httpx.Client,
    *,
    base_url: str,
    image_path: Path,
    yolo_import_zip: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    health = unwrap_ok(client.get(f"{base_url}/api/health"))
    summary: dict[str, Any] = {"health": health}

    detection_project = create_project(
        client,
        base_url,
        name=f"design-doc-detect-{int(time.time())}",
        task_type="detection",
    )
    patch_project_labels(client, base_url, detection_project, ["cat", "couch"])
    detect_train_image = upload_image(client, base_url, detection_project, image_path, "cats-train.jpg")
    detect_val_image = upload_image(client, base_url, detection_project, image_path, "cats-val.jpg")
    patch_image_split(client, base_url, detect_val_image, "val")

    detection_train_task = trigger_single_image_annotation(
        client,
        base_url,
        detect_train_image,
        timeout_seconds=timeout_seconds,
    )
    train_annotations = list_annotations(client, base_url, detect_train_image)
    if len(train_annotations) < 2:
        raise RuntimeError(f"expected >=2 train annotations, got: {train_annotations!r}")

    corrected = unwrap_ok(
        client.post(
            f"{base_url}/api/images/{detect_train_image}/predict",
            json={
                "annotation_id": int(train_annotations[0]["id"]),
                "bbox": [0.02, 0.09, 0.53, 0.99],
                "label": "cat",
            },
        )
    )
    manual_extra = unwrap_ok(
        client.post(
            f"{base_url}/api/images/{detect_train_image}/annotations",
            json={"label": "couch", "bbox": [0.0, 0.0, 1.0, 1.0], "source": "manual"},
        )
    )
    delete_id = int(train_annotations[-1]["id"])
    unwrap_ok(client.delete(f"{base_url}/api/annotations/{delete_id}"))
    confirmed_train = confirm_all_annotations(client, base_url, detect_train_image)
    if not confirmed_train or not all(bool(row.get("is_confirmed")) for row in confirmed_train):
        raise RuntimeError(f"train annotation confirmation failed: {confirmed_train!r}")

    detection_val_task = trigger_single_image_annotation(
        client,
        base_url,
        detect_val_image,
        timeout_seconds=timeout_seconds,
    )
    confirmed_val = confirm_all_annotations(client, base_url, detect_val_image)
    if not confirmed_val or not all(bool(row.get("is_confirmed")) for row in confirmed_val):
        raise RuntimeError(f"val annotation confirmation failed: {confirmed_val!r}")

    yolo_export_entries = export_zip_entries(client, base_url, detection_project, "yolo")
    coco_export_entries = export_zip_entries(client, base_url, detection_project, "coco")

    evaluation = run_evaluation(
        client,
        base_url,
        detection_project,
        split="val",
        model_tag="base",
        timeout_seconds=timeout_seconds,
    )

    imported_project = create_project(
        client,
        base_url,
        name=f"design-doc-import-{int(time.time())}",
        task_type="detection",
    )
    imported = import_yolo_zip(client, base_url, imported_project, archive_path=yolo_import_zip)

    segmentation_project = create_project(
        client,
        base_url,
        name=f"design-doc-seg-{int(time.time())}",
        task_type="segmentation",
    )
    patch_project_labels(client, base_url, segmentation_project, ["cat"])
    seg_image = upload_image(client, base_url, segmentation_project, image_path, "cats-seg.jpg")

    unwrap_ok(
        client.patch(
            f"{base_url}/api/system/settings",
            json={
                "postprocess": {
                    "enable_close": True,
                    "close_kernel": 5,
                    "enable_dp_simplify": True,
                    "epsilon_ratio": 0.02,
                    "min_area_ratio": 0.0004,
                }
            },
        )
    )
    seg_create = unwrap_ok(
        client.post(
            f"{base_url}/api/images/{seg_image}/predict",
            json={"annotation_id": None, "label": "cat", "bbox": [0.03, 0.08, 0.54, 0.99]},
        )
    )
    seg_annotation_id = int(seg_create["annotation_id"])
    seg_first = next(row for row in list_annotations(client, base_url, seg_image) if int(row["id"]) == seg_annotation_id)
    first_polygon_len = len(seg_first.get("polygon") or [])
    confirm_annotation(client, base_url, seg_annotation_id)

    refined = unwrap_ok(
        client.post(
            f"{base_url}/api/images/{seg_image}/predict",
            json={
                "annotation_id": seg_annotation_id,
                "points": [
                    {"x": 0.24, "y": 0.55, "label": 1},
                    {"x": 0.72, "y": 0.35, "label": 0},
                ],
            },
        )
    )
    seg_after_refine = next(row for row in list_annotations(client, base_url, seg_image) if int(row["id"]) == seg_annotation_id)
    if bool(seg_after_refine.get("is_confirmed")):
        raise RuntimeError("segmentation point refinement should reset confirmation")
    confirm_annotation(client, base_url, seg_annotation_id)

    unwrap_ok(
        client.patch(
            f"{base_url}/api/system/settings",
            json={
                "postprocess": {
                    "enable_close": False,
                    "close_kernel": 3,
                    "enable_dp_simplify": False,
                    "epsilon_ratio": 0.0005,
                    "min_area_ratio": 0.0001,
                }
            },
        )
    )
    seg_create_2 = unwrap_ok(
        client.post(
            f"{base_url}/api/images/{seg_image}/predict",
            json={"annotation_id": None, "label": "cat", "bbox": [0.03, 0.08, 0.54, 0.99]},
        )
    )
    seg_annotation_2 = int(seg_create_2["annotation_id"])
    seg_second = next(row for row in list_annotations(client, base_url, seg_image) if int(row["id"]) == seg_annotation_2)
    second_polygon_len = len(seg_second.get("polygon") or [])

    summary.update(
        {
            "detection": {
                "project_id": detection_project,
                "train_image_id": detect_train_image,
                "val_image_id": detect_val_image,
                "train_task": detection_train_task,
                "val_task": detection_val_task,
                "corrected_annotation_id": int(corrected["annotation_id"]),
                "manual_annotation_id": int(manual_extra["id"]),
                "deleted_annotation_id": delete_id,
                "confirmed_train_count": len(confirmed_train),
                "confirmed_val_count": len(confirmed_val),
                "train_annotations": confirmed_train,
                "val_annotations": confirmed_val,
                "yolo_export_entries": yolo_export_entries[:20],
                "coco_export_entries": coco_export_entries[:20],
            },
            "evaluation": {
                "run_id": int(evaluation["run_id"]),
                "task": evaluation["task"],
                "run": evaluation["run"],
                "metrics": evaluation["report"].get("metrics"),
            },
            "import": {
                "project_id": imported_project,
                "result": imported,
            },
            "segmentation": {
                "project_id": segmentation_project,
                "image_id": seg_image,
                "annotation_id": seg_annotation_id,
                "refined_annotation_id": int(refined["annotation_id"]),
                "second_annotation_id": seg_annotation_2,
                "first_polygon_len": first_polygon_len,
                "second_polygon_len": second_polygon_len,
                "refined_annotation": seg_after_refine,
                "second_annotation": seg_second,
            },
        }
    )
    return summary


def _load_existing_context(context_path: Path) -> dict[str, Any]:
    if not context_path.exists():
        return {}
    try:
        payload = json.loads(context_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def run_phase2(
    client: httpx.Client,
    *,
    base_url: str,
    image_path: Path,
    timeout_seconds: float,
    context_path: Path,
    project_id: int,
    finetune_job_id: int,
) -> dict[str, Any]:
    existing = _load_existing_context(context_path)
    detection_summary = existing.get("detection") if isinstance(existing.get("detection"), dict) else {}
    evaluation_summary = existing.get("evaluation") if isinstance(existing.get("evaluation"), dict) else {}

    resolved_project_id = int(project_id or detection_summary.get("project_id") or 0)
    if resolved_project_id <= 0:
        raise RuntimeError("phase2 requires --project-id or a phase1 context containing detection.project_id")

    base_evaluation_run_id = int(evaluation_summary.get("run_id") or 0)
    project_settings_before = get_project_settings(client, base_url, resolved_project_id)

    finetune_started = None
    if finetune_job_id > 0:
        job_id = finetune_job_id
        finetune_status = poll_finetune_job(client, base_url, job_id, timeout_seconds=timeout_seconds)
    else:
        finetune_started = start_finetune(client, base_url, resolved_project_id)
        job_id = int(finetune_started["job_id"])
        poll_task(client, base_url, str(finetune_started["task_id"]), timeout_seconds=timeout_seconds)
        finetune_status = poll_finetune_job(client, base_url, job_id, timeout_seconds=timeout_seconds)

    model_tag = f"lora:{job_id}"
    activation = activate_finetune_job(client, base_url, job_id)
    project_settings_after = get_project_settings(client, base_url, resolved_project_id)
    if str(project_settings_after.get("active_model_tag") or "") != model_tag:
        raise RuntimeError(f"unexpected active_model_tag after activation: {project_settings_after!r}")

    lora_image_id = upload_image(client, base_url, resolved_project_id, image_path, f"cats-{job_id}-lora.jpg")
    lora_task = trigger_single_image_annotation(
        client,
        base_url,
        lora_image_id,
        timeout_seconds=timeout_seconds,
    )
    lora_annotations = list_annotations(client, base_url, lora_image_id)
    auto_annotations = [row for row in lora_annotations if str(row.get("source") or "") == "auto"]
    if not auto_annotations:
        raise RuntimeError(f"expected auto annotations after LoRA activation, got: {lora_annotations!r}")

    mismatched = []
    for row in auto_annotations:
        inference = row.get("inference") if isinstance(row.get("inference"), dict) else {}
        if (
            str(inference.get("effective_model_tag") or "") != model_tag
            or str(inference.get("provider") or "") != "openai_compatible"
            or bool(inference.get("fallback_used"))
        ):
            mismatched.append(row)
    if mismatched:
        raise RuntimeError(f"LoRA annotation route mismatch: {mismatched!r}")

    evaluation = run_evaluation(
        client,
        base_url,
        resolved_project_id,
        split="val",
        model_tag=model_tag,
        timeout_seconds=timeout_seconds,
    )

    comparison = None
    if base_evaluation_run_id > 0:
        comparison = compare_evaluation(
            client,
            base_url,
            int(evaluation["run_id"]),
            baseline_run_id=base_evaluation_run_id,
        )

    summary = dict(existing)
    summary["finetune"] = {
        "project_id": resolved_project_id,
        "job_id": job_id,
        "model_tag": model_tag,
        "started": finetune_started,
        "status": finetune_status,
        "activation": activation,
        "project_settings_before": project_settings_before,
        "project_settings_after": project_settings_after,
        "lora_image_id": lora_image_id,
        "lora_task": lora_task,
        "lora_annotations": lora_annotations,
        "evaluation": {
            "run_id": int(evaluation["run_id"]),
            "task": evaluation["task"],
            "run": evaluation["run"],
            "metrics": evaluation["report"].get("metrics"),
            "comparison": comparison,
        },
    }
    return summary


def main() -> int:
    args = parse_args()
    base_url = args.backend_base_url.rstrip("/")
    image_path = Path(args.image_path).expanduser().resolve()
    yolo_import_zip = Path(args.yolo_import_zip).expanduser().resolve()
    context_path = Path(args.context_path).expanduser().resolve()

    if not image_path.exists():
        raise FileNotFoundError(f"image file not found: {image_path}")
    if not yolo_import_zip.exists():
        raise FileNotFoundError(f"YOLO import zip not found: {yolo_import_zip}")

    timeout = httpx.Timeout(args.request_timeout, connect=min(args.request_timeout, 30.0))
    with httpx.Client(timeout=timeout) as client:
        if args.phase == "phase1":
            summary = run_phase1(
                client,
                base_url=base_url,
                image_path=image_path,
                yolo_import_zip=yolo_import_zip,
                timeout_seconds=args.task_timeout,
            )
        elif args.phase == "phase2":
            summary = run_phase2(
                client,
                base_url=base_url,
                image_path=image_path,
                timeout_seconds=args.task_timeout,
                context_path=context_path,
                project_id=args.project_id,
                finetune_job_id=args.finetune_job_id,
            )
        else:
            raise ValueError(f"unsupported phase: {args.phase}")

    context_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
