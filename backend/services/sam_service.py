from __future__ import annotations

from dataclasses import dataclass

from backend.models.image import Image


@dataclass
class SAMPrediction:
    polygon: list[list[float]]
    mask_path: str | None = None
    provider: str = "sam_stub"


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
        return SAMPrediction(polygon=_rounded_box_polygon(bbox))
