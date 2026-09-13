"""O9-G guarded 2025 ERA5 opening kernel.

This module is deliberately network-free.  It validates the frozen O9-F 92-case
population and builds the only ERA5 request manifest that a later authenticated
retriever is allowed to consume.  Creating a manifest/receipt authorizes retrieval;
it does not download ERA5, inspect environmental outcomes, run the frozen Primary,
or unlock the Risk Engine.
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

SOURCE_ID = "NASA_IMERG_FINAL_V08"
IMERG_VERSION = "08"
SHORT_NAME = "GPM_3IMERGHH"
POSITIVE_ROLE = "POSITIVE"
COMPARISON_ROLE = "RAINFALL_MATCHED_COMPARISON_NOT_NEGATIVE_LABEL"
TIME_ANCHOR_POLICY = "IMERG_3H_P95_MAX_WINDOW_START"
TIME_ANCHOR_START_COLUMN = "imerg_3h_p95_window_start_utc"
TIME_ANCHOR_END_COLUMN = "imerg_3h_p95_window_end_utc"
SNAPSHOT_OFFSETS_HOURS = (-12, -6, -3, 0)
EXPECTED_CASE_COUNT = 92
EXPECTED_POSITIVE_COUNT = 23
EXPECTED_COMPARISON_COUNT = 69
EXPECTED_SNAPSHOT_COUNT = EXPECTED_CASE_COUNT * len(SNAPSHOT_OFFSETS_HOURS)
ERA5_PROVIDER = "COPERNICUS_CDS_ERA5"
ERA5_DATASET = "reanalysis-era5-pressure-levels"
ERA5_TIME_POLICY = "FLOOR_TO_AVAILABLE_HOUR_NO_FUTURE_SOURCE_TIME"
SPATIAL_SEMANTICS = "JMA_PRIMARY_SUBDIVISION_BBOX_PLUS_FROZEN_0P5_DEG_PADDING_CONTEXT_NOT_POLYGON_MEAN"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"JSON object required: {path}")
    return obj


def parse_utc(value: Any, *, name: str) -> pd.Timestamp:
    try:
        ts = pd.Timestamp(value)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid UTC timestamp in {name}: {value!r}") from exc
    if ts.tzinfo is None:
        raise ValueError(f"timezone-aware UTC timestamp required in {name}: {value!r}")
    ts = ts.tz_convert("UTC")
    return ts


def iso_z(ts: pd.Timestamp) -> str:
    return ts.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def floor_to_hour(ts: pd.Timestamp) -> pd.Timestamp:
    ts = ts.tz_convert("UTC")
    return ts.floor("h")


def validate_final_matched_population(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "date_utc",
        "primary_subdivision_code",
        "case_role",
        "match_set_id",
        "match_rank",
        "is_official_positive",
        "source_id",
        "imerg_final_version",
        TIME_ANCHOR_START_COLUMN,
        TIME_ANCHOR_END_COLUMN,
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"O9-G final matched population missing columns: {missing}")

    df = frame.copy()
    if len(df) != EXPECTED_CASE_COUNT:
        raise ValueError(f"O9-G requires exactly {EXPECTED_CASE_COUNT} frozen cases, got {len(df)}")

    df["date_utc"] = pd.to_datetime(df["date_utc"], utc=True, errors="raise").dt.strftime("%Y-%m-%d")
    df["primary_subdivision_code"] = df["primary_subdivision_code"].astype("string").str.zfill(6)
    if df[["date_utc", "primary_subdivision_code"]].duplicated().any():
        raise ValueError("O9-G final matched population contains duplicate region-day keys")
    if set(pd.to_datetime(df["date_utc"]).dt.year.astype(int)) != {2025}:
        raise ValueError("O9-G final matched population must contain 2025 only")
    if not (df["source_id"].astype(str) == SOURCE_ID).all():
        raise ValueError("O9-G final matched population contains a non-Final-V08 source_id")
    versions = df["imerg_final_version"].astype(str).str.replace(".0", "", regex=False).str.zfill(2)
    if not (versions == IMERG_VERSION).all():
        raise ValueError("O9-G final matched population contains a non-V08 IMERG version")

    roles = df["case_role"].astype(str)
    role_counts = roles.value_counts().to_dict()
    if int(role_counts.get(POSITIVE_ROLE, 0)) != EXPECTED_POSITIVE_COUNT:
        raise ValueError(f"O9-G requires {EXPECTED_POSITIVE_COUNT} Positive cases")
    if int(role_counts.get(COMPARISON_ROLE, 0)) != EXPECTED_COMPARISON_COUNT:
        raise ValueError(f"O9-G requires {EXPECTED_COMPARISON_COUNT} rainfall-matched comparisons")
    if set(role_counts) != {POSITIVE_ROLE, COMPARISON_ROLE}:
        raise ValueError(f"O9-G unexpected case_role values: {sorted(role_counts)}")

    bool_text = df["is_official_positive"].astype(str).str.strip().str.lower()
    truth = bool_text.isin({"true", "1", "yes", "y"})
    falsehood = bool_text.isin({"false", "0", "no", "n"})
    if not (truth | falsehood).all():
        raise ValueError("O9-G invalid is_official_positive values")
    if not truth.equals(roles.eq(POSITIVE_ROLE)):
        raise ValueError("O9-G case_role and official Positive label disagree")

    ranks = pd.to_numeric(df["match_rank"], errors="raise").astype(int)
    df["match_rank"] = ranks
    groups = list(df.groupby("match_set_id", sort=False))
    if len(groups) != EXPECTED_POSITIVE_COUNT:
        raise ValueError(f"O9-G requires exactly {EXPECTED_POSITIVE_COUNT} match sets, got {len(groups)}")
    for match_set_id, group in groups:
        if len(group) != 4:
            raise ValueError(f"O9-G match set {match_set_id} must contain 4 cases")
        pos = group.loc[group["case_role"] == POSITIVE_ROLE]
        cmp_ = group.loc[group["case_role"] == COMPARISON_ROLE]
        if len(pos) != 1 or int(pos.iloc[0]["match_rank"]) != 0:
            raise ValueError(f"O9-G match set {match_set_id} must contain one rank-0 Positive")
        if sorted(cmp_["match_rank"].astype(int).tolist()) != [1, 2, 3]:
            raise ValueError(f"O9-G match set {match_set_id} comparison ranks must be 1,2,3")

    starts: list[str] = []
    ends: list[str] = []
    for i, row in df.iterrows():
        start = parse_utc(row[TIME_ANCHOR_START_COLUMN], name=f"{TIME_ANCHOR_START_COLUMN}[{i}]")
        end = parse_utc(row[TIME_ANCHOR_END_COLUMN], name=f"{TIME_ANCHOR_END_COLUMN}[{i}]")
        if end - start != pd.Timedelta(hours=3):
            raise ValueError(f"O9-G IMERG P95 window must be exactly 3h for row {i}")
        starts.append(iso_z(start))
        ends.append(iso_z(end))
    df[TIME_ANCHOR_START_COLUMN] = starts
    df[TIME_ANCHOR_END_COLUMN] = ends

    return df.sort_values(["match_set_id", "match_rank"], kind="mergesort").reset_index(drop=True)


def load_geometry_context(
    *,
    era5_config: dict[str, Any],
    geometry_registry: dict[str, Any],
    required_codes: set[str],
) -> dict[str, list[float]]:
    if era5_config.get("provider") != ERA5_PROVIDER:
        raise ValueError("O9-G ERA5 provider mismatch")
    if era5_config.get("dataset") != ERA5_DATASET:
        raise ValueError("O9-G ERA5 dataset mismatch")
    alignment = era5_config.get("time_alignment") or {}
    if alignment.get("policy") != "FLOOR_TO_AVAILABLE_HOUR":
        raise ValueError("O9-G ERA5 time-alignment policy changed")
    if alignment.get("future_source_time_allowed") is not False:
        raise ValueError("O9-G ERA5 config unexpectedly allows future source time")
    if int(alignment.get("max_source_lag_minutes", -1)) != 59:
        raise ValueError("O9-G ERA5 max source lag must remain 59 minutes")
    spatial = era5_config.get("spatial_sampling") or {}
    padding = float(spatial.get("bbox_padding_degrees", -1))
    if padding != 0.5:
        raise ValueError("O9-G frozen ERA5 bbox padding must be 0.5 degrees")
    if geometry_registry.get("source_id") != "JMA_PRIMARY_SUBDIVISION_GIS":
        raise ValueError("O9-G geometry registry source mismatch")
    if geometry_registry.get("geometry_complete_for_required_codes") is not True:
        raise ValueError("O9-G geometry registry is not complete")

    bbox_by_code: dict[str, list[float]] = {}
    for region in geometry_registry.get("regions") or []:
        code = str(region.get("primary_subdivision_code", "")).zfill(6)
        bbox = region.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        west, south, east, north = map(float, bbox)
        # CDS area order is North, West, South, East.  This is a retrieval envelope,
        # never a subdivision-polygon mean.
        bbox_by_code[code] = [north + padding, west - padding, south - padding, east + padding]
    missing = sorted(required_codes - set(bbox_by_code))
    if missing:
        raise ValueError(f"O9-G missing JMA geometry for frozen matched regions: {missing}")
    return {k: bbox_by_code[k] for k in sorted(required_codes)}


def build_era5_request_manifest(
    frame: pd.DataFrame,
    *,
    era5_config: dict[str, Any],
    geometry_registry: dict[str, Any],
) -> dict[str, Any]:
    df = validate_final_matched_population(frame)
    bbox_by_code = load_geometry_context(
        era5_config=era5_config,
        geometry_registry=geometry_registry,
        required_codes=set(df["primary_subdivision_code"].astype(str)),
    )

    mappings: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        anchor = parse_utc(row[TIME_ANCHOR_START_COLUMN], name=TIME_ANCHOR_START_COLUMN)
        for offset in SNAPSHOT_OFFSETS_HOURS:
            requested = anchor + pd.Timedelta(hours=offset)
            source = floor_to_hour(requested)
            lag_minutes = int((requested - source).total_seconds() // 60)
            if source > requested or not 0 <= lag_minutes <= 59:
                raise AssertionError("O9-G no-future ERA5 source-time invariant failed")
            mappings.append(
                {
                    "match_set_id": str(row["match_set_id"]),
                    "match_rank": int(row["match_rank"]),
                    "case_role": str(row["case_role"]),
                    "date_utc": str(row["date_utc"]),
                    "primary_subdivision_code": str(row["primary_subdivision_code"]),
                    "imerg_p95_window_start_utc": iso_z(anchor),
                    "snapshot_offset_hours": int(offset),
                    "requested_snapshot_time_utc": iso_z(requested),
                    "era5_source_time_utc": iso_z(source),
                    "era5_source_lag_minutes": lag_minutes,
                }
            )
    if len(mappings) != EXPECTED_SNAPSHOT_COUNT:
        raise AssertionError(f"O9-G expected {EXPECTED_SNAPSHOT_COUNT} snapshot mappings")

    groups: dict[tuple[str, str], set[str]] = {}
    for m in mappings:
        source = parse_utc(m["era5_source_time_utc"], name="era5_source_time_utc")
        key = (source.strftime("%Y-%m-%d"), m["primary_subdivision_code"])
        groups.setdefault(key, set()).add(source.strftime("%H:00"))

    variables = list(era5_config.get("variables") or [])
    levels = [int(x) for x in (era5_config.get("pressure_levels_hpa") or [])]
    if not variables or not levels:
        raise ValueError("O9-G ERA5 config lacks frozen variables/pressure levels")

    request_groups: list[dict[str, Any]] = []
    for (date_s, code), times in sorted(groups.items()):
        request_groups.append(
            {
                "request_id": f"O9G-{date_s.replace('-', '')}-{code}",
                "dataset": ERA5_DATASET,
                "date_utc": date_s,
                "primary_subdivision_code": code,
                "times_utc": sorted(times),
                "pressure_levels_hpa": levels,
                "variables": variables,
                "area_nwse": bbox_by_code[code],
                "spatial_semantics": SPATIAL_SEMANTICS,
            }
        )

    return {
        "schema_version": "1.0.0",
        "phase": "O9-G-guarded-2025-ERA5-request-manifest",
        "validation_year": 2025,
        "provider": ERA5_PROVIDER,
        "dataset": ERA5_DATASET,
        "time_anchor_policy": TIME_ANCHOR_POLICY,
        "time_anchor_start_column": TIME_ANCHOR_START_COLUMN,
        "snapshot_offsets_hours": list(SNAPSHOT_OFFSETS_HOURS),
        "time_alignment_policy": ERA5_TIME_POLICY,
        "future_source_time_allowed": False,
        "matched_case_count": EXPECTED_CASE_COUNT,
        "positive_case_count": EXPECTED_POSITIVE_COUNT,
        "comparison_case_count": EXPECTED_COMPARISON_COUNT,
        "snapshot_mapping_count": EXPECTED_SNAPSHOT_COUNT,
        "request_group_count": len(request_groups),
        "snapshot_mappings": mappings,
        "request_groups": request_groups,
        "network_access_performed": False,
        "era5_environment_values_read": False,
        "primary_confirmatory_test_run": False,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
    }
