"""Explicit precipitation-source priority and disagreement policy.

This module prevents satellite backups from silently becoming equivalent to JMA 1-km
analyzed rainfall. It performs source selection/annotation only; it never emits an LPZ
classification or risk score.
"""
from __future__ import annotations

from typing import Any

PRIORITY = (
    "JMA_ANALYZED_RAINFALL_HISTORICAL",
    "GSMAP_HISTORICAL",
    "NOAA_CMORPH_CDR",
)


def select_precipitation_source(availability: dict[str, bool]) -> dict[str, Any]:
    chosen = next((s for s in PRIORITY if bool(availability.get(s))), None)
    return {
        "selected_source_id": chosen,
        "priority_order": list(PRIORITY),
        "primary_available": bool(availability.get(PRIORITY[0])),
        "backup_used": chosen is not None and chosen != PRIORITY[0],
        "selection_semantics": "EXPLICIT_PRIORITY_NO_SILENT_EQUIVALENCE",
        "hard_negative_label": None,
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
