#!/usr/bin/env python3
"""Summarize an existing F4 archived evaluation; no data acquisition or scoring."""
from __future__ import annotations
import argparse
import json
import statistics
from collections import Counter
from pathlib import Path


def summarize(report: dict) -> dict:
    if (report.get("product") != "F4_RETROSPECTIVE_ARCHIVED_POINT_PROXIMITY"
            or report.get("risk_engine_allowed") is not False
            or report.get("lpz_forecast_generated") is not False
            or report.get("research_mode") != "RETROSPECTIVE_DERIVATIVE_NOT_PROSPECTIVE_VALIDATION"):
        raise ValueError("not a locked F4 retrospective research report")
    rows = report["results"]
    statuses = Counter(r["identity_status"] for r in rows)
    horizons = {}
    for lead in (15, 30):
        eligible = [r for r in rows if r["lead_from_as_of_minutes"] == lead
                    and r["identity_verified"] is True]
        if any(r["identity_matched_distance_km"] is None
               or r["identity_persistence_distance_km"] is None for r in eligible):
            raise ValueError("verified row lacks distance")
        horizons[str(lead)] = {
            "identity_matched_count": len(eligible),
            "motion_median_km": (statistics.median(
                r["identity_matched_distance_km"] for r in eligible)
                if eligible else None),
            "persistence_median_km": (statistics.median(
                r["identity_persistence_distance_km"] for r in eligible)
                if eligible else None),
        }
    # First broken link is a radar-algorithm diagnostic, not a claim that
    # a precipitation system disappeared or an LPZ forecast was wrong.
    first_breaks = Counter()
    association_categories = Counter()
    no_overlap_geometry = Counter()
    no_overlap_nearest_distances = []
    first_break_by_horizon = {"15": Counter(), "30": Counter()}
    for row in rows:
        if row["identity_status"] != "NO_CONTINUOUS_PRIMARY_MATCH":
            continue
        info = row.get("identity_break_diagnostic")
        if not isinstance(info, dict):
            raise ValueError("missing F4-3 first-break diagnostic")
        if info["available_transition_records"] == 0:
            category = "NO_ARCHIVED_TRANSITION_RECORD"
        elif info["previous_id_primary_match_records"] == 0:
            category = "NO_PRIMARY_MATCH_FOR_PREVIOUS_COMPONENT"
        else:
            category = "PRIMARY_MATCH_UNRESOLVED"
        first_breaks[category] += 1
        association_categories[info["association_category"]] += 1
        if info["association_category"] == "NO_RECORDED_OVERLAP_CANDIDATE":
            near = info["nearest_next_frame_component"]
            if info["next_frame_component_count"] == 0:
                if near is not None:
                    raise ValueError("nearest candidate provided for empty next frame")
                no_overlap_geometry["NO_NEXT_FRAME_COMPONENTS"] += 1
            elif near is None:
                raise ValueError("missing nearest next frame component")
            else:
                no_overlap_geometry[
                    "PREVIOUS_BOUNDARY_TRUNCATED"
                    if info["previous_component_boundary_truncated"]
                    else "PREVIOUS_NOT_BOUNDARY_TRUNCATED"] += 1
                no_overlap_geometry[
                    "NEXT_NEAREST_BOUNDARY_TRUNCATED"
                    if near["boundary_truncated"]
                    else "NEXT_NEAREST_NOT_BOUNDARY_TRUNCATED"] += 1
                no_overlap_geometry[
                    "NEAREST_BBOX_INTERSECTS"
                    if near["bbox_intersects"]
                    else "NEAREST_BBOX_DISJOINT"] += 1
                no_overlap_nearest_distances.append(near["centroid_displacement_pixels"])
        lead = str(row["lead_from_as_of_minutes"])
        if lead not in first_break_by_horizon:
            raise ValueError("unsupported horizon")
        first_break_by_horizon[lead][category] += 1
    verified = sum(r["identity_verified"] is True for r in rows)
    if (verified != report["counts"]["identity_matched_projections"]
            or sum(r["identity_status"] != "NOT_EVALUATED_NO_EXACT_TARGET"
                   and r["identity_verified"] is False for r in rows)
            != report["counts"]["identity_unresolved_projections"]):
        raise ValueError("identity counts disagree")
    return {
        "source_run_id": report["source_run_id"],
        "target_run_id": report["target_run_id"],
        "counts": report["counts"],
        "identity_status_counts": dict(sorted(statuses.items())),
        "no_continuous_match_first_break_counts": dict(sorted(first_breaks.items())),
        "no_continuous_match_association_categories": dict(sorted(association_categories.items())),
        "no_overlap_geometry_diagnostics": {
            "counts": dict(sorted(no_overlap_geometry.items())),
            "nearest_next_frame_centroid_displacement_pixels_median":
                statistics.median(no_overlap_nearest_distances)
                if no_overlap_nearest_distances else None,
            "nearest_next_frame_centroid_displacement_pixels_min":
                min(no_overlap_nearest_distances) if no_overlap_nearest_distances else None,
            "nearest_next_frame_centroid_displacement_pixels_max":
                max(no_overlap_nearest_distances) if no_overlap_nearest_distances else None,
            "nearest_component_is_not_object_identity": True,
        },
        "no_continuous_match_first_break_by_horizon": {
            lead: dict(sorted(counts.items()))
            for lead, counts in first_break_by_horizon.items()},
        "horizons_from_as_of_minutes": horizons,
        "risk_engine_allowed": False,
        "lpz_forecast_generated": False,
        "interpretation": "Retrospective algorithmic radar identity, not independent ground truth or LPZ forecast skill.",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    if args.output.exists():
        p.error("refusing overwrite")
    result = summarize(json.loads(args.report.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
