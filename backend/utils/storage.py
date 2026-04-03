from __future__ import annotations

import re
import shutil
from pathlib import Path
from uuid import uuid4

from PIL import Image as PILImage

from backend.config import get_settings


def project_dir(project_id: int) -> Path:
    settings = get_settings()
    return settings.resolved_data_dir / "projects" / str(project_id)


def ensure_project_dirs(project_id: int) -> None:
    base = project_dir(project_id)
    (base / "images").mkdir(parents=True, exist_ok=True)
    (base / "masks").mkdir(parents=True, exist_ok=True)
    (base / "exports").mkdir(parents=True, exist_ok=True)


def delete_project_dirs(project_id: int) -> None:
    shutil.rmtree(project_dir(project_id), ignore_errors=True)


def safe_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    if not name:
        return "file"
    name = name.replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return name or "file"


def save_project_image_bytes(project_id: int, image_id: int, original_filename: str, content: bytes) -> str:
    ensure_project_dirs(project_id)
    dst = project_dir(project_id) / "images" / f"{image_id}_{safe_filename(original_filename)}"
    dst.write_bytes(content)

    return _stored_path_for(dst)


def save_project_mask_image(
    project_id: int,
    image_id: int,
    mask_image: PILImage.Image,
    *,
    stem: str = "sam",
) -> str:
    ensure_project_dirs(project_id)
    dst = project_dir(project_id) / "masks" / f"{image_id}_{safe_filename(stem)}_{uuid4().hex[:12]}.png"
    mask_image.save(dst, format="PNG")
    return _stored_path_for(dst)


def _stored_path_for(path: Path) -> str:
    settings = get_settings()
    try:
        rel = path.relative_to(settings.root_dir)
        return rel.as_posix()
    except ValueError:
        return path.as_posix()


def resolve_path(stored_path: str) -> Path:
    settings = get_settings()
    p = Path(stored_path)
    if p.is_absolute():
        return p
    return (settings.root_dir / p).resolve()
