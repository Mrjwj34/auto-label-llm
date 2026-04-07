from __future__ import annotations

from sqlalchemy import select

from backend.database import get_session_factory
from backend.models.image import Image
from backend.models.project import Project
from backend.services.auto_annotator import generate_auto_annotations, replace_auto_annotations
from backend.tasks.task_manager import TaskContext


def run_project_annotation_task(ctx: TaskContext, payload: dict) -> None:
    image_ids = [int(image_id) for image_id in payload.get("image_ids", []) if int(image_id) > 0]
    total = len(image_ids)
    if total == 0:
        ctx.set_progress(100, "no images to annotate")
        return

    session_factory = get_session_factory()
    success_count = 0
    failed_count = 0

    for idx, image_id in enumerate(image_ids, start=1):
        ctx.set_progress(int((idx - 1) / total * 100), f"image {idx}/{total}")

        try:
            with session_factory() as task_db:
                img = task_db.get(Image, image_id)
                if img is None:
                    continue
                task_project = task_db.get(Project, img.project_id)
                if task_project is None:
                    raise RuntimeError("project not found")

                img.status = "annotating"
                task_db.add(img)
                task_db.commit()

                result = generate_auto_annotations(task_project, img, db=task_db)
                replace_auto_annotations(task_db, img, result)
                img.status = "done"
                task_db.add(img)
                task_db.commit()

                success_count += 1
                provider_text = f" via {result.runtime_label()}"
        except Exception as exc:  # noqa: BLE001
            failed_count += 1
            with session_factory() as task_db:
                img = task_db.get(Image, image_id)
                if img is not None:
                    img.status = "error"
                    task_db.add(img)
                    task_db.commit()
            ctx.set_progress(int(idx / total * 100), f"image {idx}/{total} failed: {exc}")
            continue

        ctx.set_progress(
            int(idx / total * 100),
            f"image {idx}/{total} done ({len(result.annotations)} boxes{provider_text})",
        )

    summary = f"completed {success_count}/{total} images"
    if failed_count:
        summary += f", failed {failed_count}"
    ctx.set_progress(100, summary)
    if failed_count == total and total > 0:
        raise RuntimeError(summary)


def run_image_annotation_task(ctx: TaskContext, payload: dict) -> None:
    image_id = int(payload.get("image_id") or 0)
    if image_id <= 0:
        raise RuntimeError("image_id is required")

    session_factory = get_session_factory()

    ctx.set_progress(5, "queued")
    with session_factory() as task_db:
        img = task_db.get(Image, image_id)
        if img is None:
            raise RuntimeError("image not found")
        task_project = task_db.get(Project, img.project_id)
        if task_project is None:
            raise RuntimeError("project not found")
        img.status = "annotating"
        task_db.add(img)
        task_db.commit()

    with session_factory() as task_db:
        img = task_db.get(Image, image_id)
        if img is None:
            raise RuntimeError("image not found")
        task_project = task_db.get(Project, img.project_id)
        if task_project is None:
            raise RuntimeError("project not found")

        ctx.set_progress(40, "generating bbox")
        result = generate_auto_annotations(task_project, img, db=task_db)
        replace_auto_annotations(task_db, img, result)
        img.status = "done"
        task_db.add(img)
        task_db.commit()
        ctx.set_progress(95, f"generated {len(result.annotations)} boxes via {result.runtime_label()}")


def resolve_project_image_ids(*, project_id: int, image_ids: list[int] | None, only_pending: bool) -> list[int]:
    session_factory = get_session_factory()
    with session_factory() as db:
        if image_ids:
            rows = db.execute(select(Image.id).where(Image.project_id == project_id, Image.id.in_(image_ids))).all()
            resolved = [int(row[0]) for row in rows]
            if len(resolved) != len(set(image_ids)):
                raise RuntimeError("some image_ids do not belong to the project")
            return resolved

        query = select(Image.id).where(Image.project_id == project_id)
        if only_pending:
            query = query.where(Image.status == "pending")
        return [int(row[0]) for row in db.execute(query).all()]
