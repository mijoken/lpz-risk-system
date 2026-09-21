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
                    }}
        if len(matches) > 1:
            return {"status": "CONFLICTING_PRIMARY_MATCHES",
                    "target_component": None, "identity_verified": False,
                    "verified_transition_count": traversed}
        current = next(iter(matches))
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
