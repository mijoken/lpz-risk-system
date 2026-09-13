"""Frozen 2025 rainfall matching kernel for O9-F.

This module deliberately contains no tunable validation parameters.  The matching
contract was frozen in Phase 2L-H/K2 and is reproduced exactly here:

- same JMA primary subdivision
- +/-60 circular calendar-day season window
- exclude controls within +/-3 actual days of any Positive in the same region
- PC1/PC2 rainfall distance from the Development-fitted transform
- 1 Positive : 3 comparisons
- deterministic greedy matching without replacement, scarce positives first

No environmental/ERA5 variable is accepted by the selection logic.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

KEY = ("date_utc", "primary_subdivision_code")
MATCH_COMPONENTS = ("rain_pca_pc1", "rain_pca_pc2")
MATCH_RATIO = 3
SEASON_WINDOW_DAYS = 60
EVENT_BUFFER_DAYS = 3
COMPARISON_ROLE = "RAINFALL_MATCHED_COMPARISON_NOT_NEGATIVE_LABEL"
MATCHING_CONTRACT = "PHASE2L_D_FROZEN_SAME_REGION_PC12_60D_3D_1TO3_NOREPLACEMENT_V1"


def circular_calendar_day_distance(a: pd.Timestamp, b: pd.Timestamp) -> int:
    """Return frozen Phase 2L-D circular month/day distance on leap-year 2000."""
    aa = pd.Timestamp(year=2000, month=a.month, day=a.day)
    bb = pd.Timestamp(year=2000, month=b.month, day=b.day)
    d = abs((aa - bb).days)
    return int(min(d, 366 - d))


def _as_bool(series: pd.Series, name: str = "is_official_positive") -> pd.Series:
    def one(value: Any) -> bool:
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
        raise ValueError(f"invalid boolean in {name}: {value!r}")

    return series.map(one).astype(bool)


def normalize_matching_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize only fields used by the frozen matching algorithm.

    Extra columns are intentionally retained but never referenced for selection.
    This makes environmental columns inert rather than silently useful.
    """
    required = set(KEY) | set(MATCH_COMPONENTS) | {"is_official_positive"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"matching frame missing required columns: {missing}")

    out = frame.copy()
    out["date_utc"] = pd.to_datetime(out["date_utc"], utc=True).dt.strftime("%Y-%m-%d")
    out["primary_subdivision_code"] = (
        out["primary_subdivision_code"].astype("string").str.zfill(6)
    )
    if out["primary_subdivision_code"].isna().any() or (
        out["primary_subdivision_code"].str.len() != 6
    ).any():
        raise ValueError("invalid primary_subdivision_code")
    if out.duplicated(list(KEY)).any():
        raise ValueError("matching frame contains duplicate region-day keys")

    out["is_official_positive"] = _as_bool(out["is_official_positive"])
    pc = out.loc[:, list(MATCH_COMPONENTS)].astype(float).to_numpy()
    if not np.isfinite(pc).all():
        raise ValueError("PC1/PC2 matching coordinates must be finite")

    # Canonical key order makes matching and IDs independent of input row order.
    out = out.sort_values(list(KEY), kind="mergesort").reset_index(drop=True)
    out["_o9f_row_id"] = np.arange(len(out), dtype=int)
    out["_o9f_date_ts"] = pd.to_datetime(out["date_utc"], utc=True)
    return out


def _eligible_pool_for_positive(
    positive: pd.Series,
    controls: pd.DataFrame,
    positive_dates_by_region: dict[str, list[pd.Timestamp]],
) -> pd.DataFrame:
    """Build one frozen eligible control pool; used directly by tests and matcher."""
    region = str(positive["primary_subdivision_code"])
    pool = controls.loc[
        controls["primary_subdivision_code"].astype(str) == region
    ].copy()

    pool["season_day_difference"] = pool["_o9f_date_ts"].map(
        lambda d: circular_calendar_day_distance(d, positive["_o9f_date_ts"])
    )
    pool = pool.loc[pool["season_day_difference"] <= SEASON_WINDOW_DAYS].copy()

    region_positive_dates = positive_dates_by_region.get(region, [])
    near_event = pool["_o9f_date_ts"].map(
        lambda d: any(
            abs((d.normalize() - q.normalize()).days) <= EVENT_BUFFER_DAYS
            for q in region_positive_dates
        )
    )
    pool = pool.loc[~near_event].copy()

    pvec = positive.loc[list(MATCH_COMPONENTS)].to_numpy(dtype=float)
    cmat = pool.loc[:, list(MATCH_COMPONENTS)].to_numpy(dtype=float)
    pool["rainfall_match_distance_pc12"] = np.sqrt(
        np.mean((cmat - pvec) ** 2, axis=1)
    )
    return pool.sort_values(
        ["rainfall_match_distance_pc12", "season_day_difference", "date_utc"],
        kind="mergesort",
    )


