#!/usr/bin/env python3
"""Phase 2L-K: 2025 IMERG Final V07 half-hourly rolling 3h refinement.

This stage refines the already-frozen Phase 2L-J CMORPH target membership.
It does NOT use ERA5/environment and does NOT perform matching.

Scientific semantics are intentionally identical to the Development Phase 2L-C
rolling-3h implementation:
- NASA IMERG Final V07 half-hourly, short_name=GPM_3IMERGHH
- precipitation is mm/hr; each native 30-min slot contributes rate * 0.5 mm
- six consecutive native slots form one exact 3h accumulation
- rolling starts every 30 min from previous-day 21:30 UTC through
  candidate-day 23:30 UTC inclusive
- 53 rolling windows per target region-day
- boundary-crossing windows are included
- no missing-slot interpolation
- for mean/max/p90/p95, retain the maximum 3h statistic and its window times
- ties keep the earliest rolling start, matching the Development implementation

Operational safeguards:
- one UTC target day per atomic checkpoint
- rerun skips valid checkpoints
- raw IMERG files are deleted after each day
- sequential download only (threads=1)
- --max-new-days N enables a pilot/resume run

This script intentionally reads 2025 rainfall but still does NOT read ERA5.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from netCDF4 import Dataset

from lpz_risk.historical_spatial import build_primary_subdivision_geojson


SHORT_NAME = "GPM_3IMERGHH"
IMERG_VERSION = "07"
SOURCE_ID = "NASA_IMERG_FINAL_V07_HALFHOUR"
PADDING_DEG = 0.5
JAPAN_BBOX = (122.0, 24.0, 150.0, 47.0)
FILENAME_TIME_RE = re.compile(r"\.(\d{8})-S(\d{6})-E(\d{6})\.")

EXPECTED_TARGET_COUNT = 1218
EXPECTED_POSITIVE_COUNT = 23
EXPECTED_ROLLING_WINDOWS = 53
EXPECTED_SLOT_COUNT = 58

EXPECTED_J_GATE = (
    "PASS_PHASE2L_J_2025_CMORPH_FROZEN_SCREEN_365D_18REGIONS"
)
PASS_DAILY_GATE = "PASS_PHASE2L_K_2025_IMERG_ROLLING_3H_DAY"
PARTIAL_GATE = "PARTIAL_PHASE2L_K_2025_IMERG_ROLLING_3H_CHECKPOINTED"
PASS_GATE = "PASS_PHASE2L_K_2025_IMERG_ROLLING_3H_COMPLETE_1218_REGION_DAYS"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    # Force a complete reread before replacement.
    _ = tmp.read_text(encoding="utf-8")
    tmp.replace(path)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    json.loads(text)
    atomic_write_text(path, text)


def atomic_write_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False)
    _ = pd.read_csv(tmp, dtype={"primary_subdivision_code": "string"})
    tmp.replace(path)


def earthdata_login(tries: int = 5):
    import earthaccess

    last: Exception | None = None
    for i in range(tries):
        try:
            return earthaccess.login(strategy="environment")
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i + 1 < tries:
                time.sleep(10 * (i + 1))

    raise RuntimeError(
        f"Earthdata login failed after {tries} attempts: "
        f"{type(last).__name__}: {last}"
    ) from last


def download_small_file(url: str, dst: Path, tries: int = 5) -> None:
    last: Exception | None = None
    for i in range(tries):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": "lpz-risk-system/0.1 phase2l-k-imerg-validation"
                },
            )
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

    raise RuntimeError(
        f"download failed: {url}: {type(last).__name__}: {last}"
    ) from last


def geometry_points(g: dict[str, Any]):
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
            yield from geometry_points(part)

    else:
        raise ValueError(f"unsupported geometry type: {kind!r}")


def matched_window(g: dict[str, Any]) -> tuple[float, float, float, float]:
    pts = list(geometry_points(g))
    if not pts:
        raise ValueError("empty geometry")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    return (
        max(JAPAN_BBOX[0], min(xs) - PADDING_DEG),
        max(JAPAN_BBOX[1], min(ys) - PADDING_DEG),
        min(JAPAN_BBOX[2], max(xs) + PADDING_DEG),
        min(JAPAN_BBOX[3], max(ys) + PADDING_DEG),
    )


def load_geometry_windows(
    *,
    codes: list[str],
    gis_config: Path,
    era5_config: Path,
) -> tuple[
    dict[str, tuple[float, float, float, float]],
    dict[str, Any],
]:
    era5 = json.loads(era5_config.read_text(encoding="utf-8"))
    padding = float(
        era5["spatial_sampling"]["bbox_padding_degrees"]
    )
    if not math.isclose(
        padding,
        PADDING_DEG,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError(
            f"frozen bbox padding mismatch: expected {PADDING_DEG}, got {padding}"
        )

    gis = json.loads(gis_config.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="phase2l_k_geometry_") as td:
        jzip = Path(td) / "jma.zip"
        download_small_file(str(gis["zip_url"]), jzip)
        zip_sha = sha256_file(jzip)

        geo = build_primary_subdivision_geojson(
            jzip.read_bytes(),
            set(codes),
        )

    if not geo.get("geometry_complete_for_required_codes"):
        raise RuntimeError(
            "missing JMA geometries: "
            f"{geo.get('missing_required_codes')}"
        )

    feats = {
        str(f["properties"]["primary_subdivision_code"]).zfill(6): f["geometry"]
        for f in geo["features"]
    }

    if set(feats) != set(codes):
        raise RuntimeError(
            f"geometry code mismatch: expected={sorted(codes)}, "
            f"observed={sorted(feats)}"
        )

    windows = {
        code: matched_window(feats[code])
        for code in sorted(codes)
    }

    meta = {
        "gis_zip_url": str(gis["zip_url"]),
        "gis_zip_sha256": zip_sha,
        "padding_degrees": PADDING_DEG,
        "japan_bbox_wsen": list(JAPAN_BBOX),
        "region_codes": sorted(codes),
        "window_by_code_wsen": {
            code: list(windows[code])
            for code in sorted(windows)
        },
        "spatial_semantics": (
            "OFFICIAL_JMA_PRIMARY_SUBDIVISION_GEOMETRY_"
            "BBOX_PLUS_FROZEN_ERA5_0P5_DEG_PADDING"
        ),
    }

    return windows, meta


def extract_start_from_filename(path: Path) -> datetime:
    match = FILENAME_TIME_RE.search(path.name)
    if not match:
        raise ValueError(
            f"cannot parse IMERG slot time from filename: {path.name}"
        )

    return datetime.strptime(
        match.group(1) + match.group(2),
        "%Y%m%d%H%M%S",
    ).replace(tzinfo=timezone.utc)


def read_imerg_halfhour(path: Path):
    with Dataset(path) as ds:
        group = ds.groups.get("Grid", ds)

        lon = np.asarray(
            group.variables["lon"][:],
            dtype=float,
        ).squeeze()
        lat = np.asarray(
            group.variables["lat"][:],
            dtype=float,
        ).squeeze()
        rain = np.ma.asarray(
            group.variables["precipitation"][:]
        ).squeeze()

    if rain.shape == (lon.size, lat.size):
        rain = rain.T
    elif rain.shape != (lat.size, lon.size):
        raise ValueError(
            f"IMERG precipitation shape mismatch {rain.shape}; "
            f"lat={lat.size}; lon={lon.size}"
        )

    lon = ((lon + 180.0) % 360.0) - 180.0
    return lat, lon, rain


def download_slots(
    start: datetime,
    end: datetime,
    dest: Path,
    tries: int = 5,
) -> list[Path]:
    import earthaccess

    last: Exception | None = None

    for i in range(tries):
        try:
            granules = earthaccess.search_data(
                short_name=SHORT_NAME,
                version=IMERG_VERSION,
                bounding_box=JAPAN_BBOX,
                temporal=(start.isoformat(), end.isoformat()),
                count=200,
            )

            if not granules:
                raise RuntimeError("no IMERG half-hour granules returned")

            raw_paths = earthaccess.download(
                granules,
                str(dest),
                threads=1,
            )

            paths = [
                Path(p)
                for p in raw_paths
                if Path(p).exists()
                and Path(p).stat().st_size >= 1024
            ]

            if not paths:
                raise RuntimeError(
                    "no valid IMERG half-hour payloads downloaded"
                )

            return paths

        except Exception as exc:  # noqa: BLE001
            last = exc
            # A retry must not inherit partial files from the prior attempt.
            shutil.rmtree(dest, ignore_errors=True)
            dest.mkdir(parents=True, exist_ok=True)

            if i + 1 < tries:
                time.sleep(15 * (i + 1))

    raise RuntimeError(
        f"IMERG slot download failed after {tries} attempts: "
        f"{type(last).__name__}: {last}"
    ) from last


def build_expected_slots(day: datetime) -> tuple[
    datetime,
    datetime,
    list[datetime],
    list[datetime],
]:
    first_start = day - timedelta(hours=2, minutes=30)
    last_start = day + timedelta(hours=23, minutes=30)

    rolling_starts = [
        first_start + timedelta(minutes=30 * i)
        for i in range(EXPECTED_ROLLING_WINDOWS)
    ]

    final_slot_start = (
        last_start + timedelta(hours=2, minutes=30)
    )

    slots = [
        first_start + timedelta(minutes=30 * i)
        for i in range(EXPECTED_SLOT_COUNT)
    ]

    if rolling_starts[-1] != last_start:
        raise AssertionError("rolling-start construction mismatch")
    if slots[-1] != final_slot_start:
        raise AssertionError("slot construction mismatch")

    search_end = final_slot_start + timedelta(
        minutes=29,
        seconds=59,
    )

    return first_start, search_end, rolling_starts, slots


def checkpoint_path(outdir: Path, date_s: str) -> Path:
    return (
        outdir
        / "daily"
        / date_s[:7]
        / f"{date_s}.json"
    )


def validate_checkpoint(
    path: Path,
    *,
    date_s: str,
    expected_codes: list[str],
) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if obj.get("gate") != PASS_DAILY_GATE:
        return None
    if obj.get("date_utc") != date_s:
        return None
    if int(obj.get("expected_slot_count", -1)) != EXPECTED_SLOT_COUNT:
        return None
    if int(obj.get("available_slot_count", -1)) != EXPECTED_SLOT_COUNT:
        return None
    if obj.get("missing_slots"):
        return None

    rows = obj.get("rows")
    if not isinstance(rows, list):
        return None

    observed_codes = sorted(
        str(r.get("primary_subdivision_code", "")).zfill(6)
        for r in rows
    )
    if observed_codes != sorted(expected_codes):
        return None

    for row in rows:
        if int(row.get("rolling_window_count", -1)) != EXPECTED_ROLLING_WINDOWS:
            return None

        for stat in ("mean", "max", "p90", "p95"):
            try:
                value = float(row[f"imerg_3h_{stat}_max_mm"])
            except Exception:
                return None
            if not math.isfinite(value) or value < 0:
                return None

            if not row.get(f"imerg_3h_{stat}_window_start_utc"):
                return None
            if not row.get(f"imerg_3h_{stat}_window_end_utc"):
                return None

    return obj


def process_one_day(
    *,
    date_s: str,
    day_targets: pd.DataFrame,
    windows: dict[str, tuple[float, float, float, float]],
    outdir: Path,
    temp_root: Path,
) -> dict[str, Any]:
    codes = sorted(
        day_targets["primary_subdivision_code"]
        .astype(str)
        .unique()
    )

    cp = checkpoint_path(outdir, date_s)
    existing = validate_checkpoint(
        cp,
        date_s=date_s,
        expected_codes=codes,
    )
    if existing is not None:
        return {
            "status": "SKIP_VALID_CHECKPOINT",
            "elapsed_seconds": 0.0,
            "downloaded_bytes": 0,
        }

    day = datetime.strptime(
        date_s,
        "%Y-%m-%d",
    ).replace(tzinfo=timezone.utc)

    (
        first_start,
        search_end,
        rolling_starts,
        expected_slots,
    ) = build_expected_slots(day)

    ddir = temp_root / date_s
    shutil.rmtree(ddir, ignore_errors=True)
    ddir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()

    try:
        files = download_slots(
            first_start,
            search_end,
            ddir,
        )

        slot_files: dict[datetime, Path] = {}
        duplicate_slot_times: list[str] = []

        for fp in files:
            ts = extract_start_from_filename(fp)
            if ts in expected_slots:
                if ts in slot_files:
                    duplicate_slot_times.append(ts.isoformat())
                slot_files[ts] = fp

        missing = [
            ts.isoformat()
            for ts in expected_slots
            if ts not in slot_files
        ]

        if duplicate_slot_times:
            raise RuntimeError(
                f"duplicate IMERG slot timestamps for {date_s}: "
                f"{duplicate_slot_times[:10]}"
            )

        if missing:
            raise RuntimeError(
                f"missing IMERG slots for {date_s}: "
                f"{missing[:10]} count={len(missing)}"
            )

        # Read each source granule only once. Instead of caching the full global
        # IMERG grid 58 times, retain only the small matched arrays for the
        # target primary subdivisions of this date.
        code_slot_amounts: dict[str, list[np.ma.MaskedArray]] = {
            code: []
            for code in codes
        }

        reference_lat: np.ndarray | None = None
        reference_lon: np.ndarray | None = None
        region_indices: dict[str, tuple[np.ndarray, np.ndarray]] = {}

        source_bytes = 0

        for slot_index, ts in enumerate(expected_slots):
            fp = slot_files[ts]
            source_bytes += fp.stat().st_size

            lat, lon, rain_rate = read_imerg_halfhour(fp)

            if reference_lat is None:
                reference_lat = lat
                reference_lon = lon

                for code in codes:
                    x0, y0, x1, y1 = windows[code]
                    iy = np.where(
                        (lat >= y0) & (lat <= y1)
                    )[0]
                    ix = np.where(
                        (lon >= x0) & (lon <= x1)
                    )[0]

                    if iy.size == 0 or ix.size == 0:
                        raise RuntimeError(
                            f"empty IMERG matched window {date_s} {code}"
                        )

                    region_indices[code] = (iy, ix)

            else:
                assert reference_lon is not None

                if (
                    lat.shape != reference_lat.shape
                    or lon.shape != reference_lon.shape
                    or not np.allclose(lat, reference_lat)
                    or not np.allclose(lon, reference_lon)
                ):
                    raise RuntimeError(
                        f"IMERG grid changed within {date_s}; slot={slot_index}"
                    )

            for code in codes:
                iy, ix = region_indices[code]
                sub_rate = np.ma.asarray(
                    rain_rate[np.ix_(iy, ix)],
                    dtype=float,
                )
                # Native precipitation is mm/hr, one native slot is 0.5 h.
                code_slot_amounts[code].append(
                    sub_rate * 0.5
                )

        result_rows: list[dict[str, Any]] = []

        for code in codes:
            slots = code_slot_amounts[code]

            if len(slots) != EXPECTED_SLOT_COUNT:
                raise AssertionError(
                    f"{date_s} {code}: expected {EXPECTED_SLOT_COUNT} "
                    f"slot arrays, got {len(slots)}"
                )

            best: dict[str, tuple[float, datetime, datetime]] = {}
            valid_windows = 0

            for start_index, start in enumerate(rolling_starts):
                six = slots[start_index:start_index + 6]

                if len(six) != 6:
                    raise AssertionError(
                        f"{date_s} {code}: incomplete six-slot window "
                        f"at index {start_index}"
                    )

                accum = six[0].copy()
                for amount in six[1:]:
                    accum = accum + amount

                vals = np.asarray(
                    np.ma.asarray(accum).compressed(),
                    dtype=float,
                )
                vals = vals[
                    np.isfinite(vals)
                    & (vals >= 0)
                ]

                if vals.size == 0:
                    continue

                valid_windows += 1

                stats = {
                    "mean": float(vals.mean()),
                    "max": float(vals.max()),
                    "p90": float(np.percentile(vals, 90)),
                    "p95": float(np.percentile(vals, 95)),
                }

                for stat, value in stats.items():
                    previous = best.get(stat)
                    # Strict greater-than preserves earliest start on ties.
                    if previous is None or value > previous[0]:
                        best[stat] = (
                            value,
                            start,
                            start + timedelta(hours=3),
                        )

            if valid_windows != EXPECTED_ROLLING_WINDOWS:
                raise RuntimeError(
                    f"expected {EXPECTED_ROLLING_WINDOWS} rolling windows, "
                    f"got {valid_windows} for {date_s} {code}"
                )

            target_row = day_targets.loc[
                day_targets["primary_subdivision_code"].astype(str) == code
            ]

            if len(target_row) != 1:
                raise ValueError(
                    f"{date_s} {code}: expected one refinement target row, "
                    f"got {len(target_row)}"
                )

            target = target_row.iloc[0]

            row: dict[str, Any] = {
                "date_utc": date_s,
                "primary_subdivision_code": code,
                "rolling_window_count": valid_windows,
                "is_official_positive": bool(
                    target["is_official_positive"]
                ),
                "selected_by_frozen_cmorph_screen": bool(
                    target["selected_by_frozen_cmorph_screen"]
                ),
                "refinement_role": str(
                    target["refinement_role"]
                ),
            }

            for stat in ("mean", "max", "p90", "p95"):
                value, start, end = best[stat]
                row[f"imerg_3h_{stat}_max_mm"] = value
                row[f"imerg_3h_{stat}_window_start_utc"] = (
                    start.isoformat()
                )
                row[f"imerg_3h_{stat}_window_end_utc"] = (
                    end.isoformat()
                )

            result_rows.append(row)

        payload = {
            "schema_version": "1.0.0",
            "phase": "2L-K-2025-imerg-rolling-3h-daily",
            "gate": PASS_DAILY_GATE,
            "date_utc": date_s,
            "source_id": SOURCE_ID,
            "short_name": SHORT_NAME,
            "version": IMERG_VERSION,
            "target_region_day_count": len(result_rows),
            "target_region_codes": codes,
            "expected_slot_count": EXPECTED_SLOT_COUNT,
            "available_slot_count": EXPECTED_SLOT_COUNT,
            "missing_slots": [],
            "native_slot_minutes": 30,
            "slots_per_3h_window": 6,
            "rolling_window_count_per_region_day": EXPECTED_ROLLING_WINDOWS,
            "rolling_start_first_utc": rolling_starts[0].isoformat(),
            "rolling_start_last_utc": rolling_starts[-1].isoformat(),
            "boundary_crossing_windows_included": True,
            "missing_slot_interpolation": False,
            "download_threads": 1,
            "downloaded_file_count": len(files),
            "downloaded_source_bytes": source_bytes,
            "rows": result_rows,
            "validation_rainfall_read": True,
            "validation_era5_environment_read": False,
            "matching_performed": False,
            "primary_hypothesis_changed": False,
            "risk_engine_allowed": False,
            "elapsed_seconds": time.monotonic() - started,
        }

        atomic_write_json(cp, payload)

        return {
            "status": "SUCCESS",
            "elapsed_seconds": float(payload["elapsed_seconds"]),
            "downloaded_bytes": source_bytes,
            "target_count": len(result_rows),
        }

    finally:
        shutil.rmtree(ddir, ignore_errors=True)


def collect_checkpoints(
    *,
    outdir: Path,
    targets: pd.DataFrame,
) -> tuple[
    list[dict[str, Any]],
    list[str],
    int,
]:
    rows: list[dict[str, Any]] = []
    missing_dates: list[str] = []
    source_bytes = 0

    for date_s, day_targets in targets.groupby(
        "date_utc",
        sort=True,
    ):
        codes = sorted(
            day_targets["primary_subdivision_code"]
            .astype(str)
            .unique()
        )

        obj = validate_checkpoint(
            checkpoint_path(outdir, date_s),
            date_s=date_s,
            expected_codes=codes,
        )

        if obj is None:
            missing_dates.append(date_s)
            continue

        rows.extend(obj["rows"])
        source_bytes += int(
            obj.get("downloaded_source_bytes") or 0
        )

    return rows, missing_dates, source_bytes


def finalize(
    *,
    outdir: Path,
    targets: pd.DataFrame,
    rows: list[dict[str, Any]],
    source_bytes: int,
    phase2lj_report: Path,
    geometry_meta: dict[str, Any],
) -> dict[str, Any]:
    result = pd.DataFrame(rows)

    result["primary_subdivision_code"] = (
        result["primary_subdivision_code"]
        .astype("string")
        .str.zfill(6)
    )
    result["date_utc"] = pd.to_datetime(
        result["date_utc"]
    ).dt.strftime("%Y-%m-%d")

    if len(result) != len(targets):
        raise ValueError(
            f"expected {len(targets)} refined region-days, got {len(result)}"
        )

    if result.duplicated(
        ["date_utc", "primary_subdivision_code"]
    ).any():
        raise ValueError("duplicate IMERG refined region-day keys")

    expected_keys = set(
        map(
            tuple,
            targets[
                ["date_utc", "primary_subdivision_code"]
            ].astype(str).to_numpy(),
        )
    )
    observed_keys = set(
        map(
            tuple,
            result[
                ["date_utc", "primary_subdivision_code"]
            ].astype(str).to_numpy(),
        )
    )

    if expected_keys != observed_keys:
        raise AssertionError(
            "refined target membership changed; "
            f"missing={len(expected_keys-observed_keys)}, "
            f"extra={len(observed_keys-expected_keys)}"
        )

    result = result.sort_values(
        ["date_utc", "primary_subdivision_code"],
        kind="mergesort",
    ).reset_index(drop=True)

    unique_dates = int(result["date_utc"].nunique())

    positive_rows = result.loc[
        result["is_official_positive"].astype(bool)
    ].copy()

    if len(positive_rows) != EXPECTED_POSITIVE_COUNT:
        raise ValueError(
            f"expected {EXPECTED_POSITIVE_COUNT} refined Positive region-days, "
            f"got {len(positive_rows)}"
        )

    outside_counts: dict[str, int] = {}
    for stat in ("mean", "max", "p90", "p95"):
        starts = pd.to_datetime(
            result[f"imerg_3h_{stat}_window_start_utc"],
            utc=True,
        )
        nominal = pd.to_datetime(
            result["date_utc"],
            utc=True,
        )
        outside_counts[stat] = int(
            (starts.dt.strftime("%Y-%m-%d") != nominal.dt.strftime("%Y-%m-%d"))
            .sum()
        )

    output_csv = (
        outdir
        / "phase2l_k_2025_imerg_rolling_3h_full.csv"
    )
    report_path = (
        outdir
        / "phase2l_k_2025_imerg_rolling_3h_report.json"
    )

    atomic_write_csv(output_csv, result)

    report = {
        "schema_version": "1.0.0",
        "phase": "2L-K-2025-imerg-rolling-3h-complete",
        "gate": PASS_GATE,
        "generated_at_utc": utc_now(),
        "source_id": SOURCE_ID,
        "short_name": SHORT_NAME,
        "version": IMERG_VERSION,
        "target_region_day_count": int(len(targets)),
        "refined_region_day_count": int(len(result)),
        "official_positive_region_day_count": int(len(positive_rows)),
        "unique_utc_day_count": unique_dates,
        "native_slot_minutes": 30,
        "slots_per_3h_window": 6,
        "slot_count_per_target_utc_day": EXPECTED_SLOT_COUNT,
        "rolling_window_count_per_region_day": EXPECTED_ROLLING_WINDOWS,
        "rolling_start_range": (
            "PREVIOUS_DAY_21:30_UTC_THROUGH_"
            "CANDIDATE_DAY_23:30_UTC_INCLUSIVE"
        ),
        "boundary_crossing_windows_included": True,
        "missing_slot_interpolation": False,
        "candidate_membership_changed": False,
        "winning_window_start_outside_nominal_utc_day_count": outside_counts,
        "total_downloaded_source_bytes_across_checkpoints": source_bytes,
        "total_downloaded_source_gib": source_bytes / (1024.0 ** 3),
        "phase2l_j_report_sha256": sha256_file(phase2lj_report),
        "validation_rainfall_read": True,
        "validation_era5_environment_read": False,
        "matching_performed": False,
        "pca_refit_on_2025": False,
        "primary_hypothesis_changed": False,
        "hard_negative_label": None,
        "retrospective_2026_read": False,
        "prospective_holdout_read": False,
        "risk_engine_allowed": False,
        "geometry": geometry_meta,
        "output_csv": str(output_csv),
    }

    atomic_write_json(report_path, report)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)

    ap.add_argument(
        "--targets",
        required=True,
        type=Path,
    )
    ap.add_argument(
        "--phase2lj-report",
        required=True,
        type=Path,
    )
    ap.add_argument(
        "--gis-config",
        default="config/jma_primary_subdivision_gis.json",
        type=Path,
    )
    ap.add_argument(
        "--era5-config",
        default="config/historical_environment_era5.json",
        type=Path,
    )
    ap.add_argument(
        "--output-dir",
        required=True,
        type=Path,
    )
    ap.add_argument(
        "--max-new-days",
        type=int,
        default=None,
    )

    a = ap.parse_args()

    if a.max_new_days is not None and a.max_new_days < 1:
        raise ValueError("--max-new-days must be >= 1")

    targets_path = a.targets.resolve()
    phase2lj_report_path = a.phase2lj_report.resolve()
    outdir = a.output_dir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    phase2lj = json.loads(
        phase2lj_report_path.read_text(encoding="utf-8")
    )

    if phase2lj.get("gate") != EXPECTED_J_GATE:
        raise ValueError(
            f"Phase 2L-J gate mismatch: {phase2lj.get('gate')}"
        )
    if phase2lj.get("validation_era5_environment_read") is not False:
        raise ValueError("Phase 2L-J unexpectedly read ERA5")
    if phase2lj.get("validation_matching_performed") is not False:
        raise ValueError("Phase 2L-J unexpectedly performed matching")
    if phase2lj.get("cutoff_reestimated_from_2025") is not False:
        raise ValueError("2025 CMORPH cutoff was unexpectedly refit")

    targets = pd.read_csv(
        targets_path,
        dtype={"primary_subdivision_code": "string"},
    )

    required_cols = {
        "date_utc",
        "primary_subdivision_code",
        "is_official_positive",
        "selected_by_frozen_cmorph_screen",
        "refinement_role",
    }
    missing_cols = sorted(required_cols - set(targets.columns))
    if missing_cols:
        raise ValueError(
            f"target table missing columns: {missing_cols}"
        )

    targets["primary_subdivision_code"] = (
        targets["primary_subdivision_code"]
        .astype("string")
        .str.zfill(6)
    )
    targets["date_utc"] = pd.to_datetime(
        targets["date_utc"]
    ).dt.strftime("%Y-%m-%d")

    # Pandas may parse these booleans correctly; normalize defensively.
    for col in (
        "is_official_positive",
        "selected_by_frozen_cmorph_screen",
    ):
        if targets[col].dtype != bool:
            mapped = (
                targets[col]
                .astype(str)
                .str.strip()
                .str.lower()
                .map(
                    {
                        "true": True,
                        "false": False,
                        "1": True,
                        "0": False,
                    }
                )
            )
            if mapped.isna().any():
                raise ValueError(
                    f"cannot parse boolean column {col}"
                )
            targets[col] = mapped.astype(bool)

    if len(targets) != EXPECTED_TARGET_COUNT:
        raise ValueError(
            f"expected {EXPECTED_TARGET_COUNT} IMERG targets, "
            f"got {len(targets)}"
        )

    if targets.duplicated(
        ["date_utc", "primary_subdivision_code"]
    ).any():
        raise ValueError("duplicate IMERG target region-day keys")

    if int(targets["is_official_positive"].sum()) != EXPECTED_POSITIVE_COUNT:
        raise ValueError(
            f"expected {EXPECTED_POSITIVE_COUNT} official Positive targets"
        )

    if not targets[
        "selected_by_frozen_cmorph_screen"
    ].all():
        # Phase 2L-J reported forced-in count zero. If that changes, we should
        # not silently use an implementation specialized to the observed state.
        raise ValueError(
            "target table contains Positive forced-in rows despite "
            "Phase 2L-J report stating zero; inspect before proceeding"
        )

    target_dates = sorted(targets["date_utc"].unique())
    codes = sorted(
        targets["primary_subdivision_code"]
        .astype(str)
        .unique()
    )

    windows, geometry_meta = load_geometry_windows(
        codes=codes,
        gis_config=a.gis_config.resolve(),
        era5_config=a.era5_config.resolve(),
    )

    geometry_path = (
        outdir
        / "phase2l_k_2025_imerg_geometry_windows.json"
    )
    atomic_write_json(
        geometry_path,
        {
            "schema_version": "1.0.0",
            "phase": "2L-K-2025-imerg-geometry",
            "gate": "PASS_PHASE2L_K_GEOMETRY_COMPLETE",
            **geometry_meta,
            "risk_engine_allowed": False,
        },
    )

    _, missing_before, _ = collect_checkpoints(
        outdir=outdir,
        targets=targets,
    )

    complete_before = len(target_dates) - len(missing_before)

    print("=" * 104)
    print("LPZ PHASE 2L-K — 2025 IMERG FINAL V07 ROLLING 3H REFINEMENT")
    print("=" * 104)
    print(f"Target region-days               : {len(targets)}")
    print(f"Official Positive targets        : {int(targets['is_official_positive'].sum())}")
    print(f"Unique target UTC days           : {len(target_dates)}")
    print(f"Target regions                   : {len(codes)}")
    print(f"Valid day checkpoints before run : {complete_before}")
    print(f"Missing target days before run   : {len(missing_before)}")
    print(
        "Max new days this invocation    : "
        + (
            str(a.max_new_days)
            if a.max_new_days is not None
            else "FULL RESUME TO COMPLETION"
        )
    )
    print(f"IMERG slots per target day       : {EXPECTED_SLOT_COUNT}")
    print(f"Rolling windows / region-day     : {EXPECTED_ROLLING_WINDOWS}")
    print("Download concurrency             : 1")
    print("Boundary-crossing windows        : INCLUDED")
    print("Missing-slot interpolation       : NO")
    print("ERA5/environment read            : NO")
    print("Matching performed               : NO")
    print("Risk engine                      : NOT ALLOWED")
    print("=" * 104)

    earthdata_login()

    new_days = 0
    bytes_this_run = 0

    with tempfile.TemporaryDirectory(
        prefix="phase2l_k_imerg_"
    ) as td:
        temp_root = Path(td)

        for date_s in target_dates:
            day_targets = targets.loc[
                targets["date_utc"] == date_s
            ].copy()

            codes_this_day = sorted(
                day_targets["primary_subdivision_code"]
                .astype(str)
                .unique()
            )

            if validate_checkpoint(
                checkpoint_path(outdir, date_s),
                date_s=date_s,
                expected_codes=codes_this_day,
            ) is not None:
                continue

            if (
                a.max_new_days is not None
                and new_days >= a.max_new_days
            ):
                break

            result = process_one_day(
                date_s=date_s,
                day_targets=day_targets,
                windows=windows,
                outdir=outdir,
                temp_root=temp_root,
            )

            if result["status"] == "SUCCESS":
                new_days += 1
                bytes_this_run += int(result["downloaded_bytes"])

                print(
                    f"[{date_s}] PASS  "
                    f"targets={result['target_count']}  "
                    f"download={result['downloaded_bytes'] / (1024**2):.1f} MiB  "
                    f"elapsed={result['elapsed_seconds']:.1f}s"
                )

    rows_after, missing_after, source_bytes = collect_checkpoints(
        outdir=outdir,
        targets=targets,
    )

    complete_after = len(target_dates) - len(missing_after)

    if missing_after:
        progress_path = (
            outdir
            / "phase2l_k_2025_imerg_rolling_3h_progress.json"
        )

        atomic_write_json(
            progress_path,
            {
                "schema_version": "1.0.0",
                "phase": "2L-K-2025-imerg-rolling-3h-progress",
                "gate": PARTIAL_GATE,
                "target_region_day_count": int(len(targets)),
                "unique_target_utc_day_count": int(len(target_dates)),
                "valid_checkpoint_day_count": int(complete_after),
                "missing_target_day_count": int(len(missing_after)),
                "new_days_this_run": int(new_days),
                "downloaded_bytes_this_run": int(bytes_this_run),
                "next_missing_date_utc": missing_after[0],
                "validation_rainfall_read": True,
                "validation_era5_environment_read": False,
                "matching_performed": False,
                "risk_engine_allowed": False,
            },
        )

        print("")
        print("=" * 104)
        print(f"Gate                              : {PARTIAL_GATE}")
        print(
            f"Valid target-day checkpoints      : "
            f"{complete_after} / {len(target_dates)}"
        )
        print(f"New target days this run          : {new_days}")
        print(
            f"Downloaded this run               : "
            f"{bytes_this_run / (1024**3):.3f} GiB"
        )
        print(f"Next missing target date          : {missing_after[0]}")
        print("Resume                            : rerun the exact same command")
        print("=" * 104)
        return 0

    report = finalize(
        outdir=outdir,
        targets=targets,
        rows=rows_after,
        source_bytes=source_bytes,
        phase2lj_report=phase2lj_report_path,
        geometry_meta=geometry_meta,
    )

    print("")
    print("=" * 104)
    print("LPZ PHASE 2L-K — 2025 IMERG ROLLING 3H COMPLETE")
    print("=" * 104)
    print(
        f"Target region-days                : "
        f"{report['refined_region_day_count']} / {EXPECTED_TARGET_COUNT}"
    )
    print(
        f"Official Positive region-days     : "
        f"{report['official_positive_region_day_count']} / {EXPECTED_POSITIVE_COUNT}"
    )
    print(
        f"Unique target UTC days            : "
        f"{report['unique_utc_day_count']}"
    )
    print(
        f"Downloaded source total           : "
        f"{report['total_downloaded_source_gib']:.3f} GiB"
    )
    print(
        "Winning start outside nominal UTC:"
    )
    for stat, count in report[
        "winning_window_start_outside_nominal_utc_day_count"
    ].items():
        print(f"  {stat:4s}                              : {count}")
    print("Candidate membership changed       : NO")
    print("ERA5/environment read              : NO")
    print("Matching performed                 : NO")
    print("PCA refit on 2025                  : NO")
    print("Primary changed                    : NO")
    print("Risk engine                        : NOT ALLOWED")
    print("")
    print(f"Gate                              : {PASS_GATE}")
    print(
        "Output CSV                        : "
        f"{report['output_csv']}"
    )
    print("=" * 104)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
