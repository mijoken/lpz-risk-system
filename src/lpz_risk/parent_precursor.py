"""Per-parent descriptive precursor features for later historical validation.

This module joins temporal parent-envelope descriptors with embedded-core
genesis geometry relative to parent translation and 850-hPa inflow. It emits
raw/descriptive features only: no score, threshold, LPZ label, or back-building
classification is created here.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any


def _median(values: list[float]) -> float | None:
    return None if not values else float(statistics.median(values))


def build_parent_precursor_descriptors(
    temporal_report: dict[str, Any],
    inflow_report: dict[str, Any],
) -> list[dict[str, Any]]:
    if not temporal_report.get("execution_ok"):
        raise ValueError("temporal report is not valid")
    if not inflow_report.get("execution_ok") or not inflow_report.get("scientific_inflow_geometry_proven"):
        raise ValueError("inflow report is not scientifically proven")

    by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in inflow_report.get("events", []):
        by_parent[str(event["parent_lineage_id"])].append(event)

    out: list[dict[str, Any]] = []
    for parent in temporal_report.get("descriptors", []):
        lineage = str(parent["parent_lineage_id"])
        events = by_parent.get(lineage, [])
        usable = [
            e for e in events
            if not e.get("parent_boundary_truncated")
            and e.get("along_motion_km") is not None
            and e.get("along_inflow_km") is not None
        ]

        row: dict[str, Any] = dict(parent)
        row.update({
            "genesis_event_count": len(events),
            "usable_genesis_event_count": len(usable),
        })

        for threshold in (50, 80):
            selected = [e for e in usable if int(e["threshold_mmph"]) == threshold]
            motion = [float(e["along_motion_km"]) for e in selected]
            inflow = [float(e["along_inflow_km"]) for e in selected]
            angles = [float(e["genesis_vs_inflow_from_angle_deg"]) for e in selected]
            wind_speeds = [float(e["local_wind_850hpa"]["speed_mps"]) for e in selected]
            prefix = f"core{threshold}_genesis"
            row.update({
                f"{prefix}_usable_count": len(selected),
                f"{prefix}_behind_motion_count": sum(v < 0.0 for v in motion),
                f"{prefix}_upstream_inflow_count": sum(v > 0.0 for v in inflow),
                f"{prefix}_behind_and_upstream_count": sum(
                    float(e["along_motion_km"]) < 0.0 and float(e["along_inflow_km"]) > 0.0
                    for e in selected
                ),
                f"{prefix}_behind_motion_fraction": None if not selected else sum(v < 0.0 for v in motion) / len(selected),
                f"{prefix}_upstream_inflow_fraction": None if not selected else sum(v > 0.0 for v in inflow) / len(selected),
                f"{prefix}_behind_and_upstream_fraction": None if not selected else sum(
                    float(e["along_motion_km"]) < 0.0 and float(e["along_inflow_km"]) > 0.0
                    for e in selected
                ) / len(selected),
                f"{prefix}_median_along_motion_km": _median(motion),
                f"{prefix}_median_along_inflow_km": _median(inflow),
                f"{prefix}_median_inflow_angle_deg": _median(angles),
                f"{prefix}_median_850hpa_wind_speed_mps": _median(wind_speeds),
            })

        row["classification"] = None
        row["backbuilding_classification"] = None
        row["risk_score"] = None
        out.append(row)

    return out
