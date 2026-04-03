from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot
from typing import Any

from PIL import Image as PILImage
from PIL import ImageDraw, ImageFilter

from backend.models.image import Image
from backend.models.project import Project
from backend.services.project_settings import load_project_settings
from backend.utils.storage import save_project_mask_image

try:
    import cv2 as _cv2
except Exception:  # noqa: BLE001
    _cv2 = None

try:
    import numpy as _np
except Exception:  # noqa: BLE001
    _np = None


@dataclass
class ProcessedSegmentation:
    polygon: list[list[float]] | None
    bbox: list[float] | None
    mask_path: str | None
    score: float | None = None
    provider: str = "sam_stub"
    stats: dict[str, Any] = field(default_factory=dict)


def apply_project_postprocess(
    project: Project | None,
    image: Image,
    *,
    mask: PILImage.Image | None,
    bbox: list[float] | None,
    provider: str,
    score: float | None = None,
) -> ProcessedSegmentation:
    fallback_bbox = _normalize_bbox(bbox)
    if mask is None:
        return ProcessedSegmentation(
            polygon=_bbox_to_polygon(fallback_bbox),
            bbox=fallback_bbox,
            mask_path=None,
            score=score,
            provider=provider,
            stats={"mask_pixels": 0, "area_ratio": 0.0, "engine": "none"},
        )

    settings = load_project_settings(project)
    postprocess = settings.get("postprocess", {}) if isinstance(settings.get("postprocess"), dict) else {}

    binary_mask = _prepare_binary_mask(mask, image=image)
    if bool(postprocess.get("enable_close", True)):
        binary_mask = _close_mask(binary_mask, kernel_size=int(postprocess.get("close_kernel") or 5))

    bbox_from_mask = _bbox_from_mask(binary_mask)
    if bbox_from_mask is None:
        return ProcessedSegmentation(
            polygon=_bbox_to_polygon(fallback_bbox),
            bbox=fallback_bbox,
            mask_path=None,
            score=score,
            provider=provider,
            stats={"mask_pixels": 0, "area_ratio": 0.0, "engine": "empty-mask"},
        )

    mask_pixels = _count_mask_pixels(binary_mask)
    width, height = binary_mask.size
    area_ratio = mask_pixels / max(1, width * height)
    min_area_ratio = max(0.0, float(postprocess.get("min_area_ratio", 0.0005) or 0.0005))

    polygon = _polygon_from_mask(
        binary_mask,
        enable_dp_simplify=bool(postprocess.get("enable_dp_simplify", True)),
        epsilon_ratio=float(postprocess.get("epsilon_ratio", 0.002) or 0.002),
    )
    if area_ratio < min_area_ratio:
        polygon = None

    final_bbox = bbox_from_mask or fallback_bbox
    final_polygon = polygon or _bbox_to_polygon(final_bbox)
    mask_path = save_project_mask_image(
        image.project_id,
        image.id,
        binary_mask,
        stem=f"{provider}_mask",
    )
    return ProcessedSegmentation(
        polygon=final_polygon,
        bbox=final_bbox,
        mask_path=mask_path,
        score=score,
        provider=provider,
        stats={
            "mask_pixels": mask_pixels,
            "area_ratio": round(area_ratio, 6),
            "engine": "opencv" if _cv2 is not None and _np is not None else "fallback",
        },
    )


def save_polygon_mask(image: Image, polygon: list[list[float]] | None, *, stem: str = "import") -> str | None:
    if not polygon or len(polygon) < 3:
        return None

    width = max(1, int(image.width or 1))
    height = max(1, int(image.height or 1))
    mask = PILImage.new("L", (width, height), color=0)
    draw = ImageDraw.Draw(mask)
    draw.polygon([_norm_point_to_pixel(point, width, height) for point in polygon], fill=255)
    if mask.getbbox() is None:
        return None
    return save_project_mask_image(image.project_id, image.id, mask, stem=stem)


