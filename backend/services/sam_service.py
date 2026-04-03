from __future__ import annotations

import importlib
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

from PIL import Image as PILImage
from PIL import ImageDraw

from backend.config import get_settings
from backend.models.annotation import Annotation
from backend.models.image import Image
from backend.utils.storage import resolve_path

try:
    import numpy as _np
except Exception:  # noqa: BLE001
    _np = None


@dataclass
class SAMPrediction:
    polygon: list[list[float]] | None = None
    bbox: list[float] | None = None
    mask_path: str | None = None
    provider: str = "sam_stub"
    mask: PILImage.Image | None = None
    score: float | None = None
    cache_hit: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


class SAMPoint(TypedDict):
    x: float
    y: float
    label: int


@dataclass
class _ImageCache:
    key: str
    size: tuple[int, int]
    pil_image: PILImage.Image | None = None


@dataclass
class _SAMRuntime:
    checkpoint: str
    requested_device: str
    device: str
    kind: str
    provider: str
    model: Any | None = None
    predictor: Any | None = None
    load_error: str | None = None
    image_cache: _ImageCache | None = None


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _checkpoint_curve_ratio(checkpoint: str) -> float:
    name = checkpoint.casefold()
    if "3.1" in name:
        return 0.11
    if "large" in name:
        return 0.12
    if "base" in name:
        return 0.14
    return 0.17


def _canonicalize_bbox(bbox: list[float]) -> list[float]:
    xmin, ymin, xmax, ymax = [float(v) for v in bbox]
    if xmin > xmax:
        xmin, xmax = xmax, xmin
    if ymin > ymax:
        ymin, ymax = ymax, ymin

    xmin = _clamp01(xmin)
    ymin = _clamp01(ymin)
    xmax = _clamp01(xmax)
    ymax = _clamp01(ymax)

    min_size = 0.03
    if xmax - xmin < min_size:
        center_x = (xmin + xmax) / 2
        xmin = _clamp01(center_x - min_size / 2)
        xmax = _clamp01(center_x + min_size / 2)
    if ymax - ymin < min_size:
        center_y = (ymin + ymax) / 2
        ymin = _clamp01(center_y - min_size / 2)
        ymax = _clamp01(center_y + min_size / 2)

    return [round(xmin, 6), round(ymin, 6), round(xmax, 6), round(ymax, 6)]


def _refine_bbox_with_points(bbox: list[float], points: list[SAMPoint]) -> list[float]:
    xmin, ymin, xmax, ymax = [float(v) for v in bbox]
    pos_margin = 0.03
    neg_margin = 0.02

    for point in points:
        px = _clamp01(point["x"])
        py = _clamp01(point["y"])
        label = 1 if int(point["label"]) > 0 else 0

        cx = (xmin + xmax) / 2
        cy = (ymin + ymax) / 2

        if label == 1:
            if px <= cx:
                xmin = min(xmin, max(0.0, px - pos_margin))
            else:
                xmax = max(xmax, min(1.0, px + pos_margin))
            if py <= cy:
                ymin = min(ymin, max(0.0, py - pos_margin))
            else:
                ymax = max(ymax, min(1.0, py + pos_margin))
            continue

        if px <= cx:
            xmin = max(xmin, min(px + neg_margin, xmax - 0.03))
        else:
            xmax = min(xmax, max(px - neg_margin, xmin + 0.03))
        if py <= cy:
            ymin = max(ymin, min(py + neg_margin, ymax - 0.03))
        else:
            ymax = min(ymax, max(py - neg_margin, ymin + 0.03))

    return _canonicalize_bbox([xmin, ymin, xmax, ymax])


