#!/usr/bin/env python3
"""Phase 2L-C preflight: audit CMORPH 0.25deg coverage for frozen Development LPZ regions.

One-day geometry adequacy proof only. No threshold selection, candidate generation,
classification, source fusion, or risk scoring.
"""
from __future__ import annotations

import argparse, json, shutil, tempfile, time
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from netCDF4 import Dataset

from lpz_risk.historical_polygon import mask_grid_centres, spherical_latlon_cell_areas_km2
from lpz_risk.historical_spatial import build_primary_subdivision_geojson

CMORPH_ROOT = "https://noaa-cdr-precip-cmorph-pds.s3.amazonaws.com"
UA = "lpz-risk-system/0.1 phase2l-spatial-coverage-proof"
BBOX = (122.0, 24.0, 150.0, 47.0)


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
        except Exception as exc:
            last = exc
            if dst.exists(): dst.unlink()
            if i + 1 < tries: time.sleep(5 * (i + 1))
    raise RuntimeError(f"download failed {url}: {type(last).__name__}: {last}")


def _required_codes(phase2k: dict) -> set[str]:
    rows = phase2k.get("episode_rows") or []
    if phase2k.get("gate") != "PASS_COMPLETE_DEVELOPMENT_POSITIVE_ENVIRONMENT_BASELINE" or len(rows) != 65:
        raise ValueError("Phase 2K baseline is not frozen complete 65-episode Development data")
    codes = {str(r["primary_subdivision_code"]) for r in rows}
    if len(codes) != 58:
        raise ValueError(f"expected 58 Development primary-subdivision codes, got {len(codes)}")
    return codes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase2k", required=True)
    ap.add_argument("--gis-config", default="config/jma_primary_subdivision_gis.json")
    ap.add_argument("--date", default="2023-07-10")
    ap.add_argument("--output", required=True)
    a = ap.parse_args()

    phase2k = json.loads(Path(a.phase2k).read_text(encoding="utf-8"))
    cfg = json.loads(Path(a.gis_config).read_text(encoding="utf-8"))
    codes = _required_codes(phase2k)
    y, m, d = map(int, a.date.split("-"))
    if y not in (2023, 2024):
        raise ValueError("Development-only date required")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        gis_zip = td / "jma_primary.zip"
        _get(cfg["zip_url"], gis_zip)
        geo = build_primary_subdivision_geojson(gis_zip.read_bytes(), codes)
        if not geo.get("geometry_complete_for_required_codes"):
            raise RuntimeError(f"missing JMA geometries: {geo.get('missing_required_codes')}")

        key = f"data/daily/0.25deg/{y:04d}/{m:02d}/CMORPH_V1.0_ADJ_0.25deg-DLY_00Z_{y:04d}{m:02d}{d:02d}.nc"
        rain_path = td / "cmorph.nc"
        _get(f"{CMORPH_ROOT}/{key}", rain_path)

        with Dataset(rain_path) as ds:
            lat = np.asarray(ds.variables["lat"][:], dtype=float).squeeze()
            lon = np.asarray(ds.variables["lon"][:], dtype=float).squeeze()
            rain = np.ma.asarray(ds.variables["cmorph"][:]).squeeze()
            if rain.shape == (lon.size, lat.size): rain = rain.T
            if rain.shape != (lat.size, lon.size):
                raise ValueError(f"CMORPH shape mismatch {rain.shape} vs {(lat.size,lon.size)}")
            lon_signed = ((lon + 180.0) % 360.0) - 180.0
            lm = (lat >= BBOX[1]) & (lat <= BBOX[3])
            xm = (lon_signed >= BBOX[0]) & (lon_signed <= BBOX[2])
            lat_sub = lat[lm]
            lon_sub = lon_signed[xm]
            rain_sub = np.ma.asarray(rain[np.ix_(lm, xm)])

        lon2d, lat2d = np.meshgrid(lon_sub, lat_sub)
        areas = spherical_latlon_cell_areas_km2(lat_sub, lon_sub)
        features = {str(f["properties"]["primary_subdivision_code"]): f["geometry"] for f in geo["features"]}
        rows = []
        for code in sorted(codes):
            mask = mask_grid_centres(lat2d, lon2d, features[code])
            cell_count = int(mask.sum())
            vals = np.asarray(rain_sub[mask].compressed(), dtype=float) if cell_count else np.asarray([], dtype=float)
            vals = vals[np.isfinite(vals)]
            vals = vals[vals >= 0]
            rows.append({
                "primary_subdivision_code": code,
                "grid_cell_count": cell_count,
                "valid_rain_cell_count": int(vals.size),
                "represented_grid_area_km2": float(areas[mask].sum()) if cell_count else 0.0,
                "rain_mean_mm_day": float(vals.mean()) if vals.size else None,
                "rain_max_mm_day": float(vals.max()) if vals.size else None,
            })

    zero = [r["primary_subdivision_code"] for r in rows if r["grid_cell_count"] == 0]
    lt4 = [r["primary_subdivision_code"] for r in rows if r["grid_cell_count"] < 4]
    lt8 = [r["primary_subdivision_code"] for r in rows if r["grid_cell_count"] < 8]
    counts = [r["grid_cell_count"] for r in rows]
    gate = "PASS_CMORPH_SPATIAL_COVERAGE_NO_ZERO_CELL_REGIONS" if not zero else "FAIL_CMORPH_ZERO_CELL_REGION"
    report = {
        "schema_version": "1.0.0",
        "phase": "2L-C-cmorph-spatial-coverage-proof",
        "split": "DEVELOPMENT",
        "proof_date_utc": a.date,
        "source_id": "NOAA_CMORPH_CDR_DAILY_0P25DEG",
        "source_locator": key,
        "geometry_source": "JMA_OFFICIAL_PRIMARY_SUBDIVISION_POLYGON",
        "mask_semantics": "GRID_CELL_CENTRE_INSIDE_OFFICIAL_POLYGON",
        "required_region_count": 58,
        "resolved_region_count": len(rows),
        "minimum_grid_cell_count": int(min(counts)),
        "median_grid_cell_count": float(np.median(counts)),
        "maximum_grid_cell_count": int(max(counts)),
        "zero_cell_region_codes": zero,
        "lt4_cell_region_codes": lt4,
        "lt8_cell_region_codes": lt8,
        "region_rows": rows,
        "coverage_interpretation": "This audits coarse daily screening adequacy only; it does not validate 3h morphology or final rainfall matching.",
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
    out = Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate, "min_cells": min(counts), "median_cells": np.median(counts), "lt4": len(lt4), "lt8": len(lt8)}, ensure_ascii=False))
    return 0 if gate.startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
