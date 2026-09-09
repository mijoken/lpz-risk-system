"""Explicit zero-cost precipitation-source priority and disagreement policy.

Paid historical media and permission-restricted datasets are never required by the
core LPZ-RISK system. Historical precipitation uses only free sources. Source
selection is explicit; coarse satellite/reanalysis grids are never treated as JMA
1-km analyzed-rainfall equivalents. This module never emits LPZ classification or
risk score.
"""
from __future__ import annotations

from typing import Any

PRIORITY = (
    "GSMAP_STANDARD_V8_HISTORICAL",
    "NASA_IMERG_FINAL_V07",
    "NOAA_CMORPH_CDR",
    "ERA5_LAND_TOTAL_PRECIPITATION",
)

PROHIBITED_REQUIRED_SOURCES = (
    "JMA_ANALYZED_RAINFALL_HISTORICAL_PAID_MEDIA",
    "DIAS_XRAIN_PERMISSION_RESTRICTED",
)


def select_precipitation_source(availability: dict[str, bool]) -> dict[str, Any]:
    chosen = next((s for s in PRIORITY if bool(availability.get(s))), None)
    return {
        "selected_source_id": chosen,
        "priority_order": list(PRIORITY),
        "primary_available": bool(availability.get(PRIORITY[0])),
        "backup_used": chosen is not None and chosen != PRIORITY[0],
        "selection_semantics": "ZERO_COST_EXPLICIT_PRIORITY_NO_SILENT_EQUIVALENCE",
        "jma_1km_threshold_reuse_allowed": False,
        "hard_negative_label": None,
        "risk_score": None,
    }


def validate_zero_cost_required_sources(required_source_ids: list[str] | tuple[str, ...]) -> dict[str, Any]:
    required = [str(x) for x in required_source_ids]
    prohibited = sorted(set(required) & set(PROHIBITED_REQUIRED_SOURCES))
    unknown = sorted(set(required) - set(PRIORITY))
    return {
        "zero_cost_policy_pass": not prohibited and not unknown,
        "required_source_ids": required,
        "prohibited_required_source_ids": prohibited,
        "unknown_required_source_ids": unknown,
        "allowed_required_source_ids": list(PRIORITY),
        "risk_score": None,
    }


def source_disagreement_record(
    *,
    primary_value_mm: float | None,
    backup_value_mm: float | None,
    primary_source_id: str = PRIORITY[0],
    backup_source_id: str = PRIORITY[1],
) -> dict[str, Any]:
    if primary_value_mm is None or backup_value_mm is None:
        return {
            "primary_source_id": primary_source_id,
            "backup_source_id": backup_source_id,
            "comparison_available": False,
            "difference_mm": None,
            "absolute_difference_mm": None,
            "ratio_backup_to_primary": None,
            "risk_score": None,
        }
    p, b = float(primary_value_mm), float(backup_value_mm)
    if p < 0 or b < 0:
        raise ValueError("precipitation values must be non-negative")
    return {
        "primary_source_id": primary_source_id,
        "backup_source_id": backup_source_id,
        "comparison_available": True,
        "difference_mm": b - p,
        "absolute_difference_mm": abs(b - p),
        "ratio_backup_to_primary": None if p == 0.0 else b / p,
        "comparison_semantics": "DIAGNOSTIC_ONLY_NOT_SOURCE_AVERAGING",
        "risk_score": None,
    }
