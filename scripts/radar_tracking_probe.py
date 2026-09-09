#!/usr/bin/env python3
"""Phase 1C live proof for conservative multi-frame radar object tracking.

A settled rainy HRPN frame is selected at z=6. The same fixed z8 footprint is
then reconstructed for four consecutive 5-minute analysis frames. Exact public
PNG thresholds (30/50/80 mm/h) are segmented on every frame and associated only
when components overlap spatially.

This is a tracking proof, not an LPZ classifier. Hirockawa overlap/persistence
thresholds are recorded nowhere as operational gates here.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.radar_morphology import ALLOWED_EXACT_THRESHOLDS_MMPH  # noqa: E402
from lpz_risk.radar_science import (  # noqa: E402
    decode_jma_precipitation_png,
    descendant_tile_indices,
    lonlat_to_xyz,
    tile_pixel_center_lonlat,
    web_mercator_pixel_area_km2,
)
from lpz_risk.radar_tracking import (  # noqa: E402
    best_one_to_one_matches,
    candidate_edges,
    extract_pixel_components,
    split_merge_candidates,
)

USER_AGENT = "lpz-risk-system/0.1.0 (+https://github.com/mijoken/lpz-risk-system)"
NOWC_TIMES = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"
TIMEOUT_SECONDS = 20
MAX_TILE_BYTES = 2 * 1024 * 1024
MIN_FRAME_AGE_MINUTES = 15
DISCOVERY_ZOOM = 6
TRACKING_ZOOM = 8
FRAME_COUNT = 4
JAPAN_BBOX = {"west": 122.0, "east": 154.0, "south": 20.0, "north": 46.0}
WORKERS = 8


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_compact(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def http_get(url: str, max_bytes: int) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError(f"response exceeded {max_bytes} byte limit")
    return body


def load_json(url: str) -> Any:
    return json.loads(http_get(url, 2 * 1024 * 1024).decode("utf-8"))


def tile_url(row: dict[str, Any], z: int, x: int, y: int) -> str:
    return (
        "https://www.jma.go.jp/bosai/jmatile/data/nowc/"
        f"{row['basetime']}/none/{row['validtime']}/surf/hrpns/{z}/{x}/{y}.png"
    )


def japan_tiles(zoom: int) -> list[tuple[int, int]]:
    _, x0, y0 = lonlat_to_xyz(JAPAN_BBOX["west"], JAPAN_BBOX["north"], zoom)
    _, x1, y1 = lonlat_to_xyz(JAPAN_BBOX["east"], JAPAN_BBOX["south"], zoom)
    xa, xb = sorted((x0, x1)); ya, yb = sorted((y0, y1))
    return [(x, y) for y in range(ya, yb + 1) for x in range(xa, xb + 1)]


def usable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [r for r in rows if "hrpns" in r.get("elements", []) and r.get("validtime") and r.get("basetime")]
    return sorted(out, key=lambda r: str(r["validtime"]))


def inspect_tile(row: dict[str, Any], z: int, x: int, y: int) -> dict[str, Any]:
    try:
        decoded = decode_jma_precipitation_png(http_get(tile_url(row, z, x, y), MAX_TILE_BYTES))
        valid = decoded.class_index >= 0
        return {
            "ok": True,
            "z": z,
            "x": x,
            "y": y,
            "class_index": decoded.class_index,
            "precipitation_pixels": int(np.count_nonzero(valid)),
            "max_class_index": int(np.max(decoded.class_index[valid])) if np.any(valid) else -1,
            "unknown_opaque_pixels": decoded.unknown_opaque_pixel_count,
        }
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return {"ok": False, "z": z, "x": x, "y": y, "error": f"{type(exc).__name__}: {exc}"}


def inspect_many(row: dict[str, Any], z: int, tiles: list[tuple[int, int]]) -> list[dict[str, Any]]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(lambda xy: inspect_tile(row, z, xy[0], xy[1]), tiles))


def select_reference_and_sequence(rows: list[dict[str, Any]], now: datetime) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    ordered = usable_rows(rows)
    cutoff = now - timedelta(minutes=MIN_FRAME_AGE_MINUTES)
    discovery_tiles = japan_tiles(DISCOVERY_ZOOM)

    for idx in range(len(ordered) - 1, FRAME_COUNT - 2, -1):
        ref = ordered[idx]
        ref_dt = parse_compact(str(ref["validtime"]))
        if ref_dt > cutoff:
            continue

        sequence = ordered[idx - FRAME_COUNT + 1: idx + 1]
        dts = [parse_compact(str(r["validtime"])) for r in sequence]
        deltas = [(b - a).total_seconds() for a, b in zip(dts[:-1], dts[1:])]
        if len(sequence) != FRAME_COUNT or any(delta != 300 for delta in deltas):
            continue

        reports = inspect_many(ref, DISCOVERY_ZOOM, discovery_tiles)
        good = [r for r in reports if r.get("ok")]
        rainy = [r for r in good if int(r.get("precipitation_pixels", 0)) > 0]
        if not rainy:
            continue
        best = max(rainy, key=lambda r: (int(r["max_class_index"]), int(r["precipitation_pixels"])))
        discovery = {
            "reference_valid_time": iso_utc(ref_dt),
            "tiles_attempted": len(reports),
            "tiles_ok": len(good),
            "tiles_with_precipitation": len(rainy),
            "unknown_opaque_pixels": sum(int(r.get("unknown_opaque_pixels", 0)) for r in good),
            "parent_tile": {"z": DISCOVERY_ZOOM, "x": int(best["x"]), "y": int(best["y"])},
            "strongest_class_index": int(best["max_class_index"]),
        }
        return ref, sequence, discovery

    raise RuntimeError("no settled consecutive four-frame rainy sequence found")


def build_fixed_mosaic(row: dict[str, Any], parent_x: int, parent_y: int) -> tuple[np.ndarray, dict[str, Any]]:
    children = descendant_tile_indices(DISCOVERY_ZOOM, parent_x, parent_y, TRACKING_ZOOM)
    inspected = inspect_many(row, TRACKING_ZOOM, children)
    failures = [r for r in inspected if not r.get("ok")]
    unknown = sum(int(r.get("unknown_opaque_pixels", 0)) for r in inspected if r.get("ok"))
    if failures:
        raise RuntimeError(f"{len(failures)} z8 tiles failed for frame {row['validtime']}")
    if unknown:
        raise RuntimeError(f"unknown opaque colours in frame {row['validtime']}: {unknown}")

    xs = sorted({x for x, _ in children}); ys = sorted({y for _, y in children})
    by_xy = {(int(r["x"]), int(r["y"])): r for r in inspected}
    mosaic = np.full((len(ys) * 256, len(xs) * 256), -1, dtype=np.int8)
    for iy, y in enumerate(ys):
        for ix, x in enumerate(xs):
            mosaic[iy * 256:(iy + 1) * 256, ix * 256:(ix + 1) * 256] = by_xy[(x, y)]["class_index"]
    return mosaic, {
        "origin_tile_x": xs[0],
        "origin_tile_y": ys[0],
        "tile_count": len(inspected),
        "precipitation_pixels": int(np.count_nonzero(mosaic >= 0)),
        "max_class_index": int(np.max(mosaic[mosaic >= 0])) if np.any(mosaic >= 0) else -1,
    }


def component_summary(component, *, origin_tile_x: int, origin_tile_y: int, mosaic_width: int) -> dict[str, Any]:
    row = component.centroid_row
    col = component.centroid_col
    tile_offset_x = int(col) // 256
    tile_offset_y = int(row) // 256
    pixel_x = int(col) % 256
    pixel_y = int(row) % 256
    lon, lat = tile_pixel_center_lonlat(
        TRACKING_ZOOM,
        origin_tile_x + tile_offset_x,
        origin_tile_y + tile_offset_y,
        pixel_x,
        pixel_y,
    )
    pixel_area = web_mercator_pixel_area_km2(lat, TRACKING_ZOOM)
    return {
        "local_id": component.local_id,
        "pixel_count": component.pixel_count,
        "approx_area_km2": component.pixel_count * pixel_area,
        "centroid_pixel": {"row": row, "col": col},
        "centroid": {"lon": lon, "lat": lat},
        "bbox_pixel": list(component.bbox_pixel),
        "boundary_truncated": component.boundary_truncated,
    }


def displacement_metrics(edge, prev_component, curr_component, *, origin_tile_x: int, origin_tile_y: int, elapsed_seconds: float) -> dict[str, float | None]:
    mean_row = (prev_component.centroid_row + curr_component.centroid_row) / 2.0
    mean_col = (prev_component.centroid_col + curr_component.centroid_col) / 2.0
    tile_offset_x = int(mean_col) // 256
    tile_offset_y = int(mean_row) // 256
    px = int(mean_col) % 256
    py = int(mean_row) % 256
    _, lat = tile_pixel_center_lonlat(TRACKING_ZOOM, origin_tile_x + tile_offset_x, origin_tile_y + tile_offset_y, px, py)
    pixel_km = math.sqrt(web_mercator_pixel_area_km2(lat, TRACKING_ZOOM))
    displacement_km = edge.centroid_displacement_pixels * pixel_km
    return {
        "centroid_displacement_km": displacement_km,
        "centroid_speed_mps": displacement_km * 1000.0 / elapsed_seconds if elapsed_seconds > 0 else None,
    }


def track_threshold(frames: list[dict[str, Any]], threshold: float, origin_tile_x: int, origin_tile_y: int) -> dict[str, Any]:
    frame_components = [extract_pixel_components(f["mosaic"], threshold_mmph=threshold, min_pixels=2) for f in frames]
    lineage_by_frame: list[dict[int, str]] = []
    next_lineage = 1

    first_map: dict[int, str] = {}
    for comp in frame_components[0]:
        first_map[comp.local_id] = f"T{int(threshold)}-L{next_lineage:04d}"
        next_lineage += 1
    lineage_by_frame.append(first_map)

    transitions: list[dict[str, Any]] = []
    for i in range(1, len(frames)):
        prev = frame_components[i - 1]
        curr = frame_components[i]
        edges = candidate_edges(prev, curr)
        primary = best_one_to_one_matches(edges)
        structures = split_merge_candidates(edges)
        curr_map: dict[int, str] = {}
        primary_curr_ids = {e.current_id for e in primary}
        primary_prev_ids = {e.previous_id for e in primary}
        edge_rows: list[dict[str, Any]] = []

        prev_by_id = {c.local_id: c for c in prev}
        curr_by_id = {c.local_id: c for c in curr}
        elapsed = (frames[i]["valid_dt"] - frames[i - 1]["valid_dt"]).total_seconds()

        for edge in primary:
            lineage = lineage_by_frame[i - 1][edge.previous_id]
            curr_map[edge.current_id] = lineage
            row = edge.to_dict()
            row["lineage_id"] = lineage
            row.update(displacement_metrics(edge, prev_by_id[edge.previous_id], curr_by_id[edge.current_id], origin_tile_x=origin_tile_x, origin_tile_y=origin_tile_y, elapsed_seconds=elapsed))
            edge_rows.append(row)

        births = []
        for comp in curr:
            if comp.local_id not in primary_curr_ids:
                lineage = f"T{int(threshold)}-L{next_lineage:04d}"
                next_lineage += 1
                curr_map[comp.local_id] = lineage
                births.append({"current_id": comp.local_id, "lineage_id": lineage})

        deaths = [
            {"previous_id": comp.local_id, "lineage_id": lineage_by_frame[i - 1][comp.local_id]}
            for comp in prev
            if comp.local_id not in primary_prev_ids
        ]
        lineage_by_frame.append(curr_map)
        transitions.append({
            "from_valid_time": iso_utc(frames[i - 1]["valid_dt"]),
            "to_valid_time": iso_utc(frames[i]["valid_dt"]),
            "elapsed_seconds": elapsed,
            "candidate_edge_count": len(edges),
            "primary_match_count": len(primary),
            "primary_matches": edge_rows,
            "birth_count": len(births),
            "births": births,
            "death_count": len(deaths),
            "deaths": deaths,
            "split_candidates": structures["splits"],
            "merge_candidates": structures["merges"],
        })

    frame_rows = []
    for i, (frame, comps) in enumerate(zip(frames, frame_components)):
        frame_rows.append({
            "valid_time": iso_utc(frame["valid_dt"]),
            "component_count": len(comps),
            "components": [
                {
                    **component_summary(comp, origin_tile_x=origin_tile_x, origin_tile_y=origin_tile_y, mosaic_width=frame["mosaic"].shape[1]),
                    "lineage_id": lineage_by_frame[i][comp.local_id],
                }
                for comp in comps
            ],
        })

    lifetimes: dict[str, dict[str, Any]] = {}
    for frame_idx, fmap in enumerate(lineage_by_frame):
        for lineage in fmap.values():
            entry = lifetimes.setdefault(lineage, {"first_frame_index": frame_idx, "last_frame_index": frame_idx, "frame_count": 0})
            entry["first_frame_index"] = min(entry["first_frame_index"], frame_idx)
            entry["last_frame_index"] = max(entry["last_frame_index"], frame_idx)
            entry["frame_count"] += 1
    lifetime_rows = [
        {"lineage_id": lineage, **values, "duration_minutes": max(0, (values["frame_count"] - 1) * 5)}
        for lineage, values in sorted(lifetimes.items())
    ]

    return {
        "threshold_mmph": threshold,
        "frames": frame_rows,
        "transitions": transitions,
        "lineage_count": len(lifetime_rows),
        "lineages": lifetime_rows,
        "max_observed_lineage_duration_minutes": max((r["duration_minutes"] for r in lifetime_rows), default=0),
    }


def run() -> dict[str, Any]:
    now = utc_now()
    base = {
        "schema_version": "0.1.0",
        "phase": "1C-radar-tracking-proof",
        "feature_id": "live_precip_object_tracking_public_png",
        "paper_reproduction": False,
        "operational_lpZ_gate": False,
        "thresholds_mmph": list(ALLOWED_EXACT_THRESHOLDS_MMPH),
        "association_policy": "overlap-only conservative candidate edges; greedy one-to-one primary lineage; split/merge retained separately",
    }
    try:
        rows = load_json(NOWC_TIMES)
        if not isinstance(rows, list):
            raise ValueError("targetTimes_N1.json was not a list")
        _, sequence, discovery = select_reference_and_sequence(rows, now)
        parent_x = int(discovery["parent_tile"]["x"]); parent_y = int(discovery["parent_tile"]["y"])

        frames: list[dict[str, Any]] = []
        origin_x = origin_y = None
        for row in sequence:
            mosaic, meta = build_fixed_mosaic(row, parent_x, parent_y)
            if origin_x is None:
                origin_x = int(meta["origin_tile_x"]); origin_y = int(meta["origin_tile_y"])
            elif int(meta["origin_tile_x"]) != origin_x or int(meta["origin_tile_y"]) != origin_y:
                raise RuntimeError("fixed z8 mosaic origin changed across frames")
            frames.append({"row": row, "valid_dt": parse_compact(str(row["validtime"])), "mosaic": mosaic, "meta": meta})

        assert origin_x is not None and origin_y is not None
        tracking = {
            str(int(threshold)): track_threshold(frames, threshold, origin_x, origin_y)
            for threshold in ALLOWED_EXACT_THRESHOLDS_MMPH
        }
        any_match = any(
            any(t["primary_match_count"] > 0 for t in block["transitions"])
            for block in tracking.values()
        )
        return {
            **base,
            "execution_ok": True,
            "scientific_tracking_proven": any_match,
            "discovery": discovery,
            "fixed_mosaic": {"zoom": TRACKING_ZOOM, "origin_tile_x": origin_x, "origin_tile_y": origin_y, "tile_count": 16},
            "frame_valid_times": [iso_utc(f["valid_dt"]) for f in frames],
            "frame_interval_seconds": 300,
            "tracking": tracking,
            "interpretation": "Temporal geometry evidence only. Association weights and overlap are not LPZ meteorological thresholds.",
            "limitations": [
                "Zero-overlap fast motion is conservatively treated as death plus birth in this first proof.",
                "Primary lineage is greedy one-to-one; candidate edges preserve split/merge evidence separately.",
                "A four-frame proof demonstrates mechanics only and does not establish LPZ persistence.",
            ],
            "gates": {
                "fixed_multiframe_mosaic": True,
                "component_tracking": any_match,
                "split_merge_evidence": True,
                "stationarity_threshold": False,
                "hirockawa_persistence": False,
                "backbuilding": False,
                "historical_validation": False,
                "risk_engine_allowed": False,
            },
        }
    except Exception as exc:
        return {
            **base,
            "execution_ok": False,
            "scientific_tracking_proven": False,
            "error": f"{type(exc).__name__}: {exc}",
            "gates": {"fixed_multiframe_mosaic": False, "component_tracking": False, "risk_engine_allowed": False},
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="reports/scientific/radar_tracking.json")
    args = parser.parse_args()
    report = run()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "execution_ok": report.get("execution_ok"),
        "scientific_tracking_proven": report.get("scientific_tracking_proven"),
        "frame_valid_times": report.get("frame_valid_times"),
        "gates": report.get("gates"),
    }, indent=2))
    print(f"report={path}")
    return 0 if report.get("execution_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
