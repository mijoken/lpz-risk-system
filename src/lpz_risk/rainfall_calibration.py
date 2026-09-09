"""Development-only descriptive calibration for historical rainfall screening.

This module deliberately does not choose a production threshold. It summarizes
candidate metrics within the frozen DEVELOPMENT split and preserves source
identity so GSMaP, IMERG and later CMORPH can be compared without averaging.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

import numpy as np

_ALLOWED_METRICS = {
    "max_accumulation_mm",
    "mean_accumulation_mm",
    "p90_accumulation_mm",
    "p95_accumulation_mm",
    "p99_accumulation_mm",
}
_DEFAULT_QUANTILES = (0.50, 0.75, 0.90, 0.95, 0.99)


def summarize_development_metric(
    records: Iterable[dict[str, Any]],
    *,
    metric: str,
    quantiles: Iterable[float] = _DEFAULT_QUANTILES,
) -> dict[str, Any]:
    if metric not in _ALLOWED_METRICS:
        raise ValueError(f"unsupported rainfall calibration metric: {metric}")
    qs = tuple(float(q) for q in quantiles)
    if not qs or any((not np.isfinite(q)) or q <= 0.0 or q >= 1.0 for q in qs):
        raise ValueError("quantiles must be finite and strictly between 0 and 1")

    grouped: dict[str, list[float]] = defaultdict(list)
    row_count = 0
    for record in records:
        split = str(record.get("split", ""))
        if split != "DEVELOPMENT":
            raise ValueError(f"non-DEVELOPMENT record reached calibration: {split!r}")
        source = str(record.get("source_id", ""))
        if not source:
            raise ValueError("source_id is required")
        value = float(record[metric])
        if not np.isfinite(value) or value < 0.0:
            raise ValueError(f"invalid {metric}: {value}")
        grouped[source].append(value)
        row_count += 1

    if not row_count:
        raise ValueError("no DEVELOPMENT rainfall records supplied")

    sources: list[dict[str, Any]] = []
    for source in sorted(grouped):
        values = np.asarray(grouped[source], dtype=float)
        sources.append({
            "source_id": source,
            "sample_count": int(values.size),
            "metric": metric,
            "minimum": float(values.min()),
            "maximum": float(values.max()),
            "mean": float(values.mean()),
            "median": float(np.median(values)),
            "quantiles": [
                {"q": q, "value": float(np.quantile(values, q))}
                for q in qs
            ],
            "candidate_threshold_selected": False,
        })

    return {
        "schema_version": "0.1.0",
        "entity_type": "DEVELOPMENT_RAINFALL_CALIBRATION_SUMMARY",
        "split": "DEVELOPMENT",
        "metric": metric,
        "record_count": row_count,
        "sources": sources,
        "cross_source_averaging_performed": False,
        "threshold_selection_status": "NOT_SELECTED_DESCRIPTIVE_DISTRIBUTION_ONLY",
        "validation_data_used": False,
        "retrospective_test_data_used": False,
        "prospective_holdout_data_used": False,
        "hard_negative_label": None,
        "risk_score": None,
        "risk_engine_allowed": False,
    }
