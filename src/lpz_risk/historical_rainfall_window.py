"""Exact source-native historical rainfall windows and polygon descriptors.

This layer integrates already-decoded CanonicalRainfallField objects without
resampling or mixing providers. It is descriptive research infrastructure only:
no LPZ class, hard-negative label, candidate threshold, or risk score is assigned.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import numpy as np

from .canonical_rainfall import CanonicalRainfallField
from .historical_polygon import mask_grid_centres, spherical_latlon_cell_areas_km2


@dataclass(frozen=True)
class AccumulatedRainfallWindow:
    source_id: str
    product_version: str
    valid_start_utc: datetime
    valid_end_utc: datetime
    accumulation_seconds: int
    accumulation_mm: np.ndarray
    longitude_deg_e: np.ndarray
    latitude_deg_n: np.ndarray
    native_field_count: int
    source_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        rain = np.asarray(self.accumulation_mm, dtype=float)
        lon = np.asarray(self.longitude_deg_e, dtype=float)
        lat = np.asarray(self.latitude_deg_n, dtype=float)
        if self.valid_start_utc.tzinfo is None or self.valid_end_utc.tzinfo is None:
            raise ValueError("window times must be timezone-aware")
        if self.valid_end_utc <= self.valid_start_utc:
            raise ValueError("window end must be after start")
        expected = int((self.valid_end_utc - self.valid_start_utc).total_seconds())
        if expected != self.accumulation_seconds:
            raise ValueError("window accumulation_seconds does not match validity interval")
        if rain.shape != (lat.size, lon.size) or rain.ndim != 2:
            raise ValueError("accumulation shape must be (latitude, longitude)")
        finite = np.isfinite(rain)
        if np.any(rain[finite] < 0.0):
            raise ValueError("finite accumulated rainfall must be non-negative")
        if self.native_field_count <= 0 or len(self.source_paths) != self.native_field_count:
            raise ValueError("native field provenance is incomplete")

    def descriptor(self) -> dict[str, Any]:
        arr = np.asarray(self.accumulation_mm, dtype=float)
        finite = arr[np.isfinite(arr)]
        return {
            "schema_version": "0.1.0",
            "entity_type": "ACCUMULATED_RAINFALL_WINDOW",
            "source_id": self.source_id,
            "product_version": self.product_version,
            "valid_start_utc": self.valid_start_utc.astimezone(timezone.utc).isoformat(),
            "valid_end_utc": self.valid_end_utc.astimezone(timezone.utc).isoformat(),
            "accumulation_seconds": self.accumulation_seconds,
            "native_field_count": self.native_field_count,
            "grid_shape": list(arr.shape),
            "finite_count": int(finite.size),
            "missing_count": int(arr.size - finite.size),
            "max_accumulation_mm": None if not finite.size else float(finite.max()),
            "mean_accumulation_mm": None if not finite.size else float(finite.mean()),
            "source_paths": list(self.source_paths),
            "cross_source_averaging_performed": False,
            "hard_negative_label": None,
            "lpz_classification": None,
            "risk_score": None,
            "risk_engine_allowed": False,
        }


def build_exact_accumulation_window(
    fields: Iterable[CanonicalRainfallField],
    *,
    target_seconds: int = 10_800,
) -> AccumulatedRainfallWindow:
    """Build one exact consecutive source-native accumulation window.

    Missing native cells propagate to the accumulated field through ordinary
    NumPy NaN arithmetic. No interpolation, temporal resampling, or provider
    substitution is permitted.
    """
    ordered = sorted(list(fields), key=lambda f: f.valid_start_utc)
    if not ordered:
        raise ValueError("at least one canonical rainfall field is required")
    if target_seconds <= 0:
        raise ValueError("target_seconds must be positive")

    first = ordered[0]
    source = first.source_id
    version = first.product_version
    lon0 = np.asarray(first.longitude_deg_e, dtype=float)
    lat0 = np.asarray(first.latitude_deg_n, dtype=float)

    total_seconds = 0
    pieces: list[np.ndarray] = []
    for i, field in enumerate(ordered):
        if field.source_id != source:
            raise ValueError("cross-source accumulation is prohibited")
        if field.product_version != version:
            raise ValueError("cross-version accumulation is prohibited")
        if i and ordered[i - 1].valid_end_utc != field.valid_start_utc:
            raise ValueError("native validity intervals must be exactly consecutive")
        if not np.array_equal(np.asarray(field.longitude_deg_e, dtype=float), lon0):
            raise ValueError("longitude grid changed within accumulation window")
        if not np.array_equal(np.asarray(field.latitude_deg_n, dtype=float), lat0):
            raise ValueError("latitude grid changed within accumulation window")
        total_seconds += int(field.accumulation_seconds)
        pieces.append(field.accumulation_mm)

    if total_seconds != target_seconds:
        raise ValueError(f"exact target duration required: {total_seconds} != {target_seconds}")
    if int((ordered[-1].valid_end_utc - ordered[0].valid_start_utc).total_seconds()) != target_seconds:
        raise ValueError("elapsed validity span does not equal target duration")

    accumulation = np.sum(np.stack(pieces, axis=0), axis=0)
    return AccumulatedRainfallWindow(
        source_id=source,
        product_version=version,
        valid_start_utc=ordered[0].valid_start_utc,
        valid_end_utc=ordered[-1].valid_end_utc,
        accumulation_seconds=target_seconds,
        accumulation_mm=accumulation,
        longitude_deg_e=lon0.copy(),
        latitude_deg_n=lat0.copy(),
        native_field_count=len(ordered),
        source_paths=tuple(f.source_path for f in ordered),
    )


def _feature_geometry(feature: dict[str, Any], primary_subdivision_code: str) -> dict[str, Any]:
    props = feature.get("properties") or {}
    code = str(props.get("primary_subdivision_code", feature.get("id", "")))
    if code != str(primary_subdivision_code):
        raise ValueError(f"polygon feature code mismatch: {code} != {primary_subdivision_code}")
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        raise ValueError("polygon feature has no geometry")
    return geometry


def _geometry_bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return lon/lat bbox for Polygon/MultiPolygon/GeometryCollection."""
    points: list[tuple[float, float]] = []

    def collect(g: dict[str, Any]) -> None:
        kind = g.get("type")
        if kind == "GeometryCollection":
            for child in g.get("geometries") or []:
                collect(child)
            return
        if kind not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"unsupported GeoJSON geometry type: {kind!r}")

        def walk(node: Any) -> None:
            if isinstance(node, (list, tuple)) and len(node) >= 2 and all(isinstance(x, (int, float)) for x in node[:2]):
                points.append((float(node[0]), float(node[1])))
                return
            if isinstance(node, (list, tuple)):
                for child in node:
                    walk(child)

        walk(g.get("coordinates") or [])

    collect(geometry)
    if not points:
        raise ValueError("official polygon geometry contains no coordinate points")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _polygon_grid_subset(
    lon: np.ndarray,
    lat: np.ndarray,
    rain: np.ndarray,
    geometry: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bbox-prefilter a regular grid before exact centre-in-polygon masking.

    The bbox is only a computational prefilter. Final membership remains the
    frozen GRID_CELL_CENTRE_INSIDE_OFFICIAL_POLYGON rule.
    """
    xmin, ymin, xmax, ymax = _geometry_bbox(geometry)
    lon_idx = np.where((lon >= xmin) & (lon <= xmax))[0]
    lat_idx = np.where((lat >= ymin) & (lat <= ymax))[0]
    if not lon_idx.size or not lat_idx.size:
        raise ValueError("official polygon bbox does not intersect rainfall grid centres")
    sub_lon = lon[lon_idx]
    sub_lat = lat[lat_idx]
    sub_rain = rain[np.ix_(lat_idx, lon_idx)]
    return sub_lon, sub_lat, sub_rain


def build_subdivision_window_descriptor(
    window: AccumulatedRainfallWindow,
    *,
    primary_subdivision_code: str,
    polygon_feature: dict[str, Any],
    descriptive_thresholds_mm: Iterable[float] | None = None,
) -> dict[str, Any]:
    """Describe rainfall inside one official primary-subdivision polygon.

    Thresholds are optional and descriptive. This function never decides which
    threshold should define a heavy-rain candidate; that is a separate
    Development-only calibration decision.
    """
    geometry = _feature_geometry(polygon_feature, primary_subdivision_code)
    lon = np.asarray(window.longitude_deg_e, dtype=float)
    lat = np.asarray(window.latitude_deg_n, dtype=float)
    rain = np.asarray(window.accumulation_mm, dtype=float)

    sub_lon, sub_lat, sub_rain = _polygon_grid_subset(lon, lat, rain, geometry)
    lon2d, lat2d = np.meshgrid(sub_lon, sub_lat)
    mask = mask_grid_centres(lat2d, lon2d, geometry)
    if not np.any(mask):
        raise ValueError("official polygon contains no grid-cell centres for this product")

    # Computing areas from the bbox-subset centres is exact for these regular
    # source grids because cell spacing is unchanged by slicing.
    area = spherical_latlon_cell_areas_km2(sub_lat, sub_lon)
    region_values = sub_rain[mask]
    region_areas = area[mask]
    finite = np.isfinite(region_values)
    finite_values = region_values[finite]
    finite_areas = region_areas[finite]
    if not finite_values.size:
        raise ValueError("all rainfall cells inside official polygon are missing")

    thresholds: list[dict[str, Any]] = []
    for raw_threshold in descriptive_thresholds_mm or ():
        threshold = float(raw_threshold)
        if threshold <= 0.0 or not np.isfinite(threshold):
            raise ValueError("descriptive thresholds must be finite and positive")
        hit = finite_values >= threshold
        thresholds.append({
            "threshold_mm": threshold,
            "finite_cell_count_ge_threshold": int(np.count_nonzero(hit)),
            "finite_area_km2_ge_threshold": float(finite_areas[hit].sum()),
            "fraction_of_finite_cells_ge_threshold": float(np.mean(hit)),
        })

    return {
        "schema_version": "0.2.0",
        "entity_type": "PRIMARY_SUBDIVISION_RAINFALL_WINDOW_DESCRIPTOR",
        "source_id": window.source_id,
        "product_version": window.product_version,
        "primary_subdivision_code": str(primary_subdivision_code),
        "valid_start_utc": window.valid_start_utc.astimezone(timezone.utc).isoformat(),
        "valid_end_utc": window.valid_end_utc.astimezone(timezone.utc).isoformat(),
        "accumulation_seconds": window.accumulation_seconds,
        "native_field_count": window.native_field_count,
        "mask_semantics": "GRID_CELL_CENTRE_INSIDE_OFFICIAL_POLYGON",
        "bbox_prefilter_only": True,
        "bbox_prefilter_grid_shape": [int(sub_lat.size), int(sub_lon.size)],
        "polygon_grid_cell_count": int(np.count_nonzero(mask)),
        "finite_grid_cell_count": int(finite_values.size),
        "missing_grid_cell_count": int(region_values.size - finite_values.size),
        "finite_coverage_fraction": float(finite_values.size / region_values.size),
        "finite_polygon_area_km2": float(finite_areas.sum()),
        "max_accumulation_mm": float(np.max(finite_values)),
        "mean_accumulation_mm": float(np.mean(finite_values)),
        "p90_accumulation_mm": float(np.percentile(finite_values, 90)),
        "p95_accumulation_mm": float(np.percentile(finite_values, 95)),
        "p99_accumulation_mm": float(np.percentile(finite_values, 99)),
        "descriptive_thresholds": thresholds,
        "candidate_threshold_selected": False,
        "hard_negative_label": None,
        "lpz_classification": None,
        "risk_score": None,
        "risk_engine_allowed": False,
    }
