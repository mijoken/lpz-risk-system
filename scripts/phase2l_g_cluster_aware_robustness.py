#!/usr/bin/env python3
"""Phase 2L-G: cluster-aware robustness audit of matched environmental findings.

Why this phase exists
---------------------
Phase 2L-F treated the 52 rainfall-matched match sets as the paired analysis
units. However, multiple Positive region-days can belong to the same UTC date
and therefore share part of the same synoptic/mesoscale event.

This audit conservatively clusters by Positive UTC date and re-evaluates all
continuous Phase 2L-F contrasts without changing:
- matched membership,
- environmental variables,
- thresholds,
- labels,
- or holdout boundaries.

Primary robustness views
------------------------
1. 52-match-set weighted mean difference (reference from Phase 2L-F)
2. Equal-weight Positive-UTC-date mean difference
3. Exact sign test on UTC-date cluster means
4. Benjamini-Hochberg FDR across the same continuous contrasts
5. Cluster bootstrap 95% CI
6. Leave-one-UTC-date-out (LODO) influence/stability

No feature selection is performed here.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

EXPECTED_MATCH_SETS = 52
EXPECTED_COMPARISONS_PER_SET = 3
EXPECTED_POSITIVE_DATE_CLUSTERS = 22
EXPECTED_CONTINUOUS_TESTS = 81

PASS_GATE = (
    "PASS_PHASE2L_G_CLUSTER_AWARE_ROBUSTNESS_"
    "52_MATCH_SETS_22_POSITIVE_UTC_DATES"
)


def exact_two_sided_sign_test(values: np.ndarray) -> tuple[int, int, float]:
    x = np.asarray(values, dtype=float)
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


def bootstrap_cluster_mean_ci(
    cluster_means: np.ndarray,
    *,
    seed: int,
    resamples: int = 20000,
) -> tuple[float, float]:
    x = np.asarray(cluster_means, dtype=float)
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


def validate_pairs_mapping(pairs: pd.DataFrame) -> pd.DataFrame:
    required = {
        "match_set_id",
        "match_rank",
        "positive_date_utc",
        "positive_imerg_3h_p95_window_start_utc",
        "primary_subdivision_code",
    }
    missing = sorted(required - set(pairs.columns))
    if missing:
        raise ValueError(f"Phase 2L-D pairs missing columns: {missing}")

    if pairs["match_set_id"].nunique() != EXPECTED_MATCH_SETS:
        raise ValueError(
            f"expected {EXPECTED_MATCH_SETS} match sets in pairs, "
            f"got {pairs['match_set_id'].nunique()}"
        )

    counts = pairs.groupby("match_set_id").size()
    if not (counts == EXPECTED_COMPARISONS_PER_SET).all():
        raise ValueError(
            "each match set must have exactly 3 comparison rows; bad="
            f"{counts[counts != EXPECTED_COMPARISONS_PER_SET].to_dict()}"
        )

    mapping_rows: list[dict[str, Any]] = []
    for set_id, g in pairs.groupby("match_set_id", sort=True):
        dates = g["positive_date_utc"].astype(str).unique().tolist()
        anchors = (
            g["positive_imerg_3h_p95_window_start_utc"]
            .astype(str)
            .unique()
            .tolist()
        )
        codes = (
            g["primary_subdivision_code"]
            .astype(str)
            .unique()
            .tolist()
        )

        if len(dates) != 1:
            raise ValueError(
                f"{set_id}: multiple positive_date_utc values: {dates}"
            )
        if len(anchors) != 1:
            raise ValueError(
                f"{set_id}: multiple positive rainfall anchors: {anchors}"
            )
        if len(codes) != 1:
            raise ValueError(
                f"{set_id}: multiple subdivision codes: {codes}"
            )

        mapping_rows.append(
            {
                "match_set_id": set_id,
                "positive_date_utc": dates[0],
                "positive_rainfall_anchor_utc": anchors[0],
                "primary_subdivision_code": codes[0],
            }
        )

    mapping = pd.DataFrame(mapping_rows)

    n_dates = mapping["positive_date_utc"].nunique()
    if n_dates != EXPECTED_POSITIVE_DATE_CLUSTERS:
        raise ValueError(
            f"expected {EXPECTED_POSITIVE_DATE_CLUSTERS} Positive UTC dates, "
            f"got {n_dates}"
        )

    return mapping


def validate_phase2lf(pair_level: pd.DataFrame) -> None:
    required = {
        "match_set_id",
        "metric",
        "contrast",
        "positive_value",
        "comparison_mean_3",
        "positive_minus_comparison",
    }
    missing = sorted(required - set(pair_level.columns))
    if missing:
        raise ValueError(
            f"Phase 2L-F pair-level CSV missing columns: {missing}"
        )

    test_count = (
        pair_level[["metric", "contrast"]]
        .drop_duplicates()
        .shape[0]
    )
    if test_count != EXPECTED_CONTINUOUS_TESTS:
        raise ValueError(
            f"expected {EXPECTED_CONTINUOUS_TESTS} continuous tests, "
            f"got {test_count}"
        )

    for (metric, contrast), g in pair_level.groupby(
        ["metric", "contrast"], sort=True
    ):
        if g["match_set_id"].nunique() != EXPECTED_MATCH_SETS:
            raise ValueError(
                f"{metric}/{contrast}: expected 52 match sets, "
                f"got {g['match_set_id'].nunique()}"
            )


def analyze(
    pair_level: pd.DataFrame,
    mapping: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    merged = pair_level.merge(
        mapping,
        on="match_set_id",
        how="left",
        validate="many_to_one",
    )

    if merged["positive_date_utc"].isna().any():
        raise ValueError("some Phase 2L-F rows failed to map to Positive date")

    summaries: list[dict[str, Any]] = []
    cluster_rows: list[dict[str, Any]] = []
    lodo_rows: list[dict[str, Any]] = []

    grouped_tests = merged.groupby(
        ["metric", "contrast"],
        sort=True,
    )

    for test_idx, ((metric, contrast), g) in enumerate(grouped_tests):
        set_diffs = g["positive_minus_comparison"].astype(float).to_numpy()
        weighted_mean = float(np.mean(set_diffs))

        cluster = (
            g.groupby("positive_date_utc", sort=True)
            .agg(
                cluster_mean_difference=(
                    "positive_minus_comparison",
                    "mean",
                ),
                match_set_count=("match_set_id", "nunique"),
            )
            .reset_index()
        )

        if len(cluster) != EXPECTED_POSITIVE_DATE_CLUSTERS:
            raise ValueError(
                f"{metric}/{contrast}: expected 22 date clusters, "
                f"got {len(cluster)}"
            )

        cluster_means = (
            cluster["cluster_mean_difference"]
            .astype(float)
            .to_numpy()
        )
        equal_date_mean = float(np.mean(cluster_means))
        equal_date_median = float(np.median(cluster_means))

        sign_pos, sign_neg, sign_p = exact_two_sided_sign_test(
            cluster_means
        )

        ci_lo, ci_hi = bootstrap_cluster_mean_ci(
            cluster_means,
            seed=20260911 + test_idx,
            resamples=20000,
        )

        # Leave-one-positive-date-out influence analysis.
        lodo_means: list[float] = []
        for date in cluster["positive_date_utc"].tolist():
            remain = cluster[
                cluster["positive_date_utc"] != date
            ]["cluster_mean_difference"].astype(float).to_numpy()

            lodo_mean = float(np.mean(remain))
            lodo_means.append(lodo_mean)

            lodo_rows.append(
                {
                    "metric": metric,
                    "contrast": contrast,
                    "left_out_positive_date_utc": date,
                    "remaining_cluster_count": len(remain),
                    "leave_one_date_out_mean_difference": lodo_mean,
                    "full_equal_date_mean_difference": equal_date_mean,
                    "absolute_shift_from_full_mean": abs(
                        lodo_mean - equal_date_mean
                    ),
                }
            )

        lodo = np.asarray(lodo_means, dtype=float)

        if equal_date_mean > 0:
            same_sign_fraction = float(np.mean(lodo > 0))
        elif equal_date_mean < 0:
            same_sign_fraction = float(np.mean(lodo < 0))
        else:
            same_sign_fraction = float(np.mean(lodo == 0))

        cluster_sd = float(np.std(cluster_means, ddof=1))
        cluster_dz = (
            float(equal_date_mean / cluster_sd)
            if cluster_sd > 0
            else float("nan")
        )

        for _, row in cluster.iterrows():
            cluster_rows.append(
                {
                    "metric": metric,
                    "contrast": contrast,
                    "positive_date_utc": row["positive_date_utc"],
                    "match_set_count": int(row["match_set_count"]),
                    "cluster_mean_difference": float(
                        row["cluster_mean_difference"]
                    ),
                }
            )

        summaries.append(
            {
                "metric": metric,
                "contrast": contrast,
                "n_match_sets": EXPECTED_MATCH_SETS,
                "n_positive_utc_date_clusters": (
                    EXPECTED_POSITIVE_DATE_CLUSTERS
                ),
                "match_set_weighted_mean_difference": weighted_mean,
                "equal_date_mean_difference": equal_date_mean,
                "equal_date_median_difference": equal_date_median,
                "cluster_sd": cluster_sd,
                "cluster_effect_dz": cluster_dz,
                "date_positive_fraction": float(
                    np.mean(cluster_means > 0)
                ),
                "date_negative_fraction": float(
                    np.mean(cluster_means < 0)
                ),
                "date_sign_test_positive_count": sign_pos,
                "date_sign_test_negative_count": sign_neg,
                "date_sign_test_p_value": sign_p,
                "cluster_bootstrap_ci95_low": ci_lo,
                "cluster_bootstrap_ci95_high": ci_hi,
                "lodo_min_mean_difference": float(np.min(lodo)),
                "lodo_max_mean_difference": float(np.max(lodo)),
                "lodo_same_sign_fraction": same_sign_fraction,
                "lodo_max_abs_shift": float(
                    np.max(np.abs(lodo - equal_date_mean))
                ),
            }
        )

    summary = pd.DataFrame(summaries)
    summary["bh_fdr_q_value_cluster_sign_test"] = bh_adjust(
        summary["date_sign_test_p_value"].astype(float).tolist()
    )
    summary["abs_cluster_effect_dz"] = summary["cluster_effect_dz"].abs()
    summary["direction_equal_date"] = np.where(
        summary["equal_date_mean_difference"] > 0,
        "POSITIVE_HIGHER",
        np.where(
            summary["equal_date_mean_difference"] < 0,
            "POSITIVE_LOWER",
            "NO_MEAN_DIFFERENCE",
        ),
    )
    summary["cluster_bootstrap_ci_excludes_zero"] = (
        (
            summary["cluster_bootstrap_ci95_low"] > 0
        )
        | (
            summary["cluster_bootstrap_ci95_high"] < 0
        )
    )
    summary["lodo_crosses_zero"] = (
        (
            summary["lodo_min_mean_difference"] <= 0
        )
        & (
            summary["lodo_max_mean_difference"] >= 0
        )
    )

    return (
        summary,
        pd.DataFrame(cluster_rows),
        pd.DataFrame(lodo_rows),
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--phase2lf-pair-level",
        default=(
            "local_data/phase2l_f_environment_discovery/"
            "phase2l_f_continuous_pair_level_differences.csv"
        ),
    )
    p.add_argument(
        "--phase2ld-pairs",
        default=(
            "local_data/phase2l_d_rainfall_matched_comparison/"
            "phase2l_d_rainfall_matched_pairs.csv"
        ),
    )
    p.add_argument(
        "--output-dir",
        default="local_data/phase2l_g_cluster_robustness",
    )
    a = p.parse_args()

    pair_level_path = Path(a.phase2lf_pair_level)
    pairs_path = Path(a.phase2ld_pairs)
    output_dir = Path(a.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pair_level = pd.read_csv(pair_level_path)
    pairs = pd.read_csv(pairs_path)

    validate_phase2lf(pair_level)
    mapping = validate_pairs_mapping(pairs)

    summary, cluster_table, lodo_table = analyze(
        pair_level,
        mapping,
    )

    summary_path = (
        output_dir
        / "phase2l_g_cluster_aware_robustness_summary.csv"
    )
    cluster_path = (
        output_dir
        / "phase2l_g_positive_date_cluster_differences.csv"
    )
    lodo_path = (
        output_dir
        / "phase2l_g_leave_one_positive_date_out.csv"
    )
    report_path = (
        output_dir
        / "phase2l_g_cluster_robustness_report.json"
    )

    summary.to_csv(summary_path, index=False)
    cluster_table.to_csv(cluster_path, index=False)
    lodo_table.to_csv(lodo_path, index=False)

    ranked = summary.sort_values(
        [
            "bh_fdr_q_value_cluster_sign_test",
            "abs_cluster_effect_dz",
        ],
        ascending=[True, False],
    ).reset_index(drop=True)

    top = []
    for _, row in ranked.head(20).iterrows():
        top.append(
            {
                "metric": row["metric"],
                "contrast": row["contrast"],
                "direction_equal_date": row["direction_equal_date"],
                "match_set_weighted_mean_difference": float(
                    row["match_set_weighted_mean_difference"]
                ),
                "equal_date_mean_difference": float(
                    row["equal_date_mean_difference"]
                ),
                "cluster_effect_dz": float(
                    row["cluster_effect_dz"]
                ),
                "date_sign_test_p_value": float(
                    row["date_sign_test_p_value"]
                ),
                "bh_fdr_q_value_cluster_sign_test": float(
                    row["bh_fdr_q_value_cluster_sign_test"]
                ),
                "cluster_bootstrap_ci95": [
                    float(row["cluster_bootstrap_ci95_low"]),
                    float(row["cluster_bootstrap_ci95_high"]),
                ],
                "lodo_same_sign_fraction": float(
                    row["lodo_same_sign_fraction"]
                ),
                "lodo_crosses_zero": bool(
                    row["lodo_crosses_zero"]
                ),
            }
        )

    report = {
        "schema_version": "0.1.0",
        "phase": "2L-G-cluster-aware-robustness-audit",
        "gate": PASS_GATE,
        "match_set_count": EXPECTED_MATCH_SETS,
        "positive_utc_date_cluster_count": (
            EXPECTED_POSITIVE_DATE_CLUSTERS
        ),
        "continuous_test_count": int(len(summary)),
        "cluster_unit": "POSITIVE_DATE_UTC",
        "primary_cluster_estimand": (
            "EQUAL_WEIGHT_MEAN_OF_POSITIVE_UTC_DATE_CLUSTER_MEANS"
        ),
        "reference_estimand": (
            "MATCH_SET_WEIGHTED_MEAN_FROM_PHASE2L_F"
        ),
        "multiplicity_control": (
            "BENJAMINI_HOCHBERG_FDR_OVER_CLUSTER_SIGN_TESTS"
        ),
        "cluster_bootstrap_resamples_per_test": 20000,
        "leave_one_cluster_out": True,
        "top_findings_ranked_for_review_only": top,
        "matching_membership_changed": False,
        "environment_variables_used_for_matching_membership": False,
        "threshold_selected": False,
        "hard_negative_label": None,
        "validation_data_used": False,
        "retrospective_2026_used": False,
        "prospective_holdout_used": False,
        "risk_engine_allowed": False,
        "outputs": {
            "summary": str(summary_path),
            "cluster_differences": str(cluster_path),
            "leave_one_date_out": str(lodo_path),
        },
    }

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=" * 96)
    print("LPZ PHASE 2L-G CLUSTER-AWARE ROBUSTNESS AUDIT")
    print("=" * 96)
    print(f"Match sets                       : {EXPECTED_MATCH_SETS}")
    print(
        f"Positive UTC-date clusters       : "
        f"{EXPECTED_POSITIVE_DATE_CLUSTERS}"
    )
    print(f"Continuous tests                 : {len(summary)}")
    print("Cluster bootstrap / test          : 20,000 resamples")
    print("")
    print("Top cluster-aware findings (review only; NOT feature selection):")
    print(
        ranked.head(12)[
            [
                "metric",
                "contrast",
                "direction_equal_date",
                "cluster_effect_dz",
                "date_sign_test_p_value",
                "bh_fdr_q_value_cluster_sign_test",
                "cluster_bootstrap_ci_excludes_zero",
                "lodo_same_sign_fraction",
                "lodo_crosses_zero",
            ]
        ].to_string(index=False)
    )
    print("")
    print(f"Gate                              : {PASS_GATE}")
    print("Matching membership               : FROZEN")
    print("Environment used for membership   : NO")
    print("Threshold selected                : NO")
    print("Hard negative label               : NOT CREATED")
    print("Validation / 2026 / holdout       : NOT USED")
    print("Risk engine                       : NOT ALLOWED")
    print(f"Summary                           : {summary_path}")
    print(f"Cluster differences               : {cluster_path}")
    print(f"Leave-one-date-out                : {lodo_path}")
    print(f"Report                            : {report_path}")
    print("=" * 96)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
