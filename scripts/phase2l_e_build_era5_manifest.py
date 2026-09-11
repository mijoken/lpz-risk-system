#!/usr/bin/env python3
"""Phase 2L-E: build a rainfall-anchored ERA5 manifest for matched environmental comparison.

The Phase 2L-D matched pairs are frozen and MUST NOT be changed here.

Fair timing policy:
- Positive and matched-comparison cases use the SAME rainfall-defined anchor:
  the start of the IMERG 3-hour P95-maximum window.
- ERA5 snapshots are sampled at -12h, -6h, -3h, and 0h from that anchor.
- Every requested timestamp is floored to the latest whole ERA5 hour <= requested time.
- No environment variable is used to change matching membership.
- No hard-negative label is created.
- Validation / retrospective 2026 / prospective holdout are not used.
- Risk-engine use remains prohibited.

The output manifest is intentionally compatible with
scripts/era5_batch_reconstruction_pilot.py.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

ANCHOR_POLICY = "IMERG_3H_P95_MAX_WINDOW_START"
SNAPSHOT_OFFSETS_HOURS = (-12, -6, -3, 0)

EXPECTED_MATCH_SET_COUNT = 52
EXPECTED_POSITIVE_CASE_COUNT = 52
EXPECTED_COMPARISON_CASE_COUNT = 156
EXPECTED_TOTAL_CASE_COUNT = 208
EXPECTED_SNAPSHOT_MAPPING_COUNT = 832

PASS_GATE = (
    "PASS_PHASE2L_E_RAINFALL_ANCHORED_ERA5_MANIFEST_"
    "208_CASES_832_SNAPSHOTS"
)


def parse_utc(value: str) -> datetime:
    text = str(value).strip()
    if not text:
        raise ValueError("empty UTC timestamp")
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timezone-aware timestamp required: {value!r}")
    return dt.astimezone(UTC)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def floor_to_hour(dt: datetime) -> tuple[datetime, int]:
    source = dt.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    lag = int((dt - source).total_seconds() // 60)
    if source > dt:
        raise AssertionError("future ERA5 time selected")
    if not 0 <= lag <= 59:
        raise AssertionError(f"unexpected ERA5 source lag: {lag}")
    return source, lag


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_pairs(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"matched-pairs CSV is empty: {path}")
    return rows


def normalize_code(value: str) -> str:
    code = str(value).strip()
    if not code:
        raise ValueError("empty primary_subdivision_code")
    if code.endswith(".0") and code[:-2].isdigit():
        code = code[:-2]
    if not code.isdigit():
        raise ValueError(f"invalid primary_subdivision_code: {value!r}")
    return code.zfill(6)


def build_case_table(pair_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    required = {
        "match_set_id",
        "match_rank",
        "positive_date_utc",
        "primary_subdivision_code",
        "positive_episode_count",
        "positive_local_episode_ids",
        "positive_anchor_ids",
        "positive_analysis_times_utc",
        "comparison_date_utc",
        "comparison_role",
        "positive_imerg_3h_p95_window_start_utc",
        "comparison_imerg_3h_p95_window_start_utc",
    }
    missing = sorted(required - set(pair_rows[0]))
    if missing:
        raise ValueError(f"matched-pairs CSV missing columns: {missing}")

    by_set: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in pair_rows:
        by_set[str(row["match_set_id"])].append(row)

    if len(by_set) != EXPECTED_MATCH_SET_COUNT:
        raise ValueError(
            f"expected {EXPECTED_MATCH_SET_COUNT} match sets, got {len(by_set)}"
        )

    cases: list[dict[str, Any]] = []
    seen_comparison_region_days: set[tuple[str, str]] = set()

    for set_id in sorted(by_set):
        rows = sorted(
            by_set[set_id],
            key=lambda r: int(float(r["match_rank"])),
        )
        ranks = [int(float(r["match_rank"])) for r in rows]
        if ranks != [1, 2, 3]:
            raise ValueError(f"{set_id}: expected ranks [1,2,3], got {ranks}")

        first = rows[0]
        code = normalize_code(first["primary_subdivision_code"])

        # The positive side must be identical across all 3 comparison rows.
        invariant_fields = (
            "positive_date_utc",
            "primary_subdivision_code",
            "positive_episode_count",
            "positive_local_episode_ids",
            "positive_anchor_ids",
            "positive_analysis_times_utc",
            "positive_imerg_3h_p95_window_start_utc",
        )
        for field in invariant_fields:
            values = {str(r[field]) for r in rows}
            if len(values) != 1:
                raise ValueError(
                    f"{set_id}: positive field {field!r} differs across ranks: {values}"
                )

        positive_anchor = parse_utc(
            first["positive_imerg_3h_p95_window_start_utc"]
        )
        cases.append(
            {
                "case_id": f"{set_id}-P",
                "match_set_id": set_id,
                "match_rank": 0,
                "group": "POSITIVE",
                "primary_subdivision_code": code,
                "nominal_region_day_utc": str(first["positive_date_utc"]),
                "rainfall_anchor_time_utc": iso_z(positive_anchor),
                "anchor_policy": ANCHOR_POLICY,
                "positive_episode_count": int(
                    float(first["positive_episode_count"])
                ),
                "positive_local_episode_ids": str(
                    first["positive_local_episode_ids"]
                ),
                "positive_anchor_ids": str(first["positive_anchor_ids"]),
                "positive_analysis_times_utc": str(
                    first["positive_analysis_times_utc"]
                ),
                "comparison_role": None,
            }
        )

        for row in rows:
            rank = int(float(row["match_rank"]))
            row_code = normalize_code(row["primary_subdivision_code"])
            if row_code != code:
                raise ValueError(
                    f"{set_id}: positive/comparison subdivision mismatch "
                    f"{code} vs {row_code}"
                )
            comparison_anchor = parse_utc(
                row["comparison_imerg_3h_p95_window_start_utc"]
            )
            region_day_key = (
                str(row["comparison_date_utc"]),
                row_code,
            )
            if region_day_key in seen_comparison_region_days:
                raise ValueError(
                    "comparison region-day reused despite no-replacement matching: "
                    f"{region_day_key}"
                )
            seen_comparison_region_days.add(region_day_key)

            cases.append(
                {
                    "case_id": f"{set_id}-C{rank}",
                    "match_set_id": set_id,
                    "match_rank": rank,
                    "group": "COMPARISON",
                    "primary_subdivision_code": row_code,
                    "nominal_region_day_utc": str(row["comparison_date_utc"]),
                    "rainfall_anchor_time_utc": iso_z(comparison_anchor),
                    "anchor_policy": ANCHOR_POLICY,
                    "positive_episode_count": None,
                    "positive_local_episode_ids": None,
                    "positive_anchor_ids": None,
                    "positive_analysis_times_utc": None,
                    "comparison_role": str(row["comparison_role"]),
                }
            )

    positive_count = sum(c["group"] == "POSITIVE" for c in cases)
    comparison_count = sum(c["group"] == "COMPARISON" for c in cases)
    if positive_count != EXPECTED_POSITIVE_CASE_COUNT:
        raise ValueError(
            f"expected {EXPECTED_POSITIVE_CASE_COUNT} positive cases, "
            f"got {positive_count}"
        )
    if comparison_count != EXPECTED_COMPARISON_CASE_COUNT:
        raise ValueError(
            f"expected {EXPECTED_COMPARISON_CASE_COUNT} comparison cases, "
            f"got {comparison_count}"
        )
    if len(cases) != EXPECTED_TOTAL_CASE_COUNT:
        raise ValueError(
            f"expected {EXPECTED_TOTAL_CASE_COUNT} total cases, got {len(cases)}"
        )

    return sorted(
        cases,
        key=lambda c: (
            c["match_set_id"],
            c["match_rank"],
            c["case_id"],
        ),
    )


def geometry_map(registry: dict[str, Any]) -> dict[str, list[float]]:
    if not registry.get("geometry_complete_for_required_codes"):
        raise ValueError("official JMA primary-subdivision geometry is incomplete")

    result: dict[str, list[float]] = {}
    for row in registry.get("regions", []):
        code = normalize_code(row["primary_subdivision_code"])
        bbox = [float(x) for x in row["bbox"]]
        if len(bbox) != 4:
            raise ValueError(f"invalid bbox for {code}: {bbox}")
        west, south, east, north = bbox
        if west >= east or south >= north:
            raise ValueError(f"invalid bbox order for {code}: {bbox}")
        result[code] = bbox

    if not result:
        raise ValueError("geometry registry contains no regions")
    return result


def pad_bbox(
    bbox: list[float],
    padding_deg: float,
) -> list[float]:
    west, south, east, north = bbox
    return [
        max(-180.0, west - padding_deg),
        max(-90.0, south - padding_deg),
        min(180.0, east + padding_deg),
        min(90.0, north + padding_deg),
    ]


def build_snapshot_mappings(
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []

    for case in cases:
        anchor = parse_utc(case["rainfall_anchor_time_utc"])
        for offset_h in SNAPSHOT_OFFSETS_HOURS:
            requested = anchor + timedelta(hours=offset_h)
            source, lag_minutes = floor_to_hour(requested)
            mappings.append(
                {
                    "case_id": case["case_id"],
                    "match_set_id": case["match_set_id"],
                    "match_rank": case["match_rank"],
                    "group": case["group"],
                    "primary_subdivision_code": case[
                        "primary_subdivision_code"
                    ],
                    "nominal_region_day_utc": case[
                        "nominal_region_day_utc"
                    ],
                    "rainfall_anchor_time_utc": case[
                        "rainfall_anchor_time_utc"
                    ],
                    "anchor_policy": ANCHOR_POLICY,
                    "snapshot_offset_hours": offset_h,
                    "requested_snapshot_time_utc": iso_z(requested),
                    "era5_source_time_utc": iso_z(source),
                    "source_lag_minutes": lag_minutes,
                    "future_source_time_used": False,
                    "time_alignment": "FLOOR_TO_AVAILABLE_HOUR",
                }
            )

    if len(mappings) != EXPECTED_SNAPSHOT_MAPPING_COUNT:
        raise ValueError(
            f"expected {EXPECTED_SNAPSHOT_MAPPING_COUNT} mappings, "
            f"got {len(mappings)}"
        )
    if any(m["future_source_time_used"] for m in mappings):
        raise AssertionError("future ERA5 source time detected")
    return mappings


def build_requests(
    mappings: list[dict[str, Any]],
    config: dict[str, Any],
    geometry: dict[str, list[float]],
) -> list[dict[str, Any]]:
    padding = float(
        config["spatial_sampling"].get("bbox_padding_degrees", 0.0)
    )
    needed_codes = sorted(
        {m["primary_subdivision_code"] for m in mappings}
    )
    missing_codes = sorted(set(needed_codes) - set(geometry))
    if missing_codes:
        raise ValueError(
            f"matched-case codes missing from official geometry: {missing_codes}"
        )

    grouped: dict[
        tuple[str, str],
        dict[str, set[str]],
    ] = defaultdict(
        lambda: {
            "times": set(),
            "case_ids": set(),
            "groups": set(),
        }
    )

    for mapping in mappings:
        source = parse_utc(mapping["era5_source_time_utc"])
        key = (
            source.strftime("%Y-%m-%d"),
            mapping["primary_subdivision_code"],
        )
        grouped[key]["times"].add(source.strftime("%H:00"))
        grouped[key]["case_ids"].add(mapping["case_id"])
        grouped[key]["groups"].add(mapping["group"])

    requests: list[dict[str, Any]] = []
    for (date, code), info in sorted(grouped.items()):
        raw_bbox = geometry[code]
        west, south, east, north = pad_bbox(raw_bbox, padding)
        requests.append(
            {
                "date": date,
                "primary_subdivision_code": code,
                "times_utc": sorted(info["times"]),
                "pressure_levels_hpa": list(config["pressure_levels_hpa"]),
                "variables": list(config["variables"]),
                "source_bbox_west_south_east_north": raw_bbox,
                "padded_bbox_west_south_east_north": [
                    west,
                    south,
                    east,
                    north,
                ],
                "cds_area_north_west_south_east": [
                    north,
                    west,
                    south,
                    east,
                ],
                "bbox_padding_degrees": padding,
                "spatial_subset_status": config[
                    "spatial_sampling"
                ]["status"],
                "case_ids": sorted(info["case_ids"]),
                "groups_present": sorted(info["groups"]),
                "download_allowed_in_ordinary_ci": False,
                "download_block_reason": (
                    "Local authenticated CDS retrieval requires CDSAPI_KEY."
                ),
            }
        )

    return requests


def write_case_csv(path: Path, cases: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "case_id",
        "match_set_id",
        "match_rank",
        "group",
        "primary_subdivision_code",
        "nominal_region_day_utc",
        "rainfall_anchor_time_utc",
        "anchor_policy",
        "positive_episode_count",
        "positive_local_episode_ids",
        "positive_anchor_ids",
        "positive_analysis_times_utc",
        "comparison_role",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(cases)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pairs",
        default=(
            "local_data/phase2l_d_rainfall_matched_comparison/"
            "phase2l_d_rainfall_matched_pairs.csv"
        ),
    )
    parser.add_argument(
        "--config",
        default="config/historical_environment_era5.json",
    )
    parser.add_argument(
        "--geometry",
        default=(
            "research/phase2/"
            "primary_subdivision_geometry_registry_20260909.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="local_data/phase2l_e_environment_manifest",
    )
    args = parser.parse_args()

    pairs_path = Path(args.pairs)
    config_path = Path(args.config)
    geometry_path = Path(args.geometry)
    output_dir = Path(args.output_dir)

    pair_rows = read_pairs(pairs_path)
    config = read_json(config_path)
    geometry_registry = read_json(geometry_path)

    cases = build_case_table(pair_rows)
    mappings = build_snapshot_mappings(cases)
    geometry = geometry_map(geometry_registry)
    requests = build_requests(
        mappings=mappings,
        config=config,
        geometry=geometry,
    )

    unique_source_times = sorted(
        {m["era5_source_time_utc"] for m in mappings}
    )
    unique_codes = sorted(
        {m["primary_subdivision_code"] for m in mappings}
    )
    max_lag = max(m["source_lag_minutes"] for m in mappings)
    request_time_counts = [len(r["times_utc"]) for r in requests]

    anchor_date_diff_count = sum(
        parse_utc(c["rainfall_anchor_time_utc"]).strftime("%Y-%m-%d")
        != c["nominal_region_day_utc"]
        for c in cases
    )

    manifest = {
        "schema_version": "0.1.0",
        "phase": "2L-E-rainfall-matched-environment-manifest",
        "gate": PASS_GATE,
        "provider": config["provider"],
        "dataset": config["dataset"],
        "input_pairs_csv": str(pairs_path),
        "environment_matching_policy": {
            "matched_population_frozen_from_phase2l_d": True,
            "environment_variables_used_for_membership": False,
            "same_subdivision_inherited_from_matching": True,
            "anchor_policy": ANCHOR_POLICY,
            "anchor_field_positive": (
                "positive_imerg_3h_p95_window_start_utc"
            ),
            "anchor_field_comparison": (
                "comparison_imerg_3h_p95_window_start_utc"
            ),
            "snapshot_offsets_hours": list(
                SNAPSHOT_OFFSETS_HOURS
            ),
            "time_alignment": "FLOOR_TO_AVAILABLE_HOUR",
            "future_source_time_allowed": False,
            "purpose": (
                "Retrospective mechanism comparison under rainfall balance; "
                "not yet a prospective prediction feature selection step."
            ),
        },
        "case_count": len(cases),
        "positive_case_count": sum(
            c["group"] == "POSITIVE" for c in cases
        ),
        "comparison_case_count": sum(
            c["group"] == "COMPARISON" for c in cases
        ),
        "match_set_count": len(
            {c["match_set_id"] for c in cases}
        ),
        "snapshot_mapping_count": len(mappings),
        "unique_era5_source_time_count": len(unique_source_times),
        "date_subdivision_request_count": len(requests),
        "unique_primary_subdivision_count": len(unique_codes),
        "maximum_times_per_request": max(request_time_counts, default=0),
        "mean_times_per_request": (
            sum(request_time_counts) / len(request_time_counts)
            if request_time_counts
            else 0.0
        ),
        "maximum_source_lag_minutes": max_lag,
        "future_source_time_count": 0,
        "anchor_date_differs_from_nominal_region_day_count": (
            anchor_date_diff_count
        ),
        "pressure_levels_hpa": list(config["pressure_levels_hpa"]),
        "variables": list(config["variables"]),
        "spatial_sampling": {
            "status": config["spatial_sampling"]["status"],
            "geometry_registry": str(geometry_path),
            "bbox_padding_degrees": float(
                config["spatial_sampling"].get(
                    "bbox_padding_degrees",
                    0.0,
                )
            ),
            "semantics": (
                "REQUEST_BBOX_CONTEXT_NOT_SUBDIVISION_POLYGON_MEAN"
            ),
        },
        "cases": cases,
        "snapshot_mappings": mappings,
        "requests": requests,
        "hard_negative_label": None,
        "validation_data_used": False,
        "retrospective_2026_used": False,
        "prospective_holdout_used": False,
        "risk_engine_allowed": False,
        "historical_environment_reconstruction_complete": False,
    }

    # Frozen empirical guardrails for the Phase 2L-D baseline currently in use.
    empirical_guardrails = {
        "case_count": EXPECTED_TOTAL_CASE_COUNT,
        "positive_case_count": EXPECTED_POSITIVE_CASE_COUNT,
        "comparison_case_count": EXPECTED_COMPARISON_CASE_COUNT,
        "match_set_count": EXPECTED_MATCH_SET_COUNT,
        "snapshot_mapping_count": EXPECTED_SNAPSHOT_MAPPING_COUNT,
        "date_subdivision_request_count": 256,
        "unique_primary_subdivision_count": 45,
        "maximum_times_per_request": 8,
        "maximum_source_lag_minutes": 30,
    }
    observed = {
        key: manifest[key]
        for key in empirical_guardrails
    }
    if observed != empirical_guardrails:
        raise RuntimeError(
            "Phase 2L-E empirical guardrail mismatch:\n"
            f"observed={observed}\n"
            f"expected={empirical_guardrails}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "phase2l_e_era5_request_manifest.json"
    case_table_path = output_dir / "phase2l_e_environment_case_table.csv"
    report_path = output_dir / "phase2l_e_manifest_report.json"

    write_json(manifest_path, manifest)
    write_case_csv(case_table_path, cases)

    report = {
        "schema_version": "0.1.0",
        "phase": manifest["phase"],
        "gate": PASS_GATE,
        "case_count": manifest["case_count"],
        "positive_case_count": manifest["positive_case_count"],
        "comparison_case_count": manifest["comparison_case_count"],
        "match_set_count": manifest["match_set_count"],
        "snapshot_mapping_count": manifest["snapshot_mapping_count"],
        "unique_era5_source_time_count": manifest[
            "unique_era5_source_time_count"
        ],
        "date_subdivision_request_count": manifest[
            "date_subdivision_request_count"
        ],
        "unique_primary_subdivision_count": manifest[
            "unique_primary_subdivision_count"
        ],
        "maximum_times_per_request": manifest[
            "maximum_times_per_request"
        ],
        "mean_times_per_request": manifest[
            "mean_times_per_request"
        ],
        "maximum_source_lag_minutes": manifest[
            "maximum_source_lag_minutes"
        ],
        "anchor_date_differs_from_nominal_region_day_count": (
            manifest[
                "anchor_date_differs_from_nominal_region_day_count"
            ]
        ),
        "anchor_policy": ANCHOR_POLICY,
        "snapshot_offsets_hours": list(SNAPSHOT_OFFSETS_HOURS),
        "hard_negative_label": None,
        "environment_variables_used_for_membership": False,
        "validation_data_used": False,
        "retrospective_2026_used": False,
        "prospective_holdout_used": False,
        "risk_engine_allowed": False,
        "manifest_path": str(manifest_path),
        "case_table_path": str(case_table_path),
    }
    write_json(report_path, report)

    print("=" * 88)
    print("LPZ PHASE 2L-E RAINFALL-MATCHED ENVIRONMENT MANIFEST")
    print("=" * 88)
    print(f"Pairs input                    : {pairs_path}")
    print(f"Positive cases                 : {manifest['positive_case_count']}")
    print(f"Comparison cases               : {manifest['comparison_case_count']}")
    print(f"Total cases                    : {manifest['case_count']}")
    print(f"Match sets                     : {manifest['match_set_count']}")
    print(f"Rainfall anchor                : {ANCHOR_POLICY}")
    print(
        "ERA5 relative offsets          : "
        + " / ".join(f"{x:+d}h" for x in SNAPSHOT_OFFSETS_HOURS)
    )
    print(f"Snapshot mappings              : {manifest['snapshot_mapping_count']}")
    print(
        "Unique ERA5 source timestamps  : "
        f"{manifest['unique_era5_source_time_count']}"
    )
    print(
        "Date x subdivision requests    : "
        f"{manifest['date_subdivision_request_count']}"
    )
    print(
        "Unique subdivisions            : "
        f"{manifest['unique_primary_subdivision_count']}"
    )
    print(
        "Maximum times / request        : "
        f"{manifest['maximum_times_per_request']}"
    )
    print(
        "Maximum floor lag              : "
        f"{manifest['maximum_source_lag_minutes']} min"
    )
    print(
        "Rainfall anchor date != nominal: "
        f"{manifest['anchor_date_differs_from_nominal_region_day_count']}"
    )
    print("")
    print(f"Gate                           : {PASS_GATE}")
    print("Matched membership             : FROZEN FROM PHASE 2L-D")
    print("Environment used for matching  : NO")
    print("Hard negative label            : NOT CREATED")
    print("Validation / 2026 / holdout    : NOT USED")
    print("Risk engine                    : NOT ALLOWED")
    print(f"Manifest                       : {manifest_path}")
    print(f"Case table                     : {case_table_path}")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
