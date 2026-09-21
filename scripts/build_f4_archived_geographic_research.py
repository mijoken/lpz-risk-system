#!/usr/bin/env python3
"""F4 map-first archival export: real observed centroids and 15/30-min point arrows.

Derives from existing archived O8.1 slots and F3 objects; no acquisition, no
imaginary footprint/municipality/LPZ prediction, and no alteration to source.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from build_f4_observed_origin_join import join
from build_f4_research_motion_baseline import project

SOURCE_RUN_ID = "35564667965"
PRODUCT = "LPZ_F4_ARCHIVED_GEOGRAPHIC_RESEARCH"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def coords(point: dict) -> list[float]:
    lon, lat = float(point["lon"]), float(point["lat"])
    if not (math.isfinite(lon) and math.isfinite(lat)
            and -180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("invalid geographic coordinates")
    return [lon, lat]


def build(root: Path) -> dict:
    batch = read(root / "batch_manifest.json")
    f3 = read(root / "f3_research" / "manifest.json")
    if (str(batch.get("run_id")) != SOURCE_RUN_ID
            or str(f3.get("source_run_id")) != SOURCE_RUN_ID
            or batch.get("risk_engine_allowed") is not False
            or f3.get("risk_engine_allowed") is not False
            or f3.get("forecast_generated") is not False):
        raise ValueError("archived F4 source provenance/release mismatch")
    features = []
    projected_objects = 0
    slot_count = 0
    for record in f3["slot_results"]:
        if record.get("research_status") != "DESCRIPTIVE_ONLY":
            continue
        name = record["source_file"]
        if Path(name).name != name or not name.endswith(".json"):
            raise ValueError("unsafe F3 slot filename")
        expected = root / "f3_research" / "slots" / name
        if (root / record["output_file"]).resolve() != expected.resolve():
            raise ValueError("F3 slot provenance mismatch")
        bundle, adapter = read(root / "slots" / name), read(expected)
        if bundle.get("collection_slot_utc") != record["collection_slot_utc"]:
            raise ValueError("slot time mismatch")
        origins = join(bundle, adapter)
        baseline = project(bundle, adapter)
        by_id = {r["research_object_id"]: r for r in origins["objects"]}
        slot_count += 1
        for row in baseline["objects"]:
            projections = row["projections"]
            if not projections:
                continue
            projected_objects += 1
            origin = by_id[row["research_object_id"]]
            if origin["origin_status"] != "OBSERVED_AT_LATEST_FRAME":
                raise ValueError("projected object without current observed origin")
            observed = coords(origin["observed_component"]["centroid"])
            base = {
                "research_object_id": row["research_object_id"],
                "source_slot_utc": bundle["collection_slot_utc"],
                "observation_valid_time_utc": origin["observation_valid_time_utc"],
                "observed_centroid_lon_lat": observed,
                "observed_bbox_pixel": origin["observed_component"]["bbox_pixel"],
                "observed_approx_area_km2": origin["observed_component"]["approx_area_km2"],
                "observed_boundary_truncated": origin["observed_component"]["boundary_truncated"],
                "observed_geometry_limit": "CENTROID_ONLY_BBOX_IS_PIXEL_SPACE_NOT_GEO_POLYGON",
                "lpz_forecast_generated": False,
            }
            features.append({
                "type": "Feature", "geometry": {"type": "Point", "coordinates": observed},
                "properties": dict(base, kind="OBSERVED_ORIGIN", lead_from_as_of_minutes=0),
            })
            for projection in projections:
                predicted = coords(projection["projected_centroid"])
                props = dict(base, kind="RESEARCH_POINT_EXTRAPOLATION",
                             lead_from_as_of_minutes=projection["lead_from_as_of_minutes"],
                             target_valid_time_utc=projection["target_valid_time_utc"],
                             research_only=True, probability=None, intensity=None,
                             footprint=None, affected_regions=None)
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": predicted},
                    "properties": props,
                })
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [observed, predicted]},
                    "properties": dict(props, kind="RESEARCH_POINT_MOTION_ARROW"),
                })
    if not projected_objects:
        raise ValueError("no archived projected objects")
    return {
        "type": "FeatureCollection",
        "product": PRODUCT,
        "schema_version": "1.0.0",
        "source_run_id": SOURCE_RUN_ID,
        "source_slot_count": slot_count,
        "projected_object_count": projected_objects,
        "feature_count": len(features),
        "archived_research_only": True,
        "risk_engine_allowed": False,
        "lpz_forecast_generated": False,
        "radar_coverage": "SELECTED_FIXED_MOSAIC_NOT_NATIONWIDE",
        "not_a_precipitation_footprint": True,
        "features": features,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    if a.output.exists():
        parser.error("refusing overwrite")
    obj = build(a.source_root)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("x", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({k: obj[k] for k in ("product", "source_run_id",
        "source_slot_count", "projected_object_count", "feature_count",
        "lpz_forecast_generated")}))


if __name__ == "__main__":
    main()
