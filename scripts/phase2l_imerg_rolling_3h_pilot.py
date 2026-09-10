#!/usr/bin/env python3
"""Phase 2L-C IMERG Final V07 half-hourly rolling 3h pilot.

This stage does not select candidates. It refines a fixed set of CMORPH-selected
Development candidate region-days into exact six-slot IMERG 3h windows, including
UTC-boundary-crossing windows.
"""
from __future__ import annotations

import argparse, csv, json, re, shutil, tempfile, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from netCDF4 import Dataset

from lpz_risk.historical_spatial import build_primary_subdivision_geojson

PADDING_DEG = 0.5
JAPAN_BBOX = (122.0, 24.0, 150.0, 47.0)
DEFAULT_DATES = ["2023-05-07", "2023-07-10", "2024-04-08", "2024-08-29"]
FILENAME_TIME_RE = re.compile(r"\.(\d{8})-S(\d{6})-E(\d{6})\.")


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


def _get(url: str, dst: Path, tries: int = 5) -> None:
    last = None
    for i in range(tries):
        try:
            req = Request(url, headers={"User-Agent": "lpz-risk-system/0.1 phase2l-imerg-3h"})
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
    pts = list(_geometry_points(g))
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (
        max(JAPAN_BBOX[0], min(xs) - PADDING_DEG),
        max(JAPAN_BBOX[1], min(ys) - PADDING_DEG),
        min(JAPAN_BBOX[2], max(xs) + PADDING_DEG),
        min(JAPAN_BBOX[3], max(ys) + PADDING_DEG),
    )


def _read_reservoir(path: Path, dates: set[str]):
    by_date = {d: [] for d in dates}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["date_utc"] in dates:
                by_date[row["date_utc"]].append(row)
    missing = [d for d, rows in by_date.items() if not rows]
    if missing:
        raise ValueError(f"pilot dates absent from frozen CMORPH reservoir: {missing}")
    return by_date


def _extract_start_from_filename(path: Path) -> datetime:
    m = FILENAME_TIME_RE.search(path.name)
    if not m:
        raise ValueError(f"cannot parse IMERG slot time from filename: {path.name}")
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def _read_imerg_halfhour(path: Path):
    with Dataset(path) as ds:
        group = ds.groups.get("Grid", ds)
        lon = np.asarray(group.variables["lon"][:], dtype=float).squeeze()
        lat = np.asarray(group.variables["lat"][:], dtype=float).squeeze()
        rain = np.ma.asarray(group.variables["precipitation"][:]).squeeze()
    if rain.shape == (lon.size, lat.size):
        rain = rain.T
    elif rain.shape != (lat.size, lon.size):
        raise ValueError(f"IMERG precipitation shape mismatch {rain.shape} vs lat={lat.size} lon={lon.size}")
    lon = ((lon + 180.0) % 360.0) - 180.0
    return lat, lon, rain


