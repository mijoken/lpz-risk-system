#!/usr/bin/env python3
"""Phase 2L-E: merge locally reconstructed ERA5 descriptors for the
rainfall-matched Positive vs Comparison population.

Input manifest:
  phase2l_e_era5_request_manifest.json

Input descriptors:
  JSON files written by scripts/era5_batch_reconstruction_pilot.py

This merger is intentionally Phase-2L-E-specific. The older
merge_era5_reconstruction.py expects anchor_id / snapshot_offset_minutes from
the Positive-only Phase 2B workflow and is therefore NOT used here.

Guardrails:
- Phase 2L-D matched membership is frozen.
- No environment variable changes matching membership.
- No hard-negative label is created.
- Validation / retrospective 2026 / prospective holdout are not used.
- Risk-engine use remains prohibited.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

EXPECTED_REQUEST_COUNT = 256
EXPECTED_SNAPSHOT_COUNT = 832
EXPECTED_CASE_COUNT = 208
EXPECTED_POSITIVE_CASE_COUNT = 52
EXPECTED_COMPARISON_CASE_COUNT = 156
EXPECTED_MATCH_SET_COUNT = 52

PASS_GATE = (
    "PASS_PHASE2L_E_COMPLETE_ERA5_RECONSTRUCTION_"
    "256_REQUESTS_832_SNAPSHOTS"
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_descriptors(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        try:
            payload = read_json(path)
        except Exception:
            continue
        if payload.get("phase") == "2B-era5-batch-request":
            payload["_descriptor_path"] = str(path)
            rows.append(payload)
    return rows


def descriptor_lookup(
    descriptors: list[dict[str, Any]],
) -> tuple[
    dict[int, dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
]:
    by_index: dict[int, dict[str, Any]] = {}
    by_region_time: dict[tuple[str, str], dict[str, Any]] = {}

    for descriptor in descriptors:
        index = int(descriptor["request_index"])

        if index in by_index:
            raise ValueError(
                f"duplicate ERA5 request descriptor index: {index}"
            )

        validation = descriptor.get("multitime_validation", {})
        if validation.get("multitime_payload_pass") is not True:
            raise ValueError(
                f"request {index} failed multi-time validation: {validation}"
            )

        by_index[index] = descriptor

        code = str(descriptor["primary_subdivision_code"]).zfill(6)
        for row in descriptor.get("time_descriptors", []):
            validation2 = row.get("validation", {})
            if validation2.get("required_fields_pass") is not True:
                raise ValueError(
                    "ERA5 required-field validation failed for "
                    f"request={index} time={row.get('era5_source_time_utc')}: "
                    f"{validation2}"
                )

            source_time = str(row["era5_source_time_utc"])
            key = (code, source_time)

            if key in by_region_time:
                raise ValueError(
                    "duplicate subdivision/source-time descriptor: "
                    f"{code}|{source_time}"
                )

            by_region_time[key] = {
                "request_index": index,
                "request_key": descriptor["request_key"],
                "downloaded_bytes": descriptor.get("downloaded_bytes"),
                "cds_area_north_west_south_east": descriptor.get(
                    "cds_area_north_west_south_east"
                ),
                "descriptor_path": descriptor["_descriptor_path"],
                **row,
            }

    return by_index, by_region_time


def snapshot_rows(
    manifest: dict[str, Any],
    by_region_time: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    result: list[dict[str, Any]] = []
    missing: list[str] = []

    for mapping in manifest.get("snapshot_mappings", []):
        code = str(mapping["primary_subdivision_code"]).zfill(6)
        source_time = str(mapping["era5_source_time_utc"])
        key = (code, source_time)
        source = by_region_time.get(key)

        snapshot_key = (
            f"{mapping['case_id']}|"
            f"{mapping['snapshot_offset_hours']}|"
            f"{code}|{source_time}"
        )

        if source is None:
            missing.append(snapshot_key)
            continue

        env = source["environment_descriptors"]
        q = env["specific_humidity_mean_kgkg"]

        result.append(
            {
                "case_id": mapping["case_id"],
                "match_set_id": mapping["match_set_id"],
                "match_rank": int(mapping["match_rank"]),
                "group": mapping["group"],
                "primary_subdivision_code": code,
                "nominal_region_day_utc": mapping[
                    "nominal_region_day_utc"
                ],
                "rainfall_anchor_time_utc": mapping[
                    "rainfall_anchor_time_utc"
                ],
                "anchor_policy": mapping["anchor_policy"],
                "snapshot_offset_hours": int(
                    mapping["snapshot_offset_hours"]
                ),
                "requested_snapshot_time_utc": mapping[
                    "requested_snapshot_time_utc"
                ],
                "era5_source_time_utc": source_time,
                "source_lag_minutes": int(mapping["source_lag_minutes"]),
                "future_source_time_used": bool(
                    mapping["future_source_time_used"]
                ),
                "source": "ERA5",
                "exactness": "PROXY_REANALYSIS",
                "request_index": int(source["request_index"]),
                "request_key": source["request_key"],
                "downloaded_bytes": source.get("downloaded_bytes"),
                "rh500_mean_pct": float(env["rh500_mean_pct"]),
                "rh700_mean_pct": float(env["rh700_mean_pct"]),
                "rh500_rh700_gt60_fraction": float(
                    env["rh500_rh700_gt60_fraction"]
                ),
                "wind600_speed_mean_mps": float(
                    env["wind600_speed_mean_mps"]
                ),
                "wind600_from_direction_median_deg": float(
                    env["wind600_from_direction_median_deg"]
                ),
                "wind850_speed_mean_mps": float(
                    env["wind850_speed_mean_mps"]
                ),
                "wind850_from_direction_median_deg": float(
                    env["wind850_from_direction_median_deg"]
                ),
                "q1000_mean_kgkg": float(q["1000"]),
                "q925_mean_kgkg": float(q["925"]),
                "q850_mean_kgkg": float(q["850"]),
                "grid_points": int(env["grid_points"]),
                "spatial_semantics": env["spatial_semantics"],
                "risk_score": None,
            }
        )

    result.sort(
        key=lambda r: (
            r["match_set_id"],
            r["match_rank"],
            r["snapshot_offset_hours"],
            r["case_id"],
        )
    )
    return result, missing


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write empty snapshot table")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        required=True,
    )
    parser.add_argument(
        "--descriptor-root",
        required=True,
    )
    parser.add_argument(
        "--output-dir",
        required=True,
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    descriptor_root = Path(args.descriptor_root)
    output_dir = Path(args.output_dir)

    manifest = read_json(manifest_path)

    if (
        manifest.get("gate")
        != "PASS_PHASE2L_E_RAINFALL_ANCHORED_ERA5_MANIFEST_"
        "208_CASES_832_SNAPSHOTS"
    ):
        raise ValueError(
            "unexpected or unpassed Phase 2L-E manifest gate: "
            f"{manifest.get('gate')}"
        )

    empirical = {
        "date_subdivision_request_count": EXPECTED_REQUEST_COUNT,
        "snapshot_mapping_count": EXPECTED_SNAPSHOT_COUNT,
        "case_count": EXPECTED_CASE_COUNT,
        "positive_case_count": EXPECTED_POSITIVE_CASE_COUNT,
        "comparison_case_count": EXPECTED_COMPARISON_CASE_COUNT,
        "match_set_count": EXPECTED_MATCH_SET_COUNT,
    }
    observed = {k: manifest.get(k) for k in empirical}
    if observed != empirical:
        raise ValueError(
            "Phase 2L-E manifest empirical guardrail mismatch:\n"
            f"observed={observed}\nexpected={empirical}"
        )

    descriptors = load_descriptors(descriptor_root)
    by_index, by_region_time = descriptor_lookup(descriptors)

    expected_indices = set(range(EXPECTED_REQUEST_COUNT))
    observed_indices = set(by_index)
    missing_request_indices = sorted(expected_indices - observed_indices)
    unexpected_request_indices = sorted(observed_indices - expected_indices)

    rows, missing_snapshot_keys = snapshot_rows(
        manifest,
        by_region_time,
    )

    future_source_time_count = sum(
        bool(r["future_source_time_used"]) for r in rows
    )

    group_counts = {
        "POSITIVE": len(
            {r["case_id"] for r in rows if r["group"] == "POSITIVE"}
        ),
        "COMPARISON": len(
            {r["case_id"] for r in rows if r["group"] == "COMPARISON"}
        ),
    }
    match_set_count = len({r["match_set_id"] for r in rows})

    complete = (
        len(by_index) == EXPECTED_REQUEST_COUNT
        and not missing_request_indices
        and not unexpected_request_indices
        and len(rows) == EXPECTED_SNAPSHOT_COUNT
        and not missing_snapshot_keys
        and future_source_time_count == 0
        and group_counts["POSITIVE"] == EXPECTED_POSITIVE_CASE_COUNT
        and group_counts["COMPARISON"] == EXPECTED_COMPARISON_CASE_COUNT
        and match_set_count == EXPECTED_MATCH_SET_COUNT
    )

    gate = PASS_GATE if complete else "FAIL_PHASE2L_E_INCOMPLETE_ERA5_RECONSTRUCTION"

    feature_json_path = (
        output_dir
        / "phase2l_e_era5_snapshot_feature_table.json"
    )
    feature_csv_path = (
        output_dir
        / "phase2l_e_era5_snapshot_feature_table.csv"
    )
    report_path = (
        output_dir
        / "phase2l_e_era5_reconstruction_report.json"
    )

    feature_payload = {
        "schema_version": "0.1.0",
        "phase": "2L-E-rainfall-matched-era5-snapshot-feature-table",
        "gate": gate,
        "source": "ERA5",
        "exactness": "PROXY_REANALYSIS",
        "manifest": str(manifest_path),
        "descriptor_root": str(descriptor_root),
        "request_descriptor_count": len(by_index),
        "expected_request_count": EXPECTED_REQUEST_COUNT,
        "snapshot_feature_row_count": len(rows),
        "expected_snapshot_count": EXPECTED_SNAPSHOT_COUNT,
        "positive_case_count": group_counts["POSITIVE"],
        "comparison_case_count": group_counts["COMPARISON"],
        "match_set_count": match_set_count,
        "missing_request_indices": missing_request_indices,
        "unexpected_request_indices": unexpected_request_indices,
        "hard_missing_snapshot_key_count": len(
            missing_snapshot_keys
        ),
        "hard_missing_snapshot_keys": missing_snapshot_keys[:100],
        "future_source_time_count": future_source_time_count,
        "matched_membership_frozen_from_phase2l_d": True,
        "environment_variables_used_for_membership": False,
        "hard_negative_label": None,
        "validation_data_used": False,
        "retrospective_2026_used": False,
        "prospective_holdout_used": False,
        "risk_engine_allowed": False,
        "snapshot_features": rows,
    }

    report = {
        k: v
        for k, v in feature_payload.items()
        if k != "snapshot_features"
    }
    report["feature_json"] = str(feature_json_path)
    report["feature_csv"] = str(feature_csv_path)

    write_json(feature_json_path, feature_payload)
    if rows:
        write_csv(feature_csv_path, rows)
    write_json(report_path, report)

    print("=" * 88)
    print("LPZ PHASE 2L-E ERA5 FULL RECONSTRUCTION MERGE")
    print("=" * 88)
    print(
        f"Request descriptors            : "
        f"{len(by_index)} / {EXPECTED_REQUEST_COUNT}"
    )
    print(
        f"Snapshot feature rows          : "
        f"{len(rows)} / {EXPECTED_SNAPSHOT_COUNT}"
    )
    print(
        f"Positive cases                 : "
        f"{group_counts['POSITIVE']} / {EXPECTED_POSITIVE_CASE_COUNT}"
    )
    print(
        f"Comparison cases               : "
        f"{group_counts['COMPARISON']} / {EXPECTED_COMPARISON_CASE_COUNT}"
    )
    print(
        f"Match sets                     : "
        f"{match_set_count} / {EXPECTED_MATCH_SET_COUNT}"
    )
    print(
        f"Missing request indices        : "
        f"{len(missing_request_indices)}"
    )
    print(
        f"Missing snapshot keys          : "
        f"{len(missing_snapshot_keys)}"
    )
    print(
        f"Future ERA5 source times       : "
        f"{future_source_time_count}"
    )
    print("")
    print(f"Gate                           : {gate}")
    print("Matched membership             : FROZEN FROM PHASE 2L-D")
    print("Environment used for matching  : NO")
    print("Hard negative label            : NOT CREATED")
    print("Validation / 2026 / holdout    : NOT USED")
    print("Risk engine                    : NOT ALLOWED")
    print(f"Feature CSV                    : {feature_csv_path}")
    print(f"Feature JSON                   : {feature_json_path}")
    print(f"Report                         : {report_path}")
    print("=" * 88)

    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
