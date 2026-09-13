"""O9-G guarded 2025 ERA5 reconstruction kernel.

Pure validation/merge helpers for the second half of O9-G.  This module never
contacts CDS.  Network access is owned by the guarded runner and is permitted
only after the immutable O9-G authorization context has been revalidated.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from lpz_risk.o9_era5_opening import (
    COMPARISON_ROLE,
    ERA5_DATASET,
    ERA5_PROVIDER,
    ERA5_TIME_POLICY,
    EXPECTED_CASE_COUNT,
    EXPECTED_COMPARISON_COUNT,
    EXPECTED_POSITIVE_COUNT,
    EXPECTED_SNAPSHOT_COUNT,
    POSITIVE_ROLE,
    SNAPSHOT_OFFSETS_HOURS,
    SPATIAL_SEMANTICS,
    TIME_ANCHOR_POLICY,
    parse_utc,
    sha256_file,
)

AUTH_GATE = "PASS_O9_G_2025_ERA5_RETRIEVAL_AUTHORIZED_AFTER_MATCHING_FREEZE"
COMPLETE_GATE = "PASS_O9_G_2025_ERA5_RECONSTRUCTION_COMPLETE_92_CASES_368_SNAPSHOTS"
AUTH_PHASE = "O9-G-guarded-2025-ERA5-retrieval-authorization"
MANIFEST_PHASE = "O9-G-guarded-2025-ERA5-request-manifest"
DESCRIPTOR_PHASE = "O9-G-2025-ERA5-request-descriptor"
COMPLETION_PHASE = "O9-G-2025-ERA5-reconstruction-complete"
DESCRIPTOR_SPATIAL_SEMANTICS = "REQUEST_BBOX_CONTEXT_NOT_SUBDIVISION_POLYGON_MEAN"


def read_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"JSON object required: {path}")
    return obj


def atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def atomic_write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write empty O9-G snapshot feature table")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fields = list(rows[0])
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _finite_number(value: Any, *, name: str) -> float:
    try:
        out = float(value)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite")
    return out


def validate_request_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate the exact immutable 92-case/368-snapshot retrieval manifest."""
    checks = {
        "phase": manifest.get("phase") == MANIFEST_PHASE,
        "validation_year": int(manifest.get("validation_year", -1)) == 2025,
        "provider": manifest.get("provider") == ERA5_PROVIDER,
        "dataset": manifest.get("dataset") == ERA5_DATASET,
        "time_anchor_policy": manifest.get("time_anchor_policy") == TIME_ANCHOR_POLICY,
        "snapshot_offsets": manifest.get("snapshot_offsets_hours") == list(SNAPSHOT_OFFSETS_HOURS),
        "time_alignment": manifest.get("time_alignment_policy") == ERA5_TIME_POLICY,
        "future_source_time_allowed": manifest.get("future_source_time_allowed") is False,
        "matched_case_count": int(manifest.get("matched_case_count", -1)) == EXPECTED_CASE_COUNT,
        "positive_case_count": int(manifest.get("positive_case_count", -1)) == EXPECTED_POSITIVE_COUNT,
        "comparison_case_count": int(manifest.get("comparison_case_count", -1)) == EXPECTED_COMPARISON_COUNT,
        "snapshot_mapping_count": int(manifest.get("snapshot_mapping_count", -1)) == EXPECTED_SNAPSHOT_COUNT,
        "network_access_performed": manifest.get("network_access_performed") is False,
        "era5_environment_values_read": manifest.get("era5_environment_values_read") is False,
        "primary_unrun": manifest.get("primary_confirmatory_test_run") is False,
        "risk_locked": manifest.get("risk_engine_allowed") is False,
        "public_risk_locked": manifest.get("public_risk_release_allowed") is False,
    }
    bad = [k for k, ok in checks.items() if not ok]
    if bad:
        raise ValueError(f"O9-G request manifest guard failed: {bad}")

    mappings = manifest.get("snapshot_mappings")
    groups = manifest.get("request_groups")
    _require(isinstance(mappings, list), "O9-G snapshot_mappings must be a list")
    _require(isinstance(groups, list), "O9-G request_groups must be a list")
    _require(len(mappings) == EXPECTED_SNAPSHOT_COUNT, "O9-G manifest must contain exactly 368 mappings")
    _require(len(groups) == int(manifest.get("request_group_count", -1)), "O9-G request_group_count mismatch")
    _require(len(groups) > 0, "O9-G request manifest contains no request groups")

    case_offsets: dict[tuple[str, int], set[int]] = {}
    case_roles: dict[tuple[str, int], str] = {}
    required_source_keys: set[tuple[str, str, str]] = set()
    snapshot_keys: set[tuple[str, int, int]] = set()
    for i, m in enumerate(mappings):
        set_id = str(m.get("match_set_id", ""))
        rank = int(m.get("match_rank", -99))
        role = str(m.get("case_role", ""))
        offset = int(m.get("snapshot_offset_hours", 999))
        code = str(m.get("primary_subdivision_code", "")).zfill(6)
        _require(set_id != "", f"mapping {i} missing match_set_id")
        _require(rank in {0, 1, 2, 3}, f"mapping {i} invalid match_rank")
        _require(role in {POSITIVE_ROLE, COMPARISON_ROLE}, f"mapping {i} invalid case_role")
        _require((rank == 0) == (role == POSITIVE_ROLE), f"mapping {i} rank/role mismatch")
        _require(offset in SNAPSHOT_OFFSETS_HOURS, f"mapping {i} invalid snapshot offset")
        _require(code.isdigit() and len(code) == 6, f"mapping {i} invalid subdivision code")

        requested = parse_utc(m.get("requested_snapshot_time_utc"), name=f"mapping[{i}].requested_snapshot_time_utc")
        source = parse_utc(m.get("era5_source_time_utc"), name=f"mapping[{i}].era5_source_time_utc")
        lag = int(m.get("era5_source_lag_minutes", -1))
        _require(source <= requested, f"mapping {i} uses future ERA5 source time")
        _require(0 <= lag <= 59, f"mapping {i} invalid ERA5 source lag")
        actual_lag = int((requested - source).total_seconds() // 60)
        _require(actual_lag == lag, f"mapping {i} ERA5 source lag mismatch")

        key = (set_id, rank, offset)
        _require(key not in snapshot_keys, f"duplicate O9-G snapshot mapping: {key}")
        snapshot_keys.add(key)
        case_key = (set_id, rank)
        case_offsets.setdefault(case_key, set()).add(offset)
        previous_role = case_roles.setdefault(case_key, role)
        _require(previous_role == role, f"case role changed within case {case_key}")
        required_source_keys.add((source.strftime("%Y-%m-%d"), code, source.strftime("%H:00")))

    _require(len(case_offsets) == EXPECTED_CASE_COUNT, f"O9-G manifest must contain {EXPECTED_CASE_COUNT} unique cases")
    for case_key, offsets in case_offsets.items():
        _require(offsets == set(SNAPSHOT_OFFSETS_HOURS), f"case {case_key} does not have exact four frozen offsets")
    role_counts = {
        POSITIVE_ROLE: sum(role == POSITIVE_ROLE for role in case_roles.values()),
        COMPARISON_ROLE: sum(role == COMPARISON_ROLE for role in case_roles.values()),
    }
    _require(role_counts[POSITIVE_ROLE] == EXPECTED_POSITIVE_COUNT, "O9-G manifest Positive case count changed")
    _require(role_counts[COMPARISON_ROLE] == EXPECTED_COMPARISON_COUNT, "O9-G manifest comparison case count changed")

    request_ids: set[str] = set()
    provided_source_keys: set[tuple[str, str, str]] = set()
    for i, group in enumerate(groups):
        rid = str(group.get("request_id", ""))
        date_s = str(group.get("date_utc", ""))
        code = str(group.get("primary_subdivision_code", "")).zfill(6)
        times = group.get("times_utc")
        _require(rid != "" and rid not in request_ids, f"request group {i} duplicate/missing request_id")
        request_ids.add(rid)
        _require(group.get("dataset") == ERA5_DATASET, f"request group {rid} dataset changed")
        _require(isinstance(times, list) and times, f"request group {rid} times_utc missing")
        _require(group.get("spatial_semantics") == SPATIAL_SEMANTICS, f"request group {rid} spatial semantics changed")
        area = group.get("area_nwse")
        _require(isinstance(area, list) and len(area) == 4, f"request group {rid} invalid area")
        _require(all(math.isfinite(float(x)) for x in area), f"request group {rid} non-finite area")
        variables = group.get("variables")
        levels = group.get("pressure_levels_hpa")
        _require(isinstance(variables, list) and variables, f"request group {rid} variables missing")
        _require(isinstance(levels, list) and levels, f"request group {rid} pressure levels missing")
        for hhmm in times:
            text = str(hhmm)
            _require(len(text) == 5 and text[2] == ":", f"request group {rid} invalid time {text}")
            provided_source_keys.add((date_s, code, text))

    _require(provided_source_keys == required_source_keys, "O9-G request groups do not exactly cover frozen snapshot source times")
    return manifest


def build_cds_request(group: dict[str, Any]) -> dict[str, Any]:
    year, month, day = str(group["date_utc"]).split("-")
    return {
        "product_type": ["reanalysis"],
        "variable": list(group["variables"]),
        "pressure_level": [str(x) for x in group["pressure_levels_hpa"]],
        "year": [year],
        "month": [month],
        "day": [day],
        "time": list(group["times_utc"]),
        "area": list(group["area_nwse"]),
        "data_format": "grib",
    }


def expected_valid_times(group: dict[str, Any]) -> list[str]:
    return [f"{group['date_utc']}T{hhmm}:00Z" for hhmm in group["times_utc"]]


def descriptor_filename(index: int, request_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in request_id)
    return f"{index:04d}_{safe}.json"


def validate_request_descriptor(
    descriptor: dict[str, Any],
    *,
    index: int,
    group: dict[str, Any],
    authorization_sha256: str,
    manifest_sha256: str,
) -> dict[str, Any]:
    rid = str(group["request_id"])
    checks = {
        "phase": descriptor.get("phase") == DESCRIPTOR_PHASE,
        "request_index": int(descriptor.get("request_index", -1)) == index,
        "request_id": descriptor.get("request_id") == rid,
        "date": descriptor.get("date_utc") == group.get("date_utc"),
        "code": str(descriptor.get("primary_subdivision_code", "")).zfill(6) == str(group.get("primary_subdivision_code", "")).zfill(6),
        "times": descriptor.get("times_utc") == group.get("times_utc"),
        "authorization_sha": descriptor.get("authorization_receipt_sha256") == authorization_sha256,
        "manifest_sha": descriptor.get("request_manifest_sha256") == manifest_sha256,
        "network": descriptor.get("network_access_performed") is True,
        "primary_unrun": descriptor.get("primary_confirmatory_test_run") is False,
        "risk_locked": descriptor.get("risk_engine_allowed") is False,
    }
    bad = [k for k, ok in checks.items() if not ok]
    if bad:
        raise ValueError(f"O9-G request descriptor {rid} guard failed: {bad}")
    _require(int(descriptor.get("downloaded_bytes", 0)) > 0, f"descriptor {rid} downloaded_bytes must be >0")
    _require(isinstance(descriptor.get("payload_sha256"), str) and len(descriptor["payload_sha256"]) == 64, f"descriptor {rid} payload SHA missing")
    validation = descriptor.get("multitime_validation") or {}
    _require(validation.get("multitime_payload_pass") is True, f"descriptor {rid} multi-time validation failed")
    rows = descriptor.get("time_descriptors")
    _require(isinstance(rows, list), f"descriptor {rid} time_descriptors missing")
    expected = expected_valid_times(group)
    observed = [str(x.get("era5_source_time_utc")) for x in rows]
    _require(observed == sorted(expected), f"descriptor {rid} valid-time set/order mismatch")
    for row in rows:
        v = row.get("validation") or {}
        _require(v.get("required_fields_pass") is True, f"descriptor {rid} required fields failed")
        env = row.get("environment_descriptors") or {}
        _validate_environment_descriptor(env, request_id=rid, source_time=str(row.get("era5_source_time_utc")))
    return descriptor


def _validate_environment_descriptor(env: dict[str, Any], *, request_id: str, source_time: str) -> None:
    _require(env.get("source") == "ERA5", f"{request_id} {source_time} environment source changed")
    _require(env.get("exactness") == "PROXY_REANALYSIS", f"{request_id} {source_time} exactness changed")
    _require(env.get("spatial_semantics") == DESCRIPTOR_SPATIAL_SEMANTICS, f"{request_id} {source_time} spatial semantics changed")
    _require(int(env.get("grid_points", 0)) > 0, f"{request_id} {source_time} grid_points invalid")
    for key in (
        "rh500_mean_pct",
        "rh700_mean_pct",
        "rh500_rh700_gt60_fraction",
        "wind600_speed_mean_mps",
        "wind600_from_direction_median_deg",
        "wind850_speed_mean_mps",
        "wind850_from_direction_median_deg",
    ):
        _finite_number(env.get(key), name=f"{request_id}.{source_time}.{key}")
    q = env.get("specific_humidity_mean_kgkg")
    _require(isinstance(q, dict), f"{request_id} {source_time} specific humidity descriptor missing")
    for level in (1000, 925, 850):
        value = _finite_number(q.get(str(level)), name=f"{request_id}.{source_time}.q{level}")
        _require(0.0 <= value < 1.0, f"{request_id} {source_time} q{level} out of range")


def collect_valid_descriptors(
    *,
    descriptor_root: Path,
    manifest: dict[str, Any],
    authorization_sha256: str,
    manifest_sha256: str,
) -> tuple[dict[int, dict[str, Any]], list[int]]:
    valid: dict[int, dict[str, Any]] = {}
    missing: list[int] = []
    for index, group in enumerate(manifest["request_groups"]):
        path = descriptor_root / descriptor_filename(index, str(group["request_id"]))
        if not path.exists():
            missing.append(index)
            continue
        obj = read_json(path)
        validate_request_descriptor(
            obj,
            index=index,
            group=group,
            authorization_sha256=authorization_sha256,
            manifest_sha256=manifest_sha256,
        )
        valid[index] = obj
    return valid, missing


def build_snapshot_feature_rows(
    *,
    manifest: dict[str, Any],
    descriptors: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_region_time: dict[tuple[str, str], dict[str, Any]] = {}
    request_meta: dict[tuple[str, str], tuple[int, str]] = {}
    for index, descriptor in descriptors.items():
        code = str(descriptor["primary_subdivision_code"]).zfill(6)
        rid = str(descriptor["request_id"])
        for row in descriptor["time_descriptors"]:
            source_time = str(row["era5_source_time_utc"])
            key = (code, source_time)
            _require(key not in by_region_time, f"duplicate ERA5 region/source time descriptor {key}")
            by_region_time[key] = row["environment_descriptors"]
            request_meta[key] = (index, rid)

    rows: list[dict[str, Any]] = []
    for m in manifest["snapshot_mappings"]:
        code = str(m["primary_subdivision_code"]).zfill(6)
        source_time = str(m["era5_source_time_utc"])
        key = (code, source_time)
        _require(key in by_region_time, f"missing reconstructed ERA5 source {key}")
        env = by_region_time[key]
        q = env["specific_humidity_mean_kgkg"]
        request_index, request_id = request_meta[key]
        rows.append({
            "match_set_id": str(m["match_set_id"]),
            "match_rank": int(m["match_rank"]),
            "case_role": str(m["case_role"]),
            "date_utc": str(m["date_utc"]),
            "primary_subdivision_code": code,
            "imerg_p95_window_start_utc": str(m["imerg_p95_window_start_utc"]),
            "snapshot_offset_hours": int(m["snapshot_offset_hours"]),
            "requested_snapshot_time_utc": str(m["requested_snapshot_time_utc"]),
            "era5_source_time_utc": source_time,
            "era5_source_lag_minutes": int(m["era5_source_lag_minutes"]),
            "request_index": request_index,
            "request_id": request_id,
            "rh500_mean_pct": float(env["rh500_mean_pct"]),
            "rh700_mean_pct": float(env["rh700_mean_pct"]),
            "rh500_rh700_gt60_fraction": float(env["rh500_rh700_gt60_fraction"]),
            "wind600_speed_mean_mps": float(env["wind600_speed_mean_mps"]),
            "wind600_from_direction_median_deg": float(env["wind600_from_direction_median_deg"]),
            "wind850_speed_mean_mps": float(env["wind850_speed_mean_mps"]),
            "wind850_from_direction_median_deg": float(env["wind850_from_direction_median_deg"]),
            "q1000_mean_kgkg": float(q["1000"]),
            "q925_mean_kgkg": float(q["925"]),
            "q850_mean_kgkg": float(q["850"]),
            "grid_points": int(env["grid_points"]),
            "spatial_semantics": str(env["spatial_semantics"]),
            "risk_score": None,
        })

    rows.sort(key=lambda r: (r["match_set_id"], r["match_rank"], r["snapshot_offset_hours"]))
    validate_snapshot_feature_rows(rows)
    return rows


def validate_snapshot_feature_rows(rows: list[dict[str, Any]]) -> None:
    _require(len(rows) == EXPECTED_SNAPSHOT_COUNT, f"O9-G reconstructed snapshot table must have {EXPECTED_SNAPSHOT_COUNT} rows")
    keys: set[tuple[str, int, int]] = set()
    cases: dict[tuple[str, int], list[dict[str, Any]]] = {}
    future = 0
    for row in rows:
        key = (str(row["match_set_id"]), int(row["match_rank"]), int(row["snapshot_offset_hours"]))
        _require(key not in keys, f"duplicate reconstructed snapshot {key}")
        keys.add(key)
        case_key = key[:2]
        cases.setdefault(case_key, []).append(row)
        requested = parse_utc(row["requested_snapshot_time_utc"], name="requested_snapshot_time_utc")
        source = parse_utc(row["era5_source_time_utc"], name="era5_source_time_utc")
        if source > requested:
            future += 1
        _finite_number(row["q850_mean_kgkg"], name="q850_mean_kgkg")
    _require(future == 0, "future ERA5 source time detected in reconstructed table")
    _require(len(cases) == EXPECTED_CASE_COUNT, "reconstructed ERA5 table does not contain 92 unique cases")
    pos = 0
    cmp_ = 0
    for case_key, case_rows in cases.items():
        offsets = {int(r["snapshot_offset_hours"]) for r in case_rows}
        _require(offsets == set(SNAPSHOT_OFFSETS_HOURS), f"reconstructed case {case_key} missing frozen offsets")
        roles = {str(r["case_role"]) for r in case_rows}
        _require(len(roles) == 1, f"reconstructed case {case_key} role changed")
        role = next(iter(roles))
        pos += role == POSITIVE_ROLE
        cmp_ += role == COMPARISON_ROLE
    _require(pos == EXPECTED_POSITIVE_COUNT and cmp_ == EXPECTED_COMPARISON_COUNT, "reconstructed role counts changed")


def build_completion_receipt(
    *,
    authorization_receipt_path: Path,
    manifest_path: Path,
    snapshot_csv_path: Path,
    snapshot_json_path: Path,
    descriptor_root: Path,
    manifest: dict[str, Any],
    descriptor_count: int,
    generated_at_utc: str,
) -> dict[str, Any]:
    _require(descriptor_count == int(manifest["request_group_count"]), "cannot complete O9-G with missing request descriptors")
    return {
        "schema_version": "1.0.0",
        "phase": COMPLETION_PHASE,
        "gate": COMPLETE_GATE,
        "generated_at_utc": generated_at_utc,
        "validation_year": 2025,
        "era5_retrieval_authorized": True,
        "era5_retrieval_completed": True,
        "network_access_performed": True,
        "era5_environment_values_read": True,
        "matching_membership_changed_by_era5": False,
        "matched_case_count": EXPECTED_CASE_COUNT,
        "positive_case_count": EXPECTED_POSITIVE_COUNT,
        "comparison_case_count": EXPECTED_COMPARISON_COUNT,
        "snapshot_mapping_count": EXPECTED_SNAPSHOT_COUNT,
        "request_group_count": int(manifest["request_group_count"]),
        "successful_request_group_count": descriptor_count,
        "failed_request_group_count": 0,
        "missing_snapshot_count": 0,
        "future_source_time_count": 0,
        "snapshot_offsets_hours": list(SNAPSHOT_OFFSETS_HOURS),
        "time_anchor_policy": TIME_ANCHOR_POLICY,
        "future_source_time_allowed": False,
        "environment_variables_used_for_matching_membership": False,
        "comparison_population_role": COMPARISON_ROLE,
        "request_manifest_sha256": sha256_file(manifest_path),
        "authorization_receipt_sha256": sha256_file(authorization_receipt_path),
        "snapshot_feature_csv": str(snapshot_csv_path),
        "snapshot_feature_csv_sha256": sha256_file(snapshot_csv_path),
        "snapshot_feature_json": str(snapshot_json_path),
        "snapshot_feature_json_sha256": sha256_file(snapshot_json_path),
        "descriptor_root": str(descriptor_root),
        "primary_confirmatory_test_run": False,
        "confirmatory_run_may_execute": True,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
        "requires_sha256": {
            authorization_receipt_path.name: sha256_file(authorization_receipt_path),
            manifest_path.name: sha256_file(manifest_path),
        },
        "next_required_stage": "O9_H_SINGLE_FROZEN_PRIMARY_CONFIRMATORY_RUN",
    }
