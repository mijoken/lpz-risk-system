#!/usr/bin/env python3
"""Phase 1C proof for JMA public precipitation PNG scientific class decoding.

The public JMA tiles are display products. The proof deliberately uses a
settled frame (not the just-announced latest target time), discovers a real
rainy parent tile, and follows its four Web-Mercator children one zoom at a
time. This separates scientific tile semantics from upstream generation/CDN
latency.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
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

from lpz_risk.radar_science import (  # noqa: E402
    JMA_PRECIPITATION_CLASSES,
    decode_jma_precipitation_png,
    descendant_tile_indices,
    lonlat_to_xyz,
    tile_pixel_center_lonlat,
    web_mercator_pixel_area_km2,
)

USER_AGENT = "lpz-risk-system/0.1.0 (+https://github.com/mijoken/lpz-risk-system)"
TIMEOUT_SECONDS = 20
MAX_TILE_BYTES = 2 * 1024 * 1024
NOWC_TIMES = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"
RASRF_TIMES = "https://www.jma.go.jp/bosai/jmatile/data/rasrf/targetTimes.json"

DISCOVERY_ZOOM = 6
VERIFY_ZOOMS = (7, 8, 9, 10)
REQUIRED_DISPLAY_ZOOM = 8
MIN_FRAME_AGE_MINUTES = 15
JAPAN_BBOX = {"west": 122.0, "east": 154.0, "south": 20.0, "north": 46.0}
MAX_FRAMES_PER_PRODUCT = 4
DISCOVERY_WORKERS = 4
VERIFY_WORKERS = 4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_compact(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def http_get(url: str, max_bytes: int) -> tuple[bytes, int, int]:
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Cache-Control": "no-cache"},
    )
    started = time.perf_counter()
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        status = int(getattr(response, "status", 200))
        body = response.read(max_bytes + 1)
    latency_ms = int((time.perf_counter() - started) * 1000)
    if len(body) > max_bytes:
        raise ValueError(f"response exceeded {max_bytes} byte limit")
    return body, status, latency_ms


def load_json(url: str) -> Any:
    body, _, _ = http_get(url, 2 * 1024 * 1024)
    return json.loads(body.decode("utf-8"))


def current_rows(product: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if product == "nowc":
        candidates = [r for r in rows if "hrpns" in r.get("elements", [])]
    elif product == "rasrf":
        candidates = [
            r for r in rows
            if "rasrf" in r.get("elements", [])
            and str(r.get("validtime", "")) == str(r.get("basetime", ""))
        ]
    else:
        raise ValueError(f"unknown product: {product}")
    if not candidates:
        raise ValueError(f"no usable targetTimes rows for {product}")
    return sorted(
        candidates,
        key=lambda r: (str(r.get("validtime", "")), str(r.get("basetime", ""))),
        reverse=True,
    )


def settled_recent_rows(
    rows: list[dict[str, Any]],
    count: int,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Choose recent frames old enough that tile-generation latency is unlikely."""
    reference = (now or utc_now()).astimezone(timezone.utc)
    cutoff = reference - timedelta(minutes=MIN_FRAME_AGE_MINUTES)
    eligible = [
        row for row in rows
        if parse_compact(str(row.get("validtime") or row.get("basetime"))) <= cutoff
    ]
    if not eligible:
        return []

    chosen: list[dict[str, Any]] = []
    last_dt: datetime | None = None
    for row in eligible:
        dt = parse_compact(str(row.get("validtime") or row.get("basetime")))
        if last_dt is None or (last_dt - dt).total_seconds() >= 1800:
            chosen.append(row)
            last_dt = dt
        if len(chosen) >= count:
            break
    return chosen


def tile_url(product: str, row: dict[str, Any], z: int, x: int, y: int) -> str:
    basetime = str(row["basetime"])
    validtime = str(row["validtime"])
    if product == "nowc":
        return (
            "https://www.jma.go.jp/bosai/jmatile/data/nowc/"
            f"{basetime}/none/{validtime}/surf/hrpns/{z}/{x}/{y}.png"
        )
    member = str(row.get("member") or "immed")
    return (
        "https://www.jma.go.jp/bosai/jmatile/data/rasrf/"
        f"{basetime}/{member}/{validtime}/surf/rasrf/{z}/{x}/{y}.png"
    )


