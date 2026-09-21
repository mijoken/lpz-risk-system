from __future__ import annotations

import math
from typing import Iterable

WEB_MERCATOR_RADIUS_KM = 6378.137
_EPS = 1e-10


def _outer_ring(geometry: dict) -> list[tuple[float, float]]:
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise ValueError("expected GeoJSON Polygon")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) != 1:
        raise ValueError("expected convex polygon with one outer ring and no holes")
    ring = coordinates[0]
    if not isinstance(ring, list) or len(ring) < 4:
        raise ValueError("polygon ring too short")
    points: list[tuple[float, float]] = []
    for row in ring:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise ValueError("invalid polygon coordinate")
        lon = float(row[0])
        lat = float(row[1])
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise ValueError("nonfinite polygon coordinate")
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError("polygon coordinate outside geographic range")
        points.append((lon, lat))
    if _same_point(points[0], points[-1]):
        points.pop()
    if len(points) < 3:
        raise ValueError("polygon has fewer than three unique vertices")
    if len({(round(lon, 12), round(lat, 12)) for lon, lat in points}) < 3:
        raise ValueError("polygon has fewer than three unique vertices")
    return points


def _same_point(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return abs(a[0] - b[0]) <= _EPS and abs(a[1] - b[1]) <= _EPS


def _unwrap_lon(lon: float, reference: float) -> float:
    return reference + ((lon - reference + 180.0) % 360.0) - 180.0


def _project_pair(
    geometry_a: dict,
    geometry_b: dict,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Project both envelopes back to their native Web Mercator tracking plane.

    F4 geographic envelopes originate from Web Mercator radar pixel-cell
    vertices. Using the same projection for overlap metrics avoids a
    pair-specific local projection and keeps motion/persistence IoU directly
    comparable. Area fields are planar Web Mercator areas, not geodesic area.
    """
    a_ll = _outer_ring(geometry_a)
    b_ll = _outer_ring(geometry_b)
    all_ll = a_ll + b_ll
    reference_lon = all_ll[0][0]

    def project(points: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
        out = []
        for lon, lat in points:
            if abs(lat) >= 85.05112878:
                raise ValueError("polygon outside Web Mercator latitude range")
            lon_u = _unwrap_lon(lon, reference_lon)
            x = WEB_MERCATOR_RADIUS_KM * math.radians(lon_u)
            y = WEB_MERCATOR_RADIUS_KM * math.log(
                math.tan(math.pi / 4.0 + math.radians(lat) / 2.0)
            )
            out.append((x, y))
        return out

    return project(a_ll), project(b_ll)


def _signed_area(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    return abs(_signed_area(points))


def _cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _as_ccw_convex(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(points) < 3:
        raise ValueError("polygon has fewer than three vertices")
    if _signed_area(points) < 0:
        points = list(reversed(points))
    sign = 0
    scale = max(1.0, max(abs(x) + abs(y) for x, y in points))
    tolerance = 1e-10 * scale * scale
    for i in range(len(points)):
        value = _cross(points[i], points[(i + 1) % len(points)], points[(i + 2) % len(points)])
        if abs(value) <= tolerance:
            continue
        current = 1 if value > 0 else -1
        if sign == 0:
            sign = current
        elif current != sign:
            raise ValueError("polygon is not convex")
    if sign == 0 or _area(points) <= tolerance:
        raise ValueError("degenerate polygon")
    if sign < 0:
        points = list(reversed(points))
    return points


def _inside(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
    tolerance: float,
) -> bool:
    return _cross(a, b, point) >= -tolerance


def _line_intersection(
    p: tuple[float, float],
    q: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> tuple[float, float]:
    rx, ry = q[0] - p[0], q[1] - p[1]
    sx, sy = b[0] - a[0], b[1] - a[1]
    denominator = rx * sy - ry * sx
    if abs(denominator) <= 1e-14:
        return q
    apx, apy = a[0] - p[0], a[1] - p[1]
    t = (apx * sy - apy * sx) / denominator
    return (p[0] + t * rx, p[1] + t * ry)


def _clip_convex(
    subject: list[tuple[float, float]],
    clip: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    output = subject[:]
    if not output:
        return []
    scale = max(1.0, max(abs(x) + abs(y) for x, y in subject + clip))
    tolerance = 1e-10 * scale * scale
    for i, a in enumerate(clip):
        b = clip[(i + 1) % len(clip)]
        input_points = output
        output = []
        if not input_points:
            break
        previous = input_points[-1]
        previous_inside = _inside(previous, a, b, tolerance)
        for current in input_points:
            current_inside = _inside(current, a, b, tolerance)
            if current_inside:
                if not previous_inside:
                    output.append(_line_intersection(previous, current, a, b))
                output.append(current)
            elif previous_inside:
                output.append(_line_intersection(previous, current, a, b))
            previous = current
            previous_inside = current_inside
    return output


def convex_polygon_overlap_metrics(
    predicted_geometry: dict,
    observed_geometry: dict,
) -> dict[str, float | str]:
    predicted, observed = _project_pair(predicted_geometry, observed_geometry)
    predicted = _as_ccw_convex(predicted)
    observed = _as_ccw_convex(observed)
    intersection = _clip_convex(predicted, observed)

    predicted_area = _area(predicted)
    observed_area = _area(observed)
    intersection_area = _area(intersection)
    max_intersection = min(predicted_area, observed_area)
    if intersection_area > max_intersection and intersection_area - max_intersection < 1e-7:
        intersection_area = max_intersection
    if intersection_area > max_intersection + 1e-7:
        raise ValueError("polygon intersection exceeds source area")
    union_area = predicted_area + observed_area - intersection_area
    if predicted_area <= 0 or observed_area <= 0 or union_area <= 0:
        raise ValueError("degenerate polygon area")

    return {
        "projection": "WEB_MERCATOR_TRACKING_PLANE",
        "predicted_planar_area_km2": predicted_area,
        "observed_planar_area_km2": observed_area,
        "intersection_planar_area_km2": intersection_area,
        "union_planar_area_km2": union_area,
        "iou": intersection_area / union_area,
        "predicted_overlap_fraction": intersection_area / predicted_area,
        "observed_coverage_fraction": intersection_area / observed_area,
    }
