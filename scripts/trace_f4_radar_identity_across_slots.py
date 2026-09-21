#!/usr/bin/env python3
"""F4-3 research-only identity continuity through overlapping archived radar frames.

Across O8.1 bundles, lineage_id is LOCAL to a tracking run and MUST NOT be
compared as a globally persistent ID. Bridge the exact shared frame using
observed component identity, then follow only explicit primary matches.
A broken chain is UNKNOWN, not disappearance or a negative LPZ label.
"""
from __future__ import annotations

import json
from datetime import timedelta

from build_f4_research_motion_baseline import utc


def _signature(c: dict) -> tuple:
    """Stable exact-frame component fields, excluding per-run lineage."""
    return (c["local_id"], c["pixel_count"],
            json.dumps(c["centroid_pixel"], sort_keys=True),
            json.dumps(c["centroid"], sort_keys=True),
            tuple(c["bbox_pixel"]), c["boundary_truncated"])


def _frames(bundle: dict) -> list:
    if (bundle.get("bundle_complete") is not True
            or bundle.get("as_of_time_guard_pass") is not True
            or bundle.get("risk_engine_allowed") is not False):
        raise ValueError("unsafe or incomplete O8.1 bundle")
    radar = bundle["components"]["radar_tracking"]
    if (radar.get("execution_ok") is not True
            or radar.get("scientific_tracking_proven") is not True
            or radar.get("fixed_mosaic") is None):
        raise ValueError("radar tracking or fixed mosaic unproven")
    frames = radar["tracking"]["30"]["frames"]
    if not frames or any(utc(f["valid_time"]) > utc(bundle["prospective_as_of_utc"])
                         for f in frames):
        raise ValueError("future observation or empty frames")
    return frames

def _initial_motion_reference(source_bundle: dict, origin_component: dict) -> dict | None:
    """Return the component immediately preceding the source origin when unique."""
    radar = source_bundle["components"]["radar_tracking"]["tracking"]["30"]
    frames = radar["frames"]
    transitions = radar.get("transitions", [])
    if len(frames) < 2 or not transitions:
        return None
    previous_frame = frames[-2]
    current_frame = frames[-1]
    candidates = [
        transition for transition in transitions
        if transition.get("from_valid_time") == previous_frame.get("valid_time")
        and transition.get("to_valid_time") == current_frame.get("valid_time")
    ]
    if len(candidates) != 1:
        return None
    matches = [
        match for match in candidates[0].get("primary_matches", [])
        if match.get("current_id") == origin_component.get("local_id")
    ]
    if len(matches) != 1:
        return None
    previous = [
        component for component in previous_frame.get("components", [])
        if component.get("local_id") == matches[0].get("previous_id")
    ]
    if len(previous) != 1:
        return None
    return {
        "valid_time": previous_frame["valid_time"],
        "component": previous[0],
    }


def _motion_candidate_diagnostic(
    motion_reference: dict | None,
    current_component: dict,
    next_components: list[dict],
) -> dict | None:
    """Rank next-frame components around one-step constant-velocity prediction."""
    if motion_reference is None or not next_components:
        return None
    prior = motion_reference["component"]
    p0 = prior["centroid_pixel"]
    p1 = current_component["centroid_pixel"]
    row0, col0 = float(p0["row"]), float(p0["col"])
    row1, col1 = float(p1["row"]), float(p1["col"])
    predicted_row = row1 + (row1 - row0)
    predicted_col = col1 + (col1 - col0)

    ranked = []
    for candidate in next_components:
        centroid = candidate["centroid_pixel"]
        row = float(centroid["row"])
        col = float(centroid["col"])
        error = ((row - predicted_row) ** 2 + (col - predicted_col) ** 2) ** 0.5
        from_current = ((row - row1) ** 2 + (col - col1) ** 2) ** 0.5
        ranked.append((error, int(candidate["local_id"]), from_current, candidate))
    ranked.sort(key=lambda item: (item[0], item[1]))

    best = ranked[0]
    second_distance = ranked[1][0] if len(ranked) > 1 else None
    margin = second_distance - best[0] if second_distance is not None else None
    current_pixels = float(current_component["pixel_count"])
    best_pixels = float(best[3]["pixel_count"])
    thresholds = (3, 5, 8, 10, 15, 20)
    return {
        "motion_reference_valid_time_utc": motion_reference["valid_time"],
        "prior_centroid_pixel": {
            "row": row0,
            "col": col0,
        },
        "current_centroid_pixel": {
            "row": row1,
            "col": col1,
        },
        "predicted_next_centroid_pixel": {
            "row": predicted_row,
            "col": predicted_col,
        },
        "nearest_candidate": {
            "local_id": best[1],
            "motion_error_pixels": best[0],
            "centroid_displacement_from_current_pixels": best[2],
            "pixel_count": best[3]["pixel_count"],
            "pixel_count_ratio_to_current": (
                best_pixels / current_pixels if current_pixels > 0 else None
            ),
            "boundary_truncated": best[3]["boundary_truncated"],
        },
        "second_nearest_motion_error_pixels": second_distance,
        "nearest_to_second_margin_pixels": margin,
        "candidate_count": len(ranked),
        "within_motion_error_threshold_counts": {
            str(threshold): sum(item[0] <= threshold for item in ranked)
            for threshold in thresholds
        },
        "research_candidate_only": True,
    }