class SAMService:
    _instance: "SAMService | None" = None

    def __new__(cls) -> "SAMService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._runtimes = {}
        return cls._instance

    def set_image(self, image: Image) -> None:
        runtime = self._get_runtime(checkpoint="sam3", device="cpu")
        self._prepare_image(runtime, image)

    def predict_polygon(
        self,
        image: Image,
        bbox: list[float],
        *,
        checkpoint: str = "sam3",
        device: str = "cuda",
        multimask_output: bool = False,
    ) -> SAMPrediction:
        normalized_bbox = _canonicalize_bbox(bbox)
        runtime = self._get_runtime(checkpoint=checkpoint, device=device)
        cache_hit = self._prepare_image(runtime, image)

        if runtime.kind == "sam3":
            try:
                prediction = self._predict_with_sam3(
                    runtime,
                    bbox=normalized_bbox,
                    points=None,
                    multimask_output=multimask_output,
                )
                prediction.cache_hit = cache_hit
                return prediction
            except Exception as exc:  # noqa: BLE001
                runtime.load_error = str(exc)

        return self._predict_with_stub(
            runtime,
            bbox=normalized_bbox,
            points=None,
            image=image,
            multimask_output=multimask_output,
            cache_hit=cache_hit,
        )

    def refine_annotation(
        self,
        image: Image,
        annotation: Annotation,
        points: list[SAMPoint],
        *,
        checkpoint: str = "sam3",
        device: str = "cuda",
        multimask_output: bool = False,
    ) -> SAMPrediction:
        if annotation.bbox is None:
            raise ValueError("annotation bbox is required for point correction")

        runtime = self._get_runtime(checkpoint=checkpoint, device=device)
        cache_hit = self._prepare_image(runtime, image)

        if runtime.kind == "sam3":
            try:
                prediction = self._predict_with_sam3(
                    runtime,
                    bbox=_canonicalize_bbox(annotation.bbox),
                    points=points,
                    multimask_output=multimask_output,
                )
                prediction.cache_hit = cache_hit
                return prediction
            except Exception as exc:  # noqa: BLE001
                runtime.load_error = str(exc)

        return self._predict_with_stub(
            runtime,
            bbox=_refine_bbox_with_points(annotation.bbox, points),
            points=points,
            image=image,
            multimask_output=multimask_output,
            cache_hit=cache_hit,
        )

    def _get_runtime(self, *, checkpoint: str, device: str) -> _SAMRuntime:
        normalized_checkpoint = str(checkpoint or "sam3").strip() or "sam3"
        resolved_device = self._resolve_device(device)
        key = (normalized_checkpoint, resolved_device)
        if key not in self._runtimes:
            self._runtimes[key] = self._build_runtime(normalized_checkpoint, device=resolved_device)
        return self._runtimes[key]

    def _build_runtime(self, checkpoint: str, *, device: str) -> _SAMRuntime:
        try:
            checkpoint_path, checkpoint_label = self._resolve_real_checkpoint(checkpoint)
            sam3_module = importlib.import_module("sam3")
            build_model = getattr(sam3_module, "build_sam3_image_model")
            model = build_model(
                checkpoint_path=checkpoint_path,
                load_from_HF=False,
                device=device,
                enable_inst_interactivity=True,
            )
            predictor = getattr(model, "inst_interactive_predictor", None)
            if predictor is None:
                raise RuntimeError("SAM3 interactive predictor is unavailable")
            return _SAMRuntime(
                checkpoint=checkpoint,
                requested_device=device,
                device=device,
                kind="sam3",
                provider=f"sam3:{checkpoint_label}:{device}",
                model=model,
                predictor=predictor,
            )
        except Exception as exc:  # noqa: BLE001
            return _SAMRuntime(
                checkpoint=checkpoint,
                requested_device=device,
                device=device,
                kind="stub",
                provider=f"sam_stub:{checkpoint}:{device}",
                load_error=str(exc),
            )

    def _resolve_real_checkpoint(self, checkpoint: str) -> tuple[str, str]:
        raw = str(checkpoint or "").strip()
        if self._looks_like_checkpoint_path(raw):
            checkpoint_path = resolve_path(raw)
            if not checkpoint_path.exists():
                raise RuntimeError(f"SAM3 checkpoint not found: {checkpoint_path}")
            return checkpoint_path.as_posix(), checkpoint_path.name

        local_checkpoint = self._find_local_checkpoint(raw)
        if local_checkpoint is not None:
            return local_checkpoint.as_posix(), local_checkpoint.name

        if os.getenv("SAM3_ALLOW_HF_DOWNLOAD", "").strip() != "1":
            raise RuntimeError(
                "SAM3 real runtime is disabled until a local .pt checkpoint is configured "
                "or SAM3_ALLOW_HF_DOWNLOAD=1 is set."
            )

        builder_module = importlib.import_module("sam3.model_builder")
        download_ckpt_from_hf = getattr(builder_module, "download_ckpt_from_hf")
        version = "sam3.1" if "3.1" in raw else "sam3"
        checkpoint_path = Path(download_ckpt_from_hf(version=version))
        return checkpoint_path.as_posix(), f"{version}:{checkpoint_path.name}"

    def _prepare_image(self, runtime: _SAMRuntime, image: Image) -> bool:
        image_path = resolve_path(image.file_path)
        image_key = f"{image.id}:{image_path.as_posix()}"
        if runtime.image_cache is not None and runtime.image_cache.key == image_key:
            return True

        pil_image = PILImage.open(image_path).convert("RGB")
        pil_image.load()

        if runtime.kind == "sam3" and runtime.predictor is not None:
            if _np is None:
                raise RuntimeError("numpy is required for SAM3 runtime")
            runtime.predictor.set_image(_np.asarray(pil_image))
            runtime.image_cache = _ImageCache(key=image_key, size=pil_image.size, pil_image=None)
        else:
            runtime.image_cache = _ImageCache(key=image_key, size=pil_image.size, pil_image=pil_image)
        return False

    def _predict_with_sam3(
        self,
        runtime: _SAMRuntime,
        *,
        bbox: list[float],
        points: list[SAMPoint] | None,
        multimask_output: bool,
    ) -> SAMPrediction:
        if runtime.predictor is None or _np is None:
            raise RuntimeError("SAM3 predictor is unavailable")

        point_coords = None
        point_labels = None
        if points:
            point_coords = _np.asarray([[float(point["x"]), float(point["y"])] for point in points], dtype=_np.float32)
            point_labels = _np.asarray([1 if int(point["label"]) > 0 else 0 for point in points], dtype=_np.int32)

        masks, scores, _logits = runtime.predictor.predict(
            point_coords=point_coords,
            point_labels=point_labels,
            box=_np.asarray(bbox, dtype=_np.float32),
            multimask_output=bool(multimask_output),
            normalize_coords=True,
        )
        mask_image, score = _select_mask_candidate(masks, scores)
        return SAMPrediction(
            bbox=_mask_bbox(mask_image) or bbox,
            mask=mask_image,
            provider=runtime.provider,
            score=score,
            meta={"backend": "sam3"},
        )

    def _predict_with_stub(
        self,
        runtime: _SAMRuntime,
        *,
        bbox: list[float],
        points: list[SAMPoint] | None,
        image: Image,
        multimask_output: bool,
        cache_hit: bool,
    ) -> SAMPrediction:
        size = runtime.image_cache.size if runtime.image_cache is not None else (
            max(1, int(image.width or 1)),
            max(1, int(image.height or 1)),
        )
        mask = _build_stub_mask(
            size=size,
            bbox=bbox,
            checkpoint=runtime.checkpoint,
            points=points or [],
            multimask_output=multimask_output,
        )
        score = _stub_score(points or [], checkpoint=runtime.checkpoint, multimask_output=multimask_output)
        metadata: dict[str, Any] = {"backend": "stub"}
        if runtime.load_error:
            metadata["fallback_reason"] = runtime.load_error
        return SAMPrediction(
            bbox=_mask_bbox(mask) or bbox,
            mask=mask,
            provider=runtime.provider,
            score=score,
            cache_hit=cache_hit,
            meta=metadata,
        )

    def _resolve_device(self, requested: str) -> str:
        desired = str(requested or "cpu").strip().lower() or "cpu"
        if desired != "cuda":
            return "cpu"
        try:
            torch = importlib.import_module("torch")
        except Exception:  # noqa: BLE001
            return "cpu"
        return "cuda" if bool(torch.cuda.is_available()) else "cpu"

    def _looks_like_checkpoint_path(self, value: str) -> bool:
        if not value:
            return False
        return value.endswith(".pt") or value.endswith(".pth") or "/" in value or "\\" in value

    def _find_local_checkpoint(self, checkpoint: str) -> Path | None:
        raw = str(checkpoint or "").strip()
        env_override = os.getenv("SAM3_CHECKPOINT_PATH", "").strip()
        if env_override:
            env_path = resolve_path(env_override)
            if not env_path.exists():
                raise RuntimeError(f"SAM3 checkpoint from SAM3_CHECKPOINT_PATH was not found: {env_path}")
            if env_path.is_dir():
                raise RuntimeError(f"SAM3_CHECKPOINT_PATH must point to a checkpoint file, got directory: {env_path}")
            return env_path

        root = get_settings().root_dir.resolve()
        model_dir = (root / "models" / "sam3").resolve()
        if not model_dir.exists():
            return None

        candidates = sorted(
            [path for path in model_dir.rglob("*") if path.is_file() and path.suffix.lower() in (".pt", ".pth")],
            key=lambda path: path.name.lower(),
        )
        if not candidates:
            return None

        wanted_tags: list[str] = []
        lowered = raw.casefold()
        if "3.1" in lowered:
            wanted_tags.extend(["3.1", "sam3.1", "multiplex"])
        elif lowered == "sam3":
            wanted_tags.extend(["sam3", "3.1", "multiplex"])
        else:
            wanted_tags.append(lowered)

        for tag in wanted_tags:
            for candidate in candidates:
                if tag in candidate.name.casefold():
                    return candidate
        return candidates[0]


