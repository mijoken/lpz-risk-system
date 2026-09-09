"""Historical analyzed-rainfall descriptors for case screening.

These functions are descriptive only. They do NOT assign HARD_NEGATIVE labels.
The purpose is to turn audited 1-hour analyzed-rainfall grids into stable 3-hour
accumulation descriptors that can later support frozen candidate-generation
rules without outcome/model-score cherry-picking.
"""

from __future__ import annotations

from typing import Any

import numpy as np

DEFAULT_ACCUM_THRESHOLDS_MM = (80.0, 100.0, 150.0)


def accumulate_three_hour(one_hour_fields: list[np.ndarray]) -> np.ndarray:
    if len(one_hour_fields) != 3:
        raise ValueError("exactly three 1-hour fields are required")
    arrays = [np.asarray(x, dtype=float) for x in one_hour_fields]
    shape = arrays[0].shape
    if any(a.shape != shape for a in arrays):
        raise ValueError("all 1-hour fields must share one grid shape")
    if any(np.any(~np.isfinite(a)) for a in arrays):
        raise ValueError("non-finite analyzed-rainfall value present")
    if any(np.any(a < 0.0) for a in arrays):
        raise ValueError("negative analyzed-rainfall value present")
    return np.sum(np.stack(arrays, axis=0), axis=0)


def accumulation_descriptors(
    accumulation_mm: np.ndarray,
    *,
    cell_area_km2: float | np.ndarray,
    thresholds_mm: tuple[float, ...] = DEFAULT_ACCUM_THRESHOLDS_MM,
) -> dict[str, Any]:
    field = np.asarray(accumulation_mm, dtype=float)
    if field.ndim != 2 or field.size == 0:
        raise ValueError("accumulation field must be a non-empty 2-D grid")
    if np.any(~np.isfinite(field)) or np.any(field < 0.0):
        raise ValueError("accumulation field contains invalid values")

    if np.isscalar(cell_area_km2):
        area = np.full(field.shape, float(cell_area_km2), dtype=float)
    else:
        area = np.asarray(cell_area_km2, dtype=float)
        if area.shape != field.shape:
            raise ValueError("cell-area grid shape mismatch")
    if np.any(~np.isfinite(area)) or np.any(area <= 0.0):
        raise ValueError("cell areas must be finite and positive")

    threshold_rows: list[dict[str, Any]] = []
    for threshold in thresholds_mm:
        threshold = float(threshold)
        if threshold <= 0:
            raise ValueError("accumulation thresholds must be positive")
        mask = field >= threshold
        threshold_rows.append({
            "threshold_mm": threshold,
            "cell_count": int(np.count_nonzero(mask)),
            "area_km2": float(area[mask].sum()),
            "area_ge_500km2": bool(area[mask].sum() >= 500.0),
        })

    return {
        "max_accumulation_mm": float(np.max(field)),
        "mean_accumulation_mm": float(np.mean(field)),
        "p90_accumulation_mm": float(np.percentile(field, 90)),
        "p95_accumulation_mm": float(np.percentile(field, 95)),
        "p99_accumulation_mm": float(np.percentile(field, 99)),
        "grid_cell_count": int(field.size),
        "grid_area_km2": float(area.sum()),
        "threshold_descriptors": threshold_rows,
        "hard_negative_label": None,
        "lpz_classification": None,
        "risk_score": None,
    }


def build_three_hour_screening_record(
    one_hour_fields: list[np.ndarray],
    *,
    cell_area_km2: float | np.ndarray,
    valid_time_utc: str,
    primary_subdivision_code: str,
) -> dict[str, Any]:
    accum = accumulate_three_hour(one_hour_fields)
    desc = accumulation_descriptors(accum, cell_area_km2=cell_area_km2)
    return {
        "schema_version": "0.1.0",
        "entity_type": "THREE_HOUR_RAINFALL_SCREENING_RECORD",
        "valid_time_utc": str(valid_time_utc),
        "primary_subdivision_code": str(primary_subdivision_code),
        "source_product": "JMA_ANALYZED_RAINFALL_ANNUAL_1KM",
        "three_hour_derivation": "SUM_OF_THREE_TIME_ALIGNED_ONE_HOUR_FIELDS",
        **desc,
    }
