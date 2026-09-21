#!/usr/bin/env python3
"""F4-2 retrospective research-only evaluation from TWO existing O8.1 artifacts.

Use when old source artifact predates F4-1 and contains archived F3 objects.
Rebuilds ONLY the F4-1 research derivative, never weather acquisition or
scientific features. Retrospective, not a prospective out-of-sample claim.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_f4_observed_origin_join import join
from build_f4_research_motion_baseline import project, utc
from verify_f4_research_point_proximity import distance_km, verify
from trace_f4_radar_identity_across_slots import trace_identity


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(source_root: Path, target_root: Path) -> dict:
    source_manifest = read(source_root / "batch_manifest.json")
    target_manifest = read(target_root / "batch_manifest.json")
    f3_manifest = read(source_root / "f3_research" / "manifest.json")
    if (source_manifest.get("risk_engine_allowed") is not False
            or target_manifest.get("risk_engine_allowed") is not False
            or f3_manifest.get("risk_engine_allowed") is not False
            or f3_manifest.get("forecast_generated") is not False
            or f3_manifest.get("source_run_id") != source_manifest.get("run_id")
            or source_manifest.get("run_id") == target_manifest.get("run_id")):
        raise ValueError("invalid distinct archived research batches")
    targets = []
    for row in target_manifest["slot_results"]:
        slot = row["collection_slot_utc"]
        name = utc(slot).strftime("%Y%m%dT%H%M%SZ.json")
        b = read(target_root / "slots" / name)
        if b.get("collection_slot_utc") != slot:
            raise ValueError("target slot mismatch")
        tr = b.get("components", {}).get("radar_tracking", {})
        if (b.get("bundle_complete") is True and b.get("as_of_time_guard_pass") is True
                and b.get("risk_engine_allowed") is False
                and tr.get("execution_ok") is True
                and tr.get("scientific_tracking_proven") is True):
            targets.append(b)
    rows = []
    counts = {"source_research_objects": 0, "current_origin_objects": 0,
              "projected_objects": 0, "comparable_projections": 0,
              "no_exact_comparable_target": 0,
              "identity_matched_projections": 0,
              "identity_unresolved_projections": 0}
    for f3_row in f3_manifest["slot_results"]:
        if f3_row["research_status"] != "DESCRIPTIVE_ONLY":
            continue
        name = f3_row["source_file"]
        if Path(name).name != name:
            raise ValueError("invalid source name")
        source = read(source_root / "slots" / name)
        if source.get("collection_slot_utc") != f3_row["collection_slot_utc"]:
            raise ValueError("source slot mismatch")
        expected = (source_root / "f3_research" / "slots" / name).resolve()
        if (source_root / f3_row["output_file"]).resolve() != expected:
            raise ValueError("F3 path mismatch")
        f3 = read(expected)
        baseline = project(source, f3)
        origin = join(source, f3)
        observed = {o["research_object_id"]: o for o in origin["objects"]}
        counts["source_research_objects"] += baseline["research_object_count"]
        counts["current_origin_objects"] += origin["current_origin_count"]
        counts["projected_objects"] += baseline["projected_object_count"]
        for obj in baseline["objects"]:
            for projection in obj["projections"]:
                valid = projection["target_valid_time_utc"]
                future = utc(valid)
                candidates = [b for b in targets
                              if utc(b["prospective_as_of_utc"]) >= future
                              and utc(b["prospective_as_of_utc"]) > utc(baseline["source_as_of_utc"])
                              and b["components"]["radar_tracking"].get("fixed_mosaic") is not None
                              and b["components"]["radar_tracking"]["fixed_mosaic"]
                              == source["components"]["radar_tracking"].get("fixed_mosaic")
                              and any(f["valid_time"] == valid for f in
                                      b["components"]["radar_tracking"]["tracking"]["30"]["frames"])]
                result = {
                    "source_slot_utc": source["collection_slot_utc"],
                    "research_object_id": obj["research_object_id"],
                    "target_valid_time_utc": valid,
                    "lead_from_as_of_minutes": projection["lead_from_as_of_minutes"],
                    "verification_status": "NO_EXACT_COMPARABLE_TARGET_IN_PROVIDED_ARTIFACT",
                    "target_slot_utc": None,
                    "nearest_component_distance_km": None,
                    "persistence_nearest_component_distance_km": None,
                    "identity_status": "NOT_EVALUATED_NO_EXACT_TARGET",
                    "identity_verified": False,
                    "identity_matched_distance_km": None,
                    "identity_persistence_distance_km": None,
                    "lpz_classification": None,
                }
                if candidates:
                    target = min(candidates, key=lambda b: (
                        utc(b["prospective_as_of_utc"]), b["collection_slot_utc"]))
                    one = dict(baseline, objects=[dict(obj, projections=[projection])])
                    verified = verify(one, source, target)["results"][0]
                    result["verification_status"] = verified["verification_status"]
                    result["target_slot_utc"] = target["collection_slot_utc"]
                    result["nearest_component_distance_km"] = verified[
                        "nearest_observed_component_distance_km"]
                    if verified["verification_status"] == "NEAREST_COMPONENT_PROXIMITY_ONLY":
                        frame = next(f for f in target["components"]["radar_tracking"]["tracking"]["30"]["frames"]
                                     if f["valid_time"] == valid)
                        point = observed[obj["research_object_id"]]["observed_component"]["centroid"]
                        result["persistence_nearest_component_distance_km"] = min(
                            distance_km(point, c["centroid"]) for c in frame["components"])
                        counts["comparable_projections"] += 1
                        identity = trace_identity(
                            source, obj["parent_lineage_id"], valid, targets)
                        result["identity_status"] = identity["status"]
                        result["identity_verified"] = identity["identity_verified"]
                        if identity["identity_verified"]:
                            actual = identity["target_component"]["centroid"]
                            result["identity_matched_distance_km"] = distance_km(
                                projection["projected_centroid"], actual)
                            result["identity_persistence_distance_km"] = distance_km(
                                point, actual)
                            counts["identity_matched_projections"] += 1
                        else:
                            counts["identity_unresolved_projections"] += 1
                else:
                    counts["no_exact_comparable_target"] += 1
                rows.append(result)
    return {
        "schema_version": "0.2.0",
        "product": "F4_RETROSPECTIVE_ARCHIVED_POINT_PROXIMITY",
        "source_run_id": source_manifest["run_id"],
        "target_run_id": target_manifest["run_id"],
        "research_mode": "RETROSPECTIVE_DERIVATIVE_NOT_PROSPECTIVE_VALIDATION",
        "counts": counts,
        "results": rows,
        "risk_engine_allowed": False,
        "lpz_forecast_generated": False,
        "object_identity_verified": counts["identity_matched_projections"] > 0,
        "interpretation": "Identity-matched distances use continuous primary-match chains over exact shared radar frames. Unresolved is unknown, not negative LPZ; algorithmic identity is not independent truth or validated LPZ skill.",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--target-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error("refusing overwrite")
    result = evaluate(args.source_root, args.target_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps(result["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
