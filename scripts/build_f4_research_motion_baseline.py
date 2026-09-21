#!/usr/bin/env python3
"""F4-1 research-only constant-motion centroid baseline from observed parent tracks.

Predicts *points*, not LPZ genesis, precipitation footprint or probability.
Uses the last matched two radar frames and only targets strictly after as-of.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

from build_f4_observed_origin_join import join

EARTH_RADIUS_KM = 6371.0088
HORIZONS_MIN = (15, 30)


def utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be UTC Z")
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.utcoffset() != timedelta(0):
        raise ValueError("timestamp is not UTC")
    return t


def project(bundle: dict, f3: dict) -> dict:
    origins = join(bundle, f3)
    as_of = utc(origins["source_as_of_utc"])
    frames = bundle["components"]["radar_tracking"]["tracking"]["30"]["frames"]
    times = [utc(f["valid_time"]) for f in frames]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("radar frame times must be strictly increasing")
    if len(frames) < 2:
        raise ValueError("requires at least two radar frames")
    observation = times[-1]
    if not (observation <= as_of and as_of - observation <= timedelta(minutes=30)):
        raise ValueError("radar observation too stale for research baseline")
    interval = (times[-1] - times[-2]).total_seconds()
    if interval <= 0 or interval > 900:
        raise ValueError("unusable observed motion interval")
    parent = bundle["components"]["radar_tracking"]["tracking"]["30"]
    transitions = parent.get("transitions")
    if not isinstance(transitions, list) or not transitions:
        raise ValueError("missing radar primary-match transitions")
    transition = transitions[-1]
    if (transition.get("from_valid_time") != frames[-2]["valid_time"]
            or transition.get("to_valid_time") != frames[-1]["valid_time"]
            or abs(transition.get("elapsed_seconds", -1) - interval) > 0.001):
        raise ValueError("last transition time mismatch")
    previous = {str(c["lineage_id"]): c for c in frames[-2]["components"]}
    current = {str(c["lineage_id"]): c for c in frames[-1]["components"]}
    if len(previous) != len(frames[-2]["components"]) or len(current) != len(frames[-1]["components"]):
        raise ValueError("duplicate parent lineage in observed frames")
    matches = {}
    for match in transition.get("primary_matches", []):
        key = str(match["lineage_id"])
        if key in matches:
            raise ValueError("duplicate primary match")
        matches[key] = match

    rows = []
    for obj in origins["objects"]:
        item = {
            "research_object_id": obj["research_object_id"],
            "parent_lineage_id": obj["parent_lineage_id"],
            "baseline_status": None,
            "source_observation_valid_time_utc": obj["observation_valid_time_utc"],
            "projections": [],
            "lpz_classification": None,
            "forecast_probability": None,
        }
        lineage = obj["parent_lineage_id"]
        if obj["origin_status"] != "OBSERVED_AT_LATEST_FRAME":
            item["baseline_status"] = "NO_CURRENT_OBSERVED_ORIGIN"
        elif lineage not in previous or lineage not in matches:
            item["baseline_status"] = "INSUFFICIENT_MATCHED_MOTION"
        else:
            prev, curr, match = previous[lineage], current[lineage], matches[lineage]
            if (match["previous_id"] != prev["local_id"]
                    or match["current_id"] != curr["local_id"]):
                raise ValueError("primary match does not correspond to observed components")
            p, c = prev["centroid"], curr["centroid"]
            lat0, lon0 = float(p["lat"]), float(p["lon"])
            lat1, lon1 = float(c["lat"]), float(c["lon"])
            if not all(math.isfinite(v) for v in (lat0, lon0, lat1, lon1)):
                raise ValueError("nonfinite radar centroid")
            if not (-90 <= lat0 <= 90 and -90 <= lat1 <= 90
                    and -180 <= lon0 <= 180 and -180 <= lon1 <= 180):
                raise ValueError("invalid radar centroid coordinates")
            dlon = ((lon1 - lon0 + 180) % 360) - 180
            mean_lat = math.radians((lat0 + lat1) / 2)
            if abs(math.cos(mean_lat)) < 0.01:
                item["baseline_status"] = "UNUSABLE_POLAR_GEOMETRY"
            else:
                north_km = EARTH_RADIUS_KM * math.radians(lat1 - lat0)
                east_km = EARTH_RADIUS_KM * math.cos(mean_lat) * math.radians(dlon)
                speed_mps = math.hypot(east_km, north_km) * 1000 / interval
                if speed_mps > 60:
                    item["baseline_status"] = "UNUSABLE_MOTION_SPEED"
                else:
                    for lead in HORIZONS_MIN:
                        target = as_of + timedelta(minutes=lead)
                        extrapolation_s = (target - observation).total_seconds()
                        projected_lat = lat1 + math.degrees(north_km / EARTH_RADIUS_KM) * extrapolation_s / interval
                        projected_lon = lon1 + math.degrees(
                            east_km / (EARTH_RADIUS_KM * math.cos(math.radians(lat1)))
                        ) * extrapolation_s / interval
                        if not -90 <= projected_lat <= 90:
                            item["baseline_status"] = "PROJECTION_OUTSIDE_GEOGRAPHIC_RANGE"
                            item["projections"] = []
                            break
                        projected_lon = ((projected_lon + 180) % 360) - 180
                        item["projections"].append({
                            "target_valid_time_utc": target.isoformat().replace("+00:00", "Z"),
                            "lead_from_as_of_minutes": lead,
                            "lead_from_last_observation_minutes": extrapolation_s / 60,
                            "projected_centroid": {"lon": projected_lon, "lat": projected_lat},
                            "baseline_method": "LAST_MATCHED_TWO_FRAME_CONSTANT_VELOCITY",
                            "geometry_type": "POINT_ONLY_NOT_PRECIPITATION_FOOTPRINT",
                        })
                    if item["projections"]:
                        item["baseline_status"] = "RESEARCH_POINT_BASELINE_GENERATED"
        rows.append(item)
    return {
        "schema_version": "0.1.0", "product": "F4_RESEARCH_CENTROID_MOTION_BASELINE",
        "source_as_of_utc": origins["source_as_of_utc"],
        "latest_observation_utc": origins["latest_observation_utc"],
        "research_object_count": len(rows),
        "projected_object_count": sum(bool(r["projections"]) for r in rows),
        "horizons_from_as_of_minutes": list(HORIZONS_MIN),
        "objects": rows,
        "risk_engine_allowed": False, "official_risk_output": False,
        "lpz_forecast_generated": False, "research_point_baseline_generated": any(r["projections"] for r in rows),
        "interpretation": "Unvalidated point-motion research baseline, NOT LPZ genesis/footprint/probability.",
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", required=True, type=Path)
    p.add_argument("--f3", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    if a.output.exists():
        p.error("refusing overwrite")
    result = project(json.loads(a.bundle.read_text(encoding="utf-8")),
                     json.loads(a.f3.read_text(encoding="utf-8")))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({"projected_object_count": result["projected_object_count"],
                      "research_object_count": result["research_object_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
