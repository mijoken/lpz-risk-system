#!/usr/bin/env python3
"""F4-2 cross-run bridge for two already archived prospective batch artifacts.

Selects an EXACT radar frame at a projected valid time, never nearest-time
substitution. Does not download weather or infer same-object identity.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_f4_research_motion_baseline import utc
from verify_f4_research_point_proximity import verify


def read(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"not a JSON object: {path}")
    return obj


def cross_run(source_root: Path, target_root: Path) -> dict:
    source_manifest = read(source_root / "batch_manifest.json")
    motion_manifest = read(source_root / "f4_research_motion" / "manifest.json")
    target_manifest = read(target_root / "batch_manifest.json")
    if (source_manifest.get("risk_engine_allowed") is not False
            or target_manifest.get("risk_engine_allowed") is not False
            or motion_manifest.get("risk_engine_allowed") is not False
            or motion_manifest.get("lpz_forecast_generated") is not False
            or motion_manifest.get("source_run_id") != source_manifest.get("run_id")
            or source_manifest.get("run_id") == target_manifest.get("run_id")):
        raise ValueError("source/target run or research lock invalid")
    if (motion_manifest.get("source_slot_count") != len(motion_manifest.get("slot_results", []))
            or target_manifest.get("requested_slot_count") != len(target_manifest.get("slot_results", []))):
        raise ValueError("manifest counts invalid")
    targets = []
    for row in target_manifest["slot_results"]:
        name = utc(row["collection_slot_utc"]).strftime("%Y%m%dT%H%M%SZ.json")
        bundle = read(target_root / "slots" / name)
        if bundle.get("collection_slot_utc") != row["collection_slot_utc"]:
            raise ValueError("target slot mismatch")
        if (bundle.get("bundle_complete") is not True
                or bundle.get("as_of_time_guard_pass") is not True
                or bundle.get("risk_engine_allowed") is not False):
            continue
        tracking = bundle.get("components", {}).get("radar_tracking", {})
        if tracking.get("execution_ok") is not True:
            continue
        times = {f["valid_time"] for f in tracking.get("tracking", {}).get("30", {}).get("frames", [])}
        targets.append((bundle, times))
    results = []
    seen = set()
    for row in motion_manifest["slot_results"]:
        if row["research_status"] != "RESEARCH_POINT_BASELINE":
            continue
        name = row["source_file"]
        if Path(name).name != name:
            raise ValueError("invalid source file")
        source_bundle = read(source_root / "slots" / name)
        motion_path = (source_root / "f4_research_motion" / "slots" / name)
        if (source_root / row["output_file"]).resolve() != motion_path.resolve():
            raise ValueError("source motion path mismatch")
        baseline = read(motion_path)
        source_asof = utc(baseline["source_as_of_utc"])
        for obj in baseline["objects"]:
            for projection in obj["projections"]:
                valid = projection["target_valid_time_utc"]
                t = utc(valid)
                key = (name, obj["research_object_id"], valid)
                if key in seen:
                    raise ValueError("duplicate source prediction")
                seen.add(key)
                candidates = [(bundle, times) for bundle, times in targets
                              if valid in times and utc(bundle["prospective_as_of_utc"]) >= t
                              and utc(bundle["prospective_as_of_utc"]) > source_asof
                              and bundle.get("components", {}).get("radar_tracking", {}).get("fixed_mosaic")
                              == source_bundle.get("components", {}).get("radar_tracking", {}).get("fixed_mosaic")]
                if not candidates:
                    results.append({
                        "source_file": name, "research_object_id": obj["research_object_id"],
                        "target_valid_time_utc": valid,
                        "verification_status": "NO_EXACT_TIME_COMPARABLE_TARGET_IN_PROVIDED_BATCH",
                        "nearest_observed_component_distance_km": None,
                        "lpz_classification": None,
                    })
                    continue
                # Earliest archived as-of after exact target time: no later outcome shopping.
                chosen = min((bundle for bundle, _ in candidates),
                             key=lambda b: (utc(b["prospective_as_of_utc"]),
                                            b["collection_slot_utc"]))
                subset = dict(baseline, objects=[dict(obj, projections=[projection])])
                checked = verify(subset, source_bundle, chosen)
                if checked["result_count"] != 1:
                    raise ValueError("unexpected F4-2 verification cardinality")
                result = checked["results"][0]
                results.append({
                    "source_file": name, "research_object_id": obj["research_object_id"],
                    "target_valid_time_utc": valid,
                    "target_slot_utc": chosen["collection_slot_utc"],
                    "target_as_of_utc": chosen["prospective_as_of_utc"],
                    **result,
                })
    return {
        "schema_version": "0.1.0",
        "product": "F4_CROSS_RUN_POINT_PROXIMITY_RESEARCH",
        "source_run_id": source_manifest["run_id"],
        "target_run_id": target_manifest["run_id"],
        "result_count": len(results),
        "nearest_component_count": sum(r["verification_status"] == "NEAREST_COMPONENT_PROXIMITY_ONLY"
                                       for r in results),
        "results": results,
        "risk_engine_allowed": False,
        "lpz_forecast_generated": False,
        "object_identity_verified": False,
        "interpretation": "Exact-time sampled-mosaic proximity only; not same-object or LPZ forecast skill.",
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root", required=True, type=Path)
    p.add_argument("--target-root", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    if args.output.exists():
        p.error("refusing overwrite")
    result = cross_run(args.source_root, args.target_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, indent=2, ensure_ascii=False, allow_nan=False)
        out.write("\n")
    print(json.dumps({"result_count": result["result_count"],
                      "nearest_component_count": result["nearest_component_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