def _prepare_binary_mask(mask: PILImage.Image, *, image: Image) -> PILImage.Image:
    width = max(1, int(image.width or mask.size[0] or 1))
    height = max(1, int(image.height or mask.size[1] or 1))
    prepared = mask.convert("L")
    if prepared.size != (width, height):
        prepared = prepared.resize((width, height), resample=PILImage.Resampling.NEAREST)
    return prepared.point(lambda value: 255 if value >= 128 else 0, mode="L")


def _close_mask(mask: PILImage.Image, *, kernel_size: int) -> PILImage.Image:
    size = _normalize_kernel_size(kernel_size)
    if _cv2 is not None and _np is not None:
        array = _np.array(mask, dtype=_np.uint8)
        kernel = _np.ones((size, size), dtype=_np.uint8)
        closed = _cv2.morphologyEx(array, _cv2.MORPH_CLOSE, kernel)
        return PILImage.fromarray(closed, mode="L")
    return mask.filter(ImageFilter.MaxFilter(size)).filter(ImageFilter.MinFilter(size))


def _polygon_from_mask(
    mask: PILImage.Image,
    *,
    enable_dp_simplify: bool,
    epsilon_ratio: float,
) -> list[list[float]] | None:
    if _cv2 is not None and _np is not None:
        polygon = _polygon_from_mask_opencv(mask, enable_dp_simplify=enable_dp_simplify, epsilon_ratio=epsilon_ratio)
        if polygon:
            return polygon

    polygon = _polygon_from_mask_scan(mask)
    if polygon and enable_dp_simplify:
        epsilon = max(1e-4, _perimeter(polygon) * max(0.0, epsilon_ratio))
        polygon = _simplify_closed_polygon(polygon, epsilon=epsilon)
    return polygon


