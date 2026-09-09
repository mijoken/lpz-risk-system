#!/usr/bin/env python3
"""Phase 1C proof for JMA public precipitation PNG scientific class decoding.

The proof searches a bounded Japan tile set for real precipitation colours,
then verifies the entire high-zoom descendant footprint of the rainy parent
tile. It never assumes that one low-zoom pixel centre remains rainy after map
resampling at a different zoom.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from datetime import datetime, timezone
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
VERIFY_ZOOM = 9
JAPAN_BBOX = {"west": 122.0, "east": 154.0, "south": 20.0, "north": 46.0}
MAX_FRAMES_PER_PRODUCT = 4
DISCOVERY_WORKERS = 4
VERIFY_WORKERS = 8


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_compact(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def http_get(url: str, max_bytes: int) -> tuple[bytes, int, int]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        },
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


def spaced_recent_rows(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    last_dt: datetime | None = None
    for row in rows:
        dt = parse_compact(str(row.get("validtime") or row.get("basetime")))
        if last_dt is None or (last_dt - dt).total_seconds() >= 30 * 60:
            chosen.append(row)
            last_dt = dt
        if len(chosen) >= count:
            break
    return chosen or rows[:1]


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


def _strongest_rainy_report(reports: list[dict[str, Any]]) -> dict[str, Any] | None:
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


def discover_rain_seed(product: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    tiles = japan_tile_indices(DISCOVERY_ZOOM)
    selected_rows = spaced_recent_rows(rows, MAX_FRAMES_PER_PRODUCT)
    frame_reports: list[dict[str, Any]] = []
    total_unknown = 0
    successful_tiles = 0

    for row in selected_rows:
        reports: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=DISCOVERY_WORKERS) as pool:
            futures = [
                pool.submit(inspect_tile, product, row, DISCOVERY_ZOOM, x, y)
                for x, y in tiles
            ]
            for future in concurrent.futures.as_completed(futures):
                report = future.result()
                reports.append(report)
                if report.get("status") == "PASS":
                    successful_tiles += 1
                    total_unknown += int(report.get("unknown_opaque_pixels", 0))

        strongest = _strongest_rainy_report(reports)
        rainy_count = sum(bool(r.get("seed")) for r in reports)
        frame_reports.append(
            {
                "basetime": row.get("basetime"),
                "validtime": row.get("validtime"),
                "tiles_attempted": len(reports),
                "tiles_pass": sum(r.get("status") == "PASS" for r in reports),
                "tiles_with_precipitation": rainy_count,
                "unknown_opaque_pixels": sum(int(r.get("unknown_opaque_pixels", 0)) for r in reports),
                "strongest_class_index": None if strongest is None else strongest.get("max_class_index"),
            }
        )
        if strongest is not None:
            return {
                "found": True,
                "row": row,
                "seed": strongest["seed"],
                "seed_tile": {k: strongest[k] for k in ("z", "x", "y", "url")},
                "frame_reports": frame_reports,
                "successful_tiles": successful_tiles,
                "unknown_opaque_pixels": total_unknown,
            }

    return {
        "found": False,
        "row": selected_rows[0] if selected_rows else None,
        "seed": None,
        "seed_tile": None,
        "frame_reports": frame_reports,
        "successful_tiles": successful_tiles,
        "unknown_opaque_pixels": total_unknown,
    }


def verify_parent_descendants(
    product: str,
    row: dict[str, Any],
    parent_tile: dict[str, Any],
) -> dict[str, Any]:
    children = descendant_tile_indices(
        int(parent_tile["z"]),
        int(parent_tile["x"]),
        int(parent_tile["y"]),
        VERIFY_ZOOM,
    )
    reports: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as pool:
        futures = [
            pool.submit(inspect_tile, product, row, VERIFY_ZOOM, x, y)
            for x, y in children
        ]
        for future in concurrent.futures.as_completed(futures):
            reports.append(future.result())

    successful = [r for r in reports if r.get("status") == "PASS"]
    strongest = _strongest_rainy_report(successful)
    aggregate_classes: dict[str, int] = {}
    for report in successful:
        for class_id, count in report.get("class_counts", {}).items():
            aggregate_classes[class_id] = aggregate_classes.get(class_id, 0) + int(count)

    output: dict[str, Any] = {
        "status": "PASS" if successful else "FAIL",
        "parent_tile": {k: parent_tile[k] for k in ("z", "x", "y", "url")},
        "verification_zoom": VERIFY_ZOOM,
        "child_tiles_expected": len(children),
        "child_tiles_pass": len(successful),
        "child_tiles_with_precipitation": sum(bool(r.get("seed")) for r in successful),
        "unknown_opaque_pixels": sum(int(r.get("unknown_opaque_pixels", 0)) for r in successful),
        "class_counts": aggregate_classes,
        "rain_verified": strongest is not None,
        "strongest_seed": None if strongest is None else strongest.get("seed"),
        "strongest_tile": None if strongest is None else {k: strongest[k] for k in ("z", "x", "y", "url")},
        "note": (
            "The full z=9 descendant footprint is checked. A low-zoom pixel centre is not assumed "
            "to remain rainy after resampling. z=9 is a display-tile verification, not a claim "
            "that every tile pixel is a native radar cell."
        ),
    }
    if strongest and strongest.get("seed"):
        output["approx_pixel_area_km2_at_strongest_seed_lat"] = web_mercator_pixel_area_km2(
            float(strongest["seed"]["lat"]), VERIFY_ZOOM
        )
    return output


def run() -> dict[str, Any]:
    generated = datetime.now(timezone.utc)
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
            "schema_version": "0.3.0",
            "phase": "1C-radar-scientific-decode-proof",
            "generated_at": iso_utc(generated),
            "execution_ok": False,
            "scientific_decode_proven": False,
            "error": f"{type(exc).__name__}: {exc}",
            "official_palette": official_palette,
            "gates": {
                "target_times": False,
                "png_transport": False,
                "official_palette_integrity": False,
                "precipitation_palette_observed": False,
                "high_zoom_descendant_verification": False,
                "continuous_mmph_recovery": False,
                "risk_engine_allowed": False,
            },
        }

    discovery: dict[str, Any] = {}
    high_zoom: dict[str, Any] = {}
    technical_failure = False
    total_unknown = 0
    total_success_tiles = 0

    for product in ("nowc", "rasrf"):
        found = discover_rain_seed(product, product_rows[product])
        discovery[product] = found
        total_unknown += int(found.get("unknown_opaque_pixels", 0))
        total_success_tiles += int(found.get("successful_tiles", 0))
        if found.get("found") and found.get("row") and found.get("seed_tile"):
            high_zoom[product] = verify_parent_descendants(product, found["row"], found["seed_tile"])
            total_unknown += int(high_zoom[product].get("unknown_opaque_pixels", 0))
        else:
            high_zoom[product] = {"status": "NO_RAIN_SAMPLE", "rain_verified": False}
        if int(found.get("successful_tiles", 0)) == 0:
            technical_failure = True

    palette_observed = all(bool(discovery[p].get("found")) for p in ("nowc", "rasrf"))
    high_zoom_verified = all(bool(high_zoom[p].get("rain_verified")) for p in ("nowc", "rasrf"))
    palette_integrity = total_unknown == 0
    transport_gate = total_success_tiles > 0 and not technical_failure
    scientific_decode_proven = transport_gate and palette_integrity and palette_observed and high_zoom_verified

    latest_nowc = parse_compact(str(product_rows["nowc"][0]["validtime"]))
    latest_rasrf = parse_compact(str(product_rows["rasrf"][0]["validtime"]))

    return {
        "schema_version": "0.3.0",
        "phase": "1C-radar-scientific-decode-proof",
        "generated_at": iso_utc(generated),
        "execution_ok": transport_gate and palette_integrity,
        "scientific_decode_proven": scientific_decode_proven,
        "metadata": {
            "latest_nowc_valid_time": iso_utc(latest_nowc),
            "latest_rasrf_valid_time": iso_utc(latest_rasrf),
            "discovery_zoom": DISCOVERY_ZOOM,
            "verification_zoom": VERIFY_ZOOM,
            "discovery_tile_count_per_frame": len(japan_tile_indices(DISCOVERY_ZOOM)),
            "verification_child_tiles_per_parent": len(descendant_tile_indices(DISCOVERY_ZOOM, 0, 0, VERIFY_ZOOM)),
            "max_frames_per_product": MAX_FRAMES_PER_PRODUCT,
            "bbox": JAPAN_BBOX,
        },
        "official_palette": official_palette,
        "discovery": discovery,
        "high_zoom_verification": high_zoom,
        "interpretation": {
            "public_png_semantics": "official precipitation colour intervals only",
            "exact_continuous_mmph": False,
            "transparent_pixels_as_zero": False,
            "no_rain_sample_is_technical_failure": False,
            "reason": (
                "The public PNG is a display-class product. LPZ-RISK preserves bucket bounds, "
                "does not invent midpoints, and verifies cross-zoom colour evidence over the full descendant footprint."
            ),
        },
        "gates": {
            "target_times": True,
            "png_transport": transport_gate,
            "official_palette_integrity": palette_integrity,
            "precipitation_palette_observed": palette_observed,
            "high_zoom_descendant_verification": high_zoom_verified,
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
    print(
        json.dumps(
            {
                "execution_ok": report.get("execution_ok"),
                "scientific_decode_proven": report.get("scientific_decode_proven"),
                "gates": report.get("gates"),
            },
            indent=2,
        )
    )
    print(f"report={output}")
    return 0 if report.get("execution_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
