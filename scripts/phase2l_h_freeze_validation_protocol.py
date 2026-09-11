#!/usr/bin/env python3
"""Phase 2L-H: freeze the discovery result and 2025 validation protocol.

This script MUST be run before any Phase 2L validation-year analysis.

It reads only Development-era Phase 2L-D/F/G artifacts, verifies the completed
discovery gates, records hashes of the exact code/artifacts used, and writes a
version-controlled protocol freeze under research/phase2/.

It does NOT read 2025 validation data.
It does NOT select new thresholds.
It does NOT alter the rainfall-matched population.
It does NOT enable the risk engine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


EXPECTED_F_GATE = (
    "PASS_PHASE2L_F_MATCHED_ENVIRONMENT_DISCOVERY_"
    "52_MATCH_SETS_832_SNAPSHOTS"
)
EXPECTED_G_GATE = (
    "PASS_PHASE2L_G_CLUSTER_AWARE_ROBUSTNESS_"
    "52_MATCH_SETS_22_POSITIVE_UTC_DATES"
)
FREEZE_GATE = (
    "PASS_PHASE2L_H_DISCOVERY_AND_VALIDATION_PROTOCOL_FREEZE_"
    "PRIMARY_Q850_T0H"
)

PRIMARY_METRIC = "q850_mean_kgkg"
PRIMARY_CONTRAST = "t+0h"

SECONDARY_HYPOTHESES = [
    {
        "metric": "q925_mean_kgkg",
        "contrast": "t-3h",
        "direction": "POSITIVE_HIGHER",
        "status": "SECONDARY_PRE_SPECIFIED_NOT_PRIMARY",
    },
    {
        "metric": "q925_mean_kgkg",
        "contrast": "t-6h",
        "direction": "POSITIVE_HIGHER",
        "status": "SECONDARY_PRE_SPECIFIED_NOT_PRIMARY",
    },
    {
        "metric": "wind600_speed_mean_mps",
        "contrast": "t+0h",
        "direction": "POSITIVE_HIGHER",
        "status": "SECONDARY_PRE_SPECIFIED_NOT_PRIMARY",
    },
    {
        "metric": "q850_mean_kgkg",
        "contrast": "persistence_mean",
        "direction": "POSITIVE_HIGHER",
        "status": "SECONDARY_PRE_SPECIFIED_NOT_PRIMARY",
    },
    {
        "metric": "q850_mean_kgkg",
        "contrast": "delta_-6h_to_0h",
        "direction": "POSITIVE_HIGHER",
        "status": "SECONDARY_PRE_SPECIFIED_NOT_PRIMARY",
    },
    {
        "metric": "rh500_mean_pct",
        "contrast": "delta_-3h_to_0h",
        "direction": "POSITIVE_LOWER",
        "status": "MECHANISTIC_EXPLORATORY_PRE_SPECIFIED",
    },
]

HASH_PATHS = [
    "scripts/phase2l_d_rainfall_matched_comparison.py",
    "scripts/phase2l_e_build_era5_manifest.py",
    "scripts/phase2l_e_merge_era5_reconstruction.py",
    "scripts/phase2l_f_matched_environment_discovery.py",
    "scripts/phase2l_g_cluster_aware_robustness.py",
    (
        "local_data/phase2l_d_rainfall_matched_comparison/"
        "phase2l_d_rainfall_matched_comparison_report.json"
    ),
    (
        "local_data/phase2l_e_environment_features/"
        "phase2l_e_era5_reconstruction_report.json"
    ),
    (
        "local_data/phase2l_f_environment_discovery/"
        "phase2l_f_environment_discovery_report.json"
    ),
    (
        "local_data/phase2l_f_environment_discovery/"
        "phase2l_f_continuous_matched_summary.csv"
    ),
    (
        "local_data/phase2l_g_cluster_robustness/"
        "phase2l_g_cluster_robustness_report.json"
    ),
    (
        "local_data/phase2l_g_cluster_robustness/"
        "phase2l_g_cluster_aware_robustness_summary.csv"
    ),
]


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
    # Re-read before replace so a partial/invalid write never becomes canonical.
    _ = tmp.read_text(encoding="utf-8")
    tmp.replace(path)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    # Validate serialized JSON before canonical replace.
    json.loads(text)
    atomic_write_text(path, text)


def git_text(args: list[str]) -> str | None:
    try:
        cp = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return cp.stdout.strip()
    except Exception:
        return None


def find_row(
    df: pd.DataFrame,
    metric: str,
    contrast: str,
) -> dict[str, Any]:
    rows = df[
        (df["metric"] == metric)
        & (df["contrast"] == contrast)
    ]
    if len(rows) != 1:
        raise ValueError(
            f"expected exactly one row for {metric}/{contrast}, got {len(rows)}"
        )
    return rows.iloc[0].to_dict()


def require_bool(value: Any, expected: bool, name: str) -> None:
    observed = bool(value)
    if observed != expected:
        raise ValueError(
            f"{name}: expected {expected}, got {observed}"
        )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--phase2lf-report",
        default=(
            "local_data/phase2l_f_environment_discovery/"
            "phase2l_f_environment_discovery_report.json"
        ),
    )
    p.add_argument(
        "--phase2lf-summary",
        default=(
            "local_data/phase2l_f_environment_discovery/"
            "phase2l_f_continuous_matched_summary.csv"
        ),
    )
    p.add_argument(
        "--phase2lg-report",
        default=(
            "local_data/phase2l_g_cluster_robustness/"
            "phase2l_g_cluster_robustness_report.json"
        ),
    )
    p.add_argument(
        "--phase2lg-summary",
        default=(
            "local_data/phase2l_g_cluster_robustness/"
            "phase2l_g_cluster_aware_robustness_summary.csv"
        ),
    )
    p.add_argument(
        "--output-json",
        default=(
            "research/phase2/"
            "phase2l_h_validation_protocol_freeze_20260911.json"
        ),
    )
    p.add_argument(
        "--output-md",
        default=(
            "research/phase2/"
            "phase2l_h_validation_protocol_freeze_20260911.md"
        ),
    )
    args = p.parse_args()

    f_report_path = Path(args.phase2lf_report)
    f_summary_path = Path(args.phase2lf_summary)
    g_report_path = Path(args.phase2lg_report)
    g_summary_path = Path(args.phase2lg_summary)

    f_report = json.loads(
        f_report_path.read_text(encoding="utf-8")
    )
    g_report = json.loads(
        g_report_path.read_text(encoding="utf-8")
    )
    f_summary = pd.read_csv(f_summary_path)
    g_summary = pd.read_csv(g_summary_path)

    if f_report.get("gate") != EXPECTED_F_GATE:
        raise ValueError(
            f"Phase 2L-F gate mismatch: {f_report.get('gate')}"
        )
    if g_report.get("gate") != EXPECTED_G_GATE:
        raise ValueError(
            f"Phase 2L-G gate mismatch: {g_report.get('gate')}"
        )

    # Guardrails from completed discovery.
    require_bool(
        f_report.get("environment_variables_used_for_matching_membership"),
        False,
        "F environment used for membership",
    )
    require_bool(
        f_report.get("matching_membership_changed"),
        False,
        "F matching membership changed",
    )
    require_bool(
        f_report.get("threshold_selected"),
        False,
        "F threshold selected",
    )
    require_bool(
        f_report.get("validation_data_used"),
        False,
        "F validation data used",
    )
    require_bool(
        g_report.get("matching_membership_changed"),
        False,
        "G matching membership changed",
    )
    require_bool(
        g_report.get("threshold_selected"),
        False,
        "G threshold selected",
    )
    require_bool(
        g_report.get("validation_data_used"),
        False,
        "G validation data used",
    )

    f_primary = find_row(
        f_summary,
        PRIMARY_METRIC,
        PRIMARY_CONTRAST,
    )
    g_primary = find_row(
        g_summary,
        PRIMARY_METRIC,
        PRIMARY_CONTRAST,
    )

    # Primary candidate must have the frozen positive direction in both views.
    if f_primary["direction_of_difference"] != "POSITIVE_HIGHER":
        raise ValueError(
            "Phase 2L-F primary direction is not POSITIVE_HIGHER"
        )
    if g_primary["direction_equal_date"] != "POSITIVE_HIGHER":
        raise ValueError(
            "Phase 2L-G primary direction is not POSITIVE_HIGHER"
        )

    # Discovery robustness facts are recorded, not turned into a tuned threshold.
    g_ci_excludes_zero = bool(
        g_primary["cluster_bootstrap_ci_excludes_zero"]
    )
    g_lodo_same_sign = float(
        g_primary["lodo_same_sign_fraction"]
    )
    g_lodo_crosses_zero = bool(
        g_primary["lodo_crosses_zero"]
    )

    repo_root = Path(".").resolve()
    hashes: dict[str, Any] = {}
    missing_hash_paths: list[str] = []

    for rel in HASH_PATHS:
        path = repo_root / rel
        if path.exists():
            hashes[rel] = {
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        else:
            missing_hash_paths.append(rel)

    if missing_hash_paths:
        raise FileNotFoundError(
            "freeze source files missing: "
            + ", ".join(missing_hash_paths)
        )

    git_head = git_text(["rev-parse", "HEAD"])
    git_branch = git_text(["rev-parse", "--abbrev-ref", "HEAD"])
    git_status = git_text(["status", "--short"])

    frozen_at = datetime.now(timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )

    protocol = {
        "schema_version": "1.0.0",
        "phase": "2L-H-discovery-validation-protocol-freeze",
        "gate": FREEZE_GATE,
        "frozen_at_utc": frozen_at,
        "purpose": (
            "Freeze the Development-era discovery result and the exact "
            "2025 validation question before opening validation outcomes."
        ),
        "development_period": {
            "used_for_discovery": True,
            "years": [2023, 2024],
        },
        "validation_period": {
            "year": 2025,
            "status_at_freeze": "UNTOUCHED_FOR_THIS_ANALYSIS",
            "may_be_opened_only_after_this_freeze": True,
        },
        "retrospective_2026": {
            "status": "UNTOUCHED",
        },
        "prospective_holdout": {
            "status": "UNTOUCHED",
        },
        "population_design": {
            "unit": "JMA_PRIMARY_SUBDIVISION_REGION_DAY",
            "positive_episode_count_development": 65,
            "positive_unique_region_day_count_development": 52,
            "comparison_case_count_development": 156,
            "match_set_count_development": 52,
            "comparison_role": (
                "RAINFALL_MATCHED_COMPARISON_NOT_NEGATIVE_LABEL"
            ),
            "hard_negative_label_created": False,
            "match_ratio": "1_POSITIVE_TO_3_COMPARISONS",
            "same_primary_subdivision_required": True,
            "season_window_calendar_days": 60,
            "positive_event_exclusion_buffer_actual_days": 3,
            "rainfall_matching_space": (
                "LOG1P_STANDARDIZED_FOUR_IMERG_3H_METRICS_PCA_PC1_PC2"
            ),
            "environment_variables_used_for_matching": False,
            "membership_policy": (
                "FROZEN_FROM_PHASE_2L_D_AND_MUST_NOT_BE_CHANGED_BY_ERA5"
            ),
        },
        "time_anchor": {
            "policy": "IMERG_3H_P95_MAX_WINDOW_START",
            "applies_symmetrically_to": [
                "POSITIVE",
                "COMPARISON",
            ],
            "era5_offsets_hours": [-12, -6, -3, 0],
            "era5_alignment": (
                "FLOOR_TO_LATEST_AVAILABLE_WHOLE_HOUR_NO_FUTURE_SOURCE_TIME"
            ),
        },
        "primary_hypothesis": {
            "id": "H_PRIMARY_Q850_T0H",
            "metric": PRIMARY_METRIC,
            "pressure_level_hpa": 850,
            "contrast": PRIMARY_CONTRAST,
            "era5_snapshot_offset_hours": 0,
            "spatial_semantics": (
                "ERA5_REQUEST_BBOX_CONTEXT_NOT_SUBDIVISION_POLYGON_MEAN"
            ),
            "directional_alternative": (
                "POSITIVE_Q850_GREATER_THAN_MEAN_OF_3_MATCHED_COMPARISONS"
            ),
            "scientific_statement": (
                "Among rainfall-severity-matched heavy-rain cases, LPZ "
                "Positive cases have higher ERA5 850-hPa specific humidity "
                "at the start of the IMERG P95-max 3-hour rainfall window."
            ),
            "confirmatory_status": "ONLY_PRIMARY_CONFIRMATORY_HYPOTHESIS",
        },
        "primary_validation_estimand": {
            "match_set_difference": (
                "POSITIVE_VALUE_MINUS_MEAN_OF_3_MATCHED_COMPARISON_VALUES"
            ),
            "cluster_unit": "POSITIVE_DATE_UTC",
            "within_cluster_aggregation": (
                "MEAN_OF_MATCH_SET_DIFFERENCES_WITHIN_POSITIVE_DATE_UTC"
            ),
            "primary_effect_estimate": (
                "EQUAL_WEIGHT_MEAN_OF_POSITIVE_DATE_UTC_CLUSTER_MEANS"
            ),
        },
        "primary_validation_test": {
            "test": "EXACT_ONE_SIDED_SIGN_TEST_ON_POSITIVE_DATE_UTC_CLUSTER_MEANS",
            "alternative": "CLUSTER_MEAN_DIFFERENCE_GT_0",
            "zeros": "IGNORED",
            "alpha": 0.05,
            "multiplicity_correction": (
                "NONE_REQUIRED_FOR_SINGLE_PRE_SPECIFIED_PRIMARY_HYPOTHESIS"
            ),
            "primary_confirmation_rule": [
                "PRIMARY_EFFECT_ESTIMATE_GT_0",
                "ONE_SIDED_EXACT_SIGN_TEST_P_LT_0_05",
            ],
            "important_note": (
                "The primary rule is frozen before 2025 outcome inspection. "
                "Secondary or exploratory results cannot rescue a failed primary."
            ),
        },
        "pre_specified_robustness_checks": {
            "cluster_bootstrap": {
                "resamples": 20000,
                "ci": 0.95,
                "desired_support": (
                    "LOWER_CONFIDENCE_BOUND_GT_0"
                ),
            },
            "leave_one_positive_date_out": {
                "desired_support": [
                    "SAME_SIGN_FRACTION_EQ_1_0",
                    "LODO_RANGE_DOES_NOT_CROSS_ZERO",
                ],
            },
            "interpretation": (
                "These are robustness/support criteria, not substitutes for "
                "the frozen primary confirmation rule."
            ),
        },
        "pre_specified_secondary_hypotheses": SECONDARY_HYPOTHESES,
        "secondary_analysis_policy": {
            "confirmatory": False,
            "report_effect_sizes": True,
            "report_cluster_bootstrap_ci": True,
            "report_sign_tests": True,
            "multiplicity": (
                "BENJAMINI_HOCHBERG_FDR_ACROSS_SECONDARY_AND_EXPLORATORY_PANEL"
            ),
            "cannot_override_primary_failure": True,
        },
        "full_exploratory_panel_policy": {
            "phase2lf_continuous_test_count": 81,
            "allowed": True,
            "status": "EXPLORATORY_ONLY",
            "new_feature_creation_after_validation_open": False,
            "new_time_offset_creation_after_validation_open": False,
            "threshold_search_after_validation_open": False,
        },
        "physical_semantics_guardrails": {
            "q850_mean_kgkg": (
                "ERA5 pressure-level low-level moisture context"
            ),
            "q850_x_wind850_speed_bbox_proxy": (
                "BBOX_CONTEXT_MOISTURE_TRANSPORT_PROXY_ONLY"
            ),
            "kato_500m_flwv_equivalence": False,
            "note": (
                "850-hPa moisture/wind metrics must never be called or "
                "silently substituted for Kato 500-m FLWV."
            ),
        },
        "validation_prohibitions": [
            "DO_NOT_USE_2025_TO_CHANGE_MATCHING_MEMBERSHIP",
            "DO_NOT_USE_2025_TO_CHANGE_PRIMARY_METRIC",
            "DO_NOT_USE_2025_TO_CHANGE_PRIMARY_TIME_OFFSET",
            "DO_NOT_USE_2025_TO_CHANGE_DIRECTIONAL_HYPOTHESIS",
            "DO_NOT_USE_2025_TO_TUNE_THRESHOLDS",
            "DO_NOT_PROMOTE_SECONDARY_TO_PRIMARY_AFTER_SEEING_2025",
            "DO_NOT_CREATE_HARD_NEGATIVE_LABEL_FROM_ENVIRONMENTAL_SEPARATION",
            "DO_NOT_USE_FUTURE_ERA5_SOURCE_TIMES",
            "DO_NOT_ENABLE_RISK_ENGINE",
        ],
        "development_evidence_snapshot": {
            "phase2lf_primary": {
                "metric": PRIMARY_METRIC,
                "contrast": PRIMARY_CONTRAST,
                "paired_effect_dz": float(
                    f_primary["paired_effect_dz"]
                ),
                "sign_test_p_value_two_sided": float(
                    f_primary["sign_test_p_value"]
                ),
                "bh_fdr_q_value_81_test_panel": float(
                    f_primary["bh_fdr_q_value"]
                ),
                "mean_matched_difference": float(
                    f_primary["mean_matched_difference"]
                ),
                "bootstrap_ci95": [
                    float(f_primary["bootstrap_mean_diff_ci95_low"]),
                    float(f_primary["bootstrap_mean_diff_ci95_high"]),
                ],
            },
            "phase2lg_primary": {
                "metric": PRIMARY_METRIC,
                "contrast": PRIMARY_CONTRAST,
                "cluster_effect_dz": float(
                    g_primary["cluster_effect_dz"]
                ),
                "date_sign_test_p_value_two_sided": float(
                    g_primary["date_sign_test_p_value"]
                ),
                "bh_fdr_q_value_81_test_panel": float(
                    g_primary[
                        "bh_fdr_q_value_cluster_sign_test"
                    ]
                ),
                "equal_date_mean_difference": float(
                    g_primary["equal_date_mean_difference"]
                ),
                "cluster_bootstrap_ci95": [
                    float(g_primary["cluster_bootstrap_ci95_low"]),
                    float(g_primary["cluster_bootstrap_ci95_high"]),
                ],
                "cluster_bootstrap_ci_excludes_zero": (
                    g_ci_excludes_zero
                ),
                "lodo_same_sign_fraction": g_lodo_same_sign,
                "lodo_crosses_zero": g_lodo_crosses_zero,
            },
            "interpretation": (
                "Development evidence selects q850@0h as the sole Primary "
                "candidate. It is robust to date clustering in effect size, "
                "bootstrap CI, and LODO, but is NOT multiplicity-confirmed "
                "across the 81-test discovery panel. Therefore independent "
                "2025 validation is required."
            ),
        },
        "source_integrity": {
            "repo_root": str(repo_root),
            "git_head_before_freeze_commit": git_head,
            "git_branch": git_branch,
            "git_status_before_freeze_commit": git_status,
            "sha256": hashes,
        },
        "risk_engine_allowed": False,
    }

    json_path = Path(args.output_json)
    md_path = Path(args.output_md)

    atomic_write_json(json_path, protocol)

    md = f"""# Phase 2L-H — Discovery & 2025 Validation Protocol Freeze

