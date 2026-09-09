"""Geometry of embedded-core genesis relative to parent-system motion.

Negative along-motion displacement means a newly observed child core lies
behind the current parent centroid relative to the parent's preceding motion
vector. This is a geometric descriptor only and must not be labeled
back-building without environmental and historical evidence.
"""

from __future__ import annotations

import math
from typing import Any

EARTH_RADIUS_M = 6378137.0
TILE_SIZE = 256


def meters_per_pixel(lat_deg: float, zoom: int) -> float:
    circumference = 2.0 * math.pi * EARTH_RADIUS_M
    return circumference * math.cos(math.radians(lat_deg)) / (TILE_SIZE * (2 ** zoom))


def relative_motion_geometry(
    *,
    previous_parent_row: float,
    previous_parent_col: float,
    current_parent_row: float,
    current_parent_col: float,
    child_row: float,
    child_col: float,
    latitude_deg: float,
    zoom: int,
    elapsed_seconds: float,
) -> dict[str, float | bool | None]:
    """Calculate child position in the translating parent reference frame.

    Coordinates use east/north physical axes after converting image rows so
    north is positive. Along-motion is positive ahead of the parent's motion
    and negative behind it. Signed cross-motion is positive to the left of the
    motion vector in the local east/north plane.
    """
    if elapsed_seconds <= 0:
        raise ValueError("elapsed_seconds must be positive")

    motion_east_px = current_parent_col - previous_parent_col
    motion_north_px = -(current_parent_row - previous_parent_row)
    motion_px = math.hypot(motion_east_px, motion_north_px)

    rel_east_px = child_col - current_parent_col
    rel_north_px = -(child_row - current_parent_row)
    rel_px = math.hypot(rel_east_px, rel_north_px)
    scale_km = meters_per_pixel(latitude_deg, zoom) / 1000.0

    if motion_px <= 1e-12:
        return {
            "parent_motion_pixels": 0.0,
            "parent_motion_km": 0.0,
            "parent_motion_speed_mps": 0.0,
            "parent_motion_direction_deg": None,
            "child_relative_distance_km": rel_px * scale_km,
            "along_motion_km": None,
            "cross_motion_km": None,
            "negative_along_motion": False,
        }

    ux = motion_east_px / motion_px
    uy = motion_north_px / motion_px
    along_px = rel_east_px * ux + rel_north_px * uy
    # Positive is left of motion in local east/north coordinates.
    cross_px = motion_east_px / motion_px * rel_north_px - motion_north_px / motion_px * rel_east_px
    motion_km = motion_px * scale_km
    direction = math.degrees(math.atan2(motion_east_px, motion_north_px)) % 360.0

    return {
        "parent_motion_pixels": motion_px,
        "parent_motion_km": motion_km,
        "parent_motion_speed_mps": motion_km * 1000.0 / elapsed_seconds,
        "parent_motion_direction_deg": direction,
        "child_relative_distance_km": rel_px * scale_km,
        "along_motion_km": along_px * scale_km,
        "cross_motion_km": cross_px * scale_km,
        "negative_along_motion": along_px < 0.0,
    }


def build_genesis_geometry_descriptors(
    tracking_report: dict[str, Any],
    hierarchy_report: dict[str, Any],
    *,
    zoom: int = 8,
) -> list[dict[str, Any]]:
    if not tracking_report.get("scientific_tracking_proven"):
        raise ValueError("tracking report is not scientifically proven")
    if not hierarchy_report.get("scientific_hierarchy_proven"):
        raise ValueError("hierarchy report is not scientifically proven")

    times = list(tracking_report["frame_valid_times"])
    time_to_index = {str(value): idx for idx, value in enumerate(times)}

    component_lookup: dict[tuple[int, int, int], dict[str, Any]] = {}
    for threshold in (30, 50, 80):
        for frame_idx, frame in enumerate(tracking_report["tracking"][str(threshold)]["frames"]):
            for comp in frame["components"]:
                component_lookup[(threshold, frame_idx, int(comp["local_id"]))] = comp

    parent_lineage_lookup: dict[tuple[int, str], dict[str, Any]] = {}
    for frame_idx, frame in enumerate(tracking_report["tracking"]["30"]["frames"]):
        for comp in frame["components"]:
            parent_lineage_lookup[(frame_idx, str(comp["lineage_id"]))] = comp

    hierarchy_assignment_lookup: dict[tuple[int, int, str, str], dict[str, Any]] = {}
    for frame in hierarchy_report["frames"]:
        frame_idx = int(frame["frame_index"])
        for threshold in (50, 80):
            for assignment in frame["children"][str(threshold)]["assignments"]:
                key = (
                    frame_idx,
                    threshold,
                    str(assignment["child_lineage_id"]),
                    str(assignment["parent_lineage_id"]),
                )
                hierarchy_assignment_lookup[key] = assignment

    results: list[dict[str, Any]] = []
    for event in hierarchy_report.get("genesis_events", []):
        valid_time = str(event["valid_time"])
        frame_idx = time_to_index.get(valid_time)
        if frame_idx is None or frame_idx <= 0:
            continue
        threshold = int(event["threshold_mmph"])
        child_lineage = str(event["child_lineage_id"])
        parent_lineage = str(event["parent_lineage_id"])
        assignment = hierarchy_assignment_lookup.get((frame_idx, threshold, child_lineage, parent_lineage))
        if assignment is None:
            raise ValueError("could not resolve hierarchy assignment for genesis event")

        current_parent = component_lookup[(30, frame_idx, int(assignment["parent_id"]))]
        previous_parent = parent_lineage_lookup.get((frame_idx - 1, parent_lineage))
        child = component_lookup[(threshold, frame_idx, int(assignment["child_id"]))]
        if previous_parent is None:
            # Hierarchy event definition should imply this exists; keep explicit.
            raise ValueError("genesis parent lineage missing from previous frame")

        current_centroid = current_parent["centroid"]
        geometry = relative_motion_geometry(
            previous_parent_row=float(previous_parent["centroid_pixel"]["row"]),
            previous_parent_col=float(previous_parent["centroid_pixel"]["col"]),
            current_parent_row=float(current_parent["centroid_pixel"]["row"]),
            current_parent_col=float(current_parent["centroid_pixel"]["col"]),
            child_row=float(child["centroid_pixel"]["row"]),
            child_col=float(child["centroid_pixel"]["col"]),
            latitude_deg=float(current_centroid["lat"]),
            zoom=zoom,
            elapsed_seconds=300.0,
        )
        results.append({
            "valid_time": valid_time,
            "threshold_mmph": threshold,
            "child_lineage_id": child_lineage,
            "parent_lineage_id": parent_lineage,
            "parent_boundary_truncated": bool(current_parent["boundary_truncated"]),
            "child_boundary_truncated": bool(child["boundary_truncated"]),
            "parent_centroid": current_parent["centroid"],
            "child_centroid": child["centroid"],
            **geometry,
        })

    return results
