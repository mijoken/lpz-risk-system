#!/usr/bin/env python3
"""F4-4: build research-only geographic envelopes from F4 observed + motion data.

This converts the observed 30 mm/h component geographic envelope into a
short-horizon translated envelope using the existing F4-1 constant-motion
centroid baseline. It does not estimate LPZ genesis, probability, severity,
intensity, or validated future precipitation extent.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lpz_risk.radar_geographic_envelope import translate_polygon_lonlat


def build(origins: dict, motion: dict) -> dict:
    if (origins.get("product") != "F4_OBSERVED_ORIGIN_JOIN"
            or origins.get("risk_engine_allowed") is not False
            or origins.get("forecast_generated") is not False):
        raise ValueError("requires locked F4 observed-origin input")
    if (motion.get("product") != "F4_RESEARCH_CENTROID_MOTION_BASELINE"
            or motion.get("risk_engine_allowed") is not False
            or motion.get("lpz_forecast_generated") is not False):
        raise ValueError("requires locked F4 research-motion input")
    if origins.get("source_as_of_utc") != motion.get("source_as_of_utc"):
        raise ValueError("F4 as-of mismatch")
    if origins.get("research_object_count") != motion.get("research_object_count"):
        raise ValueError("F4 object-count mismatch")

    origin_rows = origins.get("objects")
    motion_rows = motion.get("objects")
    if not isinstance(origin_rows, list) or not isinstance(motion_rows, list):
        raise ValueError("missing F4 object rows")
    motion_by_id = {row.get("research_object_id"): row for row in motion_rows}
    if len(motion_by_id) != len(motion_rows):
        raise ValueError("duplicate F4 motion research_object_id")

    features = []
    source_envelope_count = 0
    projected_envelope_count = 0
    missing_envelope_count = 0

    for origin in origin_rows:
        object_id = origin.get("research_object_id")
        row = motion_by_id.get(object_id)
        if row is None:
            raise ValueError("F4 motion object missing")
        if origin.get("parent_lineage_id") != row.get("parent_lineage_id"):
            raise ValueError("F4 lineage mismatch")
        if origin.get("origin_status") != "OBSERVED_AT_LATEST_FRAME":
            continue
        observed = origin.get("observed_component") or {}
        envelope = observed.get("geographic_envelope")
        centroid = observed.get("centroid") or {}
        if envelope is None:
            missing_envelope_count += 1
            continue
        if (not isinstance(envelope, dict)
                or envelope.get("method") != "CONVEX_HULL_OF_COMPONENT_PIXEL_CELLS"
                or envelope.get("exact_precipitation_contour") is not False
                or not isinstance(envelope.get("geometry"), dict)
                or envelope["geometry"].get("type") != "Polygon"):
            raise ValueError("invalid F4 observed geographic envelope")
        if not all(k in centroid for k in ("lon", "lat")):
            raise ValueError("observed centroid missing")

        common = {
            "research_object_id": object_id,
            "parent_lineage_id": origin["parent_lineage_id"],
            "source_as_of_utc": origins["source_as_of_utc"],
            "source_observation_valid_time_utc": origin["observation_valid_time_utc"],
            "observed_centroid_lon_lat": [float(centroid["lon"]), float(centroid["lat"])],
            "observed_approx_area_km2": observed.get("approx_area_km2"),
            "envelope_method": envelope["method"],
            "exact_precipitation_contour": False,
            "research_only": True,
            "risk_engine_allowed": False,
            "lpz_forecast_generated": False,
            "probability": None,
            "severity": None,
            "intensity": None,
        }
        features.append({
            "type": "Feature",
            "geometry": envelope["geometry"],
            "properties": {
                **common,
                "kind": "OBSERVED_THRESHOLD_COMPONENT_ENVELOPE",
                "lead_from_as_of_minutes": 0,
                "target_valid_time_utc": origin["observation_valid_time_utc"],
                "projection_method": None,
            },
        })
        source_envelope_count += 1

        for projection in row.get("projections", []):
            target = projection.get("projected_centroid") or {}
            if not all(k in target for k in ("lon", "lat")):
                raise ValueError("projected centroid missing")
            geometry = translate_polygon_lonlat(
                envelope["geometry"],
                from_lon=float(centroid["lon"]),
                from_lat=float(centroid["lat"]),
                to_lon=float(target["lon"]),
                to_lat=float(target["lat"]),
            )
            features.append({
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    **common,
                    "kind": "PROJECTED_RESEARCH_GEOGRAPHIC_ENVELOPE",
                    "lead_from_as_of_minutes": projection["lead_from_as_of_minutes"],
                    "lead_from_last_observation_minutes": projection["lead_from_last_observation_minutes"],
                    "target_valid_time_utc": projection["target_valid_time_utc"],
                    "projected_centroid_lon_lat": [float(target["lon"]), float(target["lat"])],
                    "projection_method": projection["baseline_method"],
                },
            })
            projected_envelope_count += 1

    return {
        "type": "FeatureCollection",
        "product": "F4_RESEARCH_GEOGRAPHIC_ENVELOPES",
        "schema_version": "0.1.0",
        "source_as_of_utc": origins["source_as_of_utc"],
        "latest_observation_utc": origins["latest_observation_utc"],
        "source_envelope_count": source_envelope_count,
        "projected_envelope_count": projected_envelope_count,
        "missing_envelope_count": missing_envelope_count,
        "feature_count": len(features),
        "features": features,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
        "interpretation": (
            "Research-only translated geographic envelopes derived from observed >=30 mm/h "
            "tracked components and the F4-1 constant-motion baseline. They are not validated "
            "LPZ occurrence, probability, severity, or exact future precipitation footprints."
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--origins", required=True, type=Path)
    p.add_argument("--motion", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    if a.output.exists():
        p.error("refusing overwrite")
    result = build(
        json.loads(a.origins.read_text(encoding="utf-8")),
        json.loads(a.motion.read_text(encoding="utf-8")),
    )
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({
        "source_envelope_count": result["source_envelope_count"],
        "projected_envelope_count": result["projected_envelope_count"],
        "feature_count": result["feature_count"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
