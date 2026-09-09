"""Temporal descriptors for broader precipitation-parent lineages.

Descriptors summarize observed motion, overlap, area evolution, and embedded
core activity. They intentionally avoid stationarity/back-building thresholds.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def _mean(values: list[float]) -> float | None:
    return None if not values else float(sum(values) / len(values))


def _median(values: list[float]) -> float | None:
    return None if not values else float(statistics.median(values))


def build_parent_temporal_descriptors(
    tracking_report: dict[str, Any],
    hierarchy_report: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build one descriptor per >=30 mm/h parent lineage."""
    if not tracking_report.get("scientific_tracking_proven"):
        raise ValueError("tracking report is not scientifically proven")
    if not hierarchy_report.get("scientific_hierarchy_proven"):
        raise ValueError("hierarchy report is not scientifically proven")

    parent_track = tracking_report["tracking"]["30"]
    frame_components: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for frame_index, frame in enumerate(parent_track["frames"]):
        for comp in frame["components"]:
            frame_components[str(comp["lineage_id"])].append({"frame_index": frame_index, **comp})

    transition_metrics: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for transition in parent_track["transitions"]:
        for match in transition["primary_matches"]:
            transition_metrics[str(match["lineage_id"])].append(match)

    core_presence_frames: dict[tuple[str, int], set[int]] = defaultdict(set)
    for frame in hierarchy_report["frames"]:
        frame_index = int(frame["frame_index"])
        for threshold in (50, 80):
            for assignment in frame["children"][str(threshold)]["assignments"]:
                core_presence_frames[(str(assignment["parent_lineage_id"]), threshold)].add(frame_index)

    core_genesis: dict[tuple[str, int], int] = defaultdict(int)
    for event in hierarchy_report.get("genesis_events", []):
        core_genesis[(str(event["parent_lineage_id"]), int(event["threshold_mmph"]))] += 1

    lineage_meta = {str(row["lineage_id"]): row for row in parent_track["lineages"]}
    descriptors: list[dict[str, Any]] = []

    for lineage_id, components in frame_components.items():
        components = sorted(components, key=lambda row: row["frame_index"])
        meta = lineage_meta[lineage_id]
        matches = transition_metrics.get(lineage_id, [])
        areas = [float(row["approx_area_km2"]) for row in components]
        first_centroid = components[0]["centroid"]
        last_centroid = components[-1]["centroid"]
        net_displacement = haversine_km(
            float(first_centroid["lon"]), float(first_centroid["lat"]),
            float(last_centroid["lon"]), float(last_centroid["lat"]),
        ) if len(components) > 1 else 0.0
        path_km = sum(float(row.get("centroid_displacement_km") or 0.0) for row in matches)
        speeds = [float(row["centroid_speed_mps"]) for row in matches if row.get("centroid_speed_mps") is not None]
        ious = [float(row["iou"]) for row in matches]
        overlap_prev = [float(row["overlap_previous"]) for row in matches]
        overlap_curr = [float(row["overlap_current"]) for row in matches]
        frame_count = int(meta["frame_count"])
        frames50 = core_presence_frames.get((lineage_id, 50), set())
        frames80 = core_presence_frames.get((lineage_id, 80), set())

        descriptors.append({
            "parent_lineage_id": lineage_id,
            "first_frame_index": int(meta["first_frame_index"]),
            "last_frame_index": int(meta["last_frame_index"]),
            "frame_count": frame_count,
            "duration_minutes": int(meta["duration_minutes"]),
            "first_centroid": first_centroid,
            "last_centroid": last_centroid,
            "net_centroid_displacement_km": net_displacement,
            "matched_path_displacement_km": path_km,
            "mean_speed_mps": _mean(speeds),
            "median_speed_mps": _median(speeds),
            "max_speed_mps": None if not speeds else max(speeds),
            "median_iou": _median(ious),
            "mean_overlap_previous": _mean(overlap_prev),
            "mean_overlap_current": _mean(overlap_curr),
            "mean_area_km2": _mean(areas),
            "min_area_km2": min(areas),
            "max_area_km2": max(areas),
            "area_change_last_minus_first_km2": areas[-1] - areas[0],
            "boundary_truncated_any": any(bool(row["boundary_truncated"]) for row in components),
            "frames_with_50_core": len(frames50),
            "frames_with_80_core": len(frames80),
            "fraction_frames_with_50_core": len(frames50) / frame_count if frame_count else 0.0,
            "fraction_frames_with_80_core": len(frames80) / frame_count if frame_count else 0.0,
            "embedded_50_core_genesis_count": core_genesis.get((lineage_id, 50), 0),
            "embedded_80_core_genesis_count": core_genesis.get((lineage_id, 80), 0),
            "embedded_core_genesis_count": core_genesis.get((lineage_id, 50), 0) + core_genesis.get((lineage_id, 80), 0),
        })

    return sorted(
        descriptors,
        key=lambda row: (
            int(row["duration_minutes"]),
            int(row["embedded_core_genesis_count"]),
            float(row["max_area_km2"]),
        ),
        reverse=True,
    )
