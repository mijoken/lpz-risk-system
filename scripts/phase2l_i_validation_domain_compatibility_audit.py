#!/usr/bin/env python3
"""Phase 2L-I: audit whether 2025 validation Positive regions are covered by the frozen Development domain.

This audit runs BEFORE any 2025 rainfall matching.

It answers one question only:
Do all 2025 VALIDATION Positive region-days fall inside the 45 primary-subdivision
codes for which the 2023-2024 Development CMORPH 731-day reference distribution
was actually built?

Why this matters:
- The frozen screening rule is same-region Development P80 on CMORPH max/p90/p95.
- A validation Positive in a novel region would not have a frozen same-region
  Development reference distribution.
- Re-estimating a P80 threshold from 2025 would contaminate validation.
- Therefore novel-region cases must be surfaced explicitly, not silently adapted.

No 2025 rainfall, ERA5, threshold tuning, or risk scoring is performed here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


EXPECTED_DEV_REGION_COUNT = 45
EXPECTED_DEV_REGION_DAY_COUNT = 32895
EXPECTED_DEV_DAY_COUNT = 731

PASS_GATE = "PASS_PHASE2L_I_2025_VALIDATION_DOMAIN_COMPATIBILITY"
REVIEW_GATE = "REVIEW_PHASE2L_I_2025_VALIDATION_NOVEL_PRIMARY_SUBDIVISIONS"


def resolve_baseline_root(path: Path) -> Path:
    path = path.resolve()

    if (path / "BASELINE_MANIFEST.json").exists():
        return path

    found = sorted(path.rglob("BASELINE_MANIFEST.json"))
    if len(found) == 1:
        return found[0].parent
    if not found:
        raise FileNotFoundError(
            f"BASELINE_MANIFEST.json not found under {path}"
        )
    raise RuntimeError(
        "multiple BASELINE_MANIFEST.json files found:\n"
        + "\n".join(str(x) for x in found)
    )


def find_dev_census(root: Path) -> Path:
    preferred = (
        root
        / "cmorph_matched_window_census"
        / "phase2l_cmorph_matched_window_region_day_census.csv"
    )
    if preferred.exists():
        return preferred

    candidates = sorted(
        root.rglob("phase2l_cmorph_matched_window_region_day_census.csv")
    )
    if len(candidates) == 1:
        return candidates[0]

    # Defensive fallback: inspect CSVs under the CMORPH census directory.
    census_dir = root / "cmorph_matched_window_census"
    csvs = sorted(census_dir.rglob("*.csv")) if census_dir.exists() else []
    matching = []
    for path in csvs:
        try:
            df = pd.read_csv(
                path,
                nrows=5,
                dtype={"primary_subdivision_code": "string"},
            )
        except Exception:
            continue

        required = {
            "date_utc",
            "primary_subdivision_code",
            "rain_max_mm_day",
            "rain_p90_mm_day",
            "rain_p95_mm_day",
        }
        if required.issubset(df.columns):
            matching.append(path)

    if len(matching) == 1:
        return matching[0]

    raise FileNotFoundError(
        "could not uniquely resolve Development CMORPH region-day census; "
        f"preferred={preferred}, candidates={matching}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--validation-positive-region-days",
        required=True,
        type=Path,
    )
    ap.add_argument(
        "--development-baseline-root",
        required=True,
        type=Path,
    )
    ap.add_argument(
        "--output-dir",
        required=True,
        type=Path,
    )
    a = ap.parse_args()

    val_path = a.validation_positive_region_days.resolve()
    root = resolve_baseline_root(a.development_baseline_root)
    dev_path = find_dev_census(root)

    outdir = a.output_dir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    val = pd.read_csv(
        val_path,
        dtype={"primary_subdivision_code": "string"},
    )
    dev = pd.read_csv(
        dev_path,
        dtype={"primary_subdivision_code": "string"},
    )

    val["primary_subdivision_code"] = (
        val["primary_subdivision_code"].astype("string").str.zfill(6)
    )
    dev["primary_subdivision_code"] = (
        dev["primary_subdivision_code"].astype("string").str.zfill(6)
    )

    required_val = {
        "date_utc",
        "primary_subdivision_code",
        "role",
    }
    missing_val = sorted(required_val - set(val.columns))
    if missing_val:
        raise ValueError(
            f"validation Positive table missing columns: {missing_val}"
        )

    required_dev = {
        "date_utc",
        "primary_subdivision_code",
        "rain_max_mm_day",
        "rain_p90_mm_day",
        "rain_p95_mm_day",
    }
    missing_dev = sorted(required_dev - set(dev.columns))
    if missing_dev:
        raise ValueError(
            f"Development census missing columns: {missing_dev}"
        )

    if len(dev) != EXPECTED_DEV_REGION_DAY_COUNT:
        raise ValueError(
            f"expected {EXPECTED_DEV_REGION_DAY_COUNT} Development region-days, "
            f"got {len(dev)}"
        )
    if dev["date_utc"].nunique() != EXPECTED_DEV_DAY_COUNT:
        raise ValueError(
            f"expected {EXPECTED_DEV_DAY_COUNT} Development UTC days, "
            f"got {dev['date_utc'].nunique()}"
        )
    if dev["primary_subdivision_code"].nunique() != EXPECTED_DEV_REGION_COUNT:
        raise ValueError(
            f"expected {EXPECTED_DEV_REGION_COUNT} Development regions, "
            f"got {dev['primary_subdivision_code'].nunique()}"
        )

    if not (val["role"] == "VALIDATION_POSITIVE_REGION_DAY").all():
        bad = val.loc[
            val["role"] != "VALIDATION_POSITIVE_REGION_DAY",
            ["date_utc", "primary_subdivision_code", "role"],
        ]
        raise ValueError(
            "unexpected validation roles:\n"
            + bad.to_string(index=False)
        )

    if val.duplicated(
        ["date_utc", "primary_subdivision_code"]
    ).any():
        raise ValueError(
            "validation Positive region-day table has duplicate keys"
        )

    dev_codes = set(dev["primary_subdivision_code"].astype(str))
    val_codes = set(val["primary_subdivision_code"].astype(str))

    covered_codes = sorted(val_codes & dev_codes)
    novel_codes = sorted(val_codes - dev_codes)

    audit = val[
        [
            "date_utc",
            "primary_subdivision_code",
            "anchor_count",
            "local_episode_count",
        ]
    ].copy()

    audit["covered_by_frozen_development_731d_region_reference"] = (
        audit["primary_subdivision_code"].astype(str).isin(dev_codes)
    )
    audit["domain_status"] = audit[
        "covered_by_frozen_development_731d_region_reference"
    ].map(
        {
            True: "COVERED_BY_FROZEN_DEVELOPMENT_REGION",
            False: "NOVEL_REGION_NO_FROZEN_SAME_REGION_P80_REFERENCE",
        }
    )

    covered_rows = audit[
        audit[
            "covered_by_frozen_development_731d_region_reference"
        ]
    ].copy()
    novel_rows = audit[
        ~audit[
            "covered_by_frozen_development_731d_region_reference"
        ]
    ].copy()

    gate = PASS_GATE if not novel_codes else REVIEW_GATE

    audit_path = (
        outdir
        / "phase2l_i_2025_validation_domain_compatibility_rows.csv"
    )
    novel_path = (
        outdir
        / "phase2l_i_2025_validation_novel_region_rows.csv"
    )
    report_path = (
        outdir
        / "phase2l_i_2025_validation_domain_compatibility_report.json"
    )

    audit.to_csv(audit_path, index=False)
    novel_rows.to_csv(novel_path, index=False)

    report = {
        "schema_version": "1.0.0",
        "phase": "2L-I-2025-validation-domain-compatibility-audit",
        "gate": gate,
        "validation_positive_region_day_count": int(len(val)),
        "validation_unique_primary_subdivision_count": int(
            val["primary_subdivision_code"].nunique()
        ),
        "development_reference_region_count": int(
            dev["primary_subdivision_code"].nunique()
        ),
        "development_reference_day_count_per_region": EXPECTED_DEV_DAY_COUNT,
        "development_reference_region_day_count": int(len(dev)),
        "covered_validation_region_day_count": int(len(covered_rows)),
        "novel_validation_region_day_count": int(len(novel_rows)),
        "covered_validation_region_codes": covered_codes,
        "novel_validation_region_codes": novel_codes,
        "all_validation_positive_regions_have_frozen_same_region_reference": (
            len(novel_codes) == 0
        ),
        "scientific_guardrail": (
            "DO_NOT_ESTIMATE_NOVEL_REGION_P80_FROM_2025_VALIDATION_DATA"
        ),
        "next_step_if_pass": (
            "BUILD_2025_CMORPH_CENSUS_FOR_FROZEN_DEVELOPMENT_REGION_DOMAIN_"
            "AND_APPLY_FROZEN_DEVELOPMENT_P80_THRESHOLDS"
        ),
        "next_step_if_review": (
            "STOP_BEFORE_RAINFALL_MATCHING_AND_FREEZE_A_NOVEL_REGION_HANDLING_"
            "POLICY_WITHOUT_USING_2025_RAINFALL_OR_ERA5_OUTCOMES"
        ),
        "validation_rainfall_read": False,
        "era5_environment_read": False,
        "threshold_reestimated_on_2025": False,
        "primary_hypothesis_changed": False,
        "retrospective_2026_read": False,
        "prospective_holdout_read": False,
        "risk_engine_allowed": False,
        "inputs": {
            "validation_positive_region_days": str(val_path),
            "development_census": str(dev_path),
        },
        "outputs": {
            "row_audit": str(audit_path),
            "novel_rows": str(novel_path),
        },
    }

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=" * 96)
    print("LPZ PHASE 2L-I — 2025 VALIDATION DOMAIN COMPATIBILITY AUDIT")
    print("=" * 96)
    print(
        f"Validation Positive region-days : {len(val)}"
    )
    print(
        "Validation unique regions       : "
        f"{val['primary_subdivision_code'].nunique()}"
    )
    print(
        "Frozen Development regions      : "
        f"{dev['primary_subdivision_code'].nunique()}"
    )
    print(
        "Covered validation region-days  : "
        f"{len(covered_rows)}"
    )
    print(
        "Novel validation region-days    : "
        f"{len(novel_rows)}"
    )
    print(
        "Novel validation region codes   : "
        + (
            ", ".join(novel_codes)
            if novel_codes
            else "NONE"
        )
    )
    print("")
    print("2025 rainfall read               : NO")
    print("ERA5/environment read            : NO")
    print("2025 threshold re-estimation     : NO")
    print("Primary changed                  : NO")
    print("2026 / prospective read          : NO")
    print("Risk engine                      : NOT ALLOWED")
    print("")
    print(f"Gate                             : {gate}")
    print(f"Report                           : {report_path}")
    print("=" * 96)

    if novel_codes:
        print(
            "IMPORTANT: novel validation regions exist. "
            "Do NOT continue to 2025 rainfall matching yet."
        )
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
