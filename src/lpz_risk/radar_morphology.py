"""Object morphology for JMA public precipitation-class PNG tiles.

This module deliberately operates on discrete public PNG precipitation classes.
It does NOT claim to reproduce Hirockawa heavy-rainfall areas (HRA), which
require continuous accumulated precipitation and temporal persistence logic.

Only class-boundary thresholds that can be represented exactly by the public
palette (currently 30, 50, and 80 mm/h) are used for live object masks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from collections import deque

import numpy as np

from .radar_science import interval_definitely_at_least


ALLOWED_EXACT_THRESHOLDS_MMPH = (30.0, 50.0, 80.0)
EARTH_RADIUS_M = 6378137.0
TILE_SIZE = 256


@dataclass(frozen=True)
class RadarObjectMorphology:
    object_id: int
    threshold_mmph: float
    pixel_count: int
    area_km2: float
    centroid_lon: float
    centroid_lat: float
    major_axis_km: float
    minor_axis_km: float
    aspect_ratio: float | None
    orientation_deg: float | None
    max_class_index: int
    boundary_truncated: bool
    bbox_pixel: tuple[int, int, int, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "object_id": self.object_id,
            "threshold_mmph": self.threshold_mmph,
            "pixel_count": self.pixel_count,
            "area_km2": self.area_km2,
            "centroid": {"lon": self.centroid_lon, "lat": self.centroid_lat},
            "major_axis_km": self.major_axis_km,
            "minor_axis_km": self.minor_axis_km,
            "aspect_ratio": self.aspect_ratio,
            "orientation_deg": self.orientation_deg,
            "max_class_index": self.max_class_index,
            "boundary_truncated": self.boundary_truncated,
            "bbox_pixel": list(self.bbox_pixel),
        }


def _validate_threshold(threshold_mmph: float) -> None:
    if float(threshold_mmph) not in ALLOWED_EXACT_THRESHOLDS_MMPH:
        raise ValueError(
            f"threshold {threshold_mmph} mm/h is not an exact public-palette boundary; "
            f"allowed={ALLOWED_EXACT_THRESHOLDS_MMPH}"
        )


def exact_threshold_mask(class_index: np.ndarray, threshold_mmph: float) -> np.ndarray:
    """Return a conservative exact-boundary mask from precipitation classes."""
    _validate_threshold(threshold_mmph)
    return interval_definitely_at_least(class_index, float(threshold_mmph))


def connected_components_8(mask: np.ndarray) -> list[np.ndarray]:
    """Return 8-connected components as arrays of ``[row, col]`` coordinates."""
    if mask.ndim != 2:
        raise ValueError("mask must be 2-D")
    mask = np.asarray(mask, dtype=bool)
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    components: list[np.ndarray] = []
    neighbors = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))

    for r, c in np.argwhere(mask):
        r = int(r); c = int(c)
        if seen[r, c]:
            continue
        q: deque[tuple[int, int]] = deque([(r, c)])
        seen[r, c] = True
        pts: list[tuple[int, int]] = []
        while q:
            rr, cc = q.popleft()
            pts.append((rr, cc))
            for dr, dc in neighbors:
                nr, nc = rr + dr, cc + dc
                if 0 <= nr < h and 0 <= nc < w and mask[nr, nc] and not seen[nr, nc]:
                    seen[nr, nc] = True
                    q.append((nr, nc))
        components.append(np.asarray(pts, dtype=np.int32))
    return components


def _global_pixel_center_lonlat(zoom: int, global_px: np.ndarray, global_py: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    world_px = TILE_SIZE * (2 ** zoom)
    lon = global_px / world_px * 360.0 - 180.0
    merc_y = math.pi * (1.0 - 2.0 * global_py / world_px)
    lat = np.degrees(np.arctan(np.sinh(merc_y)))
    return lon, lat


def _meters_per_pixel(lat_deg: float, zoom: int) -> float:
    circumference = 2.0 * math.pi * EARTH_RADIUS_M
    return circumference * math.cos(math.radians(lat_deg)) / (TILE_SIZE * (2 ** zoom))


def _orientation_and_axes(rows: np.ndarray, cols: np.ndarray, lat_deg: float, zoom: int) -> tuple[float, float, float | None, float | None]:
    """Return PCA-derived major/minor full-axis lengths, aspect ratio and orientation.

    Axis lengths use ``4 * sqrt(eigenvalue)`` as a stable descriptive extent
    (approximately a two-standard-deviation radius on each side). They are a
    morphology descriptor, not a paper-reproduction definition.
    Orientation is clockwise from north in [0, 180).
    """
    if len(rows) < 2:
        return 0.0, 0.0, None, None
    scale_km = _meters_per_pixel(lat_deg, zoom) / 1000.0
    x = (cols.astype(float) - float(np.mean(cols))) * scale_km
    y_north = -(rows.astype(float) - float(np.mean(rows))) * scale_km
    coords = np.column_stack([x, y_north])
    cov = np.cov(coords, rowvar=False, ddof=0)
    values, vectors = np.linalg.eigh(cov)
    order = np.argsort(values)[::-1]
    values = np.maximum(values[order], 0.0)
    vectors = vectors[:, order]
    major = 4.0 * math.sqrt(float(values[0]))
    minor = 4.0 * math.sqrt(float(values[1])) if len(values) > 1 else 0.0
    aspect = None if minor <= 0.0 else major / minor
    vx_east, vy_north = map(float, vectors[:, 0])
    orientation = math.degrees(math.atan2(vx_east, vy_north)) % 180.0
    return major, minor, aspect, orientation


def extract_objects_from_mosaic(
    class_index: np.ndarray,
    *,
    zoom: int,
    origin_tile_x: int,
    origin_tile_y: int,
    threshold_mmph: float,
    min_pixels: int = 1,
) -> list[RadarObjectMorphology]:
    """Extract connected precipitation objects from an even-zoom tile mosaic.

    ``class_index`` is a stitched array whose top-left corresponds to
    ``origin_tile_x, origin_tile_y``. All tiles must be contiguous and use the
    same zoom.
    """
    if class_index.ndim != 2:
        raise ValueError("class_index must be 2-D")
    if min_pixels < 1:
        raise ValueError("min_pixels must be >= 1")
    mask = exact_threshold_mask(class_index, threshold_mmph)
    h, w = class_index.shape
    objects: list[RadarObjectMorphology] = []

    for object_id, pts in enumerate(connected_components_8(mask), start=1):
        if len(pts) < min_pixels:
            continue
        rows = pts[:, 0]
        cols = pts[:, 1]
        global_px = origin_tile_x * TILE_SIZE + cols.astype(float) + 0.5
        global_py = origin_tile_y * TILE_SIZE + rows.astype(float) + 0.5
        lons, lats = _global_pixel_center_lonlat(zoom, global_px, global_py)

        # Pixel ground area changes with latitude in Web Mercator. Sum it per pixel.
        mpp = np.array([_meters_per_pixel(float(lat), zoom) for lat in lats], dtype=float)
        area_km2 = float(np.sum((mpp * mpp) / 1_000_000.0))
        centroid_lon = float(np.mean(lons))
        centroid_lat = float(np.mean(lats))
        major, minor, aspect, orientation = _orientation_and_axes(rows, cols, centroid_lat, zoom)
        max_class = int(np.max(class_index[rows, cols]))
        r0, r1 = int(rows.min()), int(rows.max())
        c0, c1 = int(cols.min()), int(cols.max())
        boundary = r0 == 0 or c0 == 0 or r1 == h - 1 or c1 == w - 1

        objects.append(
            RadarObjectMorphology(
                object_id=object_id,
                threshold_mmph=float(threshold_mmph),
                pixel_count=int(len(pts)),
                area_km2=area_km2,
                centroid_lon=centroid_lon,
                centroid_lat=centroid_lat,
                major_axis_km=major,
                minor_axis_km=minor,
                aspect_ratio=aspect,
                orientation_deg=orientation,
                max_class_index=max_class,
                boundary_truncated=boundary,
                bbox_pixel=(c0, r0, c1, r1),
            )
        )

    return sorted(objects, key=lambda obj: (obj.area_km2, obj.pixel_count), reverse=True)
