#!/usr/bin/env python3
"""Phase 1C live proof for public-PNG precipitation-object morphology.

The proof discovers a settled rainy JMA HRPN frame at z=6, expands the selected
parent tile to its 16 real-data z=8 descendants, stitches them into one
1024x1024 class mosaic, and extracts 30/50/80 mm/h precipitation objects.

This is NOT Hirockawa HRA reproduction: no continuous 3-hour accumulation or
persistence criterion is inferred from display PNG classes.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
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

from lpz_risk.radar_morphology import (  # noqa: E402
    ALLOWED_EXACT_THRESHOLDS_MMPH,
    extract_objects_from_mosaic,
)
from lpz_risk.radar_science import (  # noqa: E402
    decode_jma_precipitation_png,
    descendant_tile_indices,
    lonlat_to_xyz,
)

USER_AGENT = "lpz-risk-system/0.1.0 (+https://github.com/mijoken/lpz-risk-system)"
NOWC_TIMES = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"
TIMEOUT_SECONDS = 20
MAX_TILE_BYTES = 2 * 1024 * 1024
MIN_FRAME_AGE_MINUTES = 15
DISCOVERY_ZOOM = 6
MORPHOLOGY_ZOOM = 8
JAPAN_BBOX = {"west": 122.0, "east": 154.0, "south": 20.0, "north": 46.0}
MAX_FRAMES = 4
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


def settled_rows(rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    usable = [r for r in rows if "hrpns" in r.get("elements", [])]
    usable.sort(key=lambda r: str(r.get("validtime", "")), reverse=True)
    cutoff = now - timedelta(minutes=MIN_FRAME_AGE_MINUTES)
    selected: list[dict[str, Any]] = []
    last_dt: datetime | None = None
    for row in usable:
        dt = parse_compact(str(row["validtime"]))
        if dt > cutoff:
            continue
        if last_dt is None or (last_dt - dt).total_seconds() >= 1800:
            selected.append(row)
            last_dt = dt
        if len(selected) >= MAX_FRAMES:
            break
    return selected


def inspect_tile(row: dict[str, Any], z: int, x: int, y: int) -> dict[str, Any]:
    url = tile_url(row, z, x, y)
    try:
        decoded = decode_jma_precipitation_png(http_get(url, MAX_TILE_BYTES))
        valid = decoded.class_index >= 0
        max_class = int(np.max(decoded.class_index[valid])) if np.any(valid) else -1
        return {
            "ok": True,
            "z": z,
            "x": x,
            "y": y,
            "url": url,
            "class_index": decoded.class_index,
            "precipitation_pixels": int(np.count_nonzero(valid)),
            "unknown_opaque_pixels": decoded.unknown_opaque_pixel_count,
            "max_class_index": max_class,
        }
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return {"ok": False, "z": z, "x": x, "y": y, "url": url, "error": f"{type(exc).__name__}: {exc}"}


def inspect_many(row: dict[str, Any], z: int, tiles: list[tuple[int, int]]) -> list[dict[str, Any]]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(lambda xy: inspect_tile(row, z, xy[0], xy[1]), tiles))


def discover_parent(rows: list[dict[str, Any]], now: datetime) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    reports: list[dict[str, Any]] = []
    tiles = japan_tiles(DISCOVERY_ZOOM)
    for row in settled_rows(rows, now):
        inspected = inspect_many(row, DISCOVERY_ZOOM, tiles)
        good = [r for r in inspected if r.get("ok")]
        rainy = [r for r in good if int(r.get("precipitation_pixels", 0)) > 0]
        best = max(rainy, key=lambda r: (int(r["max_class_index"]), int(r["precipitation_pixels"]))) if rainy else None
        reports.append({
            "validtime": row["validtime"],
            "tiles_attempted": len(inspected),
            "tiles_ok": len(good),
            "tiles_with_precipitation": len(rainy),
            "unknown_opaque_pixels": sum(int(r.get("unknown_opaque_pixels", 0)) for r in good),
            "strongest_class_index": None if best is None else int(best["max_class_index"]),
        })
        if best is not None:
            return row, best, reports
    return None, None, reports


def build_z8_mosaic(row: dict[str, Any], parent: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    children = descendant_tile_indices(DISCOVERY_ZOOM, int(parent["x"]), int(parent["y"]), MORPHOLOGY_ZOOM)
    inspected = inspect_many(row, MORPHOLOGY_ZOOM, children)
    failures = [r for r in inspected if not r.get("ok")]
    unknown = sum(int(r.get("unknown_opaque_pixels", 0)) for r in inspected if r.get("ok"))
    if failures:
        raise RuntimeError(f"{len(failures)} z8 descendant tiles failed transport/decode")
    if unknown:
        raise RuntimeError(f"z8 mosaic contains {unknown} unknown opaque pixels")

    xs = sorted({x for x, _ in children})
    ys = sorted({y for _, y in children})
    if len(xs) != 4 or len(ys) != 4:
        raise RuntimeError(f"expected a 4x4 z8 descendant grid, got {len(xs)}x{len(ys)}")
    by_xy = {(int(r["x"]), int(r["y"])): r for r in inspected}
    mosaic = np.full((4 * 256, 4 * 256), -1, dtype=np.int8)
    for iy, y in enumerate(ys):
        for ix, x in enumerate(xs):
            arr = by_xy[(x, y)]["class_index"]
            mosaic[iy * 256:(iy + 1) * 256, ix * 256:(ix + 1) * 256] = arr
    meta = {
        "origin_tile_x": xs[0],
        "origin_tile_y": ys[0],
        "tile_count": len(inspected),
        "precipitation_pixels": int(np.count_nonzero(mosaic >= 0)),
        "max_class_index": int(np.max(mosaic[mosaic >= 0])) if np.any(mosaic >= 0) else -1,
        "unknown_opaque_pixels": unknown,
    }
    return mosaic, meta


def run() -> dict[str, Any]:
    now = utc_now()
    base = {
        "schema_version": "0.1.0",
        "phase": "1C-radar-morphology-proof",
        "generated_at": iso_utc(now),
        "feature_id": "live_precip_object_morphology_public_png",
        "paper_reproduction": False,
        "hirockawa_hra_exact": False,
        "thresholds_mmph": list(ALLOWED_EXACT_THRESHOLDS_MMPH),
    }
    try:
        rows = load_json(NOWC_TIMES)
        if not isinstance(rows, list):
            raise ValueError("targetTimes_N1.json was not a list")
        row, parent, discovery_reports = discover_parent(rows, now)
        if row is None or parent is None:
            return {
                **base,
                "execution_ok": True,
                "scientific_morphology_proven": False,
                "sample_status": "NO_SETTLED_RAIN_SAMPLE",
                "discovery_reports": discovery_reports,
                "gates": {
                    "transport_and_palette": True,
                    "z8_mosaic": False,
                    "object_geometry": False,
                    "hirockawa_exact_3h_hra": False,
                    "risk_engine_allowed": False,
                },
            }

        mosaic, mosaic_meta = build_z8_mosaic(row, parent)
        threshold_results: dict[str, Any] = {}
        any_object = False
        for threshold in ALLOWED_EXACT_THRESHOLDS_MMPH:
            objects = extract_objects_from_mosaic(
                mosaic,
                zoom=MORPHOLOGY_ZOOM,
                origin_tile_x=int(mosaic_meta["origin_tile_x"]),
                origin_tile_y=int(mosaic_meta["origin_tile_y"]),
                threshold_mmph=threshold,
                min_pixels=2,
            )
            any_object = any_object or bool(objects)
            threshold_results[str(int(threshold))] = {
                "object_count": len(objects),
                "objects": [obj.to_dict() for obj in objects[:25]],
                "largest_object": None if not objects else objects[0].to_dict(),
            }

        return {
            **base,
            "execution_ok": True,
            "scientific_morphology_proven": any_object,
            "sample_status": "OBJECTS_EXTRACTED" if any_object else "RAIN_PRESENT_BUT_NO_30PLUS_OBJECT",
            "frame": {
                "basetime": row["basetime"],
                "validtime": row["validtime"],
                "valid_time_utc": iso_utc(parse_compact(str(row["validtime"]))),
            },
            "discovery_parent": {k: parent[k] for k in ("z", "x", "y", "url", "precipitation_pixels", "max_class_index")},
            "discovery_reports": discovery_reports,
            "mosaic": mosaic_meta,
            "threshold_results": threshold_results,
            "method_notes": [
                "8-connected components on exact public-palette threshold masks",
                "area sums latitude-adjusted Web-Mercator pixel ground areas",
                "centroid is mean of member pixel-center lon/lat",
                "major/minor axes and orientation are PCA morphology descriptors, not Hirockawa definitions",
                "boundary_truncated flags objects touching the 4x4 z8 mosaic edge",
            ],
            "gates": {
                "transport_and_palette": True,
                "z8_mosaic": True,
                "object_geometry": any_object,
                "hirockawa_exact_3h_hra": False,
                "risk_engine_allowed": False,
            },
        }
    except Exception as exc:
        return {
            **base,
            "execution_ok": False,
            "scientific_morphology_proven": False,
            "error": f"{type(exc).__name__}: {exc}",
            "gates": {"transport_and_palette": False, "z8_mosaic": False, "object_geometry": False, "hirockawa_exact_3h_hra": False, "risk_engine_allowed": False},
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="reports/scientific/radar_morphology.json")
    args = parser.parse_args()
    report = run()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("execution_ok", "scientific_morphology_proven", "sample_status", "gates")}, indent=2))
    print(f"report={path}")
    return 0 if report.get("execution_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
