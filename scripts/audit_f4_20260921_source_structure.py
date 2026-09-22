#!/usr/bin/env python3
"""Read-only, source-only morphology audit for one already-frozen F4-9C case.

This tool reads ONLY the immutable F4-9C case JSON and its previously captured
F4-9A decoded source archive. It never opens cohort status, verifications,
future radar targets, target labels, forecast-skill rows, or F4-9D decisions.
The source frames span 15 minutes, NOT the JMA 3-hour LPZ criterion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from lpz_risk.radar_morphology import (
    EARTH_RADIUS_M,
    TILE_SIZE,
    extract_objects_from_mosaic,
)


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def quantile(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    v = np.asarray(values, dtype=float)
    return {
        "count": len(values),
        "min": round(float(v.min()), 3),
        "median": round(float(np.median(v)), 3),
        "max": round(float(v.max()), 3),
    }


def geographic_bounds(zoom: int, tile_x: int, tile_y: int, tiles: int) -> dict:
    side = math.isqrt(tiles)
    if side * side != tiles:
        raise ValueError("tile_count must be a square mosaic")
    scale = float(2**zoom)

    def lat(y: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2*y / scale))))

    return {
        "west_lon": round(tile_x / scale * 360 - 180, 6),
        "east_lon": round((tile_x + side) / scale * 360 - 180, 6),
        "south_lat": round(lat(tile_y + side), 6),
        "north_lat": round(lat(tile_y), 6),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case-json", required=True, type=Path)
    args = ap.parse_args()
    case = json.loads(args.case_json.read_text(encoding="utf-8"))
    if case.get("product") != "F4_9C_PROSPECTIVE_CASE":
        raise ValueError("unexpected frozen case product")
    if (
        case.get("future_observations_read_at_capture") is not False
        or case.get("forecast_skill_scored_at_capture") is not False
        or case.get("parameter_tuning_performed") is not False
        or case.get("risk_engine_allowed") is not False
    ):
        raise ValueError("frozen prospective capture/source-only contract mismatch")

    source = Path(case["source_archive_dir"])
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    npz_path = source / "decoded_field.npz"
    expected = case["source_decoded_field_sha256"]
    actual = digest(npz_path)
    if expected != actual or expected != manifest["storage"]["sha256"]:
        raise ValueError("immutable source decoded-field SHA-256 mismatch")
    if manifest["product"] != "F4_DECODED_FIELD_RESEARCH_ARCHIVE":
        raise ValueError("unexpected source archive manifest product")
    if manifest["fixed_mosaic"] != case["fixed_mosaic"]:
        raise ValueError("source/case fixed mosaic mismatch")

    fixed = case["fixed_mosaic"]
    zoom = int(fixed["zoom"])
    tile_x = int(fixed["origin_tile_x"])
    tile_y = int(fixed["origin_tile_y"])
    tiles = int(fixed["tile_count"])
    with np.load(npz_path, allow_pickle=False) as npz:
        stack = np.asarray(npz["class_index"])

    valid_times = manifest["frame_valid_times"]
    if stack.ndim != 3 or stack.shape[0] != 4 or len(valid_times) != 4:
        raise ValueError("expected exactly four pre-capture frames")
    if [int((utc(valid_times[i+1])-utc(valid_times[i])).total_seconds()) for i in range(3)] != [300]*3:
        raise ValueError("source frames must be exactly five minutes apart")
    if valid_times[-1] != case["source_slot_utc"]:
        raise ValueError("source slot does not match last observed frame")
    if int((utc(case["prospective_as_of_utc"]) - utc(valid_times[-1])).total_seconds()) != 900:
        raise ValueError("source-as-of must follow last observation by 15 minutes")
    if stack.shape[1] != stack.shape[2] or stack.shape[1] != math.isqrt(tiles)*TILE_SIZE:
        raise ValueError("mosaic shape/tile-count mismatch")

    # No future observations, forecasts or outcome rows are read.
    # Public class index 5,6,7 are exactly >=30 mm/h; 6,7 >=50; 7 >=80.
    pixels_all = np.count_nonzero(np.all(stack >= 5, axis=0))
    pixels_any = np.count_nonzero(np.any(stack >= 5, axis=0))
    frame_rows = []
    for index, frame in enumerate(stack):
        frame_rows.append({
            "observation_valid_time_utc": valid_times[index],
            "known_pixels": int(np.count_nonzero(frame >= 0)),
            "unclassified_pixels": int(np.count_nonzero(frame < 0)),
            "ge30_pixels": int(np.count_nonzero(frame >= 5)),
            "ge50_pixels": int(np.count_nonzero(frame >= 6)),
            "ge80_pixels": int(np.count_nonzero(frame >= 7)),
        })

    objects = extract_objects_from_mosaic(
        stack[-1],
        zoom=zoom,
        origin_tile_x=tile_x,
        origin_tile_y=tile_y,
        threshold_mmph=30.0,
        min_pixels=2,
    )
    eligible = [o for o in objects if not o.boundary_truncated]
    if len(eligible) != int(case["source_component_count"]):
        raise ValueError("frozen eligible source component count mismatch")

    # Descriptive >=30 mm/h source-component morphology; NOT LPZ detection.
    ratios = [float(o.aspect_ratio) for o in eligible if o.aspect_ratio is not None]
    areas = [float(o.area_km2) for o in eligible]
    result = {
        "audit_product": "F4_20260921_SOURCE_ONLY_MORPHOLOGY",
        "case_id": case["case_id"],
        "source_slot_utc": case["source_slot_utc"],
        "prospective_as_of_utc": case["prospective_as_of_utc"],
        "frame_valid_times_utc": valid_times,
        "observation_window_minutes": 15,
        "frame_count": 4,
        "source_archive_sha256": actual,
        "fixed_mosaic": fixed,
        "discovery_parent": case["discovery_parent"],
        "geographic_bounds": geographic_bounds(zoom, tile_x, tile_y, tiles),
        "frames": frame_rows,
        "ge30_pixels_all_four_fixed_locations": int(pixels_all),
        "ge30_pixels_any_four_fixed_locations": int(pixels_any),
        "ge30_fixed_location_persistence_fraction": (
            round(pixels_all/pixels_any, 5) if pixels_any else None
        ),
        "eligible_ge30_source_components": len(eligible),
        "eligible_area_km2": quantile(areas),
        "eligible_aspect_ratio": quantile(ratios),
        "eligible_aspect_ge_2_5": sum(a >= 2.5 for a in ratios),
        "eligible_area_ge_500_km2": sum(a >= 500 for a in areas),
        "largest_source_components_descriptive": [
            {
                "area_km2": round(o.area_km2, 3),
                "aspect_ratio": (
                    round(o.aspect_ratio, 3)
                    if o.aspect_ratio is not None else None
                ),
                "centroid_lon": round(o.centroid_lon, 5),
                "centroid_lat": round(o.centroid_lat, 5),
                "pixel_count": o.pixel_count,
            }
            for o in sorted(eligible, key=lambda v: v.area_km2, reverse=True)[:5]
        ],
        "interpretation_limit": (
            "These are <=15-minute source-only public categorical >=30 mm/h "
            "masks on one selected mosaic. No JMA 3-hour accumulation, 5-km "
            "100/150-mm spatial test, risk grid, atmospheric process attribution, "
            "or forecast verification was calculated."
        ),
        "read_future_observations": False,
        "read_f4_9c_verifications": False,
        "forecast_skill_scored": False,
        "risk_engine_allowed": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
