#!/usr/bin/env python3
"""O9-D — resumable IMERG Final V08 rainfall rebuild for frozen populations.

This is the production-oriented rainfall stage for the V08 re-entry path.  It is
parameterized by split so Development and 2025 Validation use the same scientific
engine while preserving different population invariants.

Hard safeguards
---------------
- accepts only NASA GPM_3IMERGHH collection version 08
- Development target membership must be exactly 5,943 region-days in 2023-2024
- Validation target membership must be exactly 1,218 region-days in 2025 and
  contain exactly 23 official Positive region-days
- requires a PASS O9-C exact-slot coverage evidence file before live processing
- 58 exact half-hour starts / target day, 53 exact rolling 3-hour windows
- no missing-slot interpolation or V07/V08 mixture
- one target UTC day per atomic checkpoint; valid checkpoints are resumable
- global IMERG payloads are decoded sequentially; only small regional arrays are
  retained in memory; raw HDF5 files are deleted after each day
- no ERA5, matching, PCA, Primary outcome, or Risk Engine code is imported/read
- final O9 chain evidence is written only after the entire split is complete
- if final evidence already exists, the script refuses to rerun that scientific
  stage; the one-shot evidence chain remains immutable
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from lpz_risk.historical_spatial import build_primary_subdivision_geojson
from lpz_risk.imerg_final import decode_imerg_final_file, parse_imerg_final_filename
from lpz_risk.o9_v08_rebuild import (
    EXPECTED_ROLLING_WINDOWS,
    EXPECTED_SLOT_COUNT,
    compute_metrics_from_slot_amounts,
    expected_slot_starts,
)

SHORT_NAME = "GPM_3IMERGHH"
IMERG_VERSION = "08"
SOURCE_ID = "NASA_IMERG_FINAL_V08"
JAPAN_BBOX = (122.0, 24.0, 150.0, 47.0)
PADDING_DEG = 0.5
ENGINE_CONTRACT = "O9_D_V08_ROLLING_3H_V1"

SPLIT_RULES = {
    "DEVELOPMENT": {
        "expected_rows": 5943,
        "allowed_years": {2023, 2024},
        "gate": "PASS_O9_D_V08_DEVELOPMENT_REBUILD_5943",
        "evidence_filename": "o9_d_development_v08_rebuild.json",
    },
    "VALIDATION_2025": {
        "expected_rows": 1218,
        "allowed_years": {2025},
        "expected_positive_rows": 23,
        "gate": "PASS_O9_D_V08_VALIDATION_REBUILD_1218",
        "evidence_filename": "o9_d_validation_v08_rebuild.json",
    },
}

DAILY_GATE = "PASS_O9_D_V08_RAINFALL_REBUILD_DAY"
COVERAGE_GATE = "PASS_O9_C_V08_FULL_REQUIRED_COVERAGE"
DEV_GATE = "PASS_O9_D_V08_DEVELOPMENT_REBUILD_5943"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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


def parse_bool_series(s: pd.Series, *, name: str) -> pd.Series:
    def one(v: Any) -> bool:
        if isinstance(v, (bool, np.bool_)):
            return bool(v)
        text = str(v).strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
        raise ValueError(f"invalid boolean in {name}: {v!r}")
    return s.map(one).astype(bool)


def read_targets(path: Path, split: str) -> pd.DataFrame:
    if split not in SPLIT_RULES:
        raise ValueError(f"unsupported split: {split}")
    rule = SPLIT_RULES[split]
    df = pd.read_csv(path, dtype={"primary_subdivision_code": "string"})
    required = {"date_utc", "primary_subdivision_code"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"target CSV missing required columns: {missing}")

    df = df.copy()
    df["date_utc"] = pd.to_datetime(df["date_utc"], utc=True).dt.strftime("%Y-%m-%d")
    df["primary_subdivision_code"] = df["primary_subdivision_code"].astype("string").str.zfill(6)
    if df["primary_subdivision_code"].isna().any() or (df["primary_subdivision_code"].str.len() != 6).any():
        raise ValueError("invalid primary_subdivision_code in target CSV")
    if df.duplicated(["date_utc", "primary_subdivision_code"]).any():
        dup = df.loc[df.duplicated(["date_utc", "primary_subdivision_code"], keep=False), ["date_utc", "primary_subdivision_code"]]
        raise ValueError(f"duplicate target region-day keys: {dup.head().to_dict('records')}")

    if len(df) != int(rule["expected_rows"]):
        raise ValueError(f"{split} target count must be {rule['expected_rows']}, got {len(df)}")
    years = set(pd.to_datetime(df["date_utc"]).dt.year.astype(int).tolist())
    if not years or not years.issubset(rule["allowed_years"]):
        raise ValueError(f"{split} target years invalid: {sorted(years)}")

    if split == "VALIDATION_2025":
        if "is_official_positive" not in df.columns:
            raise ValueError("Validation targets require is_official_positive")
        df["is_official_positive"] = parse_bool_series(df["is_official_positive"], name="is_official_positive")
        count = int(df["is_official_positive"].sum())
        if count != int(rule["expected_positive_rows"]):
            raise ValueError(f"Validation official Positive count must be 23, got {count}")

    return df.sort_values(["date_utc", "primary_subdivision_code"], kind="mergesort").reset_index(drop=True)


def verify_coverage_evidence(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    checks = {
        "gate": obj.get("gate") == COVERAGE_GATE,
        "short_name": obj.get("short_name") == SHORT_NAME,
        "version": str(obj.get("imerg_final_version")).zfill(2) == IMERG_VERSION,
        "official_final_product": obj.get("official_final_product") is True,
        "development_rows": int(obj.get("development_region_day_count", -1)) == 5943,
        "validation_rows": int(obj.get("validation_region_day_count", -1)) == 1218,
        "development_missing_zero": int(obj.get("development_missing_slot_count", -1)) == 0,
        "validation_missing_zero": int(obj.get("validation_missing_slot_count", -1)) == 0,
        "all_covered": obj.get("all_required_slots_covered") is True,
        "risk_locked": obj.get("risk_engine_allowed") is False,
    }
    if not all(checks.values()):
        raise ValueError(f"O9-C coverage evidence is not PASS-compatible: {checks}")
    return {"sha256": sha256_file(path), "checks": checks}


def verify_development_evidence(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    checks = {
        "gate": obj.get("gate") == DEV_GATE,
        "split": obj.get("split") == "DEVELOPMENT",
        "rows": int(obj.get("region_day_count", -1)) == 5943,
        "version": str(obj.get("imerg_final_version")).zfill(2) == IMERG_VERSION,
        "environment_unused": obj.get("environment_variables_used") is False,
        "risk_locked": obj.get("risk_engine_allowed") is False,
    }
    if not all(checks.values()):
        raise ValueError(f"Development O9-D evidence is not PASS-compatible: {checks}")
    return {"sha256": sha256_file(path), "checks": checks}


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
        raise ValueError("empty JMA region geometry")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (
        max(JAPAN_BBOX[0], min(xs) - PADDING_DEG),
        max(JAPAN_BBOX[1], min(ys) - PADDING_DEG),
        min(JAPAN_BBOX[2], max(xs) + PADDING_DEG),
        min(JAPAN_BBOX[3], max(ys) + PADDING_DEG),
    )


def download_small_file(url: str, dst: Path, tries: int = 5) -> None:
    last: Exception | None = None
    for i in range(tries):
        try:
            req = Request(url, headers={"User-Agent": "lpz-risk-system/0.1 O9-D-V08"})
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
    raise RuntimeError(f"download failed: {url}: {type(last).__name__}: {last}") from last


def load_geometry_windows(
    codes: list[str],
    gis_config: Path,
    era5_config: Path,
) -> tuple[dict[str, tuple[float, float, float, float]], dict[str, Any]]:
    era5 = json.loads(era5_config.read_text(encoding="utf-8"))
    padding = float(era5["spatial_sampling"]["bbox_padding_degrees"])
    if not math.isclose(padding, PADDING_DEG, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"frozen bbox padding mismatch: expected {PADDING_DEG}, got {padding}")
    gis = json.loads(gis_config.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="o9_d_geometry_") as td:
        jzip = Path(td) / "jma.zip"
        download_small_file(str(gis["zip_url"]), jzip)
        zip_sha = sha256_file(jzip)
        geo = build_primary_subdivision_geojson(jzip.read_bytes(), set(codes))
    if not geo.get("geometry_complete_for_required_codes"):
        raise RuntimeError(f"missing JMA geometries: {geo.get('missing_required_codes')}")
    feats = {
        str(f["properties"]["primary_subdivision_code"]).zfill(6): f["geometry"]
        for f in geo["features"]
    }
    if set(feats) != set(codes):
        raise RuntimeError("JMA geometry code set differs from frozen target code set")
    windows = {code: matched_window(feats[code]) for code in codes}
    meta = {
        "gis_zip_url": str(gis["zip_url"]),
        "gis_zip_sha256": zip_sha,
        "padding_degrees": PADDING_DEG,
        "japan_bbox_wsen": list(JAPAN_BBOX),
        "region_count": len(codes),
        "spatial_semantics": "OFFICIAL_JMA_PRIMARY_SUBDIVISION_BBOX_PLUS_FROZEN_ERA5_0P5_DEG_PADDING",
    }
    return windows, meta


def earthdata_login() -> None:
    import earthaccess
    auth = earthaccess.login()
    if not bool(getattr(auth, "authenticated", False)):
        raise RuntimeError("Earthdata authentication required for O9-D")


def download_v08_slots(day: str, dest: Path, tries: int = 5) -> dict[datetime, Path]:
    import earthaccess
    expected = expected_slot_starts(day)
    start = expected[0]
    end = expected[-1] + timedelta(minutes=29, seconds=59)
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
                raise RuntimeError("no Final V08 granules returned")
            raw = earthaccess.download(granules, str(dest), threads=1)
            paths = [Path(p) for p in raw if Path(p).exists() and Path(p).stat().st_size >= 1024]
            mapping: dict[datetime, Path] = {}
            duplicates: list[str] = []
            for p in paths:
                try:
                    slot_start, _slot_end, version = parse_imerg_final_filename(p.name)
                except ValueError:
                    continue
                if version != IMERG_VERSION or slot_start not in expected:
                    continue
                if slot_start in mapping:
                    duplicates.append(slot_start.isoformat())
                mapping[slot_start] = p
            if duplicates:
                raise RuntimeError(f"duplicate V08 granules for exact slots: {duplicates[:10]}")
            missing = [x.isoformat() for x in expected if x not in mapping]
            if missing:
                raise RuntimeError(f"missing exact V08 slots for {day}: {missing[:10]} count={len(missing)}")
            return mapping
        except Exception as exc:  # noqa: BLE001
            last = exc
            shutil.rmtree(dest, ignore_errors=True)
            dest.mkdir(parents=True, exist_ok=True)
            if i + 1 < tries:
                time.sleep(15 * (i + 1))
    raise RuntimeError(f"V08 slot download failed after {tries} attempts: {type(last).__name__}: {last}") from last


def checkpoint_path(outdir: Path, split: str, date_s: str) -> Path:
    return outdir / split.lower() / "daily" / date_s[:7] / f"{date_s}.json"


def validate_checkpoint(
    path: Path,
    *,
    split: str,
    date_s: str,
    expected_codes: list[str],
    target_sha256: str,
    coverage_sha256: str,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    checks = [
        obj.get("gate") == DAILY_GATE,
        obj.get("engine_contract") == ENGINE_CONTRACT,
        obj.get("split") == split,
        obj.get("date_utc") == date_s,
        obj.get("source_id") == SOURCE_ID,
        str(obj.get("imerg_final_version")).zfill(2) == IMERG_VERSION,
        int(obj.get("expected_slot_count", -1)) == EXPECTED_SLOT_COUNT,
        int(obj.get("available_slot_count", -1)) == EXPECTED_SLOT_COUNT,
        int(obj.get("rolling_window_count_per_region_day", -1)) == EXPECTED_ROLLING_WINDOWS,
        obj.get("missing_slots") == [],
        obj.get("target_csv_sha256") == target_sha256,
        obj.get("coverage_evidence_sha256") == coverage_sha256,
        obj.get("validation_era5_environment_read") is False,
        obj.get("risk_engine_allowed") is False,
    ]
    if not all(checks):
        return None
    rows = obj.get("rows")
    if not isinstance(rows, list):
        return None
    observed = sorted(str(r.get("primary_subdivision_code", "")).zfill(6) for r in rows)
    if observed != sorted(expected_codes):
        return None
    for r in rows:
        if int(r.get("rolling_window_count", -1)) != EXPECTED_ROLLING_WINDOWS:
            return None
        for stat in ("mean", "max", "p90", "p95"):
            try:
                v = float(r[f"imerg_3h_{stat}_max_mm"])
            except Exception:
                return None
            if not math.isfinite(v) or v < 0:
                return None
            if not r.get(f"imerg_3h_{stat}_window_start_utc") or not r.get(f"imerg_3h_{stat}_window_end_utc"):
                return None
    return obj


def target_metadata_row(row: pd.Series) -> dict[str, Any]:
    out: dict[str, Any] = {
        "date_utc": str(row["date_utc"]),
        "primary_subdivision_code": str(row["primary_subdivision_code"]).zfill(6),
    }
    for key in ("is_official_positive", "selected_by_frozen_cmorph_screen", "refinement_role"):
        if key not in row.index:
            continue
        value = row[key]
        if pd.isna(value):
            continue
        if key in {"is_official_positive", "selected_by_frozen_cmorph_screen"}:
            out[key] = bool(value)
        else:
            out[key] = str(value)
    return out


def process_day(
    *,
    split: str,
    date_s: str,
    day_targets: pd.DataFrame,
    windows: dict[str, tuple[float, float, float, float]],
    outdir: Path,
    temp_root: Path,
    target_sha256: str,
    coverage_sha256: str,
) -> dict[str, Any]:
    codes = sorted(day_targets["primary_subdivision_code"].astype(str).unique())
    cp = checkpoint_path(outdir, split, date_s)
    existing = validate_checkpoint(
        cp,
        split=split,
        date_s=date_s,
        expected_codes=codes,
        target_sha256=target_sha256,
        coverage_sha256=coverage_sha256,
    )
    if existing is not None:
        return {"status": "SKIP_VALID_CHECKPOINT", "downloaded_bytes": 0, "elapsed_seconds": 0.0}

    ddir = temp_root / split.lower() / date_s
    shutil.rmtree(ddir, ignore_errors=True)
    ddir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        slot_files = download_v08_slots(date_s, ddir)
        expected = expected_slot_starts(date_s)
        code_amounts: dict[str, list[np.ndarray]] = {code: [] for code in codes}
        region_indices: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        reference_lon: np.ndarray | None = None
        reference_lat: np.ndarray | None = None
        source_bytes = 0

        for index, ts in enumerate(expected):
            fp = slot_files[ts]
            source_bytes += fp.stat().st_size
            field = decode_imerg_final_file(fp, expected_version=IMERG_VERSION)
            observed_start = field.valid_start_utc.astimezone(timezone.utc)
            if observed_start != ts:
                raise RuntimeError(f"decoded V08 time mismatch at slot {index}: expected {ts}, got {observed_start}")
            if field.accumulation_seconds != 1800 or field.source_id != SOURCE_ID:
                raise RuntimeError(f"decoded V08 identity/interval mismatch at slot {index}")
            lon = np.asarray(field.longitude_deg_e, dtype=float)
            lat = np.asarray(field.latitude_deg_n, dtype=float)
            if reference_lon is None:
                reference_lon = lon.copy()
                reference_lat = lat.copy()
                for code in codes:
                    west, south, east, north = windows[code]
                    ix = np.where((lon >= west) & (lon <= east))[0]
                    iy = np.where((lat >= south) & (lat <= north))[0]
                    if ix.size == 0 or iy.size == 0:
                        raise RuntimeError(f"empty V08 matched window {date_s} {code}")
                    region_indices[code] = (iy, ix)
            else:
                assert reference_lat is not None
                if (
                    lon.shape != reference_lon.shape
                    or lat.shape != reference_lat.shape
                    or not np.allclose(lon, reference_lon)
                    or not np.allclose(lat, reference_lat)
                ):
                    raise RuntimeError(f"IMERG V08 grid changed within {date_s} at slot {index}")
            amount = np.asarray(field.accumulation_mm, dtype=float)
            for code in codes:
                iy, ix = region_indices[code]
                code_amounts[code].append(amount[np.ix_(iy, ix)].copy())

        rows: list[dict[str, Any]] = []
        for code in codes:
            matches = day_targets.loc[day_targets["primary_subdivision_code"].astype(str) == code]
            if len(matches) != 1:
                raise RuntimeError(f"{date_s} {code}: expected exactly one target row")
            row = target_metadata_row(matches.iloc[0])
            row.update(compute_metrics_from_slot_amounts(day=date_s, slot_amounts_mm=code_amounts[code]))
            rows.append(row)

        payload = {
            "schema_version": "1.0.0",
            "phase": "O9-D-V08-rainfall-rebuild-daily",
            "gate": DAILY_GATE,
            "engine_contract": ENGINE_CONTRACT,
            "generated_at_utc": utc_now(),
            "split": split,
            "date_utc": date_s,
            "source_id": SOURCE_ID,
            "short_name": SHORT_NAME,
            "imerg_final_version": IMERG_VERSION,
            "official_final_product": True,
            "target_region_day_count": len(rows),
            "target_region_codes": codes,
            "expected_slot_count": EXPECTED_SLOT_COUNT,
            "available_slot_count": EXPECTED_SLOT_COUNT,
            "missing_slots": [],
            "native_slot_minutes": 30,
            "slots_per_3h_window": 6,
            "rolling_window_count_per_region_day": EXPECTED_ROLLING_WINDOWS,
            "rolling_start_range": "PREVIOUS_DAY_21:30_UTC_THROUGH_CANDIDATE_DAY_23:30_UTC_INCLUSIVE",
            "boundary_crossing_windows_included": True,
            "missing_slot_interpolation": False,
            "version_mixing_allowed": False,
            "download_threads": 1,
            "downloaded_source_bytes": source_bytes,
            "target_csv_sha256": target_sha256,
            "coverage_evidence_sha256": coverage_sha256,
            "rows": rows,
            "environment_variables_used": False,
            "validation_era5_environment_read": False,
            "matching_performed": False,
            "pca_fit_performed": False,
            "primary_confirmatory_test_run": False,
            "risk_engine_allowed": False,
            "elapsed_seconds": time.monotonic() - started,
        }
        atomic_write_json(cp, payload)
        return {
            "status": "SUCCESS",
            "downloaded_bytes": source_bytes,
            "elapsed_seconds": float(payload["elapsed_seconds"]),
            "target_count": len(rows),
        }
    finally:
        shutil.rmtree(ddir, ignore_errors=True)


def collect_checkpoints(
    *,
    split: str,
    outdir: Path,
    targets: pd.DataFrame,
    target_sha256: str,
    coverage_sha256: str,
) -> tuple[list[dict[str, Any]], list[str], int]:
    rows: list[dict[str, Any]] = []
    missing_dates: list[str] = []
    source_bytes = 0
    for date_s, day_targets in targets.groupby("date_utc", sort=True):
        codes = sorted(day_targets["primary_subdivision_code"].astype(str).unique())
        obj = validate_checkpoint(
            checkpoint_path(outdir, split, str(date_s)),
            split=split,
            date_s=str(date_s),
            expected_codes=codes,
            target_sha256=target_sha256,
            coverage_sha256=coverage_sha256,
        )
        if obj is None:
            missing_dates.append(str(date_s))
            continue
        rows.extend(obj["rows"])
        source_bytes += int(obj.get("downloaded_source_bytes") or 0)
    return rows, missing_dates, source_bytes


def finalize(
    *,
    split: str,
    outdir: Path,
    targets: pd.DataFrame,
    rows: list[dict[str, Any]],
    source_bytes: int,
    target_sha256: str,
    coverage_path: Path,
    coverage_sha256: str,
    geometry_meta: dict[str, Any],
    evidence_path: Path,
    development_evidence: Path | None,
) -> dict[str, Any]:
    rule = SPLIT_RULES[split]
    result = pd.DataFrame(rows)
    if len(result) != len(targets):
        raise ValueError(f"{split} expected {len(targets)} completed rows, got {len(result)}")
    result["primary_subdivision_code"] = result["primary_subdivision_code"].astype("string").str.zfill(6)
    result["date_utc"] = pd.to_datetime(result["date_utc"], utc=True).dt.strftime("%Y-%m-%d")
    if result.duplicated(["date_utc", "primary_subdivision_code"]).any():
        raise ValueError("duplicate rebuilt region-day keys")
    expected_keys = set(map(tuple, targets[["date_utc", "primary_subdivision_code"]].astype(str).to_numpy()))
    observed_keys = set(map(tuple, result[["date_utc", "primary_subdivision_code"]].astype(str).to_numpy()))
    if expected_keys != observed_keys:
        raise ValueError(
            f"frozen membership changed: missing={len(expected_keys-observed_keys)} extra={len(observed_keys-expected_keys)}"
        )
    result = result.sort_values(["date_utc", "primary_subdivision_code"], kind="mergesort").reset_index(drop=True)

    output_csv = outdir / split.lower() / f"o9_d_{split.lower()}_v08_rolling_3h.csv"
    atomic_write_csv(output_csv, result)

    requires: dict[str, str] = {coverage_path.name: coverage_sha256}
    dev_meta: dict[str, Any] | None = None
    if split == "VALIDATION_2025":
        if development_evidence is None:
            raise ValueError("Validation finalization requires Development O9-D evidence")
        dev_meta = verify_development_evidence(development_evidence)
        requires[development_evidence.name] = dev_meta["sha256"]

    evidence: dict[str, Any] = {
        "schema_version": "1.0.0",
        "phase": "O9-D-V08-rainfall-rebuild-complete",
        "gate": str(rule["gate"]),
        "generated_at_utc": utc_now(),
        "engine_contract": ENGINE_CONTRACT,
        "split": split,
        "source_id": SOURCE_ID,
        "short_name": SHORT_NAME,
        "imerg_final_version": IMERG_VERSION,
        "official_final_product": True,
        "region_day_count": int(len(result)),
        "unique_utc_day_count": int(result["date_utc"].nunique()),
        "native_slot_minutes": 30,
        "slot_count_per_target_utc_day": EXPECTED_SLOT_COUNT,
        "slots_per_3h_window": 6,
        "rolling_window_count_per_region_day": EXPECTED_ROLLING_WINDOWS,
        "boundary_crossing_windows_included": True,
        "missing_slot_interpolation": False,
        "version_mixing_allowed": False,
        "candidate_membership_changed": False,
        "environment_variables_used": False,
        "validation_era5_environment_read": False,
        "matching_performed": False,
        "pca_fit_performed": False,
        "primary_confirmatory_test_run": False,
        "target_csv_sha256": target_sha256,
        "coverage_evidence_sha256": coverage_sha256,
        "total_downloaded_source_bytes_across_checkpoints": int(source_bytes),
        "output_csv": str(output_csv),
        "output_csv_sha256": sha256_file(output_csv),
        "geometry": geometry_meta,
        "requires_sha256": requires,
        "risk_engine_allowed": False,
    }
    if split == "VALIDATION_2025":
        positives = int(parse_bool_series(result["is_official_positive"], name="is_official_positive").sum())
        if positives != 23:
            raise ValueError(f"final Validation Positive count must be 23, got {positives}")
        evidence["official_positive_region_day_count"] = positives
        evidence["development_evidence_verified"] = dev_meta
    else:
        evidence["validation_data_used"] = False

    if evidence_path.exists():
        raise FileExistsError(
            f"immutable O9-D evidence already exists: {evidence_path}; refuse scientific rerun"
        )
    atomic_write_json(evidence_path, evidence)
    return evidence


def write_progress(
    *,
    path: Path,
    split: str,
    targets: pd.DataFrame,
    completed_rows: list[dict[str, Any]],
    missing_dates: list[str],
    new_days_processed: int,
) -> None:
    atomic_write_json(path, {
        "schema_version": "1.0.0",
        "phase": "O9-D-V08-rainfall-rebuild-progress",
        "generated_at_utc": utc_now(),
        "split": split,
        "target_region_day_count": int(len(targets)),
        "completed_region_day_count": int(len(completed_rows)),
        "total_target_utc_day_count": int(targets["date_utc"].nunique()),
        "remaining_utc_day_count": len(missing_dates),
        "remaining_dates_preview": missing_dates[:30],
        "new_days_processed_this_run": new_days_processed,
        "complete": len(missing_dates) == 0,
        "validation_era5_environment_read": False,
        "risk_engine_allowed": False,
    })


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", required=True, choices=sorted(SPLIT_RULES))
    ap.add_argument("--targets", required=True, type=Path)
    ap.add_argument("--coverage-evidence", required=True, type=Path)
    ap.add_argument("--development-evidence", type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument("--evidence-output", required=True, type=Path)
    ap.add_argument("--gis-config", type=Path, default=Path("config/jma_primary_subdivision_gis.json"))
    ap.add_argument("--era5-spatial-config", type=Path, default=Path("config/historical_environment_era5.json"))
    ap.add_argument("--temp-root", type=Path, default=Path("work/o9_v08_rainfall"))
    ap.add_argument("--max-new-days", type=int, default=0, help="0 means no cap")
    args = ap.parse_args()

    if args.evidence_output.exists():
        raise FileExistsError(
            f"immutable final evidence already exists: {args.evidence_output}; no rerun allowed"
        )

    targets = read_targets(args.targets, args.split)
    target_sha = sha256_file(args.targets)
    coverage = verify_coverage_evidence(args.coverage_evidence)
    coverage_sha = coverage["sha256"]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.temp_root.mkdir(parents=True, exist_ok=True)
    codes = sorted(targets["primary_subdivision_code"].astype(str).unique())
    windows, geometry_meta = load_geometry_windows(codes, args.gis_config, args.era5_spatial_config)

    rows, missing_dates, source_bytes = collect_checkpoints(
        split=args.split,
        outdir=args.output_dir,
        targets=targets,
        target_sha256=target_sha,
        coverage_sha256=coverage_sha,
    )

    if missing_dates:
        earthdata_login()
    new_days = 0
    for date_s in list(missing_dates):
        if args.max_new_days > 0 and new_days >= args.max_new_days:
            break
        day_targets = targets.loc[targets["date_utc"] == date_s].copy()
        result = process_day(
            split=args.split,
            date_s=date_s,
            day_targets=day_targets,
            windows=windows,
            outdir=args.output_dir,
            temp_root=args.temp_root,
            target_sha256=target_sha,
            coverage_sha256=coverage_sha,
        )
        if result["status"] == "SUCCESS":
            new_days += 1
        print(json.dumps({"date_utc": date_s, **result}, ensure_ascii=False))

    rows, missing_dates, source_bytes = collect_checkpoints(
        split=args.split,
        outdir=args.output_dir,
        targets=targets,
        target_sha256=target_sha,
        coverage_sha256=coverage_sha,
    )
    progress_path = args.output_dir / args.split.lower() / "o9_d_progress.json"
    write_progress(
        path=progress_path,
        split=args.split,
        targets=targets,
        completed_rows=rows,
        missing_dates=missing_dates,
        new_days_processed=new_days,
    )

    if missing_dates:
        print(json.dumps({
            "state": "PARTIAL_O9_D_V08_REBUILD_CHECKPOINTED",
            "split": args.split,
            "completed_rows": len(rows),
            "remaining_dates": len(missing_dates),
            "risk_engine_allowed": False,
        }))
        return 4

    evidence = finalize(
        split=args.split,
        outdir=args.output_dir,
        targets=targets,
        rows=rows,
        source_bytes=source_bytes,
        target_sha256=target_sha,
        coverage_path=args.coverage_evidence,
        coverage_sha256=coverage_sha,
        geometry_meta=geometry_meta,
        evidence_path=args.evidence_output,
        development_evidence=args.development_evidence,
    )
    print(json.dumps({
        "gate": evidence["gate"],
        "split": args.split,
        "region_day_count": evidence["region_day_count"],
        "risk_engine_allowed": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