**Gate:** `{FREEZE_GATE}`  
**Frozen at (UTC):** `{frozen_at}`  
**Validation year:** 2025 — **UNTOUCHED at freeze**

## Primary hypothesis

`q850_mean_kgkg @ t+0h`

Directional hypothesis:

> Among rainfall-severity-matched heavy-rain cases, LPZ Positive cases have
> higher ERA5 850-hPa specific humidity at the start of the IMERG P95-max
> 3-hour rainfall window than the mean of their three matched Comparison cases.

This is the **only primary confirmatory hypothesis**.

## Frozen matched estimand

For every match set:

`Positive - mean(3 matched Comparisons)`

Match-set differences are then aggregated within `positive_date_utc`.
The primary effect estimate is the **equal-weight mean of UTC-date cluster
means**.

## Frozen primary validation test

- Exact **one-sided sign test** on `positive_date_utc` cluster means.
- Alternative: cluster mean difference `> 0`.
- Zero differences are ignored.
- Alpha: `0.05`.
- No multiplicity correction is applied to this single pre-specified Primary.
- Primary confirmation requires:
  1. primary effect estimate `> 0`, and
  2. one-sided exact sign-test `p < 0.05`.

Secondary/exploratory findings **cannot rescue a failed Primary**.

## Pre-specified robustness

