#!/usr/bin/env python3
"""Spatial co-location audit: frozen F4 45-min swept source vs IMERG Late 3h.

Uses only the already-frozen pre-22:00 JST F4 source frames and independently
downloads the same six IMERG Late V07 half-hour granules used by the prior
three-hour audit. No F4-9C future observations, verification rows, forecasts,
cohort status, or F4-9D results are opened.

The comparison is deliberately coarse: F4 source-mask pixel centers are mapped
onto native 0.1-degree IMERG cells. This tests spatial co-location only; it is
NOT forecast verification and NOT an official JMA LPZ classification.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from scripts.audit_f4_20260921_45min_source_organization import _load_frames
from scripts.audit_f4_20260921_imerg_late_3h import (
    BBOX,
    EXPECTED,
    cell_area_km2,
    component_descriptor,
    components,
    decode,
    iso,
    subset,
)

TILE_SIZE = 256


def _f4_mask_lonlat(mask: np.ndarray, fixed: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    rows, cols = np.nonzero(mask)
    z = int(fixed["zoom"])
    world = TILE_SIZE * (2**z)
    gx = int(fixed["origin_tile_x"]) * TILE_SIZE + cols.astype(float) + 0.5
    gy = int(fixed["origin_tile_y"]) * TILE_SIZE + rows.astype(float) + 0.5
    lon = gx / world * 360.0 - 180.0
    merc = math.pi * (1.0 - 2.0 * gy / world)
    lat = np.degrees(np.arctan(np.sinh(merc)))
    return lon, lat


def _nearest_regular_grid_indices(grid: np.ndarray, values: np.ndarray) -> np.ndarray:
    grid = np.asarray(grid, dtype=float)
    if grid.ndim != 1 or grid.size < 2:
        raise ValueError("grid must be one-dimensional with >=2 coordinates")
    step = float(np.median(np.diff(grid)))
    if abs(step) <= 0:
        raise ValueError("grid step is zero")
    idx = np.rint((np.asarray(values, dtype=float) - float(grid[0])) / step).astype(int)
    idx = np.clip(idx, 0, grid.size - 1)
    return idx


def touched_native_cells(
    mask: np.ndarray,
    fixed: dict[str, Any],
    lon: np.ndarray,
    lat: np.ndarray,
) -> np.ndarray:
    x, y = _f4_mask_lonlat(mask, fixed)
    if x.size == 0:
        return np.asarray([], dtype=np.int64)
    xi = _nearest_regular_grid_indices(lon, x)
    yi = _nearest_regular_grid_indices(lat, y)
    return np.unique(yi.astype(np.int64) * int(lon.size) + xi.astype(np.int64))


def _area_for_flat(flat: np.ndarray, lon: np.ndarray, lat: np.ndarray) -> float:
    if flat.size == 0:
        return 0.0
    rr, _ = np.divmod(flat.astype(np.int64), int(lon.size))
    dlat = float(np.median(np.abs(np.diff(lat))))
    dlon = float(np.median(np.abs(np.diff(lon))))
    return float(sum(cell_area_km2(float(lat[r]), dlat, dlon) for r in rr))


def overlap_summary(
    accum: np.ndarray,
    lon: np.ndarray,
    lat: np.ndarray,
    touched: np.ndarray,
) -> dict[str, Any]:
    flat_accum = accum.reshape(-1)
    if touched.size == 0:
        return {"touched_native_cell_count": 0}
    values = flat_accum[touched]
    valid = np.isfinite(values)
    valid_touched = touched[valid]
    valid_values = values[valid]
    out = {
        "touched_native_cell_count": int(touched.size),
        "valid_touched_native_cell_count": int(valid_values.size),
        "invalid_touched_native_cell_count": int(touched.size - valid_values.size),
    }
    if not valid_values.size:
        return out
    out.update({
        "accumulation_mm_min": round(float(np.min(valid_values)), 2),
        "accumulation_mm_median": round(float(np.median(valid_values)), 2),
        "accumulation_mm_p90": round(float(np.percentile(valid_values, 90)), 2),
        "accumulation_mm_max": round(float(np.max(valid_values)), 2),
    })
    thresholds = {}
    for threshold in (50.0, 80.0, 100.0, 150.0):
        selected = valid_touched[valid_values >= threshold]
        thresholds[str(int(threshold))] = {
            "overlap_native_cell_count": int(selected.size),
            "overlap_native_area_km2": round(_area_for_flat(selected, lon, lat), 2),
            "fraction_of_valid_touched_cells": (
                round(float(selected.size / valid_values.size), 6)
                if valid_values.size else None
            ),
        }
    out["threshold_overlap"] = thresholds
    return out


def component_overlap(
    accum: np.ndarray,
    lon: np.ndarray,
    lat: np.ndarray,
    touched: np.ndarray,
    threshold: float,
) -> list[dict[str, Any]]:
    mask = np.isfinite(accum) & (accum >= threshold)
    touched_set = set(map(int, touched.tolist()))
    rows = []
    for pts in components(mask):
        flat = np.ravel_multi_index((pts[:, 0], pts[:, 1]), accum.shape).astype(np.int64)
        overlap = np.asarray([x for x in flat if int(x) in touched_set], dtype=np.int64)
        desc = component_descriptor(pts, lon, lat)
        desc.update({
            "f4_touched_native_cell_count": int(overlap.size),
            "f4_overlap_native_area_km2": round(_area_for_flat(overlap, lon, lat), 2),
            "spatially_intersects_f4_mask": bool(overlap.size),
        })
        rows.append(desc)
    return sorted(rows, key=lambda x: x["area_km2"], reverse=True)


def _download_accumulation() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]]]:
    if not os.environ.get("EARTHDATA_USERNAME") or not os.environ.get("EARTHDATA_PASSWORD"):
        raise RuntimeError("EARTHDATA_USERNAME/EARTHDATA_PASSWORD are required")
    import earthaccess
    auth = earthaccess.login(strategy="environment")
    if not auth.authenticated:
        raise RuntimeError("Earthdata authentication failed")
    granules = earthaccess.search_data(
        short_name="GPM_3IMERGHHL",
        version="07",
        bounding_box=BBOX,
        temporal=(iso(EXPECTED[0]), iso(EXPECTED[-1].replace(second=0) + __import__("datetime").timedelta(minutes=30, seconds=-1))),
        count=20,
    )
    if len(granules) < 6:
        raise RuntimeError(f"expected >=6 IMERG Late granules, found {len(granules)}")
    with tempfile.TemporaryDirectory(prefix="lpz-imerg-colocation-") as td:
        paths = [Path(p) for p in earthaccess.download(granules, td, threads=1)]
        rows = {}
        provenance = []
        for p in paths:
            try:
                start, rain, glon, glat, _ = decode(p)
            except Exception:
                continue
            if start not in EXPECTED:
                continue
            sub, lon, lat = subset(rain, glon, glat)
            if start in rows:
                raise ValueError(f"duplicate IMERG Late granule {iso(start)}")
            rows[start] = sub
            provenance.append({"start_utc": iso(start), "filename": p.name})
        missing = [x for x in EXPECTED if x not in rows]
        if missing:
            raise RuntimeError("missing exact granules: " + ",".join(iso(x) for x in missing))
        stack = np.stack([rows[x] for x in EXPECTED])
        complete = np.all(np.isfinite(stack), axis=0)
        accum = np.full(stack.shape[1:], np.nan, dtype=float)
        accum[complete] = np.sum(stack[:, complete] * 0.5, axis=0)
        return accum, lon, lat, sorted(provenance, key=lambda x: x["start_utc"])


def audit(cohort_root: Path, case_path: Path) -> dict[str, Any]:
    case = json.loads(case_path.read_text(encoding="utf-8"))
    if (
        case.get("product") != "F4_9C_PROSPECTIVE_CASE"
        or case.get("future_observations_read_at_capture") is not False
        or case.get("forecast_skill_scored_at_capture") is not False
        or case.get("risk_engine_allowed") is not False
    ):
        raise ValueError("frozen case source-only contract mismatch")

    _, stack, source_provenance = _load_frames(cohort_root, case)
    known_all = np.all(stack >= 0, axis=0)
    swept = known_all & np.any(stack >= 5, axis=0)
    latest = stack[-1] >= 5

    accum, lon, lat, imerg_provenance = _download_accumulation()
    swept_cells = touched_native_cells(swept, case["fixed_mosaic"], lon, lat)
    latest_cells = touched_native_cells(latest, case["fixed_mosaic"], lon, lat)
    comps50 = component_overlap(accum, lon, lat, swept_cells, 50.0)

    return {
        "audit_product": "F4_20260921_F4_IMERG_LATE_3H_SPATIAL_COLOCATION",
        "case_id": case["case_id"],
        "f4_window": {
            "start_utc": "2026-09-21T12:15:00Z",
            "end_utc": "2026-09-21T13:00:00Z",
            "source_frame_count": 10,
            "source_provenance": source_provenance,
        },
        "imerg_window": {
            "start_utc": iso(EXPECTED[0]),
            "end_utc": "2026-09-21T13:00:00Z",
            "granule_count": 6,
            "provenance": imerg_provenance,
        },
        "f4_45min_swept_union_vs_imerg_3h": overlap_summary(accum, lon, lat, swept_cells),
        "f4_2200_ge30_vs_imerg_3h": overlap_summary(accum, lon, lat, latest_cells),
        "imerg_ge50_components_with_f4_overlap": comps50,
        "interpretation_limits": [
            "Mapping is native IMERG 0.1-degree cell co-location, not JMA 5-km analyzed-rainfall geometry.",
            "F4 swept source is only 45 minutes; IMERG accumulation is three hours.",
            "Spatial overlap does not establish causality, object identity, genesis prediction, or forecast skill.",
            "No F4-9C future observations, verification rows, scores, or F4-9D decisions are read.",
        ],
        "read_f4_9c_verifications": False,
        "forecast_skill_scored": False,
        "risk_engine_allowed": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cohort-root", required=True, type=Path)
    ap.add_argument("--reference-case", required=True, type=Path)
    args = ap.parse_args()
    print(json.dumps(audit(args.cohort_root, args.reference_case), ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
