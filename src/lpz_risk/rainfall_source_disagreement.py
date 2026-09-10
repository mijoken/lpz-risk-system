"""Descriptive disagreement analysis for complete DEVELOPMENT episode representatives.

This module is intentionally non-predictive.  It compares two independent
historical precipitation providers without selecting candidate thresholds,
creating hard-negative labels, or enabling the LPZ risk engine.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np

IMERG = "NASA_IMERG_FINAL_V07"
CMORPH = "NOAA_CMORPH_CDR"


def _rank_average(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    i = 0
    while i < len(values):
        j = i + 1
        while j < len(values) and values[order[j]] == values[order[i]]:
            j += 1
        avg = (i + 1 + j) / 2.0
        ranks[order[i:j]] = avg
        i = j
    return ranks


def _corr(a: np.ndarray, b: np.ndarray) -> float | None:
    if len(a) < 2 or np.std(a) == 0 or np.std(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def _distribution(values: np.ndarray) -> dict[str, float | int | None]:
    if len(values) == 0:
        return {"n": 0, "mean": None, "min": None, "p50": None, "p75": None, "p90": None, "p95": None, "p99": None, "max": None}
    return {
        "n": int(len(values)),
        "mean": float(np.mean(values)),
        "min": float(np.min(values)),
        "p50": float(np.percentile(values, 50)),
        "p75": float(np.percentile(values, 75)),
        "p90": float(np.percentile(values, 90)),
        "p95": float(np.percentile(values, 95)),
        "p99": float(np.percentile(values, 99)),
        "max": float(np.max(values)),
    }


def analyze_dual_source_episode_representatives(
    episode_representatives: list[dict[str, Any]],
    *,
    expected_episode_count: int = 65,
) -> dict[str, Any]:
    allowed = {IMERG, CMORPH}
    rows = [r for r in episode_representatives if str(r.get("source_id")) in allowed]
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        episode = str(row.get("local_episode_id", ""))
        source = str(row.get("source_id", ""))
        if not episode or source not in allowed:
            continue
        if source in grouped[episode]:
            raise ValueError(f"duplicate episode/provider representative: {episode} {source}")
        grouped[episode][source] = row

    complete_ids = sorted(e for e, p in grouped.items() if set(p) == allowed)
    incomplete = sorted(e for e, p in grouped.items() if set(p) != allowed)
    if len(complete_ids) != expected_episode_count or incomplete:
        raise ValueError(
            f"dual-source DEVELOPMENT completeness failed: complete={len(complete_ids)} expected={expected_episode_count} incomplete={len(incomplete)}"
        )

    metrics = ("max_accumulation_mm", "mean_accumulation_mm", "p90_accumulation_mm", "p95_accumulation_mm", "p99_accumulation_mm")
    analyses: dict[str, Any] = {}
    for metric in metrics:
        imerg = np.asarray([float(grouped[e][IMERG][metric]) for e in complete_ids], dtype=float)
        cmorph = np.asarray([float(grouped[e][CMORPH][metric]) for e in complete_ids], dtype=float)
        diff = imerg - cmorph
        absdiff = np.abs(diff)
        valid_ratio = np.abs(cmorph) > 1e-6
        ratio = imerg[valid_ratio] / cmorph[valid_ratio]
        pearson = _corr(imerg, cmorph)
        spearman = _corr(_rank_average(imerg), _rank_average(cmorph))

        # Top-decile overlap is purely descriptive: the cut is the empirical
        # within-provider rank set, not a rainfall threshold or candidate rule.
        top_n = max(1, int(np.ceil(expected_episode_count * 0.10)))
        top_imerg = set(np.argsort(imerg, kind="mergesort")[-top_n:].tolist())
        top_cmorph = set(np.argsort(cmorph, kind="mergesort")[-top_n:].tolist())
        overlap = len(top_imerg & top_cmorph)

        analyses[metric] = {
            "imerg_distribution": _distribution(imerg),
            "cmorph_distribution": _distribution(cmorph),
            "difference_imerg_minus_cmorph": _distribution(diff),
            "absolute_difference": _distribution(absdiff),
            "ratio_imerg_over_cmorph_nonzero_cmorph": _distribution(ratio),
            "ratio_valid_n": int(np.sum(valid_ratio)),
            "pearson": pearson,
            "spearman": spearman,
            "top_decile_set_size_each": top_n,
            "top_decile_overlap_count": overlap,
            "top_decile_jaccard": float(overlap / len(top_imerg | top_cmorph)),
        }

    paired_rows = []
    for e in complete_ids:
        a, b = grouped[e][IMERG], grouped[e][CMORPH]
        paired_rows.append({
            "local_episode_id": e,
            "primary_subdivision_code_imerg": a.get("primary_subdivision_code"),
            "primary_subdivision_code_cmorph": b.get("primary_subdivision_code"),
            "analysis_time_utc_imerg": a.get("analysis_time_utc"),
            "analysis_time_utc_cmorph": b.get("analysis_time_utc"),
            "imerg_max_accumulation_mm": a.get("max_accumulation_mm"),
            "cmorph_max_accumulation_mm": b.get("max_accumulation_mm"),
        })

    return {
        "schema_version": "0.1.0",
        "phase": "2J-development-dual-source-disagreement",
        "split": "DEVELOPMENT",
        "providers": [IMERG, CMORPH],
        "expected_episode_count": expected_episode_count,
        "paired_episode_count": len(complete_ids),
        "pairing_key": "local_episode_id",
        "representative_policy": "EARLIEST_REALIZED_POSITIVE_ANCHOR_PER_LOCAL_EPISODE_PROVIDER",
        "cross_subdivision_episode_grouping_complete": False,
        "metric_analyses": analyses,
        "paired_episode_rows": paired_rows,
        "source_disagreement_role": "DESCRIPTIVE_DATA_QUALITY_DIAGNOSTIC_ONLY",
        "candidate_threshold_selected": False,
        "hard_negative_label": None,
        "validation_data_used": False,
        "retrospective_test_data_used": False,
        "prospective_holdout_data_used": False,
        "risk_score": None,
        "risk_engine_allowed": False,
        "gate": "PASS_COMPLETE_DUAL_SOURCE_DEVELOPMENT_DESCRIPTIVE_ANALYSIS",
    }
