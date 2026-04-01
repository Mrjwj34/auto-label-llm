from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from backend.models.annotation import Annotation
from backend.models.image import Image


@dataclass
class SAMPrediction:
    polygon: list[list[float]]
    bbox: list[float] | None = None
    mask_path: str | None = None
    provider: str = "sam_stub"


class SAMPoint(TypedDict):
    x: float
    y: float
    label: int


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _rounded_box_polygon(bbox: list[float]) -> list[list[float]]:
    xmin, ymin, xmax, ymax = bbox
    width = xmax - xmin
    height = ymax - ymin

    if width <= 0 or height <= 0:
        return []

    dx = min(max(width * 0.18, 0.012), width / 3)
    dy = min(max(height * 0.18, 0.012), height / 3)

    points = [
        [xmin + dx, ymin],
        [xmax - dx, ymin],
        [xmax, ymin + dy],
        [xmax, ymax - dy],
        [xmax - dx, ymax],
        [xmin + dx, ymax],
        [xmin, ymax - dy],
        [xmin, ymin + dy],
    ]

    normalized: list[list[float]] = []
    seen: set[tuple[float, float]] = set()
    for x, y in points:
        px = round(_clamp01(x), 6)
        py = round(_clamp01(y), 6)
        key = (px, py)
        if key in seen:
            continue
        seen.add(key)
        normalized.append([px, py])

    if len(normalized) < 3:
        return [
            [round(_clamp01(xmin), 6), round(_clamp01(ymin), 6)],
            [round(_clamp01(xmax), 6), round(_clamp01(ymin), 6)],
            [round(_clamp01(xmax), 6), round(_clamp01(ymax), 6)],
            [round(_clamp01(xmin), 6), round(_clamp01(ymax), 6)],
        ]

    return normalized


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
            cls._instance._current_image_id = None
        return cls._instance

    def set_image(self, image: Image) -> None:
        # Real SAM integration can reuse this image-level cache contract later.
        self._current_image_id = image.id

    def predict_polygon(self, image: Image, bbox: list[float]) -> SAMPrediction:
        self.set_image(image)
        normalized_bbox = _canonicalize_bbox(bbox)
        return SAMPrediction(
            bbox=normalized_bbox,
            polygon=_rounded_box_polygon(normalized_bbox),
        )

    def refine_annotation(
        self,
        image: Image,
        annotation: Annotation,
        points: list[SAMPoint],
    ) -> SAMPrediction:
        self.set_image(image)
        if annotation.bbox is None:
            raise ValueError("annotation bbox is required for point correction")
        refined_bbox = _refine_bbox_with_points(annotation.bbox, points)
        return SAMPrediction(
            bbox=refined_bbox,
            polygon=_rounded_box_polygon(refined_bbox),
        )