def _download_slots(start: datetime, end: datetime, dest: Path):
    import earthaccess
    last = None
    for i in range(5):
        try:
            granules = earthaccess.search_data(
                short_name="GPM_3IMERGHH",
                version="07",
                bounding_box=JAPAN_BBOX,
                temporal=(start.isoformat(), end.isoformat()),
                count=200,
            )
            if not granules:
                raise RuntimeError("no IMERG half-hour granules returned")
            paths = [Path(p) for p in earthaccess.download(granules, str(dest), threads=1)]
            paths = [p for p in paths if p.exists() and p.stat().st_size >= 1024]
            if not paths:
                raise RuntimeError("no valid IMERG half-hour payloads downloaded")
            return paths
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i + 1 < 5:
                time.sleep(15 * (i + 1))
    raise RuntimeError(f"IMERG slot download failed: {type(last).__name__}: {last}")


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
    result_rows = []
    slot_audit = []
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
            day = datetime.strptime(date_s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            first_start = day - timedelta(hours=2, minutes=30)
            last_start = day + timedelta(hours=23, minutes=30)
            final_slot_start = last_start + timedelta(hours=2, minutes=30)
            search_end = final_slot_start + timedelta(minutes=29, seconds=59)
            ddir = td / date_s; ddir.mkdir()
            files = _download_slots(first_start, search_end, ddir)

            slot_files = {}
            for fp in files:
                ts = _extract_start_from_filename(fp)
                if first_start <= ts <= final_slot_start:
                    slot_files[ts] = fp
            expected_slots = [first_start + timedelta(minutes=30*i) for i in range(int((final_slot_start-first_start).total_seconds()/1800)+1)]
            missing = [x.isoformat() for x in expected_slots if x not in slot_files]
            slot_audit.append({"date_utc": date_s, "expected_slot_count": len(expected_slots), "available_slot_count": len(expected_slots)-len(missing), "missing_slots": missing})
            if missing:
                raise RuntimeError(f"missing IMERG slots for {date_s}: {missing[:10]} count={len(missing)}")

            cache = {}
            for ts in expected_slots:
                lat, lon, rain_rate = _read_imerg_halfhour(slot_files[ts])
                cache[ts] = (lat, lon, rain_rate)

            for c_row in by_date[date_s]:
                code = c_row["primary_subdivision_code"]
                x0, y0, x1, y1 = windows[code]
                best = {k: (-np.inf, None, None) for k in ("mean", "max", "p90", "p95")}
                valid_windows = 0
                start = first_start
                while start <= last_start:
                    six = [start + timedelta(minutes=30*i) for i in range(6)]
                    lat, lon, _ = cache[six[0]]
                    iy = np.where((lat >= y0) & (lat <= y1))[0]
                    ix = np.where((lon >= x0) & (lon <= x1))[0]
                    if iy.size == 0 or ix.size == 0:
                        raise RuntimeError(f"empty IMERG matched window {date_s} {code}")
                    accum = None
                    for ts in six:
                        lat2, lon2, rr = cache[ts]
                        if lat2.shape != lat.shape or lon2.shape != lon.shape or not np.allclose(lat2, lat) or not np.allclose(lon2, lon):
                            raise RuntimeError("IMERG grid changed within pilot window")
                        sub = np.ma.asarray(rr[np.ix_(iy, ix)], dtype=float)
                        amount = sub * 0.5  # precipitation is mm/hr; native slot is 30 min
                        accum = amount if accum is None else accum + amount
                    vals = np.asarray(np.ma.asarray(accum).compressed(), dtype=float)
                    vals = vals[np.isfinite(vals) & (vals >= 0)]
                    if vals.size:
                        valid_windows += 1
                        stats = {"mean": float(vals.mean()), "max": float(vals.max()), "p90": float(np.percentile(vals, 90)), "p95": float(np.percentile(vals, 95))}
                        for k, v in stats.items():
                            if v > best[k][0]:
                                best[k] = (v, start, start + timedelta(hours=3))
                    start += timedelta(minutes=30)
                if valid_windows != 53:
                    raise RuntimeError(f"expected 53 rolling starts, got {valid_windows} for {date_s} {code}")
                row = {"date_utc": date_s, "primary_subdivision_code": code, "rolling_window_count": valid_windows}
                for k, (v, s, e) in best.items():
                    row[f"imerg_3h_{k}_max_mm"] = v
                    row[f"imerg_3h_{k}_window_start_utc"] = s.isoformat()
                    row[f"imerg_3h_{k}_window_end_utc"] = e.isoformat()
                result_rows.append(row)

    with (out / "phase2l_imerg_rolling_3h_pilot.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(result_rows[0])); w.writeheader(); w.writerows(result_rows)
    (out / "phase2l_imerg_rolling_3h_slot_audit.json").write_text(json.dumps(slot_audit, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    report = {
        "schema_version": "1.0.0",
        "phase": "2L-C-imerg-rolling-3h-pilot",
        "split": "DEVELOPMENT",
        "pilot_dates": dates,
        "pilot_date_count": len(dates),
        "candidate_region_day_count": len(result_rows),
        "source_id": "NASA_IMERG_FINAL_V07_HALFHOUR",
        "short_name": "GPM_3IMERGHH",
        "native_slot_minutes": 30,
        "slots_per_3h_window": 6,
        "rolling_start_range": "PREVIOUS_DAY_21:30_UTC_THROUGH_CANDIDATE_DAY_23:30_UTC_INCLUSIVE",
        "rolling_window_count_per_region_day": 53,
        "boundary_crossing_windows_included": True,
        "missing_slot_interpolation": False,
        "candidate_membership_changed": False,
        "source_fusion_used": False,
        "environment_variables_used": False,
        "hard_negative_label": None,
        "validation_data_used": False,
        "retrospective_2026_used": False,
        "prospective_holdout_used": False,
        "risk_engine_allowed": False,
        "gate": "PASS_IMERG_ROLLING_3H_PILOT",
    }
    (out / "phase2l_imerg_rolling_3h_pilot.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
