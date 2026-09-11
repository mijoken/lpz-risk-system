#!/usr/bin/env python3
"""Phase 2L-I: freeze novel-region handling before reading 2025 rainfall/environment.

Context
-------
The 2025 validation Positive-label registry has been opened after Phase 2L-H.
A domain-compatibility audit found that some Positive region-days occur in
primary subdivisions that were not among the 45 Development regions for which
the original 2023-2024 CMORPH 731-day reference was constructed.

This is a *protocol amendment after label opening but before rainfall/environment
outcome opening*. It must not be misrepresented as part of the original
pre-validation freeze.

The amendment uses only:
- frozen Phase 2L-H protocol,
- 2025 official JMA Positive labels and their region codes/dates,
- domain-compatibility metadata,
- Development-era design semantics.

It does NOT read 2025 rainfall or ERA5.

Frozen policy
-------------
1. Do not discard novel-region Positive cases merely because the original
   Development positive-driven census lacked those regions.
2. Do not estimate screening percentiles from 2025.
3. Extend only the *reference distribution* using 2023-2024 CMORPH for the
   novel primary-subdivision codes, with the exact same geometry/bbox/padding
   semantics as the original Development census.
4. Convert the Development in-sample percentile-rank rule into fixed,
   out-of-sample numeric cutoffs using Development data only:
     for each region and each metric, cutoff = minimum Development value among
     days whose pandas average percentile rank is >= 80.
   For original 45 regions, replay must reproduce the frozen 5,943-row
   reservoir exactly before any 2025 screening is allowed.
5. 2025 Positive cases are never excluded merely for failing the CMORPH
   screening rule. The screening rule defines the Comparison candidate pool,
   not Positive eligibility.
6. IMERG PCA transformation in validation uses the frozen Development
   transform (means/std/loadings); PCA is never refit on 2025.
7. Matching remains same-region, +/-60 calendar days, +/-3 actual-day Positive
   exclusion buffer, 1:3, without replacement.
8. If a Positive case cannot obtain 3 comparisons under the frozen policy,
   mark it UNMATCHABLE_UNDER_FROZEN_PROTOCOL. Do not relax geography, season
   window, event buffer, ratio, or replacement policy after seeing 2025.
9. Primary hypothesis q850@t0h and its cluster-level confirmatory test remain
   unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_FREEZE_GATE = (
    "PASS_PHASE2L_H_DISCOVERY_AND_VALIDATION_PROTOCOL_FREEZE_"
    "PRIMARY_Q850_T0H"
)
EXPECTED_OPEN_GATE = (
    "PASS_PHASE2L_I_2025_VALIDATION_POSITIVE_REGISTRY_OPENED"
)
EXPECTED_DOMAIN_GATE = (
    "REVIEW_PHASE2L_I_2025_VALIDATION_NOVEL_PRIMARY_SUBDIVISIONS"
)
PASS_GATE = (
    "PASS_PHASE2L_I_NOVEL_REGION_REFERENCE_EXTENSION_POLICY_"
    "FROZEN_PRE_RAINFALL_ENVIRONMENT"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--freeze",
        default=(
            "research/phase2/"
            "phase2l_h_validation_protocol_freeze_20260911.json"
        ),
    )
    ap.add_argument(
        "--validation-open-report",
        default=(
            "local_data/phase2l_i_2025_validation_positive_registry/"
            "phase2l_i_2025_validation_open_report.json"
        ),
    )
    ap.add_argument(
        "--domain-report",
        default=(
            "local_data/phase2l_i_2025_validation_domain_audit/"
            "phase2l_i_2025_validation_domain_compatibility_report.json"
        ),
    )
    ap.add_argument(
        "--output-json",
        default=(
            "research/phase2/"
            "phase2l_i_novel_region_reference_extension_policy_20260911.json"
        ),
    )
    ap.add_argument(
        "--output-md",
        default=(
            "research/phase2/"
            "phase2l_i_novel_region_reference_extension_policy_20260911.md"
        ),
    )
    a = ap.parse_args()

    freeze_path = Path(a.freeze)
    open_path = Path(a.validation_open_report)
    domain_path = Path(a.domain_report)

    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    opened = json.loads(open_path.read_text(encoding="utf-8"))
    domain = json.loads(domain_path.read_text(encoding="utf-8"))

    if freeze.get("gate") != EXPECTED_FREEZE_GATE:
        raise ValueError(f"unexpected Phase 2L-H freeze gate: {freeze.get('gate')}")
    if opened.get("gate") != EXPECTED_OPEN_GATE:
        raise ValueError(f"unexpected validation-open gate: {opened.get('gate')}")
    if domain.get("gate") != EXPECTED_DOMAIN_GATE:
        raise ValueError(f"unexpected domain-audit gate: {domain.get('gate')}")

    # Verify no forbidden validation outcome variables were opened.
    if opened.get("environment_variables_read") is not False:
        raise ValueError("2025 environment was already read")
    if opened.get("validation_rainfall_matching_performed") is not False:
        raise ValueError("2025 rainfall matching was already performed")
    if opened.get("primary_hypothesis_changed") is not False:
        raise ValueError("Primary hypothesis changed before amendment")

    if domain.get("validation_rainfall_read") is not False:
        raise ValueError("domain audit says 2025 rainfall was read")
    if domain.get("era5_environment_read") is not False:
        raise ValueError("domain audit says ERA5 was read")
    if domain.get("threshold_reestimated_on_2025") is not False:
        raise ValueError("domain audit says threshold was re-estimated on 2025")

    positive_rd = int(domain["validation_positive_region_day_count"])
    novel_rd = int(domain["novel_validation_region_day_count"])
    novel_codes = sorted(str(x) for x in domain["novel_validation_region_codes"])
    covered_rd = int(domain["covered_validation_region_day_count"])
    unique_regions = int(domain["validation_unique_primary_subdivision_count"])

    if positive_rd != 23:
        raise ValueError(f"expected 23 validation Positive region-days, got {positive_rd}")
    if novel_rd <= 0 or not novel_codes:
        raise ValueError("this amendment is only for a detected novel-region condition")
    if novel_rd + covered_rd != positive_rd:
        raise ValueError("covered + novel region-day counts do not sum to total")

    frozen_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    git_head = git_text(["rev-parse", "HEAD"])
    git_branch = git_text(["rev-parse", "--abbrev-ref", "HEAD"])
    git_status = git_text(["status", "--short"])

    policy = {
        "schema_version": "1.0.0",
        "phase": "2L-I-novel-region-reference-extension-policy",
        "gate": PASS_GATE,
        "frozen_at_utc": frozen_at,
        "amendment_timing": (
            "POST_2025_POSITIVE_LABEL_OPEN_"
            "PRE_2025_RAINFALL_AND_PRE_2025_ERA5"
        ),
        "transparency_note": (
            "This is not part of the original Phase 2L-H pre-validation freeze. "
            "It is a protocol amendment made after official 2025 Positive labels "
            "revealed geographic domain mismatch, but before any 2025 rainfall "
            "or environmental outcome was read."
        ),
        "known_at_amendment": {
            "validation_positive_region_day_count": positive_rd,
            "validation_unique_primary_subdivision_count": unique_regions,
            "covered_positive_region_day_count": covered_rd,
            "novel_positive_region_day_count": novel_rd,
            "novel_positive_region_day_fraction": novel_rd / positive_rd,
            "novel_primary_subdivision_codes": novel_codes,
            "validation_rainfall_read": False,
            "validation_era5_read": False,
        },
        "problem": {
            "original_development_reference_region_count": 45,
            "original_development_reference_days_per_region": 731,
            "reason_for_mismatch": (
                "The original 45-region Development census was driven by "
                "regions represented in 2023-2024 Development positives. "
                "It was not a frozen national geographic universe."
            ),
            "scientific_risk_if_unaddressed": (
                "Dropping novel-region 2025 positives would exclude nearly half "
                "of validation Positive region-days based on Development LPZ "
                "geography and would induce geographic selection bias."
            ),
        },
        "frozen_novel_region_policy": {
            "drop_novel_region_positives": False,
            "estimate_reference_from_2025": False,
            "reference_period_for_novel_regions": [2023, 2024],
            "reference_day_count_target": 731,
            "reference_source": "NOAA_CMORPH_CDR_DAILY_0P25DEG",
            "geometry_semantics": (
                "OFFICIAL_JMA_PRIMARY_SUBDIVISION_GEOMETRY_"
                "BBOX_PLUS_FROZEN_ERA5_0P5_DEG_PADDING"
            ),
            "novel_region_codes_to_extend": novel_codes,
            "extension_scope": (
                "REFERENCE_DISTRIBUTION_ONLY_USING_PRE_VALIDATION_YEARS"
            ),
        },
        "frozen_cmorph_screening_transfer": {
            "metrics": [
                "rain_max_mm_day",
                "rain_p90_mm_day",
                "rain_p95_mm_day",
            ],
            "development_percentile_rank_method": "PANDAS_RANK_AVERAGE_PCT",
            "development_percentile_threshold": 80.0,
            "logic": "ALL_THREE_METRICS_AT_OR_ABOVE_FROZEN_REGION_CUTOFF",
            "out_of_sample_cutoff_algorithm": (
                "FOR_EACH_REGION_AND_METRIC_TAKE_THE_MINIMUM_2023_2024_VALUE_"
                "AMONG_DAYS_WHOSE_PANDAS_AVERAGE_PERCENTILE_RANK_IS_GE_80"
            ),
            "required_original_45_region_replay": (
                "MUST_REPRODUCE_EXACT_FROZEN_5943_REGION_DAY_RESERVOIR"
            ),
            "novel_region_cutoffs": (
                "COMPUTE_WITH_IDENTICAL_ALGORITHM_FROM_2023_2024_ONLY"
            ),
            "positive_case_eligibility": (
                "ALL_OFFICIAL_2025_POSITIVE_REGION_DAYS_REMAIN_ELIGIBLE_"
                "REGARDLESS_OF_CMORPH_SCREEN_PASS"
            ),
            "screening_role": (
                "DEFINES_COMPARISON_CANDIDATE_POOL_NOT_POSITIVE_INCLUSION"
            ),
        },
        "frozen_imerg_transfer": {
            "rolling_window": "30_MIN_NATIVE_SLOTS_3H_ROLLING_BOUNDARY_AWARE",
            "pca_refit_on_2025": False,
            "transform_source": (
                "FROZEN_PHASE2L_D_DEVELOPMENT_LOG1P_MEAN_STD_AND_PCA_LOADINGS"
            ),
            "matching_components": ["PC1", "PC2"],
        },
        "frozen_matching_policy": {
            "same_primary_subdivision_required": True,
            "season_window_calendar_days": 60,
            "positive_event_exclusion_buffer_actual_days": 3,
            "match_ratio": 3,
            "replacement": False,
            "distance": "EUCLIDEAN_RMS_IN_FROZEN_PC1_PC2_SPACE",
            "positive_inclusion_not_conditioned_on_candidate_screen": True,
            "if_fewer_than_3_eligible_comparisons": (
                "MARK_UNMATCHABLE_UNDER_FROZEN_PROTOCOL"
            ),
            "forbidden_relaxations": [
                "NO_CROSS_REGION_MATCHING",
                "NO_WIDER_SEASON_WINDOW",
                "NO_SMALLER_EVENT_BUFFER",
                "NO_REDUCED_MATCH_RATIO_FOR_PRIMARY",
                "NO_MATCHING_WITH_REPLACEMENT",
                "NO_PCA_REFIT",
                "NO_THRESHOLD_TUNING",
            ],
        },
        "primary_confirmatory_protocol": {
            "metric": "q850_mean_kgkg",
            "contrast": "t+0h",
            "direction": "POSITIVE_HIGHER",
            "cluster_unit": "POSITIVE_DATE_UTC",
            "primary_test": "EXACT_ONE_SIDED_SIGN_TEST",
            "alpha": 0.05,
            "changed_by_amendment": False,
        },
        "attrition_policy": {
            "report_all_positive_region_days": True,
            "report_reference_extension_failures": True,
            "report_cmorph_screen_status_for_positives": True,
            "report_unmatchable_positive_cases": True,
            "no_post_hoc_substitution": True,
        },
        "forbidden": [
            "DO_NOT_USE_2025_RAINFALL_TO_DEFINE_REGION_REFERENCE",
            "DO_NOT_USE_2025_ERA5_TO_DEFINE_REGION_REFERENCE",
            "DO_NOT_DROP_NOVEL_REGIONS_BECAUSE_THEY_ARE_NOVEL",
            "DO_NOT_REFIT_PCA_ON_2025",
            "DO_NOT_CHANGE_PRIMARY_Q850_T0H",
            "DO_NOT_CHANGE_MATCHING_PARAMETERS_AFTER_2025_RAINFALL_OPEN",
            "DO_NOT_CREATE_HARD_NEGATIVE_LABEL",
            "DO_NOT_ENABLE_RISK_ENGINE",
        ],
        "source_integrity": {
            "phase2l_h_freeze_sha256": sha256_file(freeze_path),
            "validation_open_report_sha256": sha256_file(open_path),
            "domain_report_sha256": sha256_file(domain_path),
            "git_head_before_amendment_commit": git_head,
            "git_branch": git_branch,
            "git_status_before_amendment_commit": git_status,
        },
        "retrospective_2026_read": False,
        "prospective_holdout_read": False,
        "risk_engine_allowed": False,
    }

    json_path = Path(a.output_json)
    md_path = Path(a.output_md)
    atomic_write_json(json_path, policy)

    md = f"""# Phase 2L-I — Novel-Region Reference Extension Policy

