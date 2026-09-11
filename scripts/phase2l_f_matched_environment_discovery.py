#!/usr/bin/env python3
"""Phase 2L-F: matched environmental discovery for LPZ Positive vs rainfall-matched comparisons.

Input:
  52 Positive + 156 rainfall-matched Comparison cases
  52 match sets
  4 ERA5 snapshots per case (-12h, -6h, -3h, 0h)

Primary estimand:
  Positive value - mean(three matched Comparison values)

Guardrails:
- Matching membership is frozen from Phase 2L-D.
- Environment variables are NOT used to alter membership.
- No hard-negative label.
- No threshold selection.
- Validation / retrospective 2026 / prospective holdout are untouched.
- Risk engine remains disabled.
- q850 * wind850 speed is only a bbox-context proxy, NOT Kato 500 m FLWV.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

EXPECTED_ROWS = 832
EXPECTED_MATCH_SETS = 52
EXPECTED_POSITIVE_CASES = 52
EXPECTED_COMPARISON_CASES = 156
EXPECTED_OFFSETS = (-12, -6, -3, 0)

BASE_CONTINUOUS = [
    "rh500_mean_pct",
    "rh700_mean_pct",
    "rh500_rh700_gt60_fraction",
    "wind600_speed_mean_mps",
    "wind850_speed_mean_mps",
    "q1000_mean_kgkg",
    "q925_mean_kgkg",
    "q850_mean_kgkg",
]
DERIVED_CONTINUOUS = [
    "q850_x_wind850_speed_bbox_proxy",
]
CONTINUOUS = BASE_CONTINUOUS + DERIVED_CONTINUOUS

DIRECTION_METRICS = [
    "wind600_from_direction_median_deg",
    "wind850_from_direction_median_deg",
]

PASS_GATE = (
    "PASS_PHASE2L_F_MATCHED_ENVIRONMENT_DISCOVERY_"
    "52_MATCH_SETS_832_SNAPSHOTS"
)


def exact_two_sided_sign_test(diffs: np.ndarray) -> tuple[int, int, float]:
    x = np.asarray(diffs, dtype=float)
    x = x[np.isfinite(x)]
    pos = int(np.count_nonzero(x > 0.0))
    neg = int(np.count_nonzero(x < 0.0))
    n = pos + neg
    if n == 0:
        return 0, 0, 1.0
    k = min(pos, neg)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return pos, neg, float(min(1.0, 2.0 * tail))


def bh_adjust(p_values: list[float]) -> list[float]:
    p = np.asarray(p_values, dtype=float)
    n = len(p)
    if n == 0:
        return []
    order = np.argsort(p)
    ranked = p[order]
    q_ranked = np.empty(n, dtype=float)
    running = 1.0
    for i in range(n - 1, -1, -1):
        rank = i + 1
        running = min(running, ranked[i] * n / rank)
        q_ranked[i] = min(1.0, running)
    q = np.empty(n, dtype=float)
    q[order] = q_ranked
    return q.tolist()


def bootstrap_mean_ci(
    diffs: np.ndarray,
    *,
    seed: int,
    resamples: int = 10000,
) -> tuple[float, float]:
    x = np.asarray(diffs, dtype=float)
    x = x[np.isfinite(x)]
    n = x.size
    if n == 0:
        return float("nan"), float("nan")
    if n == 1:
        return float(x[0]), float(x[0])

    rng = np.random.default_rng(seed)
    means = np.empty(resamples, dtype=float)
    batch = 1000
    cursor = 0
    while cursor < resamples:
        take = min(batch, resamples - cursor)
        idx = rng.integers(0, n, size=(take, n))
        means[cursor:cursor + take] = x[idx].mean(axis=1)
        cursor += take
    lo, hi = np.quantile(means, [0.025, 0.975])
    return float(lo), float(hi)


def circular_mean_deg(values: np.ndarray) -> float:
    vals = np.asarray(values, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return float("nan")
    rad = np.deg2rad(vals)
    return float(
        math.degrees(
            math.atan2(np.mean(np.sin(rad)), np.mean(np.cos(rad)))
        ) % 360.0
    )


def signed_angular_diff_deg(a: float, b: float) -> float:
    return float(((a - b + 180.0) % 360.0) - 180.0)


def circular_resultant_length(values_deg: np.ndarray) -> float:
    vals = np.asarray(values_deg, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return float("nan")
    rad = np.deg2rad(vals)
    return float(
        math.hypot(np.mean(np.cos(rad)), np.mean(np.sin(rad)))
    )


def validate_input(df: pd.DataFrame) -> None:
    required = {
        "case_id",
        "match_set_id",
        "match_rank",
        "group",
        "primary_subdivision_code",
        "snapshot_offset_hours",
        "future_source_time_used",
        *BASE_CONTINUOUS,
        *DIRECTION_METRICS,
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"input CSV missing columns: {missing}")

    if len(df) != EXPECTED_ROWS:
        raise ValueError(f"expected {EXPECTED_ROWS} rows, got {len(df)}")

    future = df["future_source_time_used"]
    if future.dtype == object:
        future = future.astype(str).str.lower().isin(
            {"true", "1", "yes"}
        )
    else:
        future = future.astype(bool)
    if bool(future.any()):
        raise ValueError("future ERA5 source time detected")

    offsets = tuple(sorted(df["snapshot_offset_hours"].astype(int).unique()))
    if offsets != EXPECTED_OFFSETS:
        raise ValueError(
            f"expected offsets {EXPECTED_OFFSETS}, got {offsets}"
        )

    cases = df[
        ["case_id", "match_set_id", "match_rank", "group"]
    ].drop_duplicates()

    pos = cases[cases["group"] == "POSITIVE"]
    cmp = cases[cases["group"] == "COMPARISON"]

    if len(pos) != EXPECTED_POSITIVE_CASES:
        raise ValueError(
            f"expected {EXPECTED_POSITIVE_CASES} positive cases, got {len(pos)}"
        )
    if len(cmp) != EXPECTED_COMPARISON_CASES:
        raise ValueError(
            f"expected {EXPECTED_COMPARISON_CASES} comparison cases, got {len(cmp)}"
        )

    if cases["match_set_id"].nunique() != EXPECTED_MATCH_SETS:
        raise ValueError(
            f"expected {EXPECTED_MATCH_SETS} match sets, "
            f"got {cases['match_set_id'].nunique()}"
        )

    for set_id, g in cases.groupby("match_set_id"):
        p = g[g["group"] == "POSITIVE"]
        c = g[g["group"] == "COMPARISON"]
        if len(p) != 1 or len(c) != 3:
            raise ValueError(
                f"{set_id}: expected 1 Positive + 3 Comparison, "
                f"got {len(p)} + {len(c)}"
            )
        ranks = sorted(c["match_rank"].astype(int).tolist())
        if ranks != [1, 2, 3]:
            raise ValueError(
                f"{set_id}: comparison ranks must be [1,2,3], got {ranks}"
            )

    counts = df.groupby("case_id")["snapshot_offset_hours"].nunique()
    if not (counts == 4).all():
        raise ValueError(
            f"cases without exactly four offsets: "
            f"{counts[counts != 4].to_dict()}"
        )


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["q850_x_wind850_speed_bbox_proxy"] = (
        out["q850_mean_kgkg"].astype(float)
        * out["wind850_speed_mean_mps"].astype(float)
    )
    return out


def build_case_trajectory_table(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for case_id, g in df.groupby("case_id", sort=True):
        g = g.copy()
        first = g.iloc[0]
        by_offset = {
            int(r["snapshot_offset_hours"]): r
            for _, r in g.iterrows()
        }

        row: dict[str, Any] = {
            "case_id": case_id,
            "match_set_id": first["match_set_id"],
            "match_rank": int(first["match_rank"]),
            "group": first["group"],
            "primary_subdivision_code": str(
                first["primary_subdivision_code"]
            ),
        }

        for metric in CONTINUOUS:
            for offset in EXPECTED_OFFSETS:
                row[f"{metric}__t{offset:+d}h"] = float(
                    by_offset[offset][metric]
                )

            row[f"{metric}__delta_m12_to_0"] = (
                float(by_offset[0][metric])
                - float(by_offset[-12][metric])
            )
            row[f"{metric}__delta_m6_to_0"] = (
                float(by_offset[0][metric])
                - float(by_offset[-6][metric])
            )
            row[f"{metric}__delta_m3_to_0"] = (
                float(by_offset[0][metric])
                - float(by_offset[-3][metric])
            )

            vals = np.array(
                [
                    float(by_offset[o][metric])
                    for o in EXPECTED_OFFSETS
                ],
                dtype=float,
            )
            row[f"{metric}__persistence_mean"] = float(np.mean(vals))
            row[f"{metric}__persistence_min"] = float(np.min(vals))

        for metric in DIRECTION_METRICS:
            for offset in EXPECTED_OFFSETS:
                row[f"{metric}__t{offset:+d}h"] = float(
                    by_offset[offset][metric]
                )

        rows.append(row)

    result = pd.DataFrame(rows)
    if len(result) != 208:
        raise ValueError(f"expected 208 case trajectories, got {len(result)}")
    return result


def matched_continuous_analysis(
    case_table: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    features: list[tuple[str, str, str]] = []

    for metric in CONTINUOUS:
        for offset in EXPECTED_OFFSETS:
            features.append(
                (metric, f"t{offset:+d}h", f"{metric}__t{offset:+d}h")
            )
        features.extend(
            [
                (
                    metric,
                    "delta_-12h_to_0h",
                    f"{metric}__delta_m12_to_0",
                ),
                (
                    metric,
                    "delta_-6h_to_0h",
                    f"{metric}__delta_m6_to_0",
                ),
                (
                    metric,
                    "delta_-3h_to_0h",
                    f"{metric}__delta_m3_to_0",
                ),
                (
                    metric,
                    "persistence_mean",
                    f"{metric}__persistence_mean",
                ),
                (
                    metric,
                    "persistence_min",
                    f"{metric}__persistence_min",
                ),
            ]
        )

    summaries: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []

    for idx, (metric, contrast, col) in enumerate(features):
        d_list: list[float] = []
        p_list: list[float] = []
        c_list: list[float] = []

        for set_id, g in case_table.groupby("match_set_id", sort=True):
            p = float(
                g[g["group"] == "POSITIVE"].iloc[0][col]
            )
            c = float(
                g[g["group"] == "COMPARISON"][col]
                .astype(float)
                .mean()
            )
            d = p - c

            p_list.append(p)
            c_list.append(c)
            d_list.append(d)

            pairs.append(
                {
                    "match_set_id": set_id,
                    "metric": metric,
                    "contrast": contrast,
                    "positive_value": p,
                    "comparison_mean_3": c,
                    "positive_minus_comparison": d,
                }
            )

        d = np.asarray(d_list, dtype=float)
        pvals = np.asarray(p_list, dtype=float)
        cvals = np.asarray(c_list, dtype=float)

        if len(d) != EXPECTED_MATCH_SETS:
            raise ValueError(
                f"{metric}/{contrast}: expected 52 match sets, got {len(d)}"
            )

        sd = float(np.std(d, ddof=1))
        dz = float(np.mean(d) / sd) if sd > 0 else float("nan")
        sign_pos, sign_neg, sign_p = exact_two_sided_sign_test(d)
        ci_lo, ci_hi = bootstrap_mean_ci(
            d,
            seed=20260911 + idx,
            resamples=10000,
        )

        summaries.append(
            {
                "metric": metric,
                "contrast": contrast,
                "n_match_sets": len(d),
                "positive_mean": float(np.mean(pvals)),
                "comparison_mean_3": float(np.mean(cvals)),
                "mean_matched_difference": float(np.mean(d)),
                "median_matched_difference": float(np.median(d)),
                "sd_matched_difference": sd,
                "paired_effect_dz": dz,
                "positive_gt_comparison_fraction": float(
                    np.mean(d > 0)
                ),
                "positive_lt_comparison_fraction": float(
                    np.mean(d < 0)
                ),
                "sign_test_positive_count": sign_pos,
                "sign_test_negative_count": sign_neg,
                "sign_test_p_value": sign_p,
                "bootstrap_mean_diff_ci95_low": ci_lo,
                "bootstrap_mean_diff_ci95_high": ci_hi,
            }
        )

    summary = pd.DataFrame(summaries)
    summary["bh_fdr_q_value"] = bh_adjust(
        summary["sign_test_p_value"].astype(float).tolist()
    )
    summary["abs_paired_effect_dz"] = summary["paired_effect_dz"].abs()
    summary["direction_of_difference"] = np.where(
        summary["mean_matched_difference"] > 0,
        "POSITIVE_HIGHER",
        np.where(
            summary["mean_matched_difference"] < 0,
            "POSITIVE_LOWER",
            "NO_MEAN_DIFFERENCE",
        ),
    )

    return summary, pd.DataFrame(pairs)


def matched_circular_analysis(
    case_table: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summaries: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []

    for metric in DIRECTION_METRICS:
        for offset in EXPECTED_OFFSETS:
            col = f"{metric}__t{offset:+d}h"
            signed_diffs: list[float] = []
            abs_diffs: list[float] = []
            pos_dirs: list[float] = []
            cmp_dirs: list[float] = []

            for set_id, g in case_table.groupby("match_set_id", sort=True):
                p = float(
                    g[g["group"] == "POSITIVE"].iloc[0][col]
                )
                c = circular_mean_deg(
                    g[g["group"] == "COMPARISON"][col]
                    .astype(float)
                    .to_numpy()
                )
                d = signed_angular_diff_deg(p, c)

                pos_dirs.append(p)
                cmp_dirs.append(c)
                signed_diffs.append(d)
                abs_diffs.append(abs(d))

                pairs.append(
                    {
                        "match_set_id": set_id,
                        "metric": metric,
                        "offset_hours": offset,
                        "positive_direction_deg": p,
                        "comparison_circular_mean_deg": c,
                        "signed_angular_difference_deg": d,
                        "absolute_angular_difference_deg": abs(d),
                    }
                )

            diff_arr = np.asarray(signed_diffs, dtype=float)
            abs_arr = np.asarray(abs_diffs, dtype=float)

            summaries.append(
                {
                    "metric": metric,
                    "offset_hours": offset,
                    "n_match_sets": len(diff_arr),
                    "positive_circular_mean_deg": circular_mean_deg(
                        np.asarray(pos_dirs)
                    ),
                    "comparison_circular_mean_deg": circular_mean_deg(
                        np.asarray(cmp_dirs)
                    ),
                    "signed_difference_circular_mean_deg": circular_mean_deg(
                        diff_arr % 360.0
                    ),
                    "signed_difference_resultant_length": (
                        circular_resultant_length(diff_arr)
                    ),
                    "median_absolute_angular_difference_deg": float(
                        np.median(abs_arr)
                    ),
                    "mean_absolute_angular_difference_deg": float(
                        np.mean(abs_arr)
                    ),
                    "p90_absolute_angular_difference_deg": float(
                        np.quantile(abs_arr, 0.90)
                    ),
                    "inference_note": (
                        "DESCRIPTIVE_CIRCULAR_ONLY_NO_LINEAR_P_VALUE"
                    ),
                }
            )

    return pd.DataFrame(summaries), pd.DataFrame(pairs)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--input",
        default=(
            "local_data/phase2l_e_environment_features/"
            "phase2l_e_era5_snapshot_feature_table.csv"
        ),
    )
    p.add_argument(
        "--output-dir",
        default="local_data/phase2l_f_environment_discovery",
    )
    a = p.parse_args()

    input_path = Path(a.input)
    output_dir = Path(a.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(input_path)
    validate_input(df)
    df = add_derived(df)

    case_table = build_case_trajectory_table(df)
    continuous_summary, pair_level = matched_continuous_analysis(case_table)
    circular_summary, circular_pair_level = matched_circular_analysis(
        case_table
    )

    case_table_path = output_dir / "phase2l_f_case_trajectory_table.csv"
    continuous_path = output_dir / "phase2l_f_continuous_matched_summary.csv"
    pair_path = (
        output_dir
        / "phase2l_f_continuous_pair_level_differences.csv"
    )
    circular_path = output_dir / "phase2l_f_circular_wind_summary.csv"
    circular_pair_path = (
        output_dir / "phase2l_f_circular_wind_pair_level.csv"
    )
    report_path = (
        output_dir / "phase2l_f_environment_discovery_report.json"
    )

    case_table.to_csv(case_table_path, index=False)
    continuous_summary.to_csv(continuous_path, index=False)
    pair_level.to_csv(pair_path, index=False)
    circular_summary.to_csv(circular_path, index=False)
    circular_pair_level.to_csv(circular_pair_path, index=False)

    ranked = continuous_summary.sort_values(
        ["bh_fdr_q_value", "abs_paired_effect_dz"],
        ascending=[True, False],
    ).reset_index(drop=True)

    top_findings = []
    for _, row in ranked.head(20).iterrows():
        top_findings.append(
            {
                "metric": row["metric"],
                "contrast": row["contrast"],
                "direction_of_difference": row[
                    "direction_of_difference"
                ],
                "mean_matched_difference": float(
                    row["mean_matched_difference"]
                ),
                "paired_effect_dz": float(row["paired_effect_dz"]),
                "sign_test_p_value": float(row["sign_test_p_value"]),
                "bh_fdr_q_value": float(row["bh_fdr_q_value"]),
                "bootstrap_mean_diff_ci95": [
                    float(row["bootstrap_mean_diff_ci95_low"]),
                    float(row["bootstrap_mean_diff_ci95_high"]),
                ],
            }
        )

    report = {
        "schema_version": "0.1.0",
        "phase": "2L-F-rainfall-matched-environment-discovery",
        "gate": PASS_GATE,
        "input": str(input_path),
        "snapshot_row_count": int(len(df)),
        "case_trajectory_count": int(len(case_table)),
        "positive_case_count": EXPECTED_POSITIVE_CASES,
        "comparison_case_count": EXPECTED_COMPARISON_CASES,
        "match_set_count": EXPECTED_MATCH_SETS,
        "snapshot_offsets_hours": list(EXPECTED_OFFSETS),
        "continuous_metric_count": len(CONTINUOUS),
        "continuous_test_count": int(len(continuous_summary)),
        "circular_test_count": int(len(circular_summary)),
        "matched_estimand": (
            "POSITIVE_MINUS_MEAN_OF_THREE_MATCHED_COMPARISONS"
        ),
        "multiplicity_control": (
            "BENJAMINI_HOCHBERG_FDR_OVER_CONTINUOUS_TESTS"
        ),
        "bootstrap_resamples_per_test": 10000,
        "q850_transport_proxy_note": (
            "q850_mean_kgkg * wind850_speed_mean_mps is only a "
            "bbox-context moisture-transport proxy. It is NOT Kato 500 m FLWV."
        ),
        "top_findings_ranked_for_review_only": top_findings,
        "environment_variables_used_for_matching_membership": False,
        "matching_membership_changed": False,
        "threshold_selected": False,
        "hard_negative_label": None,
        "validation_data_used": False,
        "retrospective_2026_used": False,
        "prospective_holdout_used": False,
        "risk_engine_allowed": False,
        "outputs": {
            "case_trajectory_table": str(case_table_path),
            "continuous_summary": str(continuous_path),
            "continuous_pair_level": str(pair_path),
            "circular_wind_summary": str(circular_path),
            "circular_wind_pair_level": str(circular_pair_path),
        },
    }

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=" * 92)
    print("LPZ PHASE 2L-F RAINFALL-MATCHED ENVIRONMENT DISCOVERY")
    print("=" * 92)
    print(f"Input snapshots                 : {len(df)} / {EXPECTED_ROWS}")
    print(f"Positive cases                  : {EXPECTED_POSITIVE_CASES}")
    print(f"Comparison cases                : {EXPECTED_COMPARISON_CASES}")
    print(f"Match sets                      : {EXPECTED_MATCH_SETS}")
    print(f"Continuous variables            : {len(CONTINUOUS)}")
    print(f"Continuous matched tests        : {len(continuous_summary)}")
    print(f"Circular wind summaries         : {len(circular_summary)}")
    print("")
    print("Top continuous findings (review only; NOT feature selection):")
    print(
        ranked.head(12)[
            [
                "metric",
                "contrast",
                "direction_of_difference",
                "paired_effect_dz",
                "sign_test_p_value",
                "bh_fdr_q_value",
            ]
        ].to_string(index=False)
    )
    print("")
    print(f"Gate                            : {PASS_GATE}")
    print("Matching membership             : FROZEN")
    print("Environment used for membership : NO")
    print("Threshold selected              : NO")
    print("Hard negative label             : NOT CREATED")
    print("Validation / 2026 / holdout     : NOT USED")
    print("Risk engine                     : NOT ALLOWED")
    print(f"Continuous summary              : {continuous_path}")
    print(f"Circular wind summary           : {circular_path}")
    print(f"Report                          : {report_path}")
    print("=" * 92)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
