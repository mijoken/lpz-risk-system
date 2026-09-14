"""Pure O9-H frozen Primary confirmatory analysis kernel.

This module contains no GitHub/CDS/network operations and does not own the
one-shot execution boundary.  The guarded runner must reserve and seal the
single attempt *before* calling :func:`read_snapshot_csv` or :func:`analyze_primary`.

Frozen scientific question
--------------------------
Primary: q850_mean_kgkg at t+0h.
Match-set estimand: Positive minus mean of the three rainfall-matched
comparisons.
Cluster unit: Positive UTC date.
Primary effect: equal-weight mean of Positive-date cluster means.
Test: exact one-sided sign test, alternative cluster mean difference > 0,
zeros ignored, alpha 0.05.
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from lpz_risk.o9_era5_opening import COMPARISON_ROLE, POSITIVE_ROLE, parse_utc

PRIMARY_METRIC = "q850_mean_kgkg"
PRIMARY_PRESSURE_LEVEL_HPA = 850
PRIMARY_CONTRAST = "t+0h"
PRIMARY_SNAPSHOT_OFFSET_HOURS = 0
PRIMARY_TEST = "EXACT_ONE_SIDED_SIGN_TEST_ON_POSITIVE_DATE_UTC_CLUSTER_MEANS"
PRIMARY_ALTERNATIVE = "CLUSTER_MEAN_DIFFERENCE_GT_0"
PRIMARY_DIRECTIONAL_ALTERNATIVE = "POSITIVE_Q850_GREATER_THAN_MEAN_OF_3_MATCHED_COMPARISONS"
ZEROS_POLICY = "IGNORED"
ALPHA = 0.05
PRIMARY_CONFIRMATION_RULE = [
    "PRIMARY_EFFECT_ESTIMATE_GT_0",
    "ONE_SIDED_EXACT_SIGN_TEST_P_LT_0_05",
]
MATCH_SET_DIFFERENCE = "POSITIVE_VALUE_MINUS_MEAN_OF_3_MATCHED_COMPARISON_VALUES"
CLUSTER_UNIT = "POSITIVE_DATE_UTC"
WITHIN_CLUSTER_AGGREGATION = "MEAN_OF_MATCH_SET_DIFFERENCES_WITHIN_POSITIVE_DATE_UTC"
PRIMARY_EFFECT_ESTIMATE = "EQUAL_WEIGHT_MEAN_OF_POSITIVE_DATE_UTC_CLUSTER_MEANS"
EXPECTED_SNAPSHOT_ROWS = 368
EXPECTED_CASES = 92
EXPECTED_POSITIVES = 23
EXPECTED_COMPARISONS = 69
EXPECTED_MATCH_SETS = 23
EXPECTED_OFFSETS = {-12, -6, -3, 0}
BOOTSTRAP_RESAMPLES = 20_000
BOOTSTRAP_SEED = 20260914
SPATIAL_SEMANTICS = "REQUEST_BBOX_CONTEXT_NOT_SUBDIVISION_POLYGON_MEAN"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _finite(value: Any, *, name: str) -> float:
    try:
        out = float(value)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite")
    return out


def _int(value: Any, *, name: str) -> int:
    try:
        return int(value)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"{name} must be an integer") from exc


def read_snapshot_csv(path: Path) -> list[dict[str, str]]:
    """Read the O9-G snapshot CSV.

    The guarded O9-H runner must never call this function until the immutable
    execution seal for the unique attempt has already been persisted.
    """
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if reader.fieldnames is None:
        raise ValueError("O9-G snapshot CSV has no header")
    return rows


def exact_one_sided_sign_test_gt_zero(values: list[float] | np.ndarray) -> dict[str, Any]:
    """Exact Binomial(n, .5) upper-tail sign test with exact zeros ignored."""
    x = np.asarray(values, dtype=float)
    _require(np.isfinite(x).all(), "cluster means must all be finite")
    positive = int(np.count_nonzero(x > 0.0))
    negative = int(np.count_nonzero(x < 0.0))
    zero = int(np.count_nonzero(x == 0.0))
    n = positive + negative
    if n == 0:
        p = 1.0
    else:
        numerator = sum(math.comb(n, i) for i in range(positive, n + 1))
        p = float(numerator / (2**n))
    return {
        "positive_count": positive,
        "negative_count": negative,
        "zero_count": zero,
        "nonzero_count": n,
        "p_value_one_sided": p,
    }


def primary_passes(*, effect: float, p_value: float, alpha: float = ALPHA) -> bool:
    """Frozen confirmation rule. Equality to alpha is not a PASS."""
    return bool(effect > 0.0 and p_value < alpha)


def bootstrap_cluster_mean_ci(
    cluster_means: list[float] | np.ndarray,
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    x = np.asarray(cluster_means, dtype=float)
    _require(x.size > 0, "cannot bootstrap zero Positive-date clusters")
    _require(np.isfinite(x).all(), "bootstrap cluster means must be finite")
    _require(resamples == BOOTSTRAP_RESAMPLES, "O9-H robustness bootstrap must use frozen 20,000 resamples")
    if x.size == 1:
        return float(x[0]), float(x[0])
    rng = np.random.default_rng(seed)
    means = np.empty(resamples, dtype=float)
    cursor = 0
    batch = 1000
    while cursor < resamples:
        take = min(batch, resamples - cursor)
        idx = rng.integers(0, x.size, size=(take, x.size))
        means[cursor : cursor + take] = x[idx].mean(axis=1)
        cursor += take
    lo, hi = np.quantile(means, [0.025, 0.975])
    return float(lo), float(hi)


def _risk_score_is_locked(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip().lower()
    return text in {"", "none", "null", "nan"}


def validate_snapshot_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate the complete 92 x 4 O9-G table before Primary calculation."""
    _require(len(rows) == EXPECTED_SNAPSHOT_ROWS, f"O9-H requires exactly {EXPECTED_SNAPSHOT_ROWS} O9-G snapshot rows")
    required = {
        "match_set_id",
        "match_rank",
        "case_role",
        "date_utc",
        "primary_subdivision_code",
        "snapshot_offset_hours",
        "requested_snapshot_time_utc",
        "era5_source_time_utc",
        PRIMARY_METRIC,
        "spatial_semantics",
        "risk_score",
    }
    if rows:
        missing = sorted(required - set(rows[0]))
        _require(not missing, f"O9-H snapshot table missing columns: {missing}")

    keys: set[tuple[str, int, int]] = set()
    by_case: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    role_by_case: dict[tuple[str, int], str] = {}
    set_ids: set[str] = set()
    future_count = 0

    for i, row in enumerate(rows):
        set_id = str(row.get("match_set_id", "")).strip()
        rank = _int(row.get("match_rank"), name=f"row[{i}].match_rank")
        offset = _int(row.get("snapshot_offset_hours"), name=f"row[{i}].snapshot_offset_hours")
        role = str(row.get("case_role", "")).strip()
        code = str(row.get("primary_subdivision_code", "")).strip().zfill(6)
        _require(set_id != "", f"row {i} missing match_set_id")
        _require(rank in {0, 1, 2, 3}, f"row {i} invalid match_rank")
        _require(offset in EXPECTED_OFFSETS, f"row {i} invalid snapshot offset")
        _require(role in {POSITIVE_ROLE, COMPARISON_ROLE}, f"row {i} invalid case_role")
        _require((rank == 0) == (role == POSITIVE_ROLE), f"row {i} rank/role mismatch")
        _require(code.isdigit() and len(code) == 6, f"row {i} invalid primary subdivision code")
        _require(str(row.get("spatial_semantics", "")) == SPATIAL_SEMANTICS, f"row {i} spatial semantics changed")
        _require(_risk_score_is_locked(row.get("risk_score")), f"row {i} unexpectedly contains risk_score")

        q850 = _finite(row.get(PRIMARY_METRIC), name=f"row[{i}].{PRIMARY_METRIC}")
        _require(0.0 <= q850 < 1.0, f"row {i} q850 out of physical range")
        requested = parse_utc(row.get("requested_snapshot_time_utc"), name=f"row[{i}].requested_snapshot_time_utc")
        source = parse_utc(row.get("era5_source_time_utc"), name=f"row[{i}].era5_source_time_utc")
        if source > requested:
            future_count += 1
        try:
            date.fromisoformat(str(row.get("date_utc", "")))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"row {i} invalid date_utc") from exc

        key = (set_id, rank, offset)
        _require(key not in keys, f"duplicate O9-H snapshot key {key}")
        keys.add(key)
        case_key = (set_id, rank)
        by_case[case_key].append(row)
        prior_role = role_by_case.setdefault(case_key, role)
        _require(prior_role == role, f"case {case_key} changes role across snapshots")
        set_ids.add(set_id)

    _require(future_count == 0, "O9-H detected future ERA5 source time")
    _require(len(by_case) == EXPECTED_CASES, f"O9-H requires exactly {EXPECTED_CASES} unique cases")
    _require(len(set_ids) == EXPECTED_MATCH_SETS, f"O9-H requires exactly {EXPECTED_MATCH_SETS} match sets")
    positive_cases = sum(x == POSITIVE_ROLE for x in role_by_case.values())
    comparison_cases = sum(x == COMPARISON_ROLE for x in role_by_case.values())
    _require(positive_cases == EXPECTED_POSITIVES, "O9-H Positive case count changed")
    _require(comparison_cases == EXPECTED_COMPARISONS, "O9-H comparison case count changed")

    for case_key, case_rows in by_case.items():
        offsets = {_int(r["snapshot_offset_hours"], name="snapshot_offset_hours") for r in case_rows}
        _require(offsets == EXPECTED_OFFSETS, f"case {case_key} does not have exact frozen offsets")

    return {
        "snapshot_row_count": len(rows),
        "matched_case_count": len(by_case),
        "positive_case_count": positive_cases,
        "comparison_case_count": comparison_cases,
        "match_set_count": len(set_ids),
        "future_source_time_count": future_count,
    }


