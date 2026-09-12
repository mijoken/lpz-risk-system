#!/usr/bin/env python3
"""Phase 2L-K2: freeze the IMERG Final V07 source boundary and defer 2025 validation.

This script formalizes the Phase 2L-K source-boundary finding after the
official IMERG Final V07 record ended at 2025-09-30 23:30 UTC.

It verifies:
- the original Phase 2L-H frozen validation protocol,
- the Phase 2L-K Final V07 truncation audit,
- exact supported/unavailable target counts,
- that every V07-supported target day has a valid checkpoint,
- that no frozen Positive matching universe is fully observable under V07.

It then writes:
1) machine-readable JSON freeze,
2) human-readable Markdown freeze,
3) SHA256 manifest for the two freeze artifacts and key source inputs.

This script does NOT read 2025 ERA5/environment outcomes.
It does NOT perform rainfall matching.
It does NOT substitute IMERG Late/Early or another satellite.
It does NOT change the Primary hypothesis.
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


EXPECTED_H_GATE = (
    "PASS_PHASE2L_H_DISCOVERY_AND_VALIDATION_PROTOCOL_FREEZE_PRIMARY_Q850_T0H"
)
EXPECTED_K_AUDIT_GATE = (
    "REVIEW_PHASE2L_K_IMERG_FINAL_V07_OFFICIAL_SOURCE_TRUNCATION_2025_09_30"
)
FREEZE_GATE = (
    "PASS_PHASE2L_K2_V07_BOUNDARY_AND_V08_DEFERRED_VALIDATION_FREEZE"
)

EXPECTED = {
    "total_region_days": 1218,
    "unique_target_days": 191,
    "v07_supported_region_days": 1004,
    "v07_unavailable_region_days": 214,
    "v07_supported_unique_days": 143,
    "v07_unavailable_unique_days": 48,
    "valid_total_unique_days": 143,
    "v07_supported_unique_days_missing_checkpoint": 0,
    "v07_unavailable_unique_days_with_checkpoint": 0,
    "positive_total": 23,
    "positive_v07_supported": 22,
    "positive_v07_unavailable": 1,
    "positive_fully_observable_match_universe": 0,
    "positive_source_truncated_match_universe": 23,
}

PRIMARY = {
    "id": "H_PRIMARY_Q850_T0H",
    "metric": "q850_mean_kgkg",
    "contrast": "t+0h",
    "directional_alternative": (
        "POSITIVE_Q850_GREATER_THAN_MEAN_OF_3_MATCHED_COMPARISONS"
    ),
}

FROZEN_MATCHING = {
    "unit": "JMA_PRIMARY_SUBDIVISION_REGION_DAY",
    "match_ratio": "1_POSITIVE_TO_3_COMPARISONS",
    "same_primary_subdivision_required": True,
    "season_window_calendar_days": 60,
    "positive_event_exclusion_buffer_actual_days": 3,
    "rainfall_matching_space": (
        "LOG1P_STANDARDIZED_FOUR_IMERG_3H_METRICS_PCA_PC1_PC2"
    ),
    "comparison_role": "RAINFALL_MATCHED_COMPARISON_NOT_NEGATIVE_LABEL",
    "environment_variables_used_for_matching": False,
}

PROHIBITIONS = [
    "DO_NOT_OPEN_2025_ERA5_ENVIRONMENT_FOR_PRIMARY_VALIDATION_BEFORE_RAINFALL_MATCHING_IS_RESOLVED",
    "DO_NOT_SUBSTITUTE_IMERG_LATE_OR_EARLY_FOR_FINAL_PRIMARY_VALIDATION",
    "DO_NOT_SUBSTITUTE_GSMAP_CMORPH_OR_OTHER_SATELLITE_FOR_MISSING_FINAL_IMERG_TARGETS",
    "DO_NOT_FILL_ONLY_2025_OCT_DEC_WITH_A_DIFFERENT_IMERG_VERSION",
    "DO_NOT_DROP_V07_UNAVAILABLE_2025_TARGETS_TO_FORCE_COMPLETION",
    "DO_NOT_SHRINK_OR_EXPAND_THE_FROZEN_PLUS_MINUS_60_DAY_SEASON_WINDOW",
    "DO_NOT_CHANGE_THE_PLUS_MINUS_3_DAY_POSITIVE_EVENT_BUFFER",
    "DO_NOT_CHANGE_THE_1_TO_3_NO_REPLACEMENT_MATCHING_POLICY",
    "DO_NOT_REFIT_PCA_OR_STANDARDIZATION_USING_2025_VALIDATION_DATA",
    "DO_NOT_CHANGE_PRIMARY_METRIC_TIME_OFFSET_DIRECTION_OR_TEST",
    "DO_NOT_PROMOTE_SECONDARY_OR_EXPLORATORY_FEATURES_TO_RESCUE_PRIMARY",
    "DO_NOT_USE_2026_RETROSPECTIVE_OR_PROSPECTIVE_OUTCOMES_FOR_MODEL_SELECTION",
    "DO_NOT_ENABLE_RISK_ENGINE_BEFORE_CONFIRMATORY_VALIDATION_IS_RESOLVED",
]

ALLOWED_DURING_V8_WAIT = [
    "SOURCE_HEALTH_MONITORING_AND_VERSION_DETECTION",
    "PROSPECTIVE_DATA_COLLECTION_WITHOUT_OUTCOME_DRIVEN_MODEL_SELECTION",
    "CHECKPOINT_RESUME_AND_AUDIT_INFRASTRUCTURE",
    "DATABASE_AND_SCHEMA_IMPLEMENTATION",
    "END_TO_END_PIPELINE_ORCHESTRATION_WITHOUT_2025_ENVIRONMENT_OUTCOME_OPENING",
    "DASHBOARD_AND_UI_IMPLEMENTATION_WITH_RISK_ENGINE_LOCKED",
    "WINDOWS_SCHEDULER_AND_RECOVERY_AUTOMATION",
    "V8_MIGRATION_AND_REBUILD_CODE_IMPLEMENTATION_USING_MOCK_OR_DEVELOPMENT_DATA",
    "TESTS_DOCUMENTATION_AND_OPERATIONAL_HARDENING",
]

V8_REENTRY = [
    "OFFICIAL_NASA_IMERG_FINAL_V08_IS_PUBLICLY_AVAILABLE",
    "FINAL_V08_HALF_HOURLY_PRODUCT_COVERS_ALL_REQUIRED_2023_2024_DEVELOPMENT_AND_2025_VALIDATION_DATES",
    "REBUILD_THE_FROZEN_5943_DEVELOPMENT_IMERG_REGION_DAYS_USING_FINAL_V08",
    "REBUILD_THE_FROZEN_1218_2025_VALIDATION_TARGET_REGION_DAYS_USING_THE_SAME_FINAL_V08_PRODUCT",
    "REESTIMATE_LOG1P_MEAN_STD_AND_PCA_LOADINGS_FROM_DEVELOPMENT_V08_ONLY",
    "TRANSFER_THE_DEVELOPMENT_V08_TRANSFORM_TO_2025_WITHOUT_2025_REFIT",
    "REAPPLY_THE_FROZEN_SAME_REGION_PLUS_MINUS_60_DAY_PLUS_MINUS_3_DAY_1_TO_3_NO_REPLACEMENT_MATCHING",
    "FREEZE_THE_FINAL_2025_MATCHED_POPULATION",
    "ONLY_AFTER_MATCHING_FREEZE_OPEN_2025_ERA5_ENVIRONMENT_OUTCOMES",
    "RUN_THE_SINGLE_FROZEN_Q850_T0H_CONFIRMATORY_TEST_ONCE",
    "DO_NOT_RETUNE_AFTER_PASS_OR_FAIL",
]


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
    _ = tmp.read_text(encoding="utf-8")
    tmp.replace(path)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
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


def require_equal(observed: Any, expected: Any, label: str) -> None:
    if observed != expected:
        raise ValueError(
            f"{label}: expected {expected!r}, observed {observed!r}"
        )


def require_false(observed: Any, label: str) -> None:
    if bool(observed):
        raise ValueError(f"{label}: expected False, observed {observed!r}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--phase2lh-freeze",
        default=(
            "research/phase2/"
            "phase2l_h_validation_protocol_freeze_20260911.json"
        ),
        type=Path,
    )
    p.add_argument(
        "--phase2lk-audit-report",
        default=(
            "local_data/phase2l_k_final_v07_truncation_audit/"
            "phase2l_k_final_v07_source_truncation_report.json"
        ),
        type=Path,
    )
    p.add_argument(
        "--output-json",
        default=(
            "research/phase2/"
            "phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912.json"
        ),
        type=Path,
    )
    p.add_argument(
        "--output-md",
        default=(
            "research/phase2/"
            "phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912.md"
        ),
        type=Path,
    )
    p.add_argument(
        "--output-sha256",
        default=(
            "research/phase2/"
            "phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912_sha256.json"
        ),
        type=Path,
    )
    args = p.parse_args()

    repo_root = Path(".").resolve()
    h_path = args.phase2lh_freeze.resolve()
    audit_path = args.phase2lk_audit_report.resolve()
    out_json = args.output_json.resolve()
    out_md = args.output_md.resolve()
    out_sha = args.output_sha256.resolve()

    for path in (h_path, audit_path):
        if not path.exists():
            raise FileNotFoundError(path)

    h = json.loads(h_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    require_equal(h.get("gate"), EXPECTED_H_GATE, "Phase 2L-H gate")
    require_equal(
        audit.get("gate"),
        EXPECTED_K_AUDIT_GATE,
        "Phase 2L-K truncation audit gate",
    )

    h_primary = h.get("primary_hypothesis", {})
    for key, expected in PRIMARY.items():
        require_equal(h_primary.get(key), expected, f"H primary {key}")

    h_population = h.get("population_design", {})
    for key, expected in FROZEN_MATCHING.items():
        require_equal(h_population.get(key), expected, f"H population {key}")

    targets = audit.get("targets", {})
    checkpoints = audit.get("checkpoints", {})
    positives = audit.get("official_positive_region_days", {})
    impact = audit.get("frozen_matching_impact", {})
    policy = audit.get("scientific_policy", {})

    require_equal(
        targets.get("total_region_days"),
        EXPECTED["total_region_days"],
        "total region-days",
    )
    require_equal(
        targets.get("unique_target_days"),
        EXPECTED["unique_target_days"],
        "unique target days",
    )
    require_equal(
        targets.get("v07_supported_region_days"),
        EXPECTED["v07_supported_region_days"],
        "V07-supported region-days",
    )
    require_equal(
        targets.get("v07_unavailable_region_days"),
        EXPECTED["v07_unavailable_region_days"],
        "V07-unavailable region-days",
    )
    require_equal(
        targets.get("v07_supported_unique_days"),
        EXPECTED["v07_supported_unique_days"],
        "V07-supported unique days",
    )
    require_equal(
        targets.get("v07_unavailable_unique_days"),
        EXPECTED["v07_unavailable_unique_days"],
        "V07-unavailable unique days",
    )
    require_equal(
        checkpoints.get("valid_total_unique_days"),
        EXPECTED["valid_total_unique_days"],
        "valid checkpoint days",
    )
    require_equal(
        checkpoints.get("v07_supported_unique_days_missing_checkpoint"),
        EXPECTED["v07_supported_unique_days_missing_checkpoint"],
        "supported days missing checkpoint",
    )
    require_equal(
        checkpoints.get("v07_unavailable_unique_days_with_checkpoint"),
        EXPECTED["v07_unavailable_unique_days_with_checkpoint"],
        "unsupported days with checkpoint",
    )
    require_equal(
        checkpoints.get("supported_segment_complete"),
        True,
        "supported segment complete",
    )
    require_equal(
        positives.get("total"),
        EXPECTED["positive_total"],
        "Positive total",
    )
    require_equal(
        positives.get("v07_supported"),
        EXPECTED["positive_v07_supported"],
        "Positive V07-supported",
    )
    require_equal(
        positives.get("v07_unavailable"),
        EXPECTED["positive_v07_unavailable"],
        "Positive V07-unavailable",
    )
    require_equal(
        impact.get(
            "positive_region_days_with_entire_cmorph_eligible_pool_observable_under_v07"
        ),
        EXPECTED["positive_fully_observable_match_universe"],
        "Positive fully observable matching universes",
    )
    require_equal(
        impact.get(
            "positive_region_days_with_source_truncated_candidate_universe"
        ),
        EXPECTED["positive_source_truncated_match_universe"],
        "Positive source-truncated matching universes",
    )

    # The truncation audit itself must also preserve the core policy.
    require_false(
        policy.get("fill_oct_dec_with_late_or_early_for_primary_validation"),
        "late/early substitution policy",
    )
    require_false(
        policy.get("fill_oct_dec_with_other_satellite_for_primary_validation"),
        "other-satellite substitution policy",
    )
    require_false(
        policy.get("refit_pca_on_partial_2025"),
        "partial-2025 PCA refit policy",
    )
    require_false(
        policy.get("change_primary_hypothesis"),
        "primary-change policy",
    )
    require_false(
        policy.get("open_era5_before_rainfall_matching_resolved"),
        "ERA5 opening policy",
    )
    require_false(
        policy.get("risk_engine_allowed"),
        "risk-engine policy",
    )

    generated_at = utc_now()
    git_head = git_text(["rev-parse", "HEAD"])
    git_branch = git_text(["rev-parse", "--abbrev-ref", "HEAD"])
    git_status = git_text(["status", "--short"])

    freeze = {
        "schema_version": "1.0.0",
        "phase": "2L-K2-v07-boundary-v08-deferred-validation-freeze",
        "gate": FREEZE_GATE,
        "frozen_at_utc": generated_at,
        "purpose": (
            "Freeze the official IMERG Final V07 source boundary, preserve the "
            "original Phase 2L-H confirmatory protocol, and defer the 2025 "
            "Primary validation until a consistent Final V08 reconstruction is possible."
        ),
        "upstream_protocol": {
            "phase2l_h_gate": EXPECTED_H_GATE,
            "primary_hypothesis": PRIMARY,
            "frozen_matching": FROZEN_MATCHING,
        },
        "observed_v07_boundary": {
            "source_id": "NASA_IMERG_FINAL_V07_HALFHOUR",
            "short_name": "GPM_3IMERGHH",
            "version": "07",
            "final_available_half_hour_start_utc": "2025-09-30T23:30:00Z",
            "final_available_nominal_utc_date": "2025-09-30",
            "supported_region_days": 1004,
            "unavailable_region_days": 214,
            "supported_unique_target_days": 143,
            "unavailable_unique_target_days": 48,
            "valid_supported_day_checkpoints": 143,
            "supported_days_missing_checkpoint": 0,
            "supported_segment_status": "COMPLETE",
        },
        "validation_population_impact": {
            "official_positive_region_days_total": 23,
            "official_positive_region_days_v07_supported": 22,
            "official_positive_region_days_v07_unavailable": 1,
            "fully_observed_frozen_matching_universes": 0,
            "source_truncated_frozen_matching_universes": 23,
            "exact_frozen_2025_matching_possible_under_v07": False,
        },
        "validation_state": {
            "status": "DEFERRED_PENDING_IMERG_FINAL_V08",
            "primary_confirmatory_test_run": False,
            "primary_outcome_opened": False,
            "2025_era5_environment_outcomes_may_be_opened_now": False,
            "risk_engine_allowed": False,
            "operational_system_development_may_continue": True,
        },
        "prohibitions_during_v8_wait": PROHIBITIONS,
        "allowed_work_during_v8_wait": ALLOWED_DURING_V8_WAIT,
        "v8_reentry_conditions_in_order": V8_REENTRY,
        "v8_rebuild_policy": {
            "partial_oct_dec_patch_allowed": False,
            "same_final_imerg_version_required_for_development_and_validation": True,
            "development_2023_2024_rebuild_required": True,
            "validation_2025_rebuild_required": True,
            "development_reservoir_region_days_expected": 5943,
            "validation_target_region_days_expected": 1218,
            "pca_fit_population": "DEVELOPMENT_V8_ONLY",
            "validation_transform_policy": "TRANSFER_FROZEN_DEVELOPMENT_V8_TRANSFORM_NO_2025_REFIT",
            "matching_policy_change_allowed": False,
            "primary_hypothesis_change_allowed": False,
        },
        "source_integrity": {
            "repo_root": str(repo_root),
            "git_head_before_k2_freeze_commit": git_head,
            "git_branch": git_branch,
            "git_status_before_k2_freeze_commit": git_status,
            "sha256": {
                str(h_path.relative_to(repo_root)): {
                    "sha256": sha256_file(h_path),
                    "size_bytes": h_path.stat().st_size,
                },
                str(audit_path.relative_to(repo_root)): {
                    "sha256": sha256_file(audit_path),
                    "size_bytes": audit_path.stat().st_size,
                },
            },
        },
        "next_phase": {
            "phase": "2L-L",
            "name": "SOURCE_HEALTH_AND_OPERATIONAL_READINESS",
            "goal": (
                "Continue V1 operational system completion without opening "
                "the deferred 2025 Primary environmental outcome."
            ),
        },
    }

    md = f"""# Phase 2L-K2 — IMERG Final V07 Boundary / V08 Deferred Validation Freeze