**Gate:** `{PASS_GATE}`  
**Frozen at UTC:** `{frozen_at}`

## Status of this amendment

This is a **post-label-open, pre-rainfall/pre-ERA5 protocol amendment**.

It is **not** represented as part of the original Phase 2L-H pre-validation
freeze.

At the time of this amendment:

- 2025 Positive region-days known: **{positive_rd}**
- covered by the original 45-region Development reference: **{covered_rd}**
- novel-region Positive region-days: **{novel_rd}**
- novel fraction: **{100.0 * novel_rd / positive_rd:.2f}%**
- novel region codes: `{", ".join(novel_codes)}`
- 2025 rainfall read: **NO**
- 2025 ERA5/environment read: **NO**

## Frozen decision

Novel-region Positive cases will **not** be discarded.

For the novel primary subdivisions, the same CMORPH reference distribution will
be reconstructed using **2023-2024 only** (731 days), with the same JMA geometry,
bbox, and +0.5 degree padding semantics as Development.

No 2025 rainfall is used to define any threshold.

## Frozen out-of-sample CMORPH rule

For each region and each of:

- `rain_max_mm_day`
- `rain_p90_mm_day`
- `rain_p95_mm_day`

calculate the 2023-2024 pandas average percentile ranks. The fixed numeric
cutoff is the minimum Development value among days with percentile rank >= 80.

