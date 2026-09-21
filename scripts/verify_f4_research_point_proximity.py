#!/usr/bin/env python3
"""F4-2 prospective verification of research centroid projections.

Exact future observation only. Nearest observed 30 mm/h component is a
proximity diagnostic, NOT proof of object identity or LPZ forecast skill.
Never uses future data to generate the source projection.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

from build_f4_research_motion_baseline import utc, EARTH_RADIUS_KM


def distance_km(a: dict, b: dict) -> float:
    lat1, lon1, lat2, lon2 = (float(a["lat"]), float(a["lon"]),
                              float(b["lat"]), float(b["lon"]))
    if not all(math.isfinite(v) for v in (lat1, lon1, lat2, lon2)):
        raise ValueError("nonfinite centroid")
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90
            and -180 <= lon1 <= 180 and -180 <= lon2 <= 180):
        raise ValueError("invalid centroid")
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(((lon2 - lon1 + 180) % 360) - 180)
    h = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def verify(source: dict, source_bundle: dict, target_bundle: dict) -> dict:
    if (source.get("product") != "F4_RESEARCH_CENTROID_MOTION_BASELINE"
            or source.get("risk_engine_allowed") is not False
            or source.get("lpz_forecast_generated") is not False
            or source_bundle.get("risk_engine_allowed") is not False
            or target_bundle.get("risk_engine_allowed") is not False
            or target_bundle.get("bundle_complete") is not True
            or target_bundle.get("as_of_time_guard_pass") is not True):
        raise ValueError("source/target research gates not proven")
    origin_as_of = utc(source["source_as_of_utc"])
    if origin_as_of != utc(source_bundle["prospective_as_of_utc"]):
        raise ValueError("source as-of mismatch")
    if utc(target_bundle["prospective_as_of_utc"]) <= origin_as_of:
        raise ValueError("target bundle must have later as-of")
    source_tracking = source_bundle["components"]["radar_tracking"]
    target_tracking = target_bundle["components"]["radar_tracking"]
    if (source_tracking.get("execution_ok") is not True
            or target_tracking.get("execution_ok") is not True
            or source_tracking.get("fixed_mosaic") != target_tracking.get("fixed_mosaic")):
        # fixed_mosaic may be stored under the tracking component in native bundles
        raise ValueError("tracking missing or fixed mosaics differ")
    target_frames = target_tracking["tracking"]["30"]["frames"]
    frame_by_time = {frame["valid_time"]: frame for frame in target_frames}
    if len(frame_by_time) != len(target_frames):
        raise ValueError("duplicate target observation valid time")
    if utc(source["latest_observation_utc"]) > origin_as_of:
        raise ValueError("source observation later than as-of")
    results = []
    for obj in source["objects"]:
        for projection in obj["projections"]:
            valid = projection["target_valid_time_utc"]
            target = utc(valid)
            if target <= origin_as_of:
                raise ValueError("target is not future of source as-of")
            if projection["geometry_type"] != "POINT_ONLY_NOT_PRECIPITATION_FOOTPRINT":
                raise ValueError("not a point baseline")
            row = {
                "research_object_id": obj["research_object_id"],
                "target_valid_time_utc": valid,
                "lead_from_as_of_minutes": projection["lead_from_as_of_minutes"],
                "verification_status": None,
                "nearest_observed_component_distance_km": None,
                "observed_component_count": None,
                "lpz_classification": None,
                "forecast_probability": None,
            }
            frame = frame_by_time.get(valid)
            if frame is None:
                row["verification_status"] = "TARGET_FRAME_NOT_AVAILABLE"
            elif utc(valid) > utc(target_bundle["prospective_as_of_utc"]):
                raise ValueError("future observation relative to target as-of")
            else:
                comps = frame["components"]
                row["observed_component_count"] = len(comps)
                if not comps:
                    row["verification_status"] = "NO_30MMPH_COMPONENT_IN_SAMPLED_MOSAIC"
                else:
                    distances = sorted(distance_km(projection["projected_centroid"], c["centroid"])
                                       for c in comps)
                    row["nearest_observed_component_distance_km"] = distances[0]
                    row["verification_status"] = "NEAREST_COMPONENT_PROXIMITY_ONLY"
            results.append(row)
    return {
        "schema_version": "0.1.0",
        "product": "F4_RESEARCH_POINT_PROXIMITY_VERIFICATION",
        "source_as_of_utc": source["source_as_of_utc"],
        "target_as_of_utc": target_bundle["prospective_as_of_utc"],
        "source_slot_utc": source_bundle["collection_slot_utc"],
        "target_slot_utc": target_bundle["collection_slot_utc"],
        "result_count": len(results),
        "nearest_component_count": sum(r["verification_status"] == "NEAREST_COMPONENT_PROXIMITY_ONLY"
                                       for r in results),
        "results": results,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "object_identity_verified": False,
        "interpretation": ("Nearest future observed component is not necessarily the same "
                           "precipitation object. Distance is a proximity diagnostic, "
                           "not verified tracking accuracy or LPZ forecast skill."),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--source-bundle", type=Path, required=True)
    p.add_argument("--target-bundle", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error("refusing overwrite")
    result = verify(*(json.loads(path.read_text(encoding="utf-8")) for path in
                      (args.baseline, args.source_bundle, args.target_bundle)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, indent=2, ensure_ascii=False, allow_nan=False)
        out.write("\n")
    print(json.dumps({"result_count": result["result_count"],
                      "nearest_component_count": result["nearest_component_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