def japan_tile_indices(zoom: int) -> list[tuple[int, int]]:
    _, west_x, north_y = lonlat_to_xyz(JAPAN_BBOX["west"], JAPAN_BBOX["north"], zoom)
    _, east_x, south_y = lonlat_to_xyz(JAPAN_BBOX["east"], JAPAN_BBOX["south"], zoom)
    x0, x1 = sorted((west_x, east_x))
    y0, y1 = sorted((north_y, south_y))
    return [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]


def inspect_tile(product: str, row: dict[str, Any], z: int, x: int, y: int) -> dict[str, Any]:
    url = tile_url(product, row, z, x, y)
    result: dict[str, Any] = {"z": z, "x": x, "y": y, "url": url}
    try:
        payload, status, latency = http_get(url, MAX_TILE_BYTES)
        decoded = decode_jma_precipitation_png(payload)
        precip_mask = decoded.class_index >= 0
        known_count = int(np.count_nonzero(precip_mask))
        seed = None
        max_class_index = None
        if known_count:
            max_class_index = int(np.max(decoded.class_index[precip_mask]))
            py, px = map(int, np.argwhere(decoded.class_index == max_class_index)[0])
            lon, lat = tile_pixel_center_lonlat(z, x, y, px, py)
            cls = JMA_PRECIPITATION_CLASSES[max_class_index]
            seed = {
                "pixel_x": px,
                "pixel_y": py,
                "lon": lon,
                "lat": lat,
                "class_index": max_class_index,
                "class_id": cls.class_id,
                "lower_mmph": cls.lower_mmph,
                "upper_mmph": cls.upper_mmph,
                "approx_display_pixel_area_km2": web_mercator_pixel_area_km2(lat, z),
            }
        result.update(
            {
                "status": "PASS",
                "http_status": status,
                "latency_ms": latency,
                "bytes": len(payload),
                "known_precipitation_pixels": known_count,
                "unknown_opaque_pixels": decoded.unknown_opaque_pixel_count,
                "class_counts": decoded.class_counts(),
                "max_class_index": max_class_index,
                "seed": seed,
            }
        )
    except HTTPError as exc:
        result.update({"status": "MISSING_TILE", "http_status": exc.code, "error": str(exc)})
    except (URLError, TimeoutError, ValueError, OSError) as exc:
        result.update({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
    return result


def strongest_rainy_report(reports: list[dict[str, Any]]) -> dict[str, Any] | None:
    rainy = [r for r in reports if r.get("seed")]
    if not rainy:
        return None
    return max(
        rainy,
        key=lambda r: (
            int(r.get("max_class_index") if r.get("max_class_index") is not None else -1),
            int(r.get("known_precipitation_pixels", 0)),
        ),
    )


def inspect_tiles_parallel(
    product: str,
    row: dict[str, Any],
    zoom: int,
    tiles: list[tuple[int, int]],
    workers: int,
) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(inspect_tile, product, row, zoom, x, y) for x, y in tiles]
        for future in concurrent.futures.as_completed(futures):
            reports.append(future.result())
    return reports


def discover_rain_seed(product: str, rows: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    tiles = japan_tile_indices(DISCOVERY_ZOOM)
    selected_rows = settled_recent_rows(rows, MAX_FRAMES_PER_PRODUCT, now=now)
    frame_reports: list[dict[str, Any]] = []
    total_unknown = 0
    successful_tiles = 0

    for row in selected_rows:
        frame_dt = parse_compact(str(row.get("validtime") or row.get("basetime")))
        reports = inspect_tiles_parallel(product, row, DISCOVERY_ZOOM, tiles, DISCOVERY_WORKERS)
        successful = [r for r in reports if r.get("status") == "PASS"]
        successful_tiles += len(successful)
        total_unknown += sum(int(r.get("unknown_opaque_pixels", 0)) for r in successful)
        strongest = strongest_rainy_report(successful)
        frame_reports.append(
            {
                "basetime": row.get("basetime"),
                "validtime": row.get("validtime"),
                "frame_age_seconds": int((now - frame_dt).total_seconds()),
                "tiles_attempted": len(reports),
                "tiles_pass": len(successful),
                "tiles_with_precipitation": sum(bool(r.get("seed")) for r in successful),
                "unknown_opaque_pixels": sum(int(r.get("unknown_opaque_pixels", 0)) for r in successful),
                "strongest_class_index": None if strongest is None else strongest.get("max_class_index"),
            }
        )
        if strongest is not None:
            return {
                "found": True,
                "row": row,
                "frame_age_seconds": int((now - frame_dt).total_seconds()),
                "seed": strongest["seed"],
                "seed_tile": {k: strongest[k] for k in ("z", "x", "y", "url")},
                "frame_reports": frame_reports,
                "successful_tiles": successful_tiles,
                "unknown_opaque_pixels": total_unknown,
            }

    return {
        "found": False,
        "row": selected_rows[0] if selected_rows else None,
        "frame_age_seconds": None,
        "seed": None,
        "seed_tile": None,
        "frame_reports": frame_reports,
        "successful_tiles": successful_tiles,
        "unknown_opaque_pixels": total_unknown,
        "reason": "no settled rainy frame found" if selected_rows else "no frame old enough for settled proof",
    }


def verify_zoom_hierarchy(product: str, row: dict[str, Any], parent_tile: dict[str, Any]) -> dict[str, Any]:
    current = dict(parent_tile)
    levels: list[dict[str, Any]] = []
    highest_rain_zoom = int(parent_tile["z"])
    total_unknown = 0
    strongest_overall: dict[str, Any] | None = None

    for target_zoom in VERIFY_ZOOMS:
        children = descendant_tile_indices(
            int(current["z"]), int(current["x"]), int(current["y"]), target_zoom
        )
        reports = inspect_tiles_parallel(product, row, target_zoom, children, VERIFY_WORKERS)
        successful = [r for r in reports if r.get("status") == "PASS"]
        total_unknown += sum(int(r.get("unknown_opaque_pixels", 0)) for r in successful)
        strongest = strongest_rainy_report(successful)
        levels.append(
            {
                "zoom": target_zoom,
                "child_tiles_expected": len(children),
                "child_tiles_pass": len(successful),
                "child_tiles_with_precipitation": sum(bool(r.get("seed")) for r in successful),
                "unknown_opaque_pixels": sum(int(r.get("unknown_opaque_pixels", 0)) for r in successful),
                "rain_observed": strongest is not None,
                "strongest_seed": None if strongest is None else strongest.get("seed"),
                "strongest_tile": None if strongest is None else {k: strongest[k] for k in ("z", "x", "y", "url")},
            }
        )
        if strongest is None:
            break
        highest_rain_zoom = target_zoom
        strongest_overall = strongest
        current = {k: strongest[k] for k in ("z", "x", "y", "url")}

    return {
        "status": "PASS",
        "starting_parent_tile": {k: parent_tile[k] for k in ("z", "x", "y", "url")},
        "required_display_zoom": REQUIRED_DISPLAY_ZOOM,
        "highest_zoom_with_precipitation_colour": highest_rain_zoom,
        "required_display_zoom_verified": highest_rain_zoom >= REQUIRED_DISPLAY_ZOOM,
        "z10_precipitation_observed": highest_rain_zoom >= 10,
        "unknown_opaque_pixels": total_unknown,
        "levels": levels,
        "strongest_verified_seed": None if strongest_overall is None else strongest_overall.get("seed"),
        "note": (
            "Cross-zoom verification follows only the strongest rainy child at each level. "
            "A missing higher-zoom rain tile is recorded as upstream availability behaviour."
        ),
    }


def run() -> dict[str, Any]:
    generated = utc_now()
    official_palette = {
        str(cls.rgb): {
            "class_id": cls.class_id,
            "lower_mmph": cls.lower_mmph,
            "upper_mmph": cls.upper_mmph,
        }
        for cls in JMA_PRECIPITATION_CLASSES
    }

    try:
        nowc_rows_raw = load_json(NOWC_TIMES)
        rasrf_rows_raw = load_json(RASRF_TIMES)
        if not isinstance(nowc_rows_raw, list) or not isinstance(rasrf_rows_raw, list):
            raise ValueError("targetTimes payload was not a list")
        product_rows = {
            "nowc": current_rows("nowc", nowc_rows_raw),
            "rasrf": current_rows("rasrf", rasrf_rows_raw),
        }
    except Exception as exc:
        return {
            "schema_version": "0.5.0",
            "phase": "1C-radar-scientific-decode-proof",
            "generated_at": iso_utc(generated),
            "execution_ok": False,
            "scientific_decode_proven": False,
            "error": f"{type(exc).__name__}: {exc}",
            "official_palette": official_palette,
            "gates": {"target_times": False, "risk_engine_allowed": False},
        }

    discovery: dict[str, Any] = {}
    hierarchy: dict[str, Any] = {}
    technical_failure = False
    total_unknown = 0
    total_success_tiles = 0

    for product in ("nowc", "rasrf"):
        found = discover_rain_seed(product, product_rows[product], generated)
        discovery[product] = found
        total_unknown += int(found.get("unknown_opaque_pixels", 0))
        total_success_tiles += int(found.get("successful_tiles", 0))
        if found.get("found") and found.get("row") and found.get("seed_tile"):
            hierarchy[product] = verify_zoom_hierarchy(product, found["row"], found["seed_tile"])
            total_unknown += int(hierarchy[product].get("unknown_opaque_pixels", 0))
        else:
            hierarchy[product] = {
                "status": "NO_SETTLED_RAIN_SAMPLE",
                "required_display_zoom_verified": False,
                "z10_precipitation_observed": False,
            }
        if found.get("frame_reports") and int(found.get("successful_tiles", 0)) == 0:
            technical_failure = True

    palette_observed = all(bool(discovery[p].get("found")) for p in ("nowc", "rasrf"))
    hierarchy_verified = all(
        bool(hierarchy[p].get("required_display_zoom_verified")) for p in ("nowc", "rasrf")
    )
    palette_integrity = total_unknown == 0
    transport_gate = total_success_tiles > 0 and not technical_failure
    scientific_decode_proven = transport_gate and palette_integrity and palette_observed and hierarchy_verified

    latest_nowc = parse_compact(str(product_rows["nowc"][0]["validtime"]))
    latest_rasrf = parse_compact(str(product_rows["rasrf"][0]["validtime"]))

    return {
        "schema_version": "0.5.0",
        "phase": "1C-radar-scientific-decode-proof",
        "generated_at": iso_utc(generated),
        "execution_ok": transport_gate and palette_integrity,
        "scientific_decode_proven": scientific_decode_proven,
        "metadata": {
            "latest_nowc_valid_time": iso_utc(latest_nowc),
            "latest_rasrf_valid_time": iso_utc(latest_rasrf),
            "minimum_settled_frame_age_minutes": MIN_FRAME_AGE_MINUTES,
            "discovery_zoom": DISCOVERY_ZOOM,
            "verify_zooms": list(VERIFY_ZOOMS),
            "required_display_zoom": REQUIRED_DISPLAY_ZOOM,
            "discovery_tile_count_per_frame": len(japan_tile_indices(DISCOVERY_ZOOM)),
            "max_frames_per_product": MAX_FRAMES_PER_PRODUCT,
            "bbox": JAPAN_BBOX,
        },
        "official_palette": official_palette,
        "discovery": discovery,
        "zoom_hierarchy_verification": hierarchy,
        "interpretation": {
            "public_png_semantics": "official precipitation colour intervals only",
            "exact_continuous_mmph": False,
            "transparent_pixels_as_zero": False,
            "settled_frame_used_for_science_proof": True,
            "required_zoom_is_display_validation_not_native_resolution": True,
            "reason": (
                "The public PNG is a display-class product. The proof waits for upstream settling, "
                "preserves bucket bounds, and records actual cross-zoom availability."
            ),
        },
        "gates": {
            "target_times": True,
            "png_transport": transport_gate,
            "official_palette_integrity": palette_integrity,
            "precipitation_palette_observed": palette_observed,
            "display_zoom8_hierarchy_verified": hierarchy_verified,
            "precipitation_class_decode": scientific_decode_proven,
            "continuous_mmph_recovery": False,
            "hirockawa_exact_3h_accumulation": False,
            "risk_engine_allowed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="reports/scientific/radar_scientific_decode.json")
    args = parser.parse_args()

    report = run()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "execution_ok": report.get("execution_ok"),
        "scientific_decode_proven": report.get("scientific_decode_proven"),
        "gates": report.get("gates"),
    }, indent=2))
    print(f"report={output}")
    return 0 if report.get("execution_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
