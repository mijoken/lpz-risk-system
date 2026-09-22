#!/usr/bin/env python3
"""Read-only 45-minute organization audit for the frozen 2026-09-21 Tohoku source.

The script uses only pre-existing F4-9A source archives on the SAME fixed z8
mosaic as the frozen F4-9C case, ending no later than the 22:00 JST source slot.
It deduplicates overlapping 5-minute frames by timestamp and requires duplicate
bytes to decode to identical class-index arrays.

It NEVER opens F4-9C verification rows, target/future observations, forecasts,
cohort status, F4-9D decisions, or network resources.

This is a categorical radar-structure audit, NOT a JMA LPZ classifier and NOT a
forecast-skill evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from lpz_risk.radar_morphology import (
    EARTH_RADIUS_M,
    TILE_SIZE,
    connected_components_8,
    extract_objects_from_mosaic,
)

TARGET_START = datetime(2026, 9, 21, 12, 15, tzinfo=timezone.utc)
TARGET_END = datetime(2026, 9, 21, 13, 0, tzinfo=timezone.utc)
STEP_SECONDS = 300
EXPECTED_FRAME_COUNT = 10


def utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("naive timestamp rejected")
    return dt.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fixed_key(doc: dict[str, Any]) -> tuple[int, int, int, int]:
    f = doc["fixed_mosaic"]
    return (
        int(f["zoom"]),
        int(f["origin_tile_x"]),
        int(f["origin_tile_y"]),
        int(f["tile_count"]),
    )


def _pixel_lonlat(
    rows: np.ndarray,
    cols: np.ndarray,
    *,
    zoom: int,
    origin_tile_x: int,
    origin_tile_y: int,
) -> tuple[np.ndarray, np.ndarray]:
    world = TILE_SIZE * (2**zoom)
    gx = origin_tile_x * TILE_SIZE + cols.astype(float) + 0.5
    gy = origin_tile_y * TILE_SIZE + rows.astype(float) + 0.5
    lon = gx / world * 360.0 - 180.0
    merc = math.pi * (1.0 - 2.0 * gy / world)
    lat = np.degrees(np.arctan(np.sinh(merc)))
    return lon, lat


def _field_shape(
    mask: np.ndarray,
    *,
    zoom: int,
    origin_tile_x: int,
    origin_tile_y: int,
) -> dict[str, Any]:
    pts = np.argwhere(mask)
    if len(pts) < 2:
        return {
            "pixel_count": int(len(pts)),
            "centroid_lon": None,
            "centroid_lat": None,
            "pca_aspect_ratio": None,
            "orientation_deg_clockwise_from_north": None,
        }
    rows, cols = pts[:, 0], pts[:, 1]
    lons, lats = _pixel_lonlat(
        rows, cols,
        zoom=zoom,
        origin_tile_x=origin_tile_x,
        origin_tile_y=origin_tile_y,
    )
    centroid_lon = float(np.mean(lons))
    centroid_lat = float(np.mean(lats))
    scale_km = (
        2.0 * math.pi * EARTH_RADIUS_M
        * math.cos(math.radians(centroid_lat))
        / (TILE_SIZE * (2**zoom))
        / 1000.0
    )
    x = (cols.astype(float) - float(np.mean(cols))) * scale_km
    y = -(rows.astype(float) - float(np.mean(rows))) * scale_km
    cov = np.cov(np.column_stack([x, y]), rowvar=False, ddof=0)
    vals, vecs = np.linalg.eigh(cov)
    order = np.argsort(vals)[::-1]
    vals = np.maximum(vals[order], 0.0)
    vecs = vecs[:, order]
    ratio = None if vals[1] <= 0 else math.sqrt(float(vals[0] / vals[1]))
    vx_east, vy_north = map(float, vecs[:, 0])
    orientation = math.degrees(math.atan2(vx_east, vy_north)) % 180.0
    return {
        "pixel_count": int(len(pts)),
        "centroid_lon": round(centroid_lon, 6),
        "centroid_lat": round(centroid_lat, 6),
        "pca_aspect_ratio": round(ratio, 4) if ratio is not None else None,
        "orientation_deg_clockwise_from_north": round(orientation, 3),
    }


def _area_summary(objects) -> dict[str, Any]:
    if not objects:
        return {
            "count": 0,
            "area_median_km2": None,
            "area_max_km2": None,
            "aspect_ge_2_5_count": 0,
            "aspect_max": None,
        }
    areas = np.asarray([x.area_km2 for x in objects], dtype=float)
    aspects = [float(x.aspect_ratio) for x in objects if x.aspect_ratio is not None]
    return {
        "count": len(objects),
        "area_median_km2": round(float(np.median(areas)), 3),
        "area_max_km2": round(float(np.max(areas)), 3),
        "aspect_ge_2_5_count": sum(x >= 2.5 for x in aspects),
        "aspect_max": round(max(aspects), 3) if aspects else None,
    }


def _load_frames(
    cohort_root: Path,
    case: dict[str, Any],
) -> tuple[list[datetime], np.ndarray, dict[str, Any]]:
    key = fixed_key(case)
    expected_source_end = utc(case["source_slot_utc"])
    if expected_source_end != TARGET_END:
        raise ValueError("reference case is not the 2026-09-21 22:00 JST source slot")

    candidates: dict[datetime, list[tuple[np.ndarray, str, str]]] = defaultdict(list)
    archives_used = []
    ignored_other_mosaic = 0
    ignored_after_event = 0

    for mp in sorted((cohort_root / "sources").glob("*/manifest.json")):
        doc = json.loads(mp.read_text(encoding="utf-8"))
        if doc.get("product") != "F4_DECODED_FIELD_RESEARCH_ARCHIVE":
            continue
        times = [utc(x) for x in doc["frame_valid_times"]]
        if max(times) > TARGET_END:
            ignored_after_event += 1
            continue
        if fixed_key(doc) != key:
            ignored_other_mosaic += 1
            continue
        if max(times) < TARGET_START:
            continue

        npz_path = mp.parent / doc["storage"]["file"]
        actual_sha = sha256(npz_path)
        if actual_sha != doc["storage"]["sha256"]:
            raise ValueError(f"source archive SHA-256 mismatch: {npz_path}")
        with np.load(npz_path, allow_pickle=False) as payload:
            stack = np.asarray(payload["class_index"])
        if stack.shape[0] != len(times):
            raise ValueError("source frame count mismatch")

        archives_used.append({
            "source_dir": mp.parent.name,
            "source_sha256": actual_sha,
            "frame_valid_times_utc": [iso(x) for x in times],
        })
        for idx, ts in enumerate(times):
            if TARGET_START <= ts <= TARGET_END:
                candidates[ts].append((np.asarray(stack[idx]), actual_sha, mp.parent.name))

    expected = [
        TARGET_START + (TARGET_END - TARGET_START) * 0
    ]
    # Construct exact 5-minute grid explicitly.
    expected = [
        datetime.fromtimestamp(TARGET_START.timestamp() + STEP_SECONDS*i, tz=timezone.utc)
        for i in range(EXPECTED_FRAME_COUNT)
    ]
    missing = [x for x in expected if x not in candidates]
    if missing:
        raise ValueError(
            "contiguous 45-minute source window incomplete: "
            + ",".join(iso(x) for x in missing)
        )

    frames = []
    duplicate_timestamps = []
    for ts in expected:
        rows = candidates[ts]
        ref = rows[0][0]
        if len(rows) > 1:
            duplicate_timestamps.append(iso(ts))
            for arr, _, source_dir in rows[1:]:
                if not np.array_equal(ref, arr):
                    raise ValueError(
                        f"duplicate source frame mismatch at {iso(ts)} in {source_dir}"
                    )
        frames.append(ref)

    return expected, np.stack(frames), {
        "archives_used": archives_used,
        "duplicate_timestamps_verified_identical": duplicate_timestamps,
        "ignored_other_mosaic_manifest_count": ignored_other_mosaic,
        "ignored_source_after_event_manifest_count": ignored_after_event,
    }


def audit(cohort_root: Path, case_path: Path) -> dict[str, Any]:
    case = json.loads(case_path.read_text(encoding="utf-8"))
    if (
        case.get("product") != "F4_9C_PROSPECTIVE_CASE"
        or case.get("future_observations_read_at_capture") is not False
        or case.get("forecast_skill_scored_at_capture") is not False
        or case.get("risk_engine_allowed") is not False
    ):
        raise ValueError("frozen case source-only contract mismatch")

    times, stack, provenance = _load_frames(cohort_root, case)
    fixed = case["fixed_mosaic"]
    zoom = int(fixed["zoom"])
    ox = int(fixed["origin_tile_x"])
    oy = int(fixed["origin_tile_y"])

    known = stack >= 0
    known_all = np.all(known, axis=0)
    ge30 = stack >= 5
    ge50 = stack >= 6
    ge80 = stack >= 7
    ge30_hits = np.sum(ge30, axis=0)

    frame_rows = []
    for idx, frame in enumerate(stack):
        objects = extract_objects_from_mosaic(
            frame,
            zoom=zoom,
            origin_tile_x=ox,
            origin_tile_y=oy,
            threshold_mmph=30.0,
            min_pixels=2,
        )
        eligible = [x for x in objects if not x.boundary_truncated]
        frame_rows.append({
            "observation_valid_time_utc": iso(times[idx]),
            "known_pixels": int(np.count_nonzero(frame >= 0)),
            "unclassified_pixels": int(np.count_nonzero(frame < 0)),
            "ge30_pixels": int(np.count_nonzero(ge30[idx])),
            "ge50_pixels": int(np.count_nonzero(ge50[idx])),
            "ge80_pixels": int(np.count_nonzero(ge80[idx])),
            "eligible_ge30_components": _area_summary(eligible),
            "whole_ge30_field_shape_descriptive": _field_shape(
                ge30[idx],
                zoom=zoom,
                origin_tile_x=ox,
                origin_tile_y=oy,
            ),
        })

    # Fixed-coordinate persistence only on pixels scientifically classified
    # (not transparent/unclassified) at every one of the ten timestamps.
    occurrence = {}
    for n in (1, 3, 5, 8, 10):
        occurrence[f"known_all_ge30_in_at_least_{n}_of_10"] = int(
            np.count_nonzero(known_all & (ge30_hits >= n))
        )

    union_known_all = known_all & (ge30_hits >= 1)
    union_components = connected_components_8(union_known_all)
    union_sizes = sorted((len(x) for x in union_components), reverse=True)

    # Whole 45-minute swept footprint shape: descriptive union, not accumulation.
    union_shape = _field_shape(
        union_known_all,
        zoom=zoom,
        origin_tile_x=ox,
        origin_tile_y=oy,
    )

    return {
        "audit_product": "F4_20260921_45MIN_SAME_MOSAIC_SOURCE_ORGANIZATION",
        "case_id": case["case_id"],
        "window_start_utc": iso(times[0]),
        "window_end_utc": iso(times[-1]),
        "window_minutes": 45,
        "five_minute_frame_count": len(times),
        "frame_times_utc": [iso(x) for x in times],
        "fixed_mosaic": fixed,
        "provenance": provenance,
        "frames": frame_rows,
        "known_all_ten_frames_pixel_count": int(np.count_nonzero(known_all)),
        "known_all_fraction_of_mosaic": round(float(np.mean(known_all)), 6),
        "fixed_coordinate_occurrence": occurrence,
        "fixed_coordinate_ge30_all10_over_any10_known_all_fraction": (
            round(
                occurrence["known_all_ge30_in_at_least_10_of_10"]
                / occurrence["known_all_ge30_in_at_least_1_of_10"],
                6,
            )
            if occurrence["known_all_ge30_in_at_least_1_of_10"] else None
        ),
        "swept_ge30_union_known_all_pixel_count": int(np.count_nonzero(union_known_all)),
        "swept_ge30_union_connected_component_count": len(union_components),
        "swept_ge30_union_largest_component_pixel_count": (
            union_sizes[0] if union_sizes else 0
        ),
        "swept_ge30_union_shape_descriptive": union_shape,
        "interpretation_limits": [
            "This is 45 minutes, not three hours.",
            "Instantaneous public radar intensity classes are not accumulated rainfall.",
            "Whole-field and swept-union PCA summarize geometry only; scattered cells can inflate elongation.",
            "Fixed-coordinate persistence undercounts coherent moving systems.",
            "Unclassified pixels are excluded from all-ten-frame persistence rather than treated as zero rain.",
            "No F4-9C future observations, verification rows, prediction skill, or F4-9D decision were read.",
            "No official JMA LPZ occurrence classification is produced.",
        ],
        "read_future_observations": False,
        "read_f4_9c_verifications": False,
        "forecast_skill_scored": False,
        "risk_engine_allowed": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cohort-root", required=True, type=Path)
    ap.add_argument("--reference-case", required=True, type=Path)
    args = ap.parse_args()
    print(json.dumps(
        audit(args.cohort_root, args.reference_case),
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