def _select_mask_candidate(masks: Any, scores: Any) -> tuple[PILImage.Image, float | None]:
    if _np is None:
        raise RuntimeError("numpy is required for SAM3 runtime")

    mask_array = _as_numpy(masks)
    score_array = _as_numpy(scores) if scores is not None else None

    if mask_array.ndim == 2:
        candidate = mask_array
        best_score = None if score_array is None or score_array.size == 0 else float(score_array.reshape(-1)[0])
    else:
        flat_scores = _np.zeros((mask_array.shape[0],), dtype=_np.float32)
        if score_array is not None and score_array.size:
            flat_scores = score_array.reshape(-1).astype(_np.float32)
        best_index = int(flat_scores.argmax()) if flat_scores.size else 0
        candidate = mask_array[best_index]
        best_score = float(flat_scores[best_index]) if flat_scores.size else None

    if candidate.ndim == 3:
        candidate = candidate[0]

    binary = (_np.asarray(candidate, dtype=_np.float32) > 0).astype(_np.uint8) * 255
    return PILImage.fromarray(binary, mode="L"), (round(best_score, 4) if best_score is not None else None)


def _as_numpy(value: Any) -> Any:
    if _np is None or value is None:
        return value
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        return value.numpy()
    return _np.asarray(value)


def _build_stub_mask(
    *,
    size: tuple[int, int],
    bbox: list[float],
    checkpoint: str,
    points: list[SAMPoint],
    multimask_output: bool,
) -> PILImage.Image:
    width, height = size
    left = _clamp01(bbox[0]) * max(0, width - 1)
    top = _clamp01(bbox[1]) * max(0, height - 1)
    right = _clamp01(bbox[2]) * max(0, width - 1)
    bottom = _clamp01(bbox[3]) * max(0, height - 1)

    box_width = max(8.0, right - left)
    box_height = max(8.0, bottom - top)
    center_x = (left + right) / 2.0
    center_y = (top + bottom) / 2.0
    base_rx = box_width / 2.0
    base_ry = box_height / 2.0
    curve = _checkpoint_curve_ratio(checkpoint)

    vertex_count = 28 if multimask_output or "3.1" in checkpoint.casefold() else 18
    seed = sum(ord(ch) for ch in checkpoint) % 17
    polygon: list[tuple[float, float]] = []
    for index in range(vertex_count):
        angle = (math.tau * index) / vertex_count
        rx_scale = 0.84 + curve * 0.55 * math.sin(angle * 2 + seed * 0.1)
        ry_scale = 0.82 + curve * 0.6 * math.cos(angle * 3 - seed * 0.12)

        if points:
            for point in points:
                point_angle = math.atan2(
                    _clamp01(point["y"]) * max(0, height - 1) - center_y,
                    _clamp01(point["x"]) * max(0, width - 1) - center_x,
                )
                delta = math.atan2(math.sin(angle - point_angle), math.cos(angle - point_angle))
                influence = max(0.0, 1.0 - abs(delta) / 0.9)
                if int(point["label"]) > 0:
                    rx_scale += influence * 0.08
                    ry_scale += influence * 0.08
                else:
                    rx_scale -= influence * 0.12
                    ry_scale -= influence * 0.12

        px = center_x + math.cos(angle) * base_rx * max(0.55, rx_scale)
        py = center_y + math.sin(angle) * base_ry * max(0.5, ry_scale)
        polygon.append((_clamp(px, 0.0, max(0.0, width - 1.0)), _clamp(py, 0.0, max(0.0, height - 1.0))))

    mask = PILImage.new("L", (width, height), color=0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(polygon, fill=255)
    return mask


def _mask_bbox(mask: PILImage.Image) -> list[float] | None:
    bbox = mask.getbbox()
    if bbox is None:
        return None
    left, top, right, bottom = bbox
    width, height = mask.size
    return [
        round(_pixel_to_norm(left, width), 6),
        round(_pixel_to_norm(top, height), 6),
        round(_pixel_to_norm(max(left, right - 1), width), 6),
        round(_pixel_to_norm(max(top, bottom - 1), height), 6),
    ]


def _pixel_to_norm(value: float, length: int) -> float:
    if length <= 1:
        return 0.0
    return _clamp01(float(value) / float(length - 1))


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _stub_score(points: list[SAMPoint], *, checkpoint: str, multimask_output: bool) -> float:
    bonus = 0.06 if "3.1" in checkpoint.casefold() else 0.0
    bonus += 0.04 if multimask_output else 0.0
    bonus += min(0.12, len(points) * 0.02)
    return round(min(0.97, 0.72 + bonus), 4)
