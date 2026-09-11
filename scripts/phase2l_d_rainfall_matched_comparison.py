from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

METRICS = [
    "imerg_3h_mean_max_mm",
    "imerg_3h_max_max_mm",
    "imerg_3h_p90_max_mm",
    "imerg_3h_p95_max_mm",
]
KEY = ["date_utc", "primary_subdivision_code"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Phase 2L-D: build a rainfall-matched comparison population from the "
            "frozen Phase 2L-C CMORPH/IMERG Development baseline."
        )
    )
    p.add_argument("--baseline-root", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--match-ratio", type=int, default=3)
    p.add_argument("--season-window-days", type=int, default=60)
    p.add_argument("--event-buffer-days", type=int, default=3)
    return p.parse_args()


def resolve_baseline_root(path: Path) -> Path:
    path = path.resolve()
    direct = path / "BASELINE_MANIFEST.json"
    if direct.exists():
        return path
    found = sorted(path.rglob("BASELINE_MANIFEST.json"))
    if len(found) == 1:
        return found[0].parent
    if not found:
        raise FileNotFoundError(f"BASELINE_MANIFEST.json not found under: {path}")
    raise RuntimeError(
        "Multiple BASELINE_MANIFEST.json files found:\n"
        + "\n".join(str(x) for x in found)
    )


def read_csv(path: Path, *, code_col: bool = True) -> pd.DataFrame:
    dtype = {"primary_subdivision_code": "string"} if code_col else None
    return pd.read_csv(path, dtype=dtype)


def assert_unique(df: pd.DataFrame, cols: Iterable[str], label: str) -> None:
    cols = list(cols)
    dup = df.duplicated(cols, keep=False)
    if dup.any():
        sample = df.loc[dup, cols].head(20).to_dict("records")
        raise AssertionError(f"{label} has duplicate keys {cols}: {sample}")


def circular_calendar_day_distance(a: pd.Timestamp, b: pd.Timestamp) -> int:
    # Leap-year reference preserves Feb 29 if ever present.
    aa = pd.Timestamp(year=2000, month=a.month, day=a.day)
    bb = pd.Timestamp(year=2000, month=b.month, day=b.day)
    d = abs((aa - bb).days)
    return int(min(d, 366 - d))


def standardized_mean_difference(x: np.ndarray, y: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    pooled = np.sqrt((x.var(ddof=1) + y.var(ddof=1)) / 2.0)
    if pooled == 0:
        return 0.0
    return float((x.mean() - y.mean()) / pooled)


def aggregate_positive_region_days(pos: pd.DataFrame) -> pd.DataFrame:
    p = pos.copy()
    p["date_utc"] = p["date_utc_direct"].astype(str)
    p["primary_subdivision_code"] = p["primary_subdivision_code"].astype("string")
    p["analysis_time_utc"] = p["analysis_time_utc"].astype(str)

    def join_sorted(s: pd.Series) -> str:
        return "|".join(sorted({str(x) for x in s if pd.notna(x)}))

    out = (
        p.groupby(KEY, as_index=False, sort=True)
        .agg(
            episode_count=("local_episode_id", "size"),
            local_episode_ids=("local_episode_id", join_sorted),
            anchor_ids=("anchor_id", join_sorted),
            analysis_times_utc=("analysis_time_utc", join_sorted),
        )
        .sort_values(KEY, kind="mergesort")
        .reset_index(drop=True)
    )
    return out


def build_pca(imerg: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    xlog = np.log1p(imerg[METRICS].astype(float).to_numpy())
    mu = xlog.mean(axis=0)
    sd = xlog.std(axis=0, ddof=0)
    if np.any(sd <= 0):
        raise AssertionError(f"Non-positive log-metric standard deviation: {sd}")
    z = (xlog - mu) / sd
    cov = np.cov(z, rowvar=False, ddof=0)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]

    # Deterministic sign orientation for readable reports. Distances are sign invariant.
    if eigvecs[:, 0].sum() < 0:
        eigvecs[:, 0] *= -1
    max_metric_idx = METRICS.index("imerg_3h_max_max_mm")
    if eigvecs[max_metric_idx, 1] < 0:
        eigvecs[:, 1] *= -1

    scores = z @ eigvecs
    explained = eigvals / eigvals.sum()

    out = imerg.copy()
    for i in range(4):
        out[f"rain_pca_pc{i+1}"] = scores[:, i]

    meta = {
        "transform": "log1p_then_global_zscore_on_frozen_5943_region_day_reservoir",
        "metric_order": METRICS,
        "log_mean": {m: float(v) for m, v in zip(METRICS, mu)},
        "log_std_ddof0": {m: float(v) for m, v in zip(METRICS, sd)},
        "explained_variance_ratio": {
            f"pc{i+1}": float(explained[i]) for i in range(4)
        },
        "loadings": {
            f"pc{i+1}": {m: float(eigvecs[j, i]) for j, m in enumerate(METRICS)}
            for i in range(4)
        },
        "matching_components": ["rain_pca_pc1", "rain_pca_pc2"],
        "matching_components_cumulative_variance": float(explained[:2].sum()),
    }
    return out, meta


def main() -> None:
    a = parse_args()
    if a.match_ratio < 1:
        raise ValueError("--match-ratio must be >= 1")
    if not 1 <= a.season_window_days <= 183:
        raise ValueError("--season-window-days must be in 1..183")
    if a.event_buffer_days < 0:
        raise ValueError("--event-buffer-days must be >= 0")

    root = resolve_baseline_root(a.baseline_root)
    outdir = a.output_dir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    pos_path = (
        root
        / "cmorph_matched_window_census"
        / "phase2l_cmorph_positive_region_day_positions.csv"
    )
    reservoir_path = (
        root
        / "cmorph_candidate_reservoir"
        / "phase2l_cmorph_candidate_reservoir.csv"
    )
    imerg_path = (
        root
        / "imerg_rolling_3h_full"
        / "phase2l_imerg_rolling_3h_full.csv"
    )
    imerg_report_path = (
        root
        / "imerg_rolling_3h_full"
        / "phase2l_imerg_rolling_3h_full.json"
    )

    for path in (pos_path, reservoir_path, imerg_path, imerg_report_path):
        if not path.exists():
            raise FileNotFoundError(path)

    pos = read_csv(pos_path)
    reservoir = read_csv(reservoir_path)
    imerg = read_csv(imerg_path)
    imerg_report = json.loads(imerg_report_path.read_text(encoding="utf-8"))

    assert len(pos) == 65, len(pos)
    assert len(reservoir) == 5943, len(reservoir)
    assert len(imerg) == 5943, len(imerg)
    assert_unique(reservoir, KEY, "CMORPH candidate reservoir")
    assert_unique(imerg, KEY, "IMERG rolling-3h baseline")
    assert imerg_report["gate"] == "PASS_COMPLETE_IMERG_ROLLING_3H_REFINEMENT_5943_REGION_DAYS"

    # The frozen reservoir and IMERG refinement must be the same 5,943 region-days.
    key_check = reservoir[KEY].merge(imerg[KEY], on=KEY, how="outer", indicator=True)
    if not (key_check["_merge"] == "both").all():
        raise AssertionError(key_check["_merge"].value_counts().to_dict())

    positive_rd = aggregate_positive_region_days(pos)
    assert len(positive_rd) == 52, len(positive_rd)
    assert int(positive_rd["episode_count"].sum()) == 65
    assert_unique(positive_rd, KEY, "positive region-days")

    imerg_pca, pca_meta = build_pca(imerg)
    if pca_meta["matching_components_cumulative_variance"] < 0.95:
        raise AssertionError(
            "PC1+PC2 no longer explain >=95% of frozen rainfall feature variance: "
            f"{pca_meta['matching_components_cumulative_variance']:.6f}"
        )

    positive_rd = positive_rd.merge(imerg_pca, on=KEY, how="left", validate="one_to_one")
    if positive_rd[METRICS].isna().any().any():
        missing = positive_rd.loc[positive_rd[METRICS].isna().any(axis=1), KEY]
        raise AssertionError(f"Positive region-days missing IMERG refinement:\n{missing}")

    pos_key_index = pd.MultiIndex.from_frame(positive_rd[KEY])
    all_key_index = pd.MultiIndex.from_frame(imerg_pca[KEY])
    is_positive = all_key_index.isin(pos_key_index)
    comparison_pool = imerg_pca.loc[~is_positive].copy()
    assert len(comparison_pool) == 5891

    imerg_pca["date_ts"] = pd.to_datetime(imerg_pca["date_utc"], utc=True)
    positive_rd["date_ts"] = pd.to_datetime(positive_rd["date_utc"], utc=True)
    comparison_pool["date_ts"] = pd.to_datetime(comparison_pool["date_utc"], utc=True)

    positive_dates_by_region: dict[str, list[pd.Timestamp]] = {
        str(region): list(group["date_ts"])
        for region, group in positive_rd.groupby("primary_subdivision_code")
    }

    match_components = ["rain_pca_pc1", "rain_pca_pc2"]
    eligible_pools: dict[int, pd.DataFrame] = {}
    eligibility_rows: list[dict] = []

    for pi, p in positive_rd.iterrows():
        region = str(p["primary_subdivision_code"])
        pool = comparison_pool.loc[
            comparison_pool["primary_subdivision_code"].astype(str) == region
        ].copy()

        pool["season_day_difference"] = pool["date_ts"].map(
            lambda d: circular_calendar_day_distance(d, p["date_ts"])
        )
        pool = pool.loc[
            pool["season_day_difference"] <= a.season_window_days
        ].copy()

        region_positive_dates = positive_dates_by_region[region]
        if a.event_buffer_days > 0:
            near_event = pool["date_ts"].map(
                lambda d: any(
                    abs((d.normalize() - q.normalize()).days) <= a.event_buffer_days
                    for q in region_positive_dates
                )
            )
            pool = pool.loc[~near_event].copy()

        pvec = p[match_components].to_numpy(dtype=float)
        cmat = pool[match_components].to_numpy(dtype=float)
        pool["rainfall_match_distance_pc12"] = np.sqrt(
            np.mean((cmat - pvec) ** 2, axis=1)
        )
        pool = pool.sort_values(
            ["rainfall_match_distance_pc12", "season_day_difference", "date_utc"],
            kind="mergesort",
        )
        eligible_pools[pi] = pool
        eligibility_rows.append(
            {
                "positive_index": int(pi),
                "positive_date_utc": p["date_utc"],
                "primary_subdivision_code": region,
                "episode_count": int(p["episode_count"]),
                "eligible_comparison_count_before_no_replacement": int(len(pool)),
            }
        )

    eligibility = pd.DataFrame(eligibility_rows)
    if int(eligibility["eligible_comparison_count_before_no_replacement"].min()) < a.match_ratio:
        bad = eligibility.loc[
            eligibility["eligible_comparison_count_before_no_replacement"] < a.match_ratio
        ]
        raise AssertionError(
            "At least one positive region-day has too few eligible comparisons:\n"
            + bad.to_string(index=False)
        )

    # Deterministic greedy no-replacement matching: scarce positives first.
    positive_order = sorted(
        positive_rd.index,
        key=lambda i: (
            len(eligible_pools[i]),
            str(positive_rd.loc[i, "date_utc"]),
            str(positive_rd.loc[i, "primary_subdivision_code"]),
        ),
    )

    used_controls: set[int] = set()
    pairs: list[dict] = []

    for pi in positive_order:
        p = positive_rd.loc[pi]
        pool = eligible_pools[pi].loc[
            ~eligible_pools[pi].index.isin(used_controls)
        ].head(a.match_ratio)

        if len(pool) != a.match_ratio:
            raise AssertionError(
                "No-replacement matching failed for "
                f"{p['date_utc']} / {p['primary_subdivision_code']}: "
                f"needed {a.match_ratio}, found {len(pool)}"
            )

        for rank, (ci, c) in enumerate(pool.iterrows(), start=1):
            used_controls.add(int(ci))
            row = {
                "match_set_id": f"LPZRD-{pi:03d}",
                "match_rank": rank,
                "positive_date_utc": p["date_utc"],
                "primary_subdivision_code": str(p["primary_subdivision_code"]),
                "positive_episode_count": int(p["episode_count"]),
                "positive_local_episode_ids": p["local_episode_ids"],
                "positive_anchor_ids": p["anchor_ids"],
                "positive_analysis_times_utc": p["analysis_times_utc"],
                "comparison_date_utc": c["date_utc"],
                "comparison_role": "RAINFALL_MATCHED_COMPARISON_NOT_NEGATIVE_LABEL",
                "season_day_difference": int(c["season_day_difference"]),
                "rainfall_match_distance_pc12": float(c["rainfall_match_distance_pc12"]),
                "positive_rain_pca_pc1": float(p["rain_pca_pc1"]),
                "positive_rain_pca_pc2": float(p["rain_pca_pc2"]),
                "comparison_rain_pca_pc1": float(c["rain_pca_pc1"]),
                "comparison_rain_pca_pc2": float(c["rain_pca_pc2"]),
            }
            for metric in METRICS:
                row[f"positive_{metric}"] = float(p[metric])
                row[f"comparison_{metric}"] = float(c[metric])
                row[f"comparison_to_positive_ratio_{metric}"] = (
                    float(c[metric] / p[metric]) if float(p[metric]) != 0 else None
                )
            for col in [
                "imerg_3h_mean_window_start_utc",
                "imerg_3h_mean_window_end_utc",
                "imerg_3h_max_window_start_utc",
                "imerg_3h_max_window_end_utc",
                "imerg_3h_p90_window_start_utc",
                "imerg_3h_p90_window_end_utc",
                "imerg_3h_p95_window_start_utc",
                "imerg_3h_p95_window_end_utc",
            ]:
                row[f"positive_{col}"] = p[col]
                row[f"comparison_{col}"] = c[col]
            pairs.append(row)

    pairs_df = pd.DataFrame(pairs).sort_values(
        ["positive_date_utc", "primary_subdivision_code", "match_rank"],
        kind="mergesort",
    ).reset_index(drop=True)

    expected_pairs = len(positive_rd) * a.match_ratio
    assert len(pairs_df) == expected_pairs
    assert pairs_df[["comparison_date_utc", "primary_subdivision_code"]].duplicated().sum() == 0

    comparison_population = (
        pairs_df[
            [
                "comparison_date_utc",
                "primary_subdivision_code",
                "comparison_role",
                "rainfall_match_distance_pc12",
                "season_day_difference",
                "match_set_id",
                "match_rank",
            ]
        ]
        .rename(columns={"comparison_date_utc": "date_utc"})
        .merge(imerg_pca.drop(columns=["date_ts"]), on=KEY, how="left", validate="one_to_one")
        .sort_values(KEY, kind="mergesort")
        .reset_index(drop=True)
    )
    assert len(comparison_population) == expected_pairs

    positive_output = positive_rd.drop(columns=["date_ts"]).sort_values(KEY).reset_index(drop=True)

    balance_rows = []
    for metric in METRICS:
        pvals = np.log1p(pairs_df[f"positive_{metric}"].to_numpy(dtype=float))
        cvals = np.log1p(pairs_df[f"comparison_{metric}"].to_numpy(dtype=float))
        raw_p = pairs_df[f"positive_{metric}"].to_numpy(dtype=float)
        raw_c = pairs_df[f"comparison_{metric}"].to_numpy(dtype=float)
        balance_rows.append(
            {
                "metric": metric,
                "smd_log1p_positive_minus_comparison": standardized_mean_difference(pvals, cvals),
                "abs_smd_log1p": abs(standardized_mean_difference(pvals, cvals)),
                "positive_median_mm": float(np.median(raw_p)),
                "comparison_median_mm": float(np.median(raw_c)),
                "comparison_to_positive_median_ratio": float(np.median(raw_c) / np.median(raw_p)),
                "positive_mean_mm": float(np.mean(raw_p)),
                "comparison_mean_mm": float(np.mean(raw_c)),
            }
        )
    balance = pd.DataFrame(balance_rows)
    max_abs_smd = float(balance["abs_smd_log1p"].max())

    distance_summary = {
        "min": float(pairs_df["rainfall_match_distance_pc12"].min()),
        "p25": float(pairs_df["rainfall_match_distance_pc12"].quantile(0.25)),
        "median": float(pairs_df["rainfall_match_distance_pc12"].median()),
        "p75": float(pairs_df["rainfall_match_distance_pc12"].quantile(0.75)),
        "p90": float(pairs_df["rainfall_match_distance_pc12"].quantile(0.90)),
        "max": float(pairs_df["rainfall_match_distance_pc12"].max()),
    }

    # This threshold was frozen on Development only. It is a balance gate, not a risk threshold.
    balance_gate_threshold = 0.10
    gate = (
        "PASS_RAINFALL_MATCHED_COMPARISON_POPULATION_52_POSITIVE_REGION_DAYS_156_COMPARISONS"
        if max_abs_smd <= balance_gate_threshold
        else "FAIL_RAINFALL_MATCHING_BALANCE"
    )

    report = {
        "phase": "2L-D",
        "purpose": "rainfall-matched comparison population construction",
        "gate": gate,
        "baseline_root": str(root),
        "input_imerg_gate": imerg_report["gate"],
        "positive_episode_count": int(pos.shape[0]),
        "positive_unique_region_day_count": int(len(positive_rd)),
        "candidate_reservoir_region_day_count": int(len(imerg)),
        "comparison_pool_after_positive_region_day_exclusion": int(len(comparison_pool)),
        "match_ratio": int(a.match_ratio),
        "matched_comparison_region_day_count": int(len(comparison_population)),
        "unique_comparison_region_day_count": int(
            comparison_population[KEY].drop_duplicates().shape[0]
        ),
        "replacement_used": False,
        "same_primary_subdivision_required": True,
        "season_window_circular_calendar_days": int(a.season_window_days),
        "same_region_positive_event_buffer_days": int(a.event_buffer_days),
        "rainfall_matching_method": "PC1_PC2_nearest_neighbor_on_log1p_zscored_IMERG_3h_metrics",
        "pca": pca_meta,
        "match_distance_summary": distance_summary,
        "balance_metric": "absolute_standardized_mean_difference_on_log1p_raw_IMERG_metrics",
        "balance_gate_max_abs_smd": balance_gate_threshold,
        "observed_max_abs_smd": max_abs_smd,
        "minimum_eligible_comparison_count_before_no_replacement": int(
            eligibility["eligible_comparison_count_before_no_replacement"].min()
        ),
        "median_eligible_comparison_count_before_no_replacement": float(
            eligibility["eligible_comparison_count_before_no_replacement"].median()
        ),
        "hard_negative_label": None,
        "comparison_population_role": "RAINFALL_MATCHED_COMPARISON_NOT_NEGATIVE_LABEL",
        "environment_variables_used_for_selection": False,
        "source_fusion_used": False,
        "candidate_membership_changed": False,
        "validation_data_used": False,
        "retrospective_2026_used": False,
        "prospective_holdout_used": False,
        "risk_engine_allowed": False,
        "causal_claim_allowed": False,
    }

    # Scientific guardrails.
    assert report["positive_episode_count"] == 65
    assert report["positive_unique_region_day_count"] == 52
    assert report["matched_comparison_region_day_count"] == 52 * a.match_ratio
    assert report["unique_comparison_region_day_count"] == 52 * a.match_ratio
    assert report["replacement_used"] is False
    assert report["environment_variables_used_for_selection"] is False
    assert report["validation_data_used"] is False
    assert report["retrospective_2026_used"] is False
    assert report["prospective_holdout_used"] is False
    assert report["risk_engine_allowed"] is False

    positive_output.to_csv(outdir / "phase2l_d_positive_region_days.csv", index=False)
    comparison_population.to_csv(
        outdir / "phase2l_d_rainfall_matched_comparison_population.csv", index=False
    )
    pairs_df.to_csv(outdir / "phase2l_d_rainfall_matched_pairs.csv", index=False)
    balance.to_csv(outdir / "phase2l_d_rainfall_matching_balance.csv", index=False)
    eligibility.to_csv(outdir / "phase2l_d_matching_eligibility_audit.csv", index=False)
    (outdir / "phase2l_d_rainfall_matched_comparison_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=" * 88)
    print("LPZ PHASE 2L-D RAINFALL-MATCHED COMPARISON POPULATION")
    print("=" * 88)
    print(f"Baseline root                 : {root}")
    print(f"Positive episodes             : {len(pos)}")
    print(f"Positive unique region-days   : {len(positive_rd)}")
    print(f"Frozen candidate reservoir    : {len(imerg)}")
    print(f"Comparison pool               : {len(comparison_pool)}")
    print(f"Match ratio                   : 1:{a.match_ratio}")
    print(f"Matched unique comparisons    : {len(comparison_population)}")
    print(f"Same subdivision required     : YES")
    print(f"Season window                 : +/-{a.season_window_days} calendar days")
    print(f"Positive event buffer         : +/-{a.event_buffer_days} actual days")
    print(
        "PCA PC1+PC2 variance         : "
        f"{100*pca_meta['matching_components_cumulative_variance']:.3f}%"
    )
    print(f"Minimum eligible pool         : {int(eligibility['eligible_comparison_count_before_no_replacement'].min())}")
    print(f"Median match distance         : {distance_summary['median']:.6f}")
    print(f"Maximum match distance        : {distance_summary['max']:.6f}")
    print("\nRainfall balance (log1p SMD; |SMD| <= 0.10 required):")
    print(balance[["metric", "smd_log1p_positive_minus_comparison", "abs_smd_log1p"]].to_string(index=False))
    print(f"\nObserved max |SMD|           : {max_abs_smd:.6f}")
    print(f"Gate                          : {gate}")
    print("Hard negative label           : NOT CREATED")
    print("Environment variables         : NOT USED FOR MATCHING")
    print("Validation / 2026 / holdout   : NOT USED")
    print("Risk engine                   : NOT ALLOWED")
    print("=" * 88)

    if gate.startswith("FAIL"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
