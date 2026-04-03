from __future__ import annotations

import json
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageDraw

from backend.config import get_settings
from backend.models.annotation import Annotation
from backend.models.image import Image
from backend.models.project import Project
from backend.services import postprocess as postprocess_module
from backend.services.postprocess import apply_project_postprocess, save_polygon_mask
from backend.services.sam_service import SAMService
from backend.utils.storage import resolve_path


def _write_sample_image(path: Path, *, size: tuple[int, int] = (128, 96)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = PILImage.new("RGB", size, color=(90, 140, 220))
    image.save(path, format="PNG")


def _make_image_model(path: Path) -> Image:
    return Image(
        id=1,
        project_id=1,
        filename=path.name,
        file_path=path.as_posix(),
        width=128,
        height=96,
        split="train",
        status="done",
    )


def test_sam_service_stub_reuses_current_image_cache(monkeypatch, tmp_path):
    root_dir = tmp_path / "runtime-root"
    data_dir = root_dir / "data"
    image_path = data_dir / "projects" / "1" / "images" / "1_sample.png"
    _write_sample_image(image_path)

    monkeypatch.setenv("ROOT_DIR", str(root_dir))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    SAMService._instance = None

    image = _make_image_model(image_path)
    service = SAMService()

    first = service.predict_polygon(image, [0.12, 0.18, 0.72, 0.84], checkpoint="sam3", device="cpu")
    second = service.predict_polygon(image, [0.14, 0.2, 0.7, 0.8], checkpoint="sam3", device="cpu")
    refined = service.refine_annotation(
        image,
        Annotation(image_id=image.id, label="crack", bbox=[0.14, 0.2, 0.7, 0.8], source="manual"),
        [{"x": 0.74, "y": 0.76, "label": 1}],
        checkpoint="sam3",
        device="cpu",
    )

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert refined.cache_hit is True
    assert first.mask is not None
    assert second.mask is not None
    assert refined.mask is not None
    assert first.provider.startswith("sam_stub:")


def test_mask_postprocess_persists_png_and_polygon(monkeypatch, tmp_path):
    root_dir = tmp_path / "runtime-root"
    data_dir = root_dir / "data"
    image_path = data_dir / "projects" / "1" / "images" / "1_sample.png"
    _write_sample_image(image_path)

    monkeypatch.setenv("ROOT_DIR", str(root_dir))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    SAMService._instance = None

    image = _make_image_model(image_path)
    project = Project(
        id=1,
        name="seg-project",
        task_type="segmentation",
        config=json.dumps({"postprocess": {"enable_close": True, "enable_dp_simplify": True, "epsilon_ratio": 0.05}}),
    )

    prediction = SAMService().predict_polygon(image, [0.1, 0.16, 0.74, 0.82], checkpoint="sam3", device="cpu")
    processed = apply_project_postprocess(
        project,
        image,
        mask=prediction.mask,
        bbox=prediction.bbox,
        provider=prediction.provider,
        score=prediction.score,
    )

    assert processed.bbox is not None
    assert processed.polygon is not None
    assert len(processed.polygon) >= 4
    assert processed.mask_path is not None

    mask_path = resolve_path(processed.mask_path)
    assert mask_path.exists()
    with PILImage.open(mask_path) as mask:
        mask.load()
        assert mask.format == "PNG"
        assert mask.size == (128, 96)

    imported_mask_path = save_polygon_mask(image, processed.polygon, stem="manual_import")
    assert imported_mask_path is not None
    assert resolve_path(imported_mask_path).exists()


def test_postprocess_fallback_without_opencv(monkeypatch, tmp_path):
    root_dir = tmp_path / "runtime-root"
    data_dir = root_dir / "data"
    image_path = data_dir / "projects" / "1" / "images" / "1_sample.png"
    _write_sample_image(image_path)

    monkeypatch.setenv("ROOT_DIR", str(root_dir))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()

    image = _make_image_model(image_path)
    project = Project(id=1, name="fallback", task_type="segmentation", config=json.dumps({"postprocess": {}}))

    mask = PILImage.new("L", (128, 96), color=0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((20, 16, 100, 80), fill=255)

    monkeypatch.setattr(postprocess_module, "_cv2", None)
    monkeypatch.setattr(postprocess_module, "_np", None)
    processed = apply_project_postprocess(
        project,
        image,
        mask=mask,
        bbox=[0.1, 0.1, 0.8, 0.85],
        provider="sam_stub:sam3:cpu",
        score=0.9,
    )

    assert processed.polygon is not None
    assert len(processed.polygon) >= 4
    assert processed.mask_path is not None


def test_sam_service_prefers_env_checkpoint_override(monkeypatch, tmp_path):
    root_dir = tmp_path / "runtime-root"
    checkpoint_path = root_dir / "custom" / "sam3.1_multiplex_large.pt"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_bytes(b"stub checkpoint")

    monkeypatch.setenv("ROOT_DIR", str(root_dir))
    monkeypatch.setenv("DATA_DIR", str(root_dir / "data"))
    monkeypatch.setenv("SAM3_CHECKPOINT_PATH", "custom/sam3.1_multiplex_large.pt")
    monkeypatch.delenv("SAM3_ALLOW_HF_DOWNLOAD", raising=False)
    get_settings.cache_clear()
    SAMService._instance = None

    service = SAMService()
    resolved_path, label = service._resolve_real_checkpoint("sam3")

    assert Path(resolved_path) == checkpoint_path.resolve()
    assert label == checkpoint_path.name


def test_sam_service_discovers_local_checkpoint_by_alias(monkeypatch, tmp_path):
    root_dir = tmp_path / "runtime-root"
    model_dir = root_dir / "models" / "sam3"
    model_dir.mkdir(parents=True, exist_ok=True)
    first_checkpoint = model_dir / "sam3_base.pt"
    preferred_checkpoint = model_dir / "sam3.1_multiplex_large.pt"
    first_checkpoint.write_bytes(b"first")
    preferred_checkpoint.write_bytes(b"preferred")

    monkeypatch.setenv("ROOT_DIR", str(root_dir))
    monkeypatch.setenv("DATA_DIR", str(root_dir / "data"))
    monkeypatch.delenv("SAM3_CHECKPOINT_PATH", raising=False)
    monkeypatch.delenv("SAM3_ALLOW_HF_DOWNLOAD", raising=False)
    get_settings.cache_clear()
    SAMService._instance = None

    service = SAMService()
    resolved_path, label = service._resolve_real_checkpoint("sam3.1")

    assert Path(resolved_path) == preferred_checkpoint.resolve()
    assert label == preferred_checkpoint.name


def test_sam_service_rejects_missing_env_checkpoint_override(monkeypatch, tmp_path):
    root_dir = tmp_path / "runtime-root"

    monkeypatch.setenv("ROOT_DIR", str(root_dir))
    monkeypatch.setenv("DATA_DIR", str(root_dir / "data"))
    monkeypatch.setenv("SAM3_CHECKPOINT_PATH", "models/sam3/missing.pt")
    monkeypatch.delenv("SAM3_ALLOW_HF_DOWNLOAD", raising=False)
    get_settings.cache_clear()
    SAMService._instance = None

    service = SAMService()

    try:
        service._resolve_real_checkpoint("sam3")
        assert False, "expected a RuntimeError for missing SAM3_CHECKPOINT_PATH"
    except RuntimeError as exc:
        assert "SAM3_CHECKPOINT_PATH" in str(exc)
