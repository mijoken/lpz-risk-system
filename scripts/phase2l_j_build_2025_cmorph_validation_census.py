#!/usr/bin/env python3
"""Phase 2L-J: build the 2025 CMORPH validation census and frozen candidate reservoir.

This is the first Phase 2L step that intentionally reads 2025 rainfall.

Scientific contract
-------------------
- The Phase 2L-H Primary remains q850_mean_kgkg @ t+0h, Positive higher.
- The Phase 2L-I novel-region amendment is already frozen and committed.
- CMORPH screening cutoffs come ONLY from 2023-2024 Development reference data.
- No percentile/cutoff is estimated from 2025.
- Only primary subdivisions containing a 2025 official Positive are decoded,
  because same-region matching makes all other regions irrelevant to the
  validation estimand. This is a computational restriction, not outcome-based
  case filtering.
- Official Positive region-days remain eligible whether or not they pass the
  CMORPH screen.
- Candidate reservoir = 2025 region-days satisfying all three frozen cutoffs:
    rain_max_mm_day
    rain_p90_mm_day
    rain_p95_mm_day
- Comparison pool additionally excludes every official 2025 Positive region-day.
- IMERG refinement targets are the union of:
    frozen-screen reservoir region-days
    all official 2025 Positive region-days
  so Positive rainfall severity is always reconstructed even when CMORPH misses it.
- ERA5/environment is NOT read.
- No matching is performed here.
- No hard-negative label or risk score is created.

Operational design
------------------
- Sequential daily CMORPH downloads.
- One atomic checkpoint per UTC day.
- Safe to interrupt; rerun skips valid checkpoints.
- Raw NetCDF is deleted immediately after each day.
- --max-new-days N enables a small pilot/resume run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from netCDF4 import Dataset

from lpz_risk.historical_spatial import build_primary_subdivision_geojson


CMORPH_ROOT = "https://noaa-cdr-precip-cmorph-pds.s3.amazonaws.com"
UA = "lpz-risk-system/0.1 phase2l-j-2025-validation-cmorph"

JAPAN_BBOX = (122.0, 24.0, 150.0, 47.0)
EXPECTED_PADDING_DEG = 0.5

START_DATE = date(2025, 1, 1)
END_DATE = date(2025, 12, 31)
EXPECTED_DAY_COUNT = 365

EXPECTED_POSITIVE_REGION_DAY_COUNT = 23
EXPECTED_VALIDATION_REGION_COUNT = 18
EXPECTED_CUTOFF_REGION_COUNT = 54

SCREEN_METRICS = [
    "rain_max_mm_day",
    "rain_p90_mm_day",
    "rain_p95_mm_day",
]

EXPECTED_H_FREEZE_GATE = (
    "PASS_PHASE2L_H_DISCOVERY_AND_VALIDATION_PROTOCOL_FREEZE_"
    "PRIMARY_Q850_T0H"
)
EXPECTED_I_POLICY_GATE = (
    "PASS_PHASE2L_I_NOVEL_REGION_REFERENCE_EXTENSION_POLICY_"
    "FROZEN_PRE_RAINFALL_ENVIRONMENT"
)
EXPECTED_DEV_REF_GATE = (
    "PASS_PHASE2L_I_NOVEL_REGION_DEVELOPMENT_REFERENCE_"
    "9X731_AND_5943_REPLAY"
)

PARTIAL_GATE = "PARTIAL_PHASE2L_J_2025_CMORPH_VALIDATION_CENSUS_CHECKPOINTED"
PASS_GATE = (
    "PASS_PHASE2L_J_2025_CMORPH_FROZEN_SCREEN_"
    "365D_18REGIONS"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
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


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def download_bytes(url: str, tries: int = 5) -> tuple[bytes, dict[str, Any]]:
    last: Exception | None = None
    for i in range(tries):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=180) as r:
                body = r.read()
                meta = {
                    "http_status": int(getattr(r, "status", 200)),
                    "content_type": r.headers.get("Content-Type"),
                    "last_modified": r.headers.get("Last-Modified"),
                    "bytes": len(body),
                    "sha256": sha256_bytes(body),
                }
            if len(body) < 1024:
                raise ValueError("payload too small")
            return body, meta
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i + 1 < tries:
                time.sleep(5 * (i + 1))
    raise RuntimeError(
        f"download failed after {tries} attempts: {url}: "
        f"{type(last).__name__}: {last}"
    ) from last


def download_file(url: str, dst: Path, tries: int = 5) -> dict[str, Any]:
    last: Exception | None = None

    for i in range(tries):
        h = hashlib.sha256()
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=180) as r, dst.open("wb") as f:
                total = 0
                while True:
                    chunk = r.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    total += len(chunk)

                meta = {
                    "http_status": int(getattr(r, "status", 200)),
                    "content_type": r.headers.get("Content-Type"),
                    "last_modified": r.headers.get("Last-Modified"),
                    "bytes": total,
                    "sha256": h.hexdigest(),
                }

            if dst.stat().st_size < 1024:
                raise ValueError("payload too small")
            return meta

        except Exception as exc:  # noqa: BLE001
            last = exc
            dst.unlink(missing_ok=True)
            if i + 1 < tries:
                time.sleep(5 * (i + 1))

    raise RuntimeError(
        f"download failed after {tries} attempts: {url}: "
        f"{type(last).__name__}: {last}"
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


def geometry_bbox(g: dict[str, Any]) -> tuple[float, float, float, float]:
    pts = list(geometry_points(g))
    if not pts:
        raise ValueError("geometry has no points")
    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    return min(xs), min(ys), max(xs), max(ys)


def padded_bbox(
    g: dict[str, Any],
    padding: float,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = geometry_bbox(g)
    return (
        max(JAPAN_BBOX[0], x0 - padding),
        max(JAPAN_BBOX[1], y0 - padding),
        min(JAPAN_BBOX[2], x1 + padding),
        min(JAPAN_BBOX[3], y1 + padding),
    )


def load_windows(
    *,
    codes: list[str],
    gis_config: Path,
    era5_config: Path,
) -> tuple[
    dict[str, tuple[float, float, float, float]],
    dict[str, Any],
]:
    gis_cfg = json.loads(gis_config.read_text(encoding="utf-8"))
    era5_cfg = json.loads(era5_config.read_text(encoding="utf-8"))

    padding = float(
        era5_cfg["spatial_sampling"]["bbox_padding_degrees"]
    )
    if not math.isclose(
        padding,
        EXPECTED_PADDING_DEG,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError(
            f"expected padding {EXPECTED_PADDING_DEG}, got {padding}"
        )

    zip_url = str(gis_cfg["zip_url"])
    zip_bytes, transport = download_bytes(zip_url)

    geo = build_primary_subdivision_geojson(
        zip_bytes,
        set(codes),
    )
    if not geo.get("geometry_complete_for_required_codes"):
        raise RuntimeError(
            "missing validation-region geometries: "
            f"{geo.get('missing_required_codes')}"
        )

    features = {
        str(f["properties"]["primary_subdivision_code"]).zfill(6): f["geometry"]
        for f in geo["features"]
    }

    if set(features) != set(codes):
        raise RuntimeError(
            f"geometry codes mismatch: expected={sorted(codes)}, "
            f"observed={sorted(features)}"
        )

    windows = {
        code: padded_bbox(features[code], padding)
        for code in sorted(codes)
    }

    meta = {
        "gis_zip_url": zip_url,
        "gis_zip_transport": transport,
        "padding_degrees": padding,
        "japan_bbox_wsen": list(JAPAN_BBOX),
        "validation_region_codes": sorted(codes),
        "window_by_code_wsen": {
            c: list(windows[c])
            for c in sorted(windows)
        },
        "spatial_semantics": (
            "OFFICIAL_JMA_PRIMARY_SUBDIVISION_GEOMETRY_"
            "BBOX_PLUS_FROZEN_ERA5_0P5_DEG_PADDING"
        ),
    }
    return windows, meta


def day_source(day: date) -> tuple[str, str]:
    key = (
        f"data/daily/0.25deg/{day:%Y/%m}/"
        f"CMORPH_V1.0_ADJ_0.25deg-DLY_00Z_{day:%Y%m%d}.nc"
    )
    return key, f"{CMORPH_ROOT}/{key}"


def decode_day(
    path: Path,
    *,
    day: date,
    windows: dict[str, tuple[float, float, float, float]],
) -> list[dict[str, Any]]:
    with Dataset(path) as ds:
        lat = np.asarray(ds.variables["lat"][:], dtype=float).squeeze()
        lon = np.asarray(ds.variables["lon"][:], dtype=float).squeeze()
        rain = np.ma.asarray(ds.variables["cmorph"][:]).squeeze()

        if rain.shape == (lon.size, lat.size):
            rain = rain.T
        if rain.shape != (lat.size, lon.size):
            raise ValueError(
                f"shape mismatch {rain.shape}; lat={lat.size}; lon={lon.size}"
            )

        lon = ((lon + 180.0) % 360.0) - 180.0

        rows: list[dict[str, Any]] = []

        for code, (x0, y0, x1, y1) in sorted(windows.items()):
            iy = np.where((lat >= y0) & (lat <= y1))[0]
            ix = np.where((lon >= x0) & (lon <= x1))[0]
            total = int(iy.size * ix.size)

            if total <= 0:
                raise ValueError(
                    f"{day} {code}: zero matched CMORPH grid cells"
                )

            sub = np.ma.asarray(rain[np.ix_(iy, ix)])
            vals = np.asarray(sub.compressed(), dtype=float)
            vals = vals[
                np.isfinite(vals)
                & (vals >= 0)
            ]

            if vals.size == 0:
                raise ValueError(
                    f"{day} {code}: no valid non-negative rainfall"
                )

            rows.append(
                {
                    "date_utc": day.isoformat(),
                    "primary_subdivision_code": code,
                    "grid_cell_count": total,
                    "valid_rain_cell_count": int(vals.size),
                    "valid_fraction": float(vals.size / total),
                    "rain_mean_mm_day": float(np.mean(vals)),
                    "rain_max_mm_day": float(np.max(vals)),
                    "rain_p90_mm_day": float(np.percentile(vals, 90)),
                    "rain_p95_mm_day": float(np.percentile(vals, 95)),
                }
            )

    return rows


def checkpoint_path(outdir: Path, day: date) -> Path:
    return (
        outdir
        / "daily"
        / f"{day:%Y-%m}"
        / f"{day:%Y-%m-%d}.json"
    )


def validate_checkpoint(
    path: Path,
    *,
    day: date,
    codes: list[str],
) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if obj.get("gate") != "PASS_DAILY_CMORPH_2025_VALIDATION":
        return None
    if obj.get("date_utc") != day.isoformat():
        return None

    rows = obj.get("rows")
    if not isinstance(rows, list) or len(rows) != len(codes):
        return None

    observed = sorted(
        str(r.get("primary_subdivision_code", "")).zfill(6)
        for r in rows
    )
    if observed != sorted(codes):
        return None

    return obj


def process_day(
    *,
    day: date,
    windows: dict[str, tuple[float, float, float, float]],
    codes: list[str],
    outdir: Path,
    tempdir: Path,
) -> dict[str, Any]:
    cp = checkpoint_path(outdir, day)
    existing = validate_checkpoint(
        cp,
        day=day,
        codes=codes,
    )
    if existing is not None:
        return {
            "status": "SKIP_VALID_CHECKPOINT",
            "downloaded_bytes": 0,
        }

    key, url = day_source(day)
    raw = tempdir / f"cmorph_{day:%Y%m%d}.nc"
    started = time.monotonic()

    try:
        transport = download_file(url, raw)
        rows = decode_day(
            raw,
            day=day,
            windows=windows,
        )

        payload = {
            "schema_version": "1.0.0",
            "phase": "2L-J-2025-validation-cmorph-daily",
            "gate": "PASS_DAILY_CMORPH_2025_VALIDATION",
            "date_utc": day.isoformat(),
            "source_id": "NOAA_CMORPH_CDR_DAILY_0P25DEG",
            "source_key": key,
            "source_url": url,
            "source_transport": transport,
            "validation_region_count": len(codes),
            "rows": rows,
            "validation_rainfall_read": True,
            "era5_environment_read": False,
            "risk_engine_allowed": False,
            "elapsed_seconds": time.monotonic() - started,
        }

        atomic_write_json(cp, payload)

        return {
            "status": "SUCCESS",
            "downloaded_bytes": int(transport["bytes"]),
            "elapsed_seconds": float(payload["elapsed_seconds"]),
        }

    finally:
        raw.unlink(missing_ok=True)


def collect_daily(
    *,
    outdir: Path,
    codes: list[str],
) -> tuple[list[dict[str, Any]], list[date], int]:
    rows: list[dict[str, Any]] = []
    missing: list[date] = []
    source_bytes = 0

    for d in daterange(START_DATE, END_DATE):
        obj = validate_checkpoint(
            checkpoint_path(outdir, d),
            day=d,
            codes=codes,
        )
        if obj is None:
            missing.append(d)
            continue

        rows.extend(obj["rows"])
        source_bytes += int(
            obj.get("source_transport", {}).get("bytes") or 0
        )

    return rows, missing, source_bytes


def finalize(
    *,
    outdir: Path,
    rows: list[dict[str, Any]],
    source_bytes: int,
    positives: pd.DataFrame,
    cutoffs: pd.DataFrame,
    validation_codes: list[str],
    freeze_path: Path,
    policy_path: Path,
    dev_ref_report_path: Path,
    geometry_meta: dict[str, Any],
) -> dict[str, Any]:
    census = pd.DataFrame(rows)

    census["primary_subdivision_code"] = (
        census["primary_subdivision_code"]
        .astype("string")
        .str.zfill(6)
    )
    census["date_utc"] = pd.to_datetime(
        census["date_utc"]
    ).dt.strftime("%Y-%m-%d")

    expected_rows = EXPECTED_DAY_COUNT * len(validation_codes)
    if len(census) != expected_rows:
        raise ValueError(
            f"expected {expected_rows} validation region-days, got {len(census)}"
        )
    if census["date_utc"].nunique() != EXPECTED_DAY_COUNT:
        raise ValueError("validation census is not 365 complete days")
    if census["primary_subdivision_code"].nunique() != len(validation_codes):
        raise ValueError("validation census region count mismatch")
    if census.duplicated(
        ["date_utc", "primary_subdivision_code"]
    ).any():
        raise ValueError("duplicate validation region-day keys")

    cutoff_cols = [
        f"{m}_frozen_p80_cutoff"
        for m in SCREEN_METRICS
    ]

    selected_cutoffs = cutoffs.loc[
        cutoffs["primary_subdivision_code"].isin(validation_codes),
        ["primary_subdivision_code", *cutoff_cols],
    ].copy()

    if len(selected_cutoffs) != len(validation_codes):
        missing_codes = sorted(
            set(validation_codes)
            - set(selected_cutoffs["primary_subdivision_code"].astype(str))
        )
        raise ValueError(
            f"missing frozen cutoffs for validation regions: {missing_codes}"
        )

    scored = census.merge(
        selected_cutoffs,
        on="primary_subdivision_code",
        how="left",
        validate="many_to_one",
    )

    mask = pd.Series(True, index=scored.index)
    for metric in SCREEN_METRICS:
        mask &= (
            scored[metric].astype(float)
            >= scored[f"{metric}_frozen_p80_cutoff"].astype(float)
        )

    scored["selected_by_frozen_cmorph_screen"] = mask
    scored["screening_rule_id"] = (
        "CMORPH_REGION_DEVELOPMENT_FIXED_P80_INTERSECTION_MAX_P90_P95_V1"
    )
    scored["screening_role"] = (
        "HIGH_RECALL_RAINFALL_CANDIDATE_RESERVOIR_NOT_NEGATIVE_LABEL"
    )

    reservoir = scored.loc[mask].copy()

    pos_keys = positives[
        ["date_utc", "primary_subdivision_code"]
    ].drop_duplicates().copy()

    pos_audit = positives.merge(
        scored[
            [
                "date_utc",
                "primary_subdivision_code",
                *SCREEN_METRICS,
                *cutoff_cols,
                "selected_by_frozen_cmorph_screen",
            ]
        ],
        on=["date_utc", "primary_subdivision_code"],
        how="left",
        validate="one_to_one",
    )

    if pos_audit[
        "selected_by_frozen_cmorph_screen"
    ].isna().any():
        raise ValueError("some official Positive region-days are missing CMORPH")

    comparison_pool = reservoir.merge(
        pos_keys.assign(_positive_key=True),
        on=["date_utc", "primary_subdivision_code"],
        how="left",
    )
    comparison_pool = comparison_pool.loc[
        comparison_pool["_positive_key"].isna()
    ].drop(columns=["_positive_key"])

    refinement_targets = pd.concat(
        [
            reservoir[
                ["date_utc", "primary_subdivision_code"]
            ],
            pos_keys,
        ],
        ignore_index=True,
    ).drop_duplicates().sort_values(
        ["date_utc", "primary_subdivision_code"],
        kind="mergesort",
    ).reset_index(drop=True)

    refinement_targets = refinement_targets.merge(
        pos_keys.assign(is_official_positive=True),
        on=["date_utc", "primary_subdivision_code"],
        how="left",
    )
    refinement_targets["is_official_positive"] = (
        refinement_targets["is_official_positive"]
        .fillna(False)
        .astype(bool)
    )
    refinement_targets = refinement_targets.merge(
        reservoir[
            ["date_utc", "primary_subdivision_code"]
        ].assign(selected_by_frozen_cmorph_screen=True),
        on=["date_utc", "primary_subdivision_code"],
        how="left",
    )
    refinement_targets["selected_by_frozen_cmorph_screen"] = (
        refinement_targets["selected_by_frozen_cmorph_screen"]
        .fillna(False)
        .astype(bool)
    )
    refinement_targets["refinement_role"] = np.select(
        [
            refinement_targets["is_official_positive"]
            & refinement_targets["selected_by_frozen_cmorph_screen"],
            refinement_targets["is_official_positive"],
            refinement_targets["selected_by_frozen_cmorph_screen"],
        ],
        [
            "POSITIVE_AND_SCREEN_SELECTED",
            "POSITIVE_FORCED_INCLUDE_DESPITE_SCREEN",
            "SCREEN_SELECTED_COMPARISON_CANDIDATE",
        ],
        default="UNEXPECTED",
    )

    if (refinement_targets["refinement_role"] == "UNEXPECTED").any():
        raise AssertionError("unexpected IMERG refinement target role")

    region_summary = (
        scored.groupby("primary_subdivision_code", as_index=False)
        .agg(
            total_2025_days=("date_utc", "size"),
            selected_days=(
                "selected_by_frozen_cmorph_screen",
                "sum",
            ),
        )
    )
    region_summary["selected_fraction"] = (
        region_summary["selected_days"]
        / region_summary["total_2025_days"]
    )

    positive_screen_recall = int(
        pos_audit["selected_by_frozen_cmorph_screen"].sum()
    )

    census_path = (
        outdir
        / "phase2l_j_2025_cmorph_validation_census.csv"
    )
    reservoir_path = (
        outdir
        / "phase2l_j_2025_cmorph_frozen_candidate_reservoir.csv"
    )
    comparison_pool_path = (
        outdir
        / "phase2l_j_2025_cmorph_comparison_candidate_pool.csv"
    )
    positive_audit_path = (
        outdir
        / "phase2l_j_2025_positive_cmorph_screen_audit.csv"
    )
    refinement_targets_path = (
        outdir
        / "phase2l_j_2025_imerg_refinement_targets.csv"
    )
    region_summary_path = (
        outdir
        / "phase2l_j_2025_cmorph_region_screen_summary.csv"
    )
    report_path = (
        outdir
        / "phase2l_j_2025_cmorph_validation_report.json"
    )

    atomic_write_csv(census_path, scored)
    atomic_write_csv(reservoir_path, reservoir)
    atomic_write_csv(comparison_pool_path, comparison_pool)
    atomic_write_csv(positive_audit_path, pos_audit)
    atomic_write_csv(refinement_targets_path, refinement_targets)
    atomic_write_csv(region_summary_path, region_summary)

    report = {
        "schema_version": "1.0.0",
        "phase": "2L-J-2025-validation-cmorph-frozen-screen",
        "gate": PASS_GATE,
        "generated_at_utc": utc_now(),
        "validation_year": 2025,
        "validation_day_count": EXPECTED_DAY_COUNT,
        "validation_region_count": len(validation_codes),
        "validation_region_codes": validation_codes,
        "validation_region_day_count": int(len(scored)),
        "official_positive_region_day_count": int(len(positives)),
        "frozen_screen_selected_region_day_count": int(len(reservoir)),
        "frozen_screen_selected_fraction": float(
            len(reservoir) / len(scored)
        ),
        "comparison_candidate_pool_count_after_positive_exclusion": int(
            len(comparison_pool)
        ),
        "positive_direct_utc_date_screen_recall_count": positive_screen_recall,
        "positive_direct_utc_date_screen_recall_fraction": float(
            positive_screen_recall / len(positives)
        ),
        "positive_screen_recall_is_gate": False,
        "positive_eligibility_conditioned_on_screen": False,
        "imerg_refinement_target_count": int(len(refinement_targets)),
        "positive_forced_include_despite_screen_count": int(
            (
                refinement_targets["refinement_role"]
                == "POSITIVE_FORCED_INCLUDE_DESPITE_SCREEN"
            ).sum()
        ),
        "source_id": "NOAA_CMORPH_CDR_DAILY_0P25DEG",
        "total_cmorph_source_bytes": source_bytes,
        "total_cmorph_source_megabytes_decimal": (
            source_bytes / 1_000_000.0
        ),
        "cutoff_source": "2023-2024_DEVELOPMENT_ONLY",
        "cutoff_reestimated_from_2025": False,
        "screening_rule_id": (
            "CMORPH_REGION_DEVELOPMENT_FIXED_P80_"
            "INTERSECTION_MAX_P90_P95_V1"
        ),
        "screening_metrics": SCREEN_METRICS,
        "screening_logic": "ALL_THREE_METRICS_AT_OR_ABOVE_FROZEN_REGION_CUTOFF",
        "region_domain_note": (
            "Only the 18 regions containing an official 2025 Positive were "
            "decoded because frozen matching requires same-region controls; "
            "other frozen-cutoff regions cannot contribute to any match set."
        ),
        "geometry": geometry_meta,
        "phase2l_h_freeze_sha256": sha256_file(freeze_path),
        "phase2l_i_policy_sha256": sha256_file(policy_path),
        "phase2l_i_dev_reference_report_sha256": sha256_file(
            dev_ref_report_path
        ),
        "validation_rainfall_read": True,
        "validation_era5_environment_read": False,
        "validation_matching_performed": False,
        "pca_refit_on_2025": False,
        "primary_hypothesis_changed": False,
        "hard_negative_label": None,
        "retrospective_2026_read": False,
        "prospective_holdout_read": False,
        "risk_engine_allowed": False,
        "outputs": {
            "validation_census": str(census_path),
            "frozen_candidate_reservoir": str(reservoir_path),
            "comparison_candidate_pool": str(comparison_pool_path),
            "positive_screen_audit": str(positive_audit_path),
            "imerg_refinement_targets": str(refinement_targets_path),
            "region_screen_summary": str(region_summary_path),
        },
    }

    atomic_write_json(report_path, report)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)

    ap.add_argument(
        "--freeze",
        default=(
            "research/phase2/"
            "phase2l_h_validation_protocol_freeze_20260911.json"
        ),
        type=Path,
    )
    ap.add_argument(
        "--policy",
        default=(
            "research/phase2/"
            "phase2l_i_novel_region_reference_extension_policy_20260911.json"
        ),
        type=Path,
    )
    ap.add_argument(
        "--development-reference-report",
        required=True,
        type=Path,
    )
    ap.add_argument(
        "--cutoffs",
        required=True,
        type=Path,
    )
    ap.add_argument(
        "--positive-region-days",
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

    freeze_path = a.freeze.resolve()
    policy_path = a.policy.resolve()
    dev_ref_report_path = a.development_reference_report.resolve()
    cutoff_path = a.cutoffs.resolve()
    positive_path = a.positive_region_days.resolve()
    outdir = a.output_dir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    dev_ref = json.loads(
        dev_ref_report_path.read_text(encoding="utf-8")
    )

    if freeze.get("gate") != EXPECTED_H_FREEZE_GATE:
        raise ValueError(f"Phase 2L-H gate mismatch: {freeze.get('gate')}")
    if policy.get("gate") != EXPECTED_I_POLICY_GATE:
        raise ValueError(f"Phase 2L-I policy gate mismatch: {policy.get('gate')}")
    if dev_ref.get("gate") != EXPECTED_DEV_REF_GATE:
        raise ValueError(
            f"Development reference gate mismatch: {dev_ref.get('gate')}"
        )

    if not dev_ref.get(
        "original_45_region_replay",
        {},
    ).get("exact_key_replay"):
        raise ValueError("5943 Development reservoir replay is not exact")

    positives = pd.read_csv(
        positive_path,
        dtype={"primary_subdivision_code": "string"},
    )
    positives["primary_subdivision_code"] = (
        positives["primary_subdivision_code"]
        .astype("string")
        .str.zfill(6)
    )
    positives["date_utc"] = pd.to_datetime(
        positives["date_utc"]
    ).dt.strftime("%Y-%m-%d")

    if len(positives) != EXPECTED_POSITIVE_REGION_DAY_COUNT:
        raise ValueError(
            f"expected {EXPECTED_POSITIVE_REGION_DAY_COUNT} Positive region-days, "
            f"got {len(positives)}"
        )
    if positives.duplicated(
        ["date_utc", "primary_subdivision_code"]
    ).any():
        raise ValueError("duplicate official Positive region-day keys")

    validation_codes = sorted(
        positives["primary_subdivision_code"].astype(str).unique()
    )
    if len(validation_codes) != EXPECTED_VALIDATION_REGION_COUNT:
        raise ValueError(
            f"expected {EXPECTED_VALIDATION_REGION_COUNT} validation regions, "
            f"got {len(validation_codes)}"
        )

    cutoffs = pd.read_csv(
        cutoff_path,
        dtype={"primary_subdivision_code": "string"},
    )
    cutoffs["primary_subdivision_code"] = (
        cutoffs["primary_subdivision_code"]
        .astype("string")
        .str.zfill(6)
    )

    if len(cutoffs) != EXPECTED_CUTOFF_REGION_COUNT:
        raise ValueError(
            f"expected {EXPECTED_CUTOFF_REGION_COUNT} frozen cutoff regions, "
            f"got {len(cutoffs)}"
        )
    if cutoffs["primary_subdivision_code"].nunique() != len(cutoffs):
        raise ValueError("frozen cutoff region codes are not unique")

    missing_cutoff_codes = sorted(
        set(validation_codes)
        - set(cutoffs["primary_subdivision_code"].astype(str))
    )
    if missing_cutoff_codes:
        raise ValueError(
            f"validation regions lack Development cutoffs: {missing_cutoff_codes}"
        )

    windows, geometry_meta = load_windows(
        codes=validation_codes,
        gis_config=a.gis_config.resolve(),
        era5_config=a.era5_config.resolve(),
    )

    geometry_path = outdir / "phase2l_j_2025_validation_geometry_windows.json"
    atomic_write_json(
        geometry_path,
        {
            "schema_version": "1.0.0",
            "phase": "2L-J-2025-validation-cmorph-geometry",
            "gate": "PASS_2025_VALIDATION_REGION_GEOMETRY_COMPLETE",
            **geometry_meta,
            "risk_engine_allowed": False,
        },
    )

    _, missing_before, _ = collect_daily(
        outdir=outdir,
        codes=validation_codes,
    )

    complete_before = EXPECTED_DAY_COUNT - len(missing_before)

    print("=" * 100)
    print("LPZ PHASE 2L-J — 2025 CMORPH VALIDATION CENSUS / FROZEN SCREEN")
    print("=" * 100)
    print(f"Validation Positive region-days : {len(positives)}")
    print(f"Validation regions               : {len(validation_codes)}")
    print(f"Validation region codes          : {', '.join(validation_codes)}")
    print(f"2025 UTC days target             : {EXPECTED_DAY_COUNT}")
    print(f"Valid checkpoints before run     : {complete_before}")
    print(f"Missing days before run          : {len(missing_before)}")
    print(
        "Max new days this invocation    : "
        + (
            str(a.max_new_days)
            if a.max_new_days is not None
            else "FULL RESUME TO COMPLETION"
        )
    )
    print("CMORPH cutoff source              : 2023-2024 DEVELOPMENT ONLY")
    print("2025 cutoff fitting               : FORBIDDEN")
    print("Download concurrency              : 1")
    print("ERA5/environment read             : NO")
    print("Matching performed                : NO")
    print("Risk engine                       : NOT ALLOWED")
    print("=" * 100)

    new_days = 0
    downloaded_this_run = 0
    started = time.monotonic()

    with tempfile.TemporaryDirectory(
        prefix="phase2l_j_cmorph_"
    ) as td:
        tempdir = Path(td)

        for d in daterange(START_DATE, END_DATE):
            cp = checkpoint_path(outdir, d)

            if validate_checkpoint(
                cp,
                day=d,
                codes=validation_codes,
            ) is not None:
                continue

            if (
                a.max_new_days is not None
                and new_days >= a.max_new_days
            ):
                break

            result = process_day(
                day=d,
                windows=windows,
                codes=validation_codes,
                outdir=outdir,
                tempdir=tempdir,
            )

            if result["status"] == "SUCCESS":
                new_days += 1
                downloaded_this_run += int(
                    result["downloaded_bytes"]
                )
                print(
                    f"[{d.isoformat()}] PASS  "
                    f"{result['downloaded_bytes'] / 1_000_000.0:.3f} MB  "
                    f"{result['elapsed_seconds']:.2f}s"
                )

    rows_after, missing_after, source_bytes = collect_daily(
        outdir=outdir,
        codes=validation_codes,
    )

    complete_after = EXPECTED_DAY_COUNT - len(missing_after)

    if missing_after:
        progress_path = (
            outdir
            / "phase2l_j_2025_cmorph_validation_progress.json"
        )
        atomic_write_json(
            progress_path,
            {
                "schema_version": "1.0.0",
                "phase": "2L-J-2025-validation-cmorph-progress",
                "gate": PARTIAL_GATE,
                "valid_checkpoint_day_count": complete_after,
                "missing_day_count": len(missing_after),
                "new_days_this_run": new_days,
                "downloaded_bytes_this_run": downloaded_this_run,
                "next_missing_date_utc": missing_after[0].isoformat(),
                "validation_rainfall_read": True,
                "era5_environment_read": False,
                "matching_performed": False,
                "risk_engine_allowed": False,
            },
        )

        print("")
        print("=" * 100)
        print(f"Gate                              : {PARTIAL_GATE}")
        print(
            f"Valid checkpoint days             : "
            f"{complete_after} / {EXPECTED_DAY_COUNT}"
        )
        print(f"New days this run                 : {new_days}")
        print(
            f"Downloaded this run               : "
            f"{downloaded_this_run / 1_000_000.0:.3f} MB"
        )
        print(
            f"Next missing date                 : "
            f"{missing_after[0].isoformat()}"
        )
        print("Resume                            : rerun the exact same command")
        print("=" * 100)
        return 0

    report = finalize(
        outdir=outdir,
        rows=rows_after,
        source_bytes=source_bytes,
        positives=positives,
        cutoffs=cutoffs,
        validation_codes=validation_codes,
        freeze_path=freeze_path,
        policy_path=policy_path,
        dev_ref_report_path=dev_ref_report_path,
        geometry_meta=geometry_meta,
    )

    print("")
    print("=" * 100)
    print("LPZ PHASE 2L-J — 2025 CMORPH VALIDATION CENSUS COMPLETE")
    print("=" * 100)
    print(f"Daily checkpoints                 : 365 / 365")
    print(
        f"Validation region-days            : "
        f"{report['validation_region_day_count']}"
    )
    print(
        f"Frozen-screen selected            : "
        f"{report['frozen_screen_selected_region_day_count']}"
    )
    print(
        f"Selected fraction                 : "
        f"{100.0 * report['frozen_screen_selected_fraction']:.2f}%"
    )
    print(
        f"Comparison pool after positives   : "
        f"{report['comparison_candidate_pool_count_after_positive_exclusion']}"
    )
    print(
        f"Positive screen recall            : "
        f"{report['positive_direct_utc_date_screen_recall_count']} / "
        f"{report['official_positive_region_day_count']} "
        f"(DESCRIPTIVE ONLY)"
    )
    print(
        f"IMERG refinement targets          : "
        f"{report['imerg_refinement_target_count']}"
    )
    print(
        f"Positive forced-in despite screen : "
        f"{report['positive_forced_include_despite_screen_count']}"
    )
    print(
        f"CMORPH source downloaded total    : "
        f"{report['total_cmorph_source_megabytes_decimal']:.3f} MB"
    )
    print("Cutoff refit on 2025               : NO")
    print("ERA5/environment read              : NO")
    print("Matching performed                 : NO")
    print("Primary changed                    : NO")
    print("Risk engine                        : NOT ALLOWED")
    print("")
    print(f"Gate                              : {PASS_GATE}")
    print(
        "Report                            : "
        + str(
            outdir
            / "phase2l_j_2025_cmorph_validation_report.json"
        )
    )
    print("=" * 100)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