def build_match_set_differences(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    validate_snapshot_rows(rows)
    t0 = [r for r in rows if _int(r["snapshot_offset_hours"], name="snapshot_offset_hours") == PRIMARY_SNAPSHOT_OFFSET_HOURS]
    _require(len(t0) == EXPECTED_CASES, "O9-H t+0h table must contain exactly 92 cases")
    by_set: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in t0:
        by_set[str(row["match_set_id"])].append(row)

    output: list[dict[str, Any]] = []
    for set_id in sorted(by_set):
        group = by_set[set_id]
        _require(len(group) == 4, f"{set_id} must contain exactly four t+0h cases")
        by_rank = {_int(r["match_rank"], name=f"{set_id}.match_rank"): r for r in group}
        _require(set(by_rank) == {0, 1, 2, 3}, f"{set_id} must have ranks 0,1,2,3")
        _require(len(by_rank) == 4, f"{set_id} duplicate rank")
        positive = by_rank[0]
        _require(str(positive["case_role"]) == POSITIVE_ROLE, f"{set_id} rank 0 is not Positive")
        for rank in (1, 2, 3):
            _require(str(by_rank[rank]["case_role"]) == COMPARISON_ROLE, f"{set_id} rank {rank} comparison role changed")
        codes = {str(r["primary_subdivision_code"]).zfill(6) for r in group}
        _require(len(codes) == 1, f"{set_id} no longer satisfies same-primary-subdivision matching")

        positive_value = _finite(positive[PRIMARY_METRIC], name=f"{set_id}.positive_q850")
        comparison_values = [
            _finite(by_rank[r][PRIMARY_METRIC], name=f"{set_id}.comparison_{r}_q850")
            for r in (1, 2, 3)
        ]
        comparison_mean = float(np.mean(comparison_values))
        difference = positive_value - comparison_mean
        output.append({
            "match_set_id": set_id,
            "positive_date_utc": str(positive["date_utc"]),
            "primary_subdivision_code": next(iter(codes)),
            "metric": PRIMARY_METRIC,
            "contrast": PRIMARY_CONTRAST,
            "positive_value": positive_value,
            "comparison_rank1_value": comparison_values[0],
            "comparison_rank2_value": comparison_values[1],
            "comparison_rank3_value": comparison_values[2],
            "comparison_mean_3": comparison_mean,
            "positive_minus_comparison": difference,
        })
    _require(len(output) == EXPECTED_MATCH_SETS, "O9-H did not produce exactly 23 match-set differences")
    return output


def build_positive_date_clusters(pair_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pair_rows:
        groups[str(row["positive_date_utc"])].append(row)
    _require(1 <= len(groups) <= EXPECTED_MATCH_SETS, "invalid Positive-date cluster count")
    clusters: list[dict[str, Any]] = []
    for positive_date in sorted(groups):
        members = groups[positive_date]
        values = [float(x["positive_minus_comparison"]) for x in members]
        clusters.append({
            "positive_date_utc": positive_date,
            "match_set_count": len(members),
            "cluster_mean_difference": float(np.mean(values)),
        })
    _require(sum(int(x["match_set_count"]) for x in clusters) == EXPECTED_MATCH_SETS, "cluster membership does not cover all 23 match sets")
    return clusters


def _lodo_support(cluster_means: np.ndarray, full_effect: float) -> dict[str, Any]:
    if cluster_means.size < 2:
        return {
            "available": False,
            "same_sign_fraction": None,
            "min_mean_difference": None,
            "max_mean_difference": None,
            "range_crosses_zero": None,
        }
    lodo = np.asarray([
        float(np.delete(cluster_means, i).mean()) for i in range(cluster_means.size)
    ])
    if full_effect > 0:
        same_sign = float(np.mean(lodo > 0.0))
    elif full_effect < 0:
        same_sign = float(np.mean(lodo < 0.0))
    else:
        same_sign = float(np.mean(lodo == 0.0))
    lo = float(lodo.min())
    hi = float(lodo.max())
    return {
        "available": True,
        "same_sign_fraction": same_sign,
        "min_mean_difference": lo,
        "max_mean_difference": hi,
        "range_crosses_zero": bool(lo <= 0.0 <= hi),
    }


def analyze_primary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute only the frozen Primary plus its pre-specified support checks."""
    pair_rows = build_match_set_differences(rows)
    cluster_rows = build_positive_date_clusters(pair_rows)
    cluster_means = np.asarray([float(x["cluster_mean_difference"]) for x in cluster_rows], dtype=float)
    effect = float(cluster_means.mean())
    sign = exact_one_sided_sign_test_gt_zero(cluster_means)
    p_value = float(sign["p_value_one_sided"])
    outcome = "PASS" if primary_passes(effect=effect, p_value=p_value) else "FAIL"
    ci_lo, ci_hi = bootstrap_cluster_mean_ci(cluster_means)
    lodo = _lodo_support(cluster_means, effect)
    return {
        "metric": PRIMARY_METRIC,
        "pressure_level_hpa": PRIMARY_PRESSURE_LEVEL_HPA,
        "contrast": PRIMARY_CONTRAST,
        "snapshot_offset_hours": PRIMARY_SNAPSHOT_OFFSET_HOURS,
        "match_set_difference": MATCH_SET_DIFFERENCE,
        "cluster_unit": CLUSTER_UNIT,
        "within_cluster_aggregation": WITHIN_CLUSTER_AGGREGATION,
        "primary_effect_estimate_definition": PRIMARY_EFFECT_ESTIMATE,
        "primary_effect_estimate": effect,
        "test": PRIMARY_TEST,
        "alternative": PRIMARY_ALTERNATIVE,
        "zeros": ZEROS_POLICY,
        "alpha": ALPHA,
        "sign_test": sign,
        "primary_confirmation_rule": list(PRIMARY_CONFIRMATION_RULE),
        "primary_outcome": outcome,
        "positive_date_cluster_count": int(cluster_means.size),
        "robustness": {
            "status": "SUPPORT_ONLY_CANNOT_RESCUE_PRIMARY",
            "cluster_bootstrap": {
                "resamples": BOOTSTRAP_RESAMPLES,
                "seed": BOOTSTRAP_SEED,
                "ci": 0.95,
                "ci95_low": ci_lo,
                "ci95_high": ci_hi,
                "lower_confidence_bound_gt_zero": bool(ci_lo > 0.0),
            },
            "leave_one_positive_date_out": lodo,
        },
        "pair_rows": pair_rows,
        "cluster_rows": cluster_rows,
    }