- 20,000-resample cluster bootstrap; supportive if 95% CI lower bound `> 0`.
- Leave-one-positive-date-out; supportive if same-sign fraction is `1.0`
  and the LODO mean range does not cross zero.

## Secondary / exploratory hypotheses

{json.dumps(SECONDARY_HYPOTHESES, ensure_ascii=False, indent=2)}

## Development evidence that motivated the freeze

Phase 2L-F:

- paired effect dz: `{float(f_primary["paired_effect_dz"]):.6f}`
- two-sided sign-test p: `{float(f_primary["sign_test_p_value"]):.9f}`
- 81-test BH-FDR q: `{float(f_primary["bh_fdr_q_value"]):.6f}`

Phase 2L-G:

- cluster effect dz: `{float(g_primary["cluster_effect_dz"]):.6f}`
- two-sided date sign-test p: `{float(g_primary["date_sign_test_p_value"]):.9f}`
- 81-test BH-FDR q: `{float(g_primary["bh_fdr_q_value_cluster_sign_test"]):.6f}`
- cluster bootstrap CI excludes zero: `{g_ci_excludes_zero}`
- LODO same-sign fraction: `{g_lodo_same_sign:.6f}`
- LODO crosses zero: `{g_lodo_crosses_zero}`

Interpretation: strong Development candidate, **not** multiplicity-confirmed in
the 81-test discovery panel. Independent 2025 validation is therefore required.