def trace_identity(source_bundle: dict, origin_lineage_id: str,
                   target_valid_time_utc: str, bundles: list[dict]) -> dict:
    """Return verified target component only for a continuous primary-match chain.

    Input bundles may come from separate artifacts; every intermediate 5-minute
    frame must exist, and overlapping frames must have identical components.
    """
    origin_frames = _frames(source_bundle)
    origin_frame = origin_frames[-1]
    start = utc(origin_frame["valid_time"])
    end = utc(target_valid_time_utc)
    if end <= utc(source_bundle["prospective_as_of_utc"]):
        raise ValueError("target must be strictly after source as-of")
    if end <= start:
        raise ValueError("target must follow source observation")
    origin = [c for c in origin_frame["components"]
              if str(c["lineage_id"]) == str(origin_lineage_id)]
    if len(origin) != 1:
        return {"status": "NO_UNIQUE_CURRENT_ORIGIN", "target_component": None,
                "identity_verified": False}
    grid = source_bundle["components"]["radar_tracking"]["fixed_mosaic"]
    frames = {}
    edges = {}
    for bundle in [source_bundle, *bundles]:
        fs = _frames(bundle)
        radar = bundle["components"]["radar_tracking"]
        if radar["fixed_mosaic"] != grid:
            continue
        if utc(bundle["prospective_as_of_utc"]) < utc(fs[-1]["valid_time"]):
            raise ValueError("radar as-of mismatch")
        for frame in fs:
            time = frame["valid_time"]
            if utc(time) < start or utc(time) > end:
                continue
            components = {_signature(c): c for c in frame["components"]}
            if len(components) != len(frame["components"]):
                raise ValueError("duplicate observed component signature")
            if time in frames and set(frames[time]) != set(components):
                raise ValueError("conflicting overlapping observed radar frame")
            frames[time] = components
        transitions = radar["tracking"]["30"].get("transitions", [])
        for tr in transitions:
            a, b = tr["from_valid_time"], tr["to_valid_time"]
            if utc(a) < start or utc(b) > end:
                continue
            if utc(b) - utc(a) != timedelta(minutes=5):
                continue
            if (a, b) not in edges:
                edges[a, b] = []
            edges[a, b].append((fs, tr))
    current = _signature(origin[0])
    motion_reference = _initial_motion_reference(source_bundle, origin[0])
    time = start
    traversed = 0
    while time < end:
        next_time = time + timedelta(minutes=5)
        a = time.isoformat().replace("+00:00", "Z")
        b = next_time.isoformat().replace("+00:00", "Z")
        if a not in frames or b not in frames:
            return {"status": "MISSING_INTERMEDIATE_OBSERVATION",
                    "target_component": None, "identity_verified": False,
                    "verified_transition_count": traversed}
        if current not in frames[a]:
            raise ValueError("identity component inconsistent with archived frame")
        matches = set()
        for fs, tr in edges.get((a, b), []):
            prev = next((f for f in fs if f["valid_time"] == a), None)
            curr = next((f for f in fs if f["valid_time"] == b), None)
            if prev is None or curr is None:
                raise ValueError("transition frames absent")
            local = frames[a][current]["local_id"]
            for match in tr.get("primary_matches", []):
                if match["previous_id"] != local:
                    continue
                candidates = [c for c in curr["components"]
                              if c["local_id"] == match["current_id"]]
                if len(candidates) != 1:
                    raise ValueError("primary match has ambiguous current component")
                matches.add(_signature(candidates[0]))
        if len(matches) == 0:
            transition_records = edges.get((a, b), [])
            matching_records = sum(
                m.get("previous_id") == frames[a][current]["local_id"]
                for _, transition in transition_records
                for m in transition.get("primary_matches", []))
            previous_id = frames[a][current]["local_id"]
            split_records = sum(
                previous_id == row.get("previous_id")
                for _, transition in transition_records
                for row in transition.get("split_candidates", []))
            merge_records = sum(
                previous_id in row.get("previous_ids", [])
                for _, transition in transition_records
                for row in transition.get("merge_candidates", []))
            death_records = sum(
                previous_id == row.get("previous_id")
                for _, transition in transition_records
                for row in transition.get("deaths", []))
            # Retrospective geometry only. The nearest next-frame component
            # is NOT treated as the same precipitation object or ground truth.
            previous_component = frames[a][current]
            nearby = []
            for candidate in frames[b].values():
                pr = previous_component["centroid_pixel"]
                cr = candidate["centroid_pixel"]
                dr = float(cr["row"]) - float(pr["row"])
                dc = float(cr["col"]) - float(pr["col"])
                nearby.append((dr * dr + dc * dc, candidate))
            nearest = min(nearby, key=lambda x: x[0]) if nearby else None
            previous_bbox = previous_component["bbox_pixel"]
            if nearest is not None:
                next_component = nearest[1]
                next_bbox = next_component["bbox_pixel"]
                bbox_intersects = not (
                    previous_bbox[2] < next_bbox[0] or next_bbox[2] < previous_bbox[0]
                    or previous_bbox[3] < next_bbox[1] or next_bbox[3] < previous_bbox[1])
            else:
                next_component = None
                bbox_intersects = None
            motion_candidate = _motion_candidate_diagnostic(
                motion_reference,
                previous_component,
                list(frames[b].values()),
            )
            # A single overlap candidate cannot lose the greedy one-to-one
            # match unless its destination has a competing previous component
            # (recorded as a merge candidate). These categories describe
            # stored geometry associations, NOT meteorological disappearance.
            if not transition_records:
                association_category = "NO_ARCHIVED_TRANSITION_RECORD"
            elif split_records and merge_records:
                association_category = "SPLIT_AND_MERGE_CANDIDATES"
            elif split_records:
                association_category = "SPLIT_CANDIDATE"
            elif merge_records:
                association_category = "MERGE_CANDIDATE"
            else:
                association_category = "NO_RECORDED_OVERLAP_CANDIDATE"
            return {"status": "NO_CONTINUOUS_PRIMARY_MATCH",
                    "target_component": None, "identity_verified": False,
                    "verified_transition_count": traversed,
                    "break_diagnostic": {
                        "from_valid_time_utc": a,
                        "to_valid_time_utc": b,
                        "available_transition_records": len(transition_records),
                        "previous_id_primary_match_records": matching_records,
                        "next_frame_component_count": len(frames[b]),
                        "split_candidate_records": split_records,
                        "merge_candidate_records": merge_records,
                        "death_records": death_records,
                        "association_category": association_category,
                        "previous_component_pixel_count": previous_component["pixel_count"],
                        "previous_component_boundary_truncated": previous_component["boundary_truncated"],
                        "nearest_next_frame_component": ({
                            "centroid_displacement_pixels": nearest[0] ** 0.5,
                            "pixel_count": next_component["pixel_count"],
                            "boundary_truncated": next_component["boundary_truncated"],
                            "bbox_intersects": bbox_intersects,
                        } if nearest is not None else None),
                        "motion_candidate_diagnostic": motion_candidate,
                        "geometry_diagnostic_only": True,
                    }}
        if len(matches) > 1:
            return {"status": "CONFLICTING_PRIMARY_MATCHES",
                    "target_component": None, "identity_verified": False,
                    "verified_transition_count": traversed}
        previous_for_motion = frames[a][current]
        current = next(iter(matches))
        motion_reference = {
            "valid_time": a,
            "component": previous_for_motion,
        }
        if current not in frames[b]:
            raise ValueError("matched target differs from archived observation")
        time = next_time
        traversed += 1
    valid = end.isoformat().replace("+00:00", "Z")
    return {
        "status": "CONTINUOUS_PRIMARY_MATCH_OBSERVED",
        "target_valid_time_utc": valid,
        "target_component": frames[valid][current],
        "identity_verified": True,
        "verified_transition_count": traversed,
        "interpretation": "Continuity under radar primary-match algorithm, not independent truth.",
    }
