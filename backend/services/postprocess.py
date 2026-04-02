from __future__ import annotations

from math import hypot
from typing import Any

from backend.models.project import Project
from backend.services.project_settings import load_project_settings


def apply_project_postprocess(project: Project | None, polygon: list[list[float]] | None) -> list[list[float]] | None:
    if not polygon or len(polygon) < 3:
        return polygon

    settings = load_project_settings(project)
    postprocess = settings.get("postprocess", {}) if isinstance(settings.get("postprocess"), dict) else {}
    processed = postprocess_polygon(
        polygon,
        enable_close=bool(postprocess.get("enable_close", True)),
        close_kernel=int(postprocess.get("close_kernel", 5) or 5),
        enable_dp_simplify=bool(postprocess.get("enable_dp_simplify", True)),
        epsilon_ratio=float(postprocess.get("epsilon_ratio", 0.002) or 0.002),
        min_area_ratio=float(postprocess.get("min_area_ratio", 0.0005) or 0.0005),
    )
    return processed or polygon


def postprocess_polygon(
    polygon: list[list[float]],
    *,
    enable_close: bool,
    close_kernel: int,
    enable_dp_simplify: bool,
    epsilon_ratio: float,
    min_area_ratio: float,
) -> list[list[float]] | None:
    points = _normalize_points(polygon)
    if len(points) < 3:
        return None

    if enable_close:
        points = _smooth_polygon(points, passes=max(1, close_kernel // 4))
    if enable_dp_simplify:
        epsilon = max(1e-4, _perimeter(points) * max(0.0, epsilon_ratio))
        points = _simplify_closed_polygon(points, epsilon=epsilon)

    if len(points) < 3:
        return None
    if abs(_polygon_area(points)) < max(0.0, min_area_ratio):
        return None
    return points


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


def _smooth_polygon(points: list[list[float]], *, passes: int) -> list[list[float]]:
    if len(points) < 3:
        return points
    result = [point[:] for point in points]
    for _ in range(max(1, passes)):
        next_points: list[list[float]] = []
        total = len(result)
        for idx, point in enumerate(result):
            prev_point = result[(idx - 1) % total]
            next_point = result[(idx + 1) % total]
            smoothed_x = round(_clamp01((prev_point[0] + point[0] * 2 + next_point[0]) / 4), 6)
            smoothed_y = round(_clamp01((prev_point[1] + point[1] * 2 + next_point[1]) / 4), 6)
            next_points.append([smoothed_x, smoothed_y])
        result = _normalize_points(next_points)
        if len(result) < 3:
            return points
    return result


def _simplify_closed_polygon(points: list[list[float]], *, epsilon: float) -> list[list[float]]:
    if len(points) < 4:
        return points
    line = points + [points[0]]
    simplified = _rdp(line, epsilon)
    if len(simplified) >= 2 and simplified[0] == simplified[-1]:
        simplified = simplified[:-1]
    return _normalize_points(simplified) or points


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


def _polygon_area(points: list[list[float]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for idx, point in enumerate(points):
        next_point = points[(idx + 1) % len(points)]
        area += point[0] * next_point[1] - next_point[0] * point[1]
    return abs(area) / 2.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
