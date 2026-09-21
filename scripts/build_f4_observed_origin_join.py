#!/usr/bin/env python3
"""F4-0: Join existing F3 descriptive objects to the observed 30 mm/h parent track.

Research input contract only. No new acquisition, forecast, LPZ label, risk
score, or invented precipitation polygon. Missing lineages are explicit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def join(bundle: dict, f3: dict) -> dict:
    if bundle.get("collection_status") != "COMPLETE_FEATURES" or bundle.get("bundle_complete") is not True:
        raise ValueError("requires complete O8.1 feature bundle")
    if bundle.get("as_of_time_guard_pass") is not True or bundle.get("risk_engine_allowed") is not False:
        raise ValueError("O8.1 safety gates not proven")
    if bundle.get("risk_score") is not None or bundle.get("lpz_classification") is not None:
        raise ValueError("source contains risk output")
    if f3.get("product") != "LPZ_RESEARCH_OBJECT_ADAPTER" or f3.get("forecast_generated") is not False:
        raise ValueError("requires research-only F3 adapter")
    if f3.get("risk_engine_allowed") is not False or f3.get("source_as_of_utc") != bundle.get("prospective_as_of_utc"):
        raise ValueError("F3 as-of or risk lock mismatch")

    # Reuse the F3-1 source fingerprint instead of reinterpreting descriptors.
    from build_lpz_research_candidates import _digest
    if f3.get("source_bundle_sha256") != _digest(bundle):
        raise ValueError("F3 adapter belongs to a different source bundle")

    tracking = bundle.get("components", {}).get("radar_tracking", {})
    if tracking.get("execution_ok") is not True or tracking.get("scientific_tracking_proven") is not True:
        raise ValueError("scientific tracking is not proven")
    frames = tracking.get("tracking", {}).get("30", {}).get("frames")
    times = tracking.get("frame_valid_times")
    if not isinstance(frames, list) or not frames or not isinstance(times, list) or len(frames) != len(times):
        raise ValueError("invalid 30 mm/h frame sequence")
    if any(frame.get("valid_time") != times[i] for i, frame in enumerate(frames)):
        raise ValueError("frame valid-time mismatch")
    if times[-1] > bundle["prospective_as_of_utc"]:
        raise ValueError("future observation in source bundle")

    # Only current-frame observations may serve as a future-prediction origin.
    latest = {}
    for component in frames[-1].get("components", []):
        key = str(component["lineage_id"])
        if key in latest:
            raise ValueError("duplicate parent lineage in latest frame")
        latest[key] = component

    objects = f3.get("research_objects")
    if not isinstance(objects, list) or f3.get("research_object_count") != len(objects):
        raise ValueError("F3 research object count mismatch")
    joined = []
    for obj in objects:
        desc = obj.get("source_descriptor")
        if not isinstance(desc, dict) or "parent_lineage_id" not in desc:
            raise ValueError("F3 descriptor lacks parent_lineage_id")
        if obj.get("forecast_probability") is not None or obj.get("lpz_classification") is not None:
            raise ValueError("F3 object contains prediction or classification")
        lineage = str(desc["parent_lineage_id"])
        comp = latest.get(lineage)
        active = comp is not None
        if active:
            if desc.get("last_frame_index") != len(frames) - 1:
                raise ValueError("F3 last frame does not match latest observed lineage")
            if desc.get("last_centroid") != comp.get("centroid"):
                raise ValueError("F3 centroid differs from tracking source")
        joined.append({
            "research_object_id": obj["research_object_id"],
            "parent_lineage_id": lineage,
            "origin_status": "OBSERVED_AT_LATEST_FRAME" if active else "NOT_PRESENT_AT_LATEST_FRAME",
            "observation_valid_time_utc": times[-1] if active else None,
            "observed_component": {
                "centroid": comp["centroid"],
                "centroid_pixel": comp["centroid_pixel"],
                "bbox_pixel": comp["bbox_pixel"],
                "approx_area_km2": comp["approx_area_km2"],
                "boundary_truncated": comp["boundary_truncated"],
            } if active else None,
            "geometry_type": "OBSERVED_BBOX_NOT_PRECIPITATION_POLYGON" if active else None,
            "forecast_valid_time_utc": None,
            "forecast_probability": None,
            "lpz_classification": None,
        })
    return {
        "schema_version": "0.1.0",
        "product": "F4_OBSERVED_ORIGIN_JOIN",
        "source_as_of_utc": bundle["prospective_as_of_utc"],
        "latest_observation_utc": times[-1],
        "research_object_count": len(joined),
        "current_origin_count": sum(x["origin_status"] == "OBSERVED_AT_LATEST_FRAME" for x in joined),
        "objects": joined,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "forecast_generated": False,
        "interpretation": "Observed input join only; bbox is not a precipitation polygon or future extent.",
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--f3", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error("refusing to overwrite existing output")
    result = join(json.loads(args.bundle.read_text(encoding="utf-8")),
                  json.loads(args.f3.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"product": result["product"], "current_origin_count": result["current_origin_count"],
                      "research_object_count": result["research_object_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