**Gate:** `{FREEZE_GATE}`  
**Frozen at:** `{generated_at}`

## Decision

The 2025 confirmatory Primary validation is **deferred**, not failed.

IMERG Final V07 ends at **2025-09-30 23:30 UTC**. The entire V07-supported
2025 target segment has been reconstructed successfully, but the frozen
rainfall-matching universe is not fully observable for any of the 23 Positive
region-days. Therefore the exact pre-specified 1:3 matching cannot be completed
without changing the frozen protocol.

## Verified source boundary

- 2025 IMERG refinement targets: **1218**
- Unique target UTC days: **191**
- V07-supported region-days: **1004**
- V07-unavailable region-days: **214**
- V07-supported target days: **143**
- Valid supported-day checkpoints: **143 / 143**
- V07-unavailable target days: **48**
- Positive region-days: **23**
- Positive region-days supported by V07: **22**
- Positive region-days unavailable under V07: **1**
- Fully observed frozen matching universes: **0 / 23**

## Frozen Primary remains unchanged

- Metric: `q850_mean_kgkg`
- Contrast: `t+0h`
- Direction: Positive > mean of 3 rainfall-matched Comparisons
- Primary confirmatory test has **not** been run.
- 2025 ERA5 environmental outcomes remain **sealed**.
- Risk engine remains **locked**.

