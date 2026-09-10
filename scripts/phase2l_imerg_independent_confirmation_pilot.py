#!/usr/bin/env python3
"""Phase 2L-C IMERG independent-confirmation pilot.

CMORPH has already selected the candidate reservoir. This script never uses IMERG
for candidate selection. It downloads a small fixed set of IMERG Final V07 daily
granules and computes source-native rainfall summaries in the same frozen matched
windows (JMA primary-subdivision bbox + 0.5 degree padding).
"""
from __future__ import annotations

import argparse, csv, json, os, shutil, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from netCDF4 import Dataset

from lpz_risk.historical_spatial import build_primary_subdivision_geojson

PADDING_DEG = 0.5
JAPAN_BBOX = (122.0, 24.0, 150.0, 47.0)
DEFAULT_DATES = ["2023-05-07", "2023-07-10", "2024-04-08", "2024-08-29"]


def _login(tries: int = 5):
    import earthaccess
    last = None
    for i in range(tries):
        try:
            return earthaccess.login(strategy="environment")
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i + 1 < tries:
                time.sleep(10 * (i + 1))
    raise RuntimeError(f"Earthdata login failed after {tries} attempts: {type(last).__name__}: {last}")


def _download_imerg_day(date_s: str, dest: Path) -> Path:
    import earthaccess
    dt = datetime.strptime(date_s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    last = None
    for i in range(5):
        try:
            granules = earthaccess.search_data(
                short_name="GPM_3IMERGDF",
                version="07",
                bounding_box=JAPAN_BBOX,
                temporal=(dt.isoformat(), dt.replace(hour=23, minute=59, second=59).isoformat()),
                count=5,
            )
            if len(granules) != 1:
                raise RuntimeError(f"expected one IMERG daily granule for {date_s}, got {len(granules)}")
            paths = earthaccess.download(granules, str(dest), threads=1)
            if len(paths) != 1:
                raise RuntimeError(f"IMERG download count mismatch for {date_s}: {paths}")
            p = Path(paths[0])
            if not p.exists() or p.stat().st_size < 1024:
                raise RuntimeError(f"IMERG payload invalid for {date_s}: {p}")
            return p
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i + 1 < 5:
                time.sleep(15 * (i + 1))
    raise RuntimeError(f"IMERG day failed {date_s}: {type(last).__name__}: {last}")


def _get(url: str, dst: Path, tries: int = 5) -> None:
    last = None
    for i in range(tries):
        try:
            req = Request(url, headers={"User-Agent": "lpz-risk-system/0.1 phase2l-imerg-confirmation"})
            with urlopen(req, timeout=180) as r, dst.open("wb") as f:
                shutil.copyfileobj(r, f)
            if dst.stat().st_size < 1024:
                raise ValueError("payload too small")
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            dst.unlink(missing_ok=True)
            if i + 1 < tries:
                time.sleep(5 * (i + 1))
    raise RuntimeError(f"download failed {url}: {type(last).__name__}: {last}")


def _geometry_points(g):
    kind = g.get("type")
    if kind == "Polygon":
        for ring in g.get("coordinates") or []:
            for p in ring:
                yield float(p[0]), float(p[1])
    elif kind == "MultiPolygon":
        for poly in g.get("coordinates") or []:
            for ring in poly:
                for p in ring:
                    yield float(p[0]), float(p[1])
    elif kind == "GeometryCollection":
        for part in g.get("geometries") or []:
            yield from _geometry_points(part)
    else:
        raise ValueError(f"unsupported geometry type {kind!r}")


def _matched_window(g):
    pts = list(_geometry_points(g)); xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    return (
        max(JAPAN_BBOX[0], x0 - PADDING_DEG),
        max(JAPAN_BBOX[1], y0 - PADDING_DEG),
        min(JAPAN_BBOX[2], x1 + PADDING_DEG),
        min(JAPAN_BBOX[3], y1 + PADDING_DEG),
    )


def _read_reservoir(path: Path, dates: set[str]):
    by_date: dict[str, list[dict]] = {d: [] for d in dates}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["date_utc"] in dates:
                by_date[row["date_utc"]].append(row)
    missing = [d for d, rows in by_date.items() if not rows]
    if missing:
        raise ValueError(f"pilot dates absent from frozen CMORPH reservoir: {missing}")
    return by_date


def _imerg_grid(path: Path):
    with Dataset(path) as ds:
        lon = np.asarray(ds.variables["lon"][:], dtype=float).squeeze()
        lat = np.asarray(ds.variables["lat"][:], dtype=float).squeeze()
        rain = np.ma.asarray(ds.variables["precipitation"][:]).squeeze()
    if rain.shape == (lon.size, lat.size):
        rain = rain.T
    elif rain.shape != (lat.size, lon.size):
        raise ValueError(f"IMERG precipitation shape mismatch {rain.shape} vs lat={lat.size} lon={lon.size}")
    lon = ((lon + 180.0) % 360.0) - 180.0
    return lat, lon, rain


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reservoir", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--dates", nargs="*", default=DEFAULT_DATES)
    ap.add_argument("--gis-config", default="config/jma_primary_subdivision_gis.json")
    ap.add_argument("--era5-config", default="config/historical_environment_era5.json")
    a = ap.parse_args()

    dates = list(dict.fromkeys(a.dates))
    if not dates or any(not (d.startswith("2023-") or d.startswith("2024-")) for d in dates):
        raise ValueError("Development 2023-2024 pilot dates required")
    by_date = _read_reservoir(Path(a.reservoir), set(dates))
    codes = {r["primary_subdivision_code"] for rows in by_date.values() for r in rows}

    era5 = json.loads(Path(a.era5_config).read_text(encoding="utf-8"))
    if float(era5["spatial_sampling"]["bbox_padding_degrees"]) != PADDING_DEG:
        raise ValueError("frozen ERA5 bbox padding mismatch")
    gis_cfg = json.loads(Path(a.gis_config).read_text(encoding="utf-8"))

    out = Path(a.output_dir); out.mkdir(parents=True, exist_ok=True)
    rows_out = []; total_bytes = 0
    _login()
    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        jzip = td / "jma.zip"; _get(gis_cfg["zip_url"], jzip)
        geo = build_primary_subdivision_geojson(jzip.read_bytes(), codes)
        if not geo.get("geometry_complete_for_required_codes"):
            raise RuntimeError(f"missing JMA geometries: {geo.get('missing_required_codes')}")
        feats = {str(f["properties"]["primary_subdivision_code"]): f["geometry"] for f in geo["features"]}
        windows = {c: _matched_window(feats[c]) for c in codes}

        for date_s in dates:
            daydir = td / date_s; daydir.mkdir()
            fp = _download_imerg_day(date_s, daydir); total_bytes += fp.stat().st_size
            lat, lon, rain = _imerg_grid(fp)
            for c_row in by_date[date_s]:
                code = c_row["primary_subdivision_code"]
                x0, y0, x1, y1 = windows[code]
                iy = np.where((lat >= y0) & (lat <= y1))[0]
                ix = np.where((lon >= x0) & (lon <= x1))[0]
                sub = np.ma.asarray(rain[np.ix_(iy, ix)])
                vals = np.asarray(sub.compressed(), dtype=float)
                vals = vals[np.isfinite(vals) & (vals >= 0)]
                if vals.size == 0:
                    raise RuntimeError(f"no valid IMERG cells: {date_s} {code}")
                rows_out.append({
                    "date_utc": date_s,
                    "primary_subdivision_code": code,
                    "cmorph_rain_max_mm_day": c_row["rain_max_mm_day"],
                    "cmorph_rain_p90_mm_day": c_row["rain_p90_mm_day"],
                    "cmorph_rain_p95_mm_day": c_row["rain_p95_mm_day"],
                    "imerg_grid_cell_count": int(iy.size * ix.size),
                    "imerg_valid_rain_cell_count": int(vals.size),
                    "imerg_rain_mean_mm_day": float(vals.mean()),
                    "imerg_rain_max_mm_day": float(vals.max()),
                    "imerg_rain_p90_mm_day": float(np.percentile(vals, 90)),
                    "imerg_rain_p95_mm_day": float(np.percentile(vals, 95)),
                })

    csv_path = out / "phase2l_imerg_independent_confirmation_pilot.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0])); w.writeheader(); w.writerows(rows_out)
    report = {
        "schema_version": "1.0.0",
        "phase": "2L-C-imerg-independent-confirmation-pilot",
        "split": "DEVELOPMENT",
        "pilot_dates": dates,
        "pilot_date_count": len(dates),
        "candidate_region_day_count": len(rows_out),
        "source_id": "NASA_IMERG_FINAL_V07_DAILY",
        "short_name": "GPM_3IMERGDF",
        "matched_window_semantics": "OFFICIAL_JMA_PRIMARY_SUBDIVISION_GEOMETRY_BBOX_PLUS_FROZEN_ERA5_0P5_DEG_PADDING",
        "downloaded_bytes": total_bytes,
        "cmorph_selected_candidates": True,
        "imerg_used_for_candidate_selection": False,
        "imerg_role": "INDEPENDENT_SOURCE_NATIVE_CONFIRMATION_ONLY",
        "source_fusion_used": False,
        "hard_negative_label": None,
        "environment_variables_used": False,
        "gsmap_used_for_discovery": False,
        "validation_data_used": False,
        "retrospective_2026_used": False,
        "prospective_holdout_used": False,
        "risk_engine_allowed": False,
        "gate": "PASS_IMERG_INDEPENDENT_CONFIRMATION_PILOT",
    }
    (out / "phase2l_imerg_independent_confirmation_pilot.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