Before 2025 screening is allowed, applying those cutoffs to the original 45
Development regions must reproduce the frozen **5,943 region-day reservoir
exactly**.

For the 9 novel regions, the identical algorithm is applied to their 2023-2024
731-day reference distributions.

## Positive eligibility

Official 2025 Positive cases remain eligible **even if their own CMORPH day does
not pass the screening rule**.

The CMORPH screen defines the **Comparison candidate pool**, not Positive
eligibility.

## Frozen IMERG/matching transfer

- No PCA refit on 2025.
- Use Development log1p mean/std and PCA loadings.
- Match on frozen PC1/PC2.
- Same primary subdivision.
- +/-60 calendar days.
- Exclude +/-3 actual days around same-region Positives.
- 1:3.
- No replacement.

If a Positive has fewer than 3 eligible comparisons, it is marked
`UNMATCHABLE_UNDER_FROZEN_PROTOCOL`. Parameters are not relaxed.

## Primary hypothesis

Unchanged:

`q850_mean_kgkg @ t+0h`, Positive higher.

Cluster unit and confirmatory test are unchanged from Phase 2L-H.

## Novel regions

`{", ".join(novel_codes)}`

## Scientific guardrails

No 2025 rainfall or ERA5 was read before this amendment.
No 2025 threshold estimation is allowed.
No hard-negative label is created.
Risk engine remains disabled.
"""

    atomic_write_text(md_path, md)

    sidecar_path = json_path.with_name(json_path.stem + "_sha256.json")
    sidecar = {
        "schema_version": "1.0.0",
        "gate": PASS_GATE,
        "policy_json": {
            "path": str(json_path),
            "sha256": sha256_file(json_path),
            "size_bytes": json_path.stat().st_size,
        },
        "policy_markdown": {
            "path": str(md_path),
            "sha256": sha256_file(md_path),
            "size_bytes": md_path.stat().st_size,
        },
    }
    atomic_write_json(sidecar_path, sidecar)

    print("=" * 100)
    print("LPZ PHASE 2L-I — NOVEL-REGION REFERENCE EXTENSION POLICY FREEZE")
    print("=" * 100)
    print(f"Validation Positive region-days : {positive_rd}")
    print(f"Covered by original domain      : {covered_rd}")
    print(f"Novel-region Positive days      : {novel_rd}")
    print(f"Novel fraction                  : {100.0 * novel_rd / positive_rd:.2f}%")
    print(f"Novel region codes              : {', '.join(novel_codes)}")
    print("")
    print("2025 rainfall read               : NO")
    print("2025 ERA5/environment read       : NO")
    print("Reference extension period       : 2023-2024 ONLY")
    print("Novel positives dropped          : NO")
    print("PCA refit on 2025                : NO")
    print("Primary q850@t0h changed         : NO")
    print("Risk engine                      : NOT ALLOWED")
    print("")
    print(f"Policy JSON                      : {json_path}")
    print(f"Policy Markdown                  : {md_path}")
    print(f"SHA256 sidecar                   : {sidecar_path}")
    print(f"Git HEAD before amendment commit : {git_head or 'UNAVAILABLE'}")
    print("")
    print(f"Gate                             : {PASS_GATE}")
    print("=" * 100)
    print("IMPORTANT: commit this amendment BEFORE opening 2025 rainfall.")
    print("=" * 100)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