## Scientific guardrails

- Matching membership remains frozen from Phase 2L-D.
- Environment variables never alter membership.
- Comparison cases are **not Negative labels**.
- No new primary variable, time offset, threshold, or direction may be chosen
  after 2025 outcomes are opened.
- 850-hPa metrics are **not Kato 500-m FLWV**.
- Validation 2025 cannot be used to tune the Primary.
- Retrospective 2026 and prospective holdout remain untouched.
- Risk engine remains disabled.

## Integrity

Exact source-code and source-artifact SHA256 values are stored in:

`{json_path}`

Git HEAD before the freeze commit:

`{git_head or "UNAVAILABLE"}`

This file must be committed before Phase 2L validation outcome analysis begins.
"""

    atomic_write_text(md_path, md)

    # Freeze outputs themselves receive hashes in a sidecar manifest.
    sidecar_path = json_path.with_name(
        json_path.stem + "_sha256.json"
    )
    sidecar = {
        "schema_version": "1.0.0",
        "gate": FREEZE_GATE,
        "freeze_json": {
            "path": str(json_path),
            "sha256": sha256_file(json_path),
            "size_bytes": json_path.stat().st_size,
        },
        "freeze_markdown": {
            "path": str(md_path),
            "sha256": sha256_file(md_path),
            "size_bytes": md_path.stat().st_size,
        },
    }
    atomic_write_json(sidecar_path, sidecar)

    print("=" * 96)
    print("LPZ PHASE 2L-H DISCOVERY / VALIDATION PROTOCOL FREEZE")
    print("=" * 96)
    print(f"Primary metric                   : {PRIMARY_METRIC}")
    print(f"Primary contrast                 : {PRIMARY_CONTRAST}")
    print("Primary direction                : POSITIVE_HIGHER")
    print("Primary cluster unit             : POSITIVE_DATE_UTC")
    print("Primary test                     : EXACT ONE-SIDED SIGN TEST")
    print("Primary alpha                    : 0.05")
    print("Development years                : 2023-2024")
    print("Validation 2025                  : UNTOUCHED / NOT READ")
    print("Retrospective 2026               : UNTOUCHED")
    print("Risk engine                      : NOT ALLOWED")
    print("")
    print("Development evidence snapshot:")
    print(
        "  Phase 2L-F q850@0h dz          : "
        f"{float(f_primary['paired_effect_dz']):.6f}"
    )
    print(
        "  Phase 2L-F 81-test FDR q       : "
        f"{float(f_primary['bh_fdr_q_value']):.6f}"
    )
    print(
        "  Phase 2L-G cluster dz           : "
        f"{float(g_primary['cluster_effect_dz']):.6f}"
    )
    print(
        "  Phase 2L-G date sign p (2-side) : "
        f"{float(g_primary['date_sign_test_p_value']):.9f}"
    )
    print(
        "  Phase 2L-G 81-test FDR q        : "
        f"{float(g_primary['bh_fdr_q_value_cluster_sign_test']):.6f}"
    )
    print(
        "  Cluster bootstrap excludes 0    : "
        f"{g_ci_excludes_zero}"
    )
    print(
        "  LODO same-sign fraction         : "
        f"{g_lodo_same_sign:.6f}"
    )
    print("")
    print(f"Freeze JSON                      : {json_path}")
    print(f"Freeze Markdown                  : {md_path}")
    print(f"Freeze SHA256 sidecar            : {sidecar_path}")
    print(f"Git HEAD before freeze commit    : {git_head or 'UNAVAILABLE'}")
    print("")
    print(f"Gate                             : {FREEZE_GATE}")
    print("=" * 96)
    print("IMPORTANT: commit these freeze artifacts BEFORE opening 2025 validation.")
    print("=" * 96)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