def _polygon_from_mask_opencv(
    mask: PILImage.Image,
    *,
    enable_dp_simplify: bool,
    epsilon_ratio: float,
) -> list[list[float]] | None:
    array = _np.array(mask, dtype=_np.uint8)
    contours, _hierarchy = _cv2.findContours(array, _cv2.RETR_EXTERNAL, _cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    contour = max(contours, key=_cv2.contourArea)
    if enable_dp_simplify:
        perimeter = _cv2.arcLength(contour, True)
        contour = _cv2.approxPolyDP(contour, max(1.0, perimeter * max(0.0, epsilon_ratio)), True)

    points = [[float(point[0][0]), float(point[0][1])] for point in contour]
    return _normalize_pixel_polygon(points, size=mask.size)


def _polygon_from_mask_scan(mask: PILImage.Image) -> list[list[float]] | None:
    bbox = mask.getbbox()
    if bbox is None:
        return None

    left, upper, right, lower = bbox
    pixels = mask.load()
    left_chain: list[list[float]] = []
    right_chain: list[list[float]] = []

    for y in range(upper, lower):
        left_x: int | None = None
        right_x: int | None = None
        for x in range(left, right):
            if pixels[x, y] <= 0:
                continue
            if left_x is None:
                left_x = x
            right_x = x
        if left_x is None or right_x is None:
            continue
        left_chain.append([float(left_x), float(y)])
        if right_x != left_x:
            right_chain.append([float(right_x), float(y)])

    polygon = left_chain + list(reversed(right_chain))
    return _normalize_pixel_polygon(polygon, size=mask.size)


def _normalize_pixel_polygon(points: list[list[float]], *, size: tuple[int, int]) -> list[list[float]] | None:
    width, height = size
    normalized: list[list[float]] = []
    seen: set[tuple[float, float]] = set()
    for point in points:
        if len(point) != 2:
            continue
        x = round(_pixel_to_norm(point[0], width), 6)
        y = round(_pixel_to_norm(point[1], height), 6)
        key = (x, y)
        if key in seen:
            continue
        normalized.append([x, y])
        seen.add(key)

    if len(normalized) >= 2 and normalized[0] == normalized[-1]:
        normalized.pop()
    if len(normalized) < 3:
        return None
    return normalized


def _bbox_from_mask(mask: PILImage.Image) -> list[float] | None:
    bbox = mask.getbbox()
    if bbox is None:
        return None
    left, upper, right, lower = bbox
    width, height = mask.size
    return _normalize_bbox(
        [
            _pixel_to_norm(left, width),
            _pixel_to_norm(upper, height),
            _pixel_to_norm(max(left, right - 1), width),
            _pixel_to_norm(max(upper, lower - 1), height),
        ]
    )


def _count_mask_pixels(mask: PILImage.Image) -> int:
    return sum(1 for value in mask.getdata() if int(value) > 0)


def _normalize_kernel_size(value: int) -> int:
    size = max(1, int(value))
    if size % 2 == 0:
        size += 1
    return size


def _pixel_to_norm(value: float, length: int) -> float:
    if length <= 1:
        return 0.0
    return _clamp01(float(value) / float(length - 1))


def _norm_point_to_pixel(point: list[float], width: int, height: int) -> tuple[int, int]:
    x = int(round(_clamp01(point[0]) * max(0, width - 1)))
    y = int(round(_clamp01(point[1]) * max(0, height - 1)))
    return x, y


def _bbox_to_polygon(bbox: list[float] | None) -> list[list[float]] | None:
    if not bbox or len(bbox) != 4:
        return None
    xmin, ymin, xmax, ymax = bbox
    return [[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]]


def _normalize_bbox(bbox: list[float] | None) -> list[float] | None:
    if bbox is None or len(bbox) != 4:
        return None
    xmin, ymin, xmax, ymax = [float(v) for v in bbox]
    if xmin > xmax:
        xmin, xmax = xmax, xmin
    if ymin > ymax:
        ymin, ymax = ymax, ymin
    return [
        round(_clamp01(xmin), 6),
        round(_clamp01(ymin), 6),
        round(_clamp01(xmax), 6),
        round(_clamp01(ymax), 6),
    ]


def _simplify_closed_polygon(points: list[list[float]], *, epsilon: float) -> list[list[float]]:
    if len(points) < 4:
        return points
    line = points + [points[0]]
    simplified = _rdp(line, epsilon)
    if len(simplified) >= 2 and simplified[0] == simplified[-1]:
        simplified = simplified[:-1]
    return _normalize_points(simplified) or points


def _normalize_points(points: list[list[float]]) -> list[list[float]]:
    normalized: list[list[float]] = []
    seen: set[tuple[float, float]] = set()
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            continue
        x = round(_clamp01(float(point[0])), 6)
        y = round(_clamp01(float(point[1])), 6)
        key = (x, y)
        if key in seen:
            continue
        normalized.append([x, y])
        seen.add(key)

    if len(normalized) >= 2 and normalized[0] == normalized[-1]:
        normalized.pop()
    return normalized


def _rdp(points: list[list[float]], epsilon: float) -> list[list[float]]:
    if len(points) < 3:
        return points

    start = points[0]
    end = points[-1]
    max_distance = -1.0
    index = 0
    for idx in range(1, len(points) - 1):
        distance = _point_line_distance(points[idx], start, end)
        if distance > max_distance:
            max_distance = distance
            index = idx

    if max_distance > epsilon:
        left = _rdp(points[: index + 1], epsilon)
        right = _rdp(points[index:], epsilon)
        return left[:-1] + right
    return [start, end]


def _point_line_distance(point: list[float], start: list[float], end: list[float]) -> float:
    if start == end:
        return hypot(point[0] - start[0], point[1] - start[1])

    px, py = point
    x1, y1 = start
    x2, y2 = end
    numerator = abs((y2 - y1) * px - (x2 - x1) * py + x2 * y1 - y2 * x1)
    denominator = hypot(y2 - y1, x2 - x1)
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _perimeter(points: list[list[float]]) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    for idx, point in enumerate(points):
        next_point = points[(idx + 1) % len(points)]
        total += hypot(next_point[0] - point[0], next_point[1] - point[1])
    return total


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