def frozen_match_2025(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Apply the exact frozen Phase 2L-D matching rule to a validation universe.

    The function does not inspect the year or expected 1,218/23 population size;
    those immutable production guards belong to the O9-F wrapper.  Keeping the
    kernel population-agnostic permits small, exact unit proofs without exposing
    any scientific tuning knobs.
    """
    all_rows = normalize_matching_frame(frame)
    positives = all_rows.loc[all_rows["is_official_positive"]].copy()
    controls = all_rows.loc[~all_rows["is_official_positive"]].copy()
    if positives.empty:
        raise ValueError("matching requires at least one official Positive")

    positive_dates_by_region: dict[str, list[pd.Timestamp]] = {
        str(region): list(group["_o9f_date_ts"])
        for region, group in positives.groupby("primary_subdivision_code", sort=True)
    }

    eligible_pools: dict[int, pd.DataFrame] = {}
    eligibility_rows: list[dict[str, Any]] = []
    for pi, positive in positives.iterrows():
        pool = _eligible_pool_for_positive(
            positive, controls, positive_dates_by_region
        )
        eligible_pools[int(pi)] = pool
        eligibility_rows.append(
            {
                "positive_index": int(pi),
                "positive_date_utc": str(positive["date_utc"]),
                "primary_subdivision_code": str(positive["primary_subdivision_code"]),
                "eligible_comparison_count_before_no_replacement": int(len(pool)),
            }
        )

    eligibility = pd.DataFrame(eligibility_rows).sort_values(
        ["positive_date_utc", "primary_subdivision_code"], kind="mergesort"
    ).reset_index(drop=True)
    if int(eligibility["eligible_comparison_count_before_no_replacement"].min()) < MATCH_RATIO:
        bad = eligibility.loc[
            eligibility["eligible_comparison_count_before_no_replacement"] < MATCH_RATIO
        ]
        raise ValueError(
            "At least one Positive has fewer than three frozen eligible comparisons: "
            + bad.to_dict("records").__repr__()
        )

    # Exact Phase 2L-D allocation policy: scarce Positive pools first, then date,
    # then region; comparisons are globally unavailable once used.
    positive_order = sorted(
        [int(i) for i in positives.index],
        key=lambda i: (
            len(eligible_pools[i]),
            str(positives.loc[i, "date_utc"]),
            str(positives.loc[i, "primary_subdivision_code"]),
        ),
    )

    used_controls: set[int] = set()
    pairs: list[dict[str, Any]] = []
    for pi in positive_order:
        positive = positives.loc[pi]
        pool = eligible_pools[pi].loc[
            ~eligible_pools[pi]["_o9f_row_id"].astype(int).isin(used_controls)
        ].head(MATCH_RATIO)
        if len(pool) != MATCH_RATIO:
            raise ValueError(
                "Frozen no-replacement matching exhausted controls for "
                f"{positive['date_utc']} / {positive['primary_subdivision_code']}: "
                f"needed {MATCH_RATIO}, found {len(pool)}"
            )

        match_set_id = (
            f"O9F-{str(positive['date_utc']).replace('-', '')}-"
            f"{str(positive['primary_subdivision_code'])}"
        )
        for rank, (_, control) in enumerate(pool.iterrows(), start=1):
            row_id = int(control["_o9f_row_id"])
            used_controls.add(row_id)
            pairs.append(
                {
                    "match_set_id": match_set_id,
                    "match_rank": rank,
                    "positive_date_utc": str(positive["date_utc"]),
                    "primary_subdivision_code": str(positive["primary_subdivision_code"]),
                    "comparison_date_utc": str(control["date_utc"]),
                    "comparison_role": COMPARISON_ROLE,
                    "season_day_difference": int(control["season_day_difference"]),
                    "rainfall_match_distance_pc12": float(
                        control["rainfall_match_distance_pc12"]
                    ),
                    "positive_rain_pca_pc1": float(positive["rain_pca_pc1"]),
                    "positive_rain_pca_pc2": float(positive["rain_pca_pc2"]),
                    "comparison_rain_pca_pc1": float(control["rain_pca_pc1"]),
                    "comparison_rain_pca_pc2": float(control["rain_pca_pc2"]),
                    "_o9f_control_row_id": row_id,
                }
            )

    pairs_df = pd.DataFrame(pairs).sort_values(
        ["positive_date_utc", "primary_subdivision_code", "match_rank"],
        kind="mergesort",
    ).reset_index(drop=True)
    expected_pairs = len(positives) * MATCH_RATIO
    if len(pairs_df) != expected_pairs:
        raise AssertionError(
            f"frozen matching pair count changed: {len(pairs_df)} != {expected_pairs}"
        )
    if pairs_df[["comparison_date_utc", "primary_subdivision_code"]].duplicated().any():
        raise AssertionError("frozen matching used a comparison more than once")

    comparison_meta = pairs_df[
        [
            "comparison_date_utc",
            "primary_subdivision_code",
            "comparison_role",
            "rainfall_match_distance_pc12",
            "season_day_difference",
            "match_set_id",
            "match_rank",
            "_o9f_control_row_id",
        ]
    ].rename(columns={"comparison_date_utc": "date_utc"})
    clean_all = all_rows.drop(columns=["_o9f_row_id", "_o9f_date_ts"])
    comparison_population = comparison_meta.drop(columns=["_o9f_control_row_id"]).merge(
        clean_all,
        on=list(KEY),
        how="left",
        validate="one_to_one",
    ).sort_values(list(KEY), kind="mergesort").reset_index(drop=True)
    if len(comparison_population) != expected_pairs:
        raise AssertionError("comparison population merge changed frozen membership")

    positive_output = positives.drop(columns=["_o9f_row_id", "_o9f_date_ts"]).sort_values(
        list(KEY), kind="mergesort"
    ).reset_index(drop=True)
    pairs_df = pairs_df.drop(columns=["_o9f_control_row_id"])

    return {
        "positive_population": positive_output,
        "matched_pairs": pairs_df,
        "comparison_population": comparison_population,
        "eligibility_audit": eligibility,
    }
