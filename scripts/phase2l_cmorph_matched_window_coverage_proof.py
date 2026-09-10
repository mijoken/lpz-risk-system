#!/usr/bin/env python3
"""Phase 2L-C matched-window coverage proof for CMORPH daily 0.25deg.

Uses the already-frozen ERA5 spatial retrieval semantics: official JMA primary-
subdivision geometry bounding box plus 0.5 degree padding. This is a coarse,
recall-oriented screening window only. It is not a final rainfall-matching or
LPZ classification region.

No threshold selection, candidate generation, source fusion, or risk scoring.
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from netCDF4 import Dataset

from lpz_risk.historical_spatial import build_primary_subdivision_geojson

CMORPH_ROOT = "https://noaa-cdr-precip-cmorph-pds.s3.amazonaws.com"
UA = "lpz-risk-system/0.1 phase2l-matched-window-coverage-proof"
JAPAN_BBOX = (122.0, 24.0, 150.0, 47.0)
PADDING_DEG = 0.5
MIN_CELLS_PREDECLARED = 16


def _get(url: str, dst: Path, tries: int = 4) -> None:
    last = None
    for i in range(tries):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=180) as r, dst.open("wb") as f:
                shutil.copyfileobj(r, f)
            if dst.stat().st_size < 1024:
                raise ValueError("payload too small")
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            if dst.exists():
                dst.unlink()
            if i + 1 < tries:
                time.sleep(5 * (i + 1))
    raise RuntimeError(f"download failed {url}: {type(last).__name__}: {last}")


def _required_codes(phase2k: dict) -> set[str]:
    rows = phase2k.get("episode_rows") or []
    if phase2k.get("gate") != "PASS_COMPLETE_DEVELOPMENT_POSITIVE_ENVIRONMENT_BASELINE" or len(rows) != 65:
        raise ValueError("Phase 2K baseline is not frozen complete 65-episode Development data")
    codes = {str(r["primary_subdivision_code"]) for r in rows}
    if not codes:
        raise ValueError("no Development primary-subdivision codes found")
    return codes


def _geometry_points(geometry: dict):
    kind = geometry.get("type")
    if kind == "Polygon":
        for ring in geometry.get("coordinates") or []:
            for p in ring:
                yield float(p[0]), float(p[1])
        return
    if kind == "MultiPolygon":
        for polygon in geometry.get("coordinates") or []:
            for ring in polygon:
                for p in ring:
                    yield float(p[0]), float(p[1])
        return
    if kind == "GeometryCollection":
        for part in geometry.get("geometries") or []:
            yield from _geometry_points(part)
        return
    raise ValueError(f"unsupported geometry type: {kind!r}")


def _geometry_bbox(geometry: dict) -> tuple[float, float, float, float]:
    pts = list(_geometry_points(geometry))
    if not pts:
        raise ValueError("geometry contains no coordinate points")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _clamp_bbox(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    xmin, ymin, xmax, ymax = bbox
    return (
        max(JAPAN_BBOX[0], xmin),
        max(JAPAN_BBOX[1], ymin),
        min(JAPAN_BBOX[2], xmax),
        min(JAPAN_BBOX[3], ymax),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase2k", required=True)
    ap.add_argument("--era5-config", default="config/historical_environment_era5.json")
    ap.add_argument("--gis-config", default="config/jma_primary_subdivision_gis.json")
    ap.add_argument("--date", default="2023-07-10")
    ap.add_argument("--output", required=True)
    a = ap.parse_args()

    phase2k = json.loads(Path(a.phase2k).read_text(encoding="utf-8"))
    era5 = json.loads(Path(a.era5_config).read_text(encoding="utf-8"))
    gis_cfg = json.loads(Path(a.gis_config).read_text(encoding="utf-8"))
    codes = _required_codes(phase2k)

    frozen_padding = float(era5["spatial_sampling"]["bbox_padding_degrees"])
    if frozen_padding != PADDING_DEG:
        raise ValueError(f"expected frozen ERA5 bbox padding {PADDING_DEG}, got {frozen_padding}")

    y, m, d = map(int, a.date.split("-"))
    if y not in (2023, 2024):
        raise ValueError("Development-only proof date required")

    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        gis_zip = td / "jma_primary.zip"
        _get(gis_cfg["zip_url"], gis_zip)
        geo = build_primary_subdivision_geojson(gis_zip.read_bytes(), codes)
        if not geo.get("geometry_complete_for_required_codes"):
            raise RuntimeError(f"missing JMA geometries: {geo.get('missing_required_codes')}")
        features = {
            str(f["properties"]["primary_subdivision_code"]): f["geometry"]
            for f in geo["features"]
        }

        key = f"data/daily/0.25deg/{y:04d}/{m:02d}/CMORPH_V1.0_ADJ_0.25deg-DLY_00Z_{y:04d}{m:02d}{d:02d}.nc"
        rain_path = td / "cmorph.nc"
        _get(f"{CMORPH_ROOT}/{key}", rain_path)

        with Dataset(rain_path) as ds:
            lat = np.asarray(ds.variables["lat"][:], dtype=float).squeeze()
            lon = np.asarray(ds.variables["lon"][:], dtype=float).squeeze()
            rain = np.ma.asarray(ds.variables["cmorph"][:]).squeeze()
            if rain.shape == (lon.size, lat.size):
                rain = rain.T
            if rain.shape != (lat.size, lon.size):
                raise ValueError(f"CMORPH shape mismatch {rain.shape} vs {(lat.size, lon.size)}")
            lon_signed = ((lon + 180.0) % 360.0) - 180.0

        rows = []
        for code in sorted(codes):
            xmin, ymin, xmax, ymax = _geometry_bbox(features[code])
            matched = _clamp_bbox((
                xmin - PADDING_DEG,
                ymin - PADDING_DEG,
                xmax + PADDING_DEG,
                ymax + PADDING_DEG,
            ))
            mx0, my0, mx1, my1 = matched
            iy = np.where((lat >= my0) & (lat <= my1))[0]
            ix = np.where((lon_signed >= mx0) & (lon_signed <= mx1))[0]
            cell_count = int(iy.size * ix.size)
            vals = np.asarray([], dtype=float)
            if cell_count:
                sub = np.ma.asarray(rain[np.ix_(iy, ix)])
                vals = np.asarray(sub.compressed(), dtype=float)
                vals = vals[np.isfinite(vals)]
                vals = vals[vals >= 0]
            rows.append({
                "primary_subdivision_code": code,
                "official_geometry_bbox": [xmin, ymin, xmax, ymax],
                "matched_window_bbox": [mx0, my0, mx1, my1],
                "grid_cell_count": cell_count,
                "valid_rain_cell_count": int(vals.size),
                "rain_mean_mm_day": float(vals.mean()) if vals.size else None,
                "rain_max_mm_day": float(vals.max()) if vals.size else None,
                "rain_p90_mm_day": float(np.percentile(vals, 90)) if vals.size else None,
                "rain_p95_mm_day": float(np.percentile(vals, 95)) if vals.size else None,
            })

    counts = [r["grid_cell_count"] for r in rows]
    below = [r["primary_subdivision_code"] for r in rows if r["grid_cell_count"] < MIN_CELLS_PREDECLARED]
    zero = [r["primary_subdivision_code"] for r in rows if r["grid_cell_count"] == 0]
    gate = (
        "PASS_CMORPH_MATCHED_WINDOW_COVERAGE_MIN16"
        if not below
        else "FAIL_CMORPH_MATCHED_WINDOW_COVERAGE_BELOW_MIN16"
    )

    report = {
        "schema_version": "1.0.0",
        "phase": "2L-C-cmorph-matched-window-coverage-proof",
        "split": "DEVELOPMENT",
        "proof_date_utc": a.date,
        "source_id": "NOAA_CMORPH_CDR_DAILY_0P25DEG",
        "source_locator": key,
        "matched_window_semantics": "OFFICIAL_JMA_PRIMARY_SUBDIVISION_GEOMETRY_BBOX_PLUS_FROZEN_ERA5_0P5_DEG_PADDING",
        "padding_degrees": PADDING_DEG,
        "padding_source": "config/historical_environment_era5.json spatial_sampling.bbox_padding_degrees",
        "window_role": "COARSE_RECALL_ORIENTED_DAILY_SCREENING_ONLY",
        "final_3h_matching_role": False,
        "minimum_cells_predeclared": MIN_CELLS_PREDECLARED,
        "minimum_cells_reason": "At least a 4x4-equivalent CMORPH grid support is required before using mean/tail summaries for coarse region-day screening.",
        "required_region_count": len(codes),
        "required_region_count_semantics": "UNIQUE_PRIMARY_SUBDIVISIONS_PRESENT_IN_FROZEN_PHASE2K_DEVELOPMENT_65_EPISODES",
        "resolved_region_count": len(rows),
        "minimum_grid_cell_count": int(min(counts)),
        "median_grid_cell_count": float(np.median(counts)),
        "maximum_grid_cell_count": int(max(counts)),
        "below_minimum_region_codes": below,
        "zero_cell_region_codes": zero,
        "region_rows": rows,
        "threshold_selected": False,
        "candidate_generated": False,
        "hard_negative_label": None,
        "source_fusion_used": False,
        "gsmap_used_for_discovery": False,
        "validation_data_used": False,
        "retrospective_2026_used": False,
        "prospective_holdout_used": False,
        "risk_engine_allowed": False,
        "gate": gate,
    }
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "gate": gate,
        "regions": len(codes),
        "min_cells": min(counts),
        "median_cells": float(np.median(counts)),
        "max_cells": max(counts),
        "below_min16": len(below),
    }, ensure_ascii=False))
    return 0 if gate.startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