## Work allowed while waiting for Final V08

{chr(10).join(f"- `{x}`" for x in ALLOWED_DURING_V8_WAIT)}

## Prohibited while waiting for Final V08

{chr(10).join(f"- `{x}`" for x in PROHIBITIONS)}

## Final V08 re-entry sequence

{chr(10).join(f"{i+1}. `{x}`" for i, x in enumerate(V8_REENTRY))}

## Critical version rule

Do **not** patch only October–December 2025 with V08. Development 2023–2024
and Validation 2025 must be rebuilt using the same Final V08 product family.
The rainfall transform may be re-estimated from Development V08 only and then
transferred to 2025 without validation refitting.

## Next active phase

**Phase 2L-L — Source Health and Operational Readiness**

The research confirmation branch is frozen. Operational V1 development may
continue.
"""

    atomic_write_json(out_json, freeze)
    atomic_write_text(out_md, md)

    sha_manifest = {
        "schema_version": "1.0.0",
        "gate": FREEZE_GATE,
        "generated_at_utc": utc_now(),
        "artifacts": {
            str(out_json.relative_to(repo_root)): {
                "sha256": sha256_file(out_json),
                "size_bytes": out_json.stat().st_size,
            },
            str(out_md.relative_to(repo_root)): {
                "sha256": sha256_file(out_md),
                "size_bytes": out_md.stat().st_size,
            },
        },
        "inputs": {
            str(h_path.relative_to(repo_root)): {
                "sha256": sha256_file(h_path),
                "size_bytes": h_path.stat().st_size,
            },
            str(audit_path.relative_to(repo_root)): {
                "sha256": sha256_file(audit_path),
                "size_bytes": audit_path.stat().st_size,
            },
        },
    }
    atomic_write_json(out_sha, sha_manifest)

    print("=" * 104)
    print("LPZ PHASE 2L-K2 — V07 BOUNDARY / V08 DEFERRED VALIDATION FREEZE")
    print("=" * 104)
    print("V07-supported target days          : 143 / 143 COMPLETE")
    print("V07-supported region-days          : 1004")
    print("V07-unavailable region-days        : 214")
    print("Positive region-days               : 23")
    print("Fully observed matching universes  : 0 / 23")
    print("2025 ERA5 environment opened       : NO")
    print("Primary changed                    : NO")
    print("Primary confirmatory test run      : NO")
    print("Risk engine                        : NOT ALLOWED")
    print("Operational development            : ALLOWED")
    print("Validation status                  : DEFERRED_PENDING_IMERG_FINAL_V08")
    print("")
    print(f"Gate                              : {FREEZE_GATE}")
    print(f"JSON                              : {out_json}")
    print(f"Markdown                          : {out_md}")
    print(f"SHA256 manifest                   : {out_sha}")
    print("=" * 104)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
