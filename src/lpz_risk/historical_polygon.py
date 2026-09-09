"""Polygon masking utilities for historical analyzed-rainfall research.

The official JMA primary-subdivision geometry is retained as derived GeoJSON.
Raster cells are selected by cell-centre point-in-polygon tests. Cell areas are
computed from actual latitude/longitude cell edges on a spherical Earth; no
assumption that every nominal 1 km cell is exactly 1.0 km² is permitted.

The exact historical analyzed-rainfall grid definition remains a payload audit
gate. These utilities are format-agnostic and operate only after real grid
centres have been decoded.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

EARTH_RADIUS_M = 6_371_008.8


def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray-casting point-in-ring test; boundary points count as inside."""
    if len(ring) < 4:
        return False
    inside = False
    x, y = float(lon), float(lat)
    for i in range(len(ring) - 1):
        x1, y1 = map(float, ring[i][:2])
        x2, y2 = map(float, ring[i + 1][:2])

        # Boundary check using cross product and bounding box.
        dx, dy = x2 - x1, y2 - y1
        cross = (x - x1) * dy - (y - y1) * dx
        scale = max(1.0, abs(dx), abs(dy))
        if abs(cross) <= 1e-12 * scale:
            if min(x1, x2) - 1e-12 <= x <= max(x1, x2) + 1e-12 and min(y1, y2) - 1e-12 <= y <= max(y1, y2) + 1e-12:
                return True

        if (y1 > y) != (y2 > y):
            x_intersection = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x <= x_intersection:
                inside = not inside
    return inside


def point_in_geojson_geometry(lon: float, lat: float, geometry: dict[str, Any]) -> bool:
    kind = geometry.get("type")
    if kind == "Polygon":
        rings = geometry.get("coordinates") or []
        if not rings or not _point_in_ring(lon, lat, rings[0]):
            return False
        # GeoJSON polygon holes are all rings after the exterior ring.
        return not any(_point_in_ring(lon, lat, hole) for hole in rings[1:])
    if kind == "MultiPolygon":
        return any(
            point_in_geojson_geometry(lon, lat, {"type": "Polygon", "coordinates": polygon})
            for polygon in (geometry.get("coordinates") or [])
        )
    if kind == "GeometryCollection":
        return any(point_in_geojson_geometry(lon, lat, g) for g in (geometry.get("geometries") or []))
    raise ValueError(f"unsupported GeoJSON geometry type: {kind!r}")


def mask_grid_centres(
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    geometry: dict[str, Any],
) -> np.ndarray:
    """Return boolean mask for matching 2-D latitude/longitude centre arrays."""
    lat = np.asarray(latitudes, dtype=float)
    lon = np.asarray(longitudes, dtype=float)
    if lat.shape != lon.shape or lat.ndim != 2 or lat.size == 0:
        raise ValueError("latitude/longitude centre arrays must be matching non-empty 2-D arrays")
    if np.any(~np.isfinite(lat)) or np.any(~np.isfinite(lon)):
        raise ValueError("grid coordinates must be finite")

    mask = np.zeros(lat.shape, dtype=bool)
    for idx in np.ndindex(lat.shape):
        mask[idx] = point_in_geojson_geometry(float(lon[idx]), float(lat[idx]), geometry)
    return mask


def _centres_to_edges(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1 or arr.size < 2:
        raise ValueError("at least two 1-D grid centres are required to derive edges")
    if np.any(~np.isfinite(arr)):
        raise ValueError("grid centres must be finite")
    diffs = np.diff(arr)
    if np.any(diffs == 0.0) or not (np.all(diffs > 0.0) or np.all(diffs < 0.0)):
        raise ValueError("grid centres must be strictly monotonic")
    edges = np.empty(arr.size + 1, dtype=float)
    edges[1:-1] = 0.5 * (arr[:-1] + arr[1:])
    edges[0] = arr[0] - 0.5 * diffs[0]
    edges[-1] = arr[-1] + 0.5 * diffs[-1]
    return edges


def spherical_latlon_cell_areas_km2(lat_centres_1d: np.ndarray, lon_centres_1d: np.ndarray) -> np.ndarray:
    """Area of regular lat/lon cells from centre coordinates.

    Uses A = R² * |Δλ| * |sin φ₂ - sin φ₁| for each spherical rectangle.
    This is intended for scientific screening and is materially better than
    assuming every nominal 1-km cell has identical area. If the real product
    grid is not separable regular lat/lon, a payload-specific area routine must
    replace this one rather than coercing the grid into this function.
    """
    lat = np.asarray(lat_centres_1d, dtype=float)
    lon = np.asarray(lon_centres_1d, dtype=float)
    lat_edges = _centres_to_edges(lat)
    lon_edges = _centres_to_edges(lon)
    if np.any(lat_edges < -90.0) or np.any(lat_edges > 90.0):
        raise ValueError("derived latitude edges exceed Earth bounds")

    lat_sin_diff = np.abs(np.diff(np.sin(np.radians(lat_edges))))
    lon_diff = np.abs(np.diff(np.radians(lon_edges)))
    area_m2 = (EARTH_RADIUS_M ** 2) * lat_sin_diff[:, None] * lon_diff[None, :]
    return area_m2 / 1_000_000.0


def apply_polygon_to_rainfall(
    rainfall_mm: np.ndarray,
    mask: np.ndarray,
    cell_area_km2: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return rainfall and cell areas only for cells inside the official region."""
    rain = np.asarray(rainfall_mm, dtype=float)
    m = np.asarray(mask, dtype=bool)
    area = np.asarray(cell_area_km2, dtype=float)
    if rain.shape != m.shape or rain.shape != area.shape:
        raise ValueError("rainfall, mask and area grids must share one shape")
    if np.any(~np.isfinite(rain)) or np.any(rain < 0.0):
        raise ValueError("rainfall grid contains invalid values")
    if np.any(~np.isfinite(area)) or np.any(area <= 0.0):
        raise ValueError("cell-area grid contains invalid values")
    return rain[m], area[m]
