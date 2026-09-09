#!/usr/bin/env python3
"""Phase 1C proof for JMA public precipitation PNG scientific class decoding.

JMA HRPN/RASRF display tiles are validated only on populated even zooms. The
proof waits for a settled frame, discovers real rain at z=6, then verifies the
same parent footprint at z=8 and z=10. Odd-zoom transparent placeholders are
not interpreted as meteorological no-rain.
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
VERIFY_ZOOMS = (8, 10)
REQUIRED_DISPLAY_ZOOM = 8
MIN_FRAME_AGE_MINUTES = 15
JAPAN_BBOX = {"west": 122.0, "east": 154.0, "south": 20.0, "north": 46.0}
MAX_FRAMES_PER_PRODUCT = 4
DISCOVERY_WORKERS = 4
VERIFY_WORKERS = 8


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_compact(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def http_get(url: str, max_bytes: int) -> tuple[bytes, int, int]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Cache-Control": "no-cache"})
    started = time.perf_counter()
    with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        status = int(getattr(response, "status", 200))
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError(f"response exceeded {max_bytes} byte limit")
    return body, status, int((time.perf_counter() - started) * 1000)


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
    return sorted(candidates, key=lambda r: (str(r.get("validtime", "")), str(r.get("basetime", ""))), reverse=True)


def settled_recent_rows(rows: list[dict[str, Any]], count: int, now: datetime) -> list[dict[str, Any]]:
    cutoff = now - timedelta(minutes=MIN_FRAME_AGE_MINUTES)
    eligible = [r for r in rows if parse_compact(str(r.get("validtime") or r.get("basetime"))) <= cutoff]
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
    basetime, validtime = str(row["basetime"]), str(row["validtime"])
    if product == "nowc":
        return f"https://www.jma.go.jp/bosai/jmatile/data/nowc/{basetime}/none/{validtime}/surf/hrpns/{z}/{x}/{y}.png"
    member = str(row.get("member") or "none")
    return f"https://www.jma.go.jp/bosai/jmatile/data/rasrf/{basetime}/{member}/{validtime}/surf/rasrf/{z}/{x}/{y}.png"


def japan_tile_indices(zoom: int) -> list[tuple[int, int]]:
    _, x0, y0 = lonlat_to_xyz(JAPAN_BBOX["west"], JAPAN_BBOX["north"], zoom)
    _, x1, y1 = lonlat_to_xyz(JAPAN_BBOX["east"], JAPAN_BBOX["south"], zoom)
    xa, xb = sorted((x0, x1)); ya, yb = sorted((y0, y1))
    return [(x, y) for y in range(ya, yb + 1) for x in range(xa, xb + 1)]


def inspect_tile(product: str, row: dict[str, Any], z: int, x: int, y: int) -> dict[str, Any]:
    url = tile_url(product, row, z, x, y)
    out: dict[str, Any] = {"z": z, "x": x, "y": y, "url": url}
    try:
        payload, status, latency = http_get(url, MAX_TILE_BYTES)
        decoded = decode_jma_precipitation_png(payload)
        mask = decoded.class_index >= 0
        count = int(np.count_nonzero(mask))
        seed = None
        max_idx = None
        if count:
            max_idx = int(np.max(decoded.class_index[mask]))
            py, px = map(int, np.argwhere(decoded.class_index == max_idx)[0])
            lon, lat = tile_pixel_center_lonlat(z, x, y, px, py)
            cls = JMA_PRECIPITATION_CLASSES[max_idx]
            seed = {
                "pixel_x": px, "pixel_y": py, "lon": lon, "lat": lat,
                "class_index": max_idx, "class_id": cls.class_id,
                "lower_mmph": cls.lower_mmph, "upper_mmph": cls.upper_mmph,
                "approx_display_pixel_area_km2": web_mercator_pixel_area_km2(lat, z),
            }
        out.update({
            "status": "PASS", "http_status": status, "latency_ms": latency,
            "bytes": len(payload), "known_precipitation_pixels": count,
            "unknown_opaque_pixels": decoded.unknown_opaque_pixel_count,
            "class_counts": decoded.class_counts(), "max_class_index": max_idx, "seed": seed,
        })
    except HTTPError as exc:
        out.update({"status": "MISSING_TILE", "http_status": exc.code, "error": str(exc)})
    except (URLError, TimeoutError, ValueError, OSError) as exc:
        out.update({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
    return out


def strongest(reports: list[dict[str, Any]]) -> dict[str, Any] | None:
    rainy = [r for r in reports if r.get("seed")]
    return max(rainy, key=lambda r: (int(r.get("max_class_index", -1)), int(r.get("known_precipitation_pixels", 0)))) if rainy else None


def inspect_parallel(product: str, row: dict[str, Any], zoom: int, tiles: list[tuple[int, int]], workers: int) -> list[dict[str, Any]]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda xy: inspect_tile(product, row, zoom, xy[0], xy[1]), tiles))


def discover(product: str, rows: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    tiles = japan_tile_indices(DISCOVERY_ZOOM)
    selected = settled_recent_rows(rows, MAX_FRAMES_PER_PRODUCT, now)
    frame_reports: list[dict[str, Any]] = []
    successes = 0; unknown = 0
    for row in selected:
        dt = parse_compact(str(row.get("validtime") or row.get("basetime")))
        reports = inspect_parallel(product, row, DISCOVERY_ZOOM, tiles, DISCOVERY_WORKERS)
        good = [r for r in reports if r.get("status") == "PASS"]
        successes += len(good); unknown += sum(int(r.get("unknown_opaque_pixels", 0)) for r in good)
        best = strongest(good)
        frame_reports.append({
            "basetime": row.get("basetime"), "validtime": row.get("validtime"),
            "frame_age_seconds": int((now - dt).total_seconds()), "tiles_attempted": len(reports),
            "tiles_pass": len(good), "tiles_with_precipitation": sum(bool(r.get("seed")) for r in good),
            "unknown_opaque_pixels": sum(int(r.get("unknown_opaque_pixels", 0)) for r in good),
            "strongest_class_index": None if best is None else best.get("max_class_index"),
        })
        if best:
            return {
                "found": True, "row": row, "frame_age_seconds": int((now - dt).total_seconds()),
                "seed": best["seed"], "seed_tile": {k: best[k] for k in ("z", "x", "y", "url")},
                "frame_reports": frame_reports, "successful_tiles": successes, "unknown_opaque_pixels": unknown,
            }
    return {
        "found": False, "row": selected[0] if selected else None, "seed": None, "seed_tile": None,
        "frame_reports": frame_reports, "successful_tiles": successes, "unknown_opaque_pixels": unknown,
        "reason": "no settled rainy frame found" if selected else "no frame old enough for settled proof",
    }


def verify_even_zoom_pyramid(product: str, row: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    current = dict(parent); levels: list[dict[str, Any]] = []
    highest = int(parent["z"]); unknown = 0; strongest_seed = None
    for target_zoom in VERIFY_ZOOMS:
        tiles = descendant_tile_indices(int(current["z"]), int(current["x"]), int(current["y"]), target_zoom)
        reports = inspect_parallel(product, row, target_zoom, tiles, VERIFY_WORKERS)
        good = [r for r in reports if r.get("status") == "PASS"]
        unknown_here = sum(int(r.get("unknown_opaque_pixels", 0)) for r in good); unknown += unknown_here
        best = strongest(good)
        levels.append({
            "zoom": target_zoom, "descendant_tiles_expected": len(tiles), "tiles_pass": len(good),
            "tiles_with_precipitation": sum(bool(r.get("seed")) for r in good),
            "unknown_opaque_pixels": unknown_here, "rain_observed": best is not None,
            "strongest_seed": None if best is None else best.get("seed"),
            "strongest_tile": None if best is None else {k: best[k] for k in ("z", "x", "y", "url")},
        })
        if best is None:
            break
        highest = target_zoom; strongest_seed = best.get("seed")
        current = {k: best[k] for k in ("z", "x", "y", "url")}
    return {
        "status": "PASS", "starting_parent_tile": {k: parent[k] for k in ("z", "x", "y", "url")},
        "verified_even_zooms": list(VERIFY_ZOOMS), "highest_zoom_with_precipitation_colour": highest,
        "required_display_zoom": REQUIRED_DISPLAY_ZOOM,
        "required_display_zoom_verified": highest >= REQUIRED_DISPLAY_ZOOM,
        "z10_precipitation_observed": highest >= 10, "unknown_opaque_pixels": unknown,
        "levels": levels, "strongest_verified_seed": strongest_seed,
        "odd_zoom_policy": "not requested: z5/z7/z9 are transparent placeholders in observed/current tile pyramid behaviour",
    }


def run() -> dict[str, Any]:
    generated = utc_now()
    palette = {str(c.rgb): {"class_id": c.class_id, "lower_mmph": c.lower_mmph, "upper_mmph": c.upper_mmph} for c in JMA_PRECIPITATION_CLASSES}
    try:
        nr, rr = load_json(NOWC_TIMES), load_json(RASRF_TIMES)
        if not isinstance(nr, list) or not isinstance(rr, list):
            raise ValueError("targetTimes payload was not a list")
        rows = {"nowc": current_rows("nowc", nr), "rasrf": current_rows("rasrf", rr)}
    except Exception as exc:
        return {"schema_version": "0.6.0", "phase": "1C-radar-scientific-decode-proof", "generated_at": iso_utc(generated), "execution_ok": False, "scientific_decode_proven": False, "error": f"{type(exc).__name__}: {exc}", "official_palette": palette, "gates": {"target_times": False, "risk_engine_allowed": False}}

    discovery: dict[str, Any] = {}; pyramid: dict[str, Any] = {}
    technical_failure = False; total_unknown = 0; success_tiles = 0
    for product in ("nowc", "rasrf"):
        found = discover(product, rows[product], generated); discovery[product] = found
        total_unknown += int(found.get("unknown_opaque_pixels", 0)); success_tiles += int(found.get("successful_tiles", 0))
        if found.get("found") and found.get("row") and found.get("seed_tile"):
            pyramid[product] = verify_even_zoom_pyramid(product, found["row"], found["seed_tile"])
            total_unknown += int(pyramid[product].get("unknown_opaque_pixels", 0))
        else:
            pyramid[product] = {"status": "NO_SETTLED_RAIN_SAMPLE", "required_display_zoom_verified": False, "z10_precipitation_observed": False}
        if found.get("frame_reports") and int(found.get("successful_tiles", 0)) == 0:
            technical_failure = True

    palette_observed = all(bool(discovery[p].get("found")) for p in ("nowc", "rasrf"))
    zoom8_verified = all(bool(pyramid[p].get("required_display_zoom_verified")) for p in ("nowc", "rasrf"))
    palette_integrity = total_unknown == 0
    transport = success_tiles > 0 and not technical_failure
    proven = transport and palette_integrity and palette_observed and zoom8_verified

    return {
        "schema_version": "0.6.0", "phase": "1C-radar-scientific-decode-proof",
        "generated_at": iso_utc(generated), "execution_ok": transport and palette_integrity,
        "scientific_decode_proven": proven,
        "metadata": {
            "latest_nowc_valid_time": iso_utc(parse_compact(str(rows["nowc"][0]["validtime"]))),
            "latest_rasrf_valid_time": iso_utc(parse_compact(str(rows["rasrf"][0]["validtime"]))),
            "minimum_settled_frame_age_minutes": MIN_FRAME_AGE_MINUTES,
            "discovery_zoom": DISCOVERY_ZOOM, "verified_even_zooms": list(VERIFY_ZOOMS),
            "required_display_zoom": REQUIRED_DISPLAY_ZOOM,
            "discovery_tile_count_per_frame": len(japan_tile_indices(DISCOVERY_ZOOM)), "bbox": JAPAN_BBOX,
        },
        "official_palette": palette, "discovery": discovery, "even_zoom_pyramid_verification": pyramid,
        "interpretation": {
            "public_png_semantics": "official precipitation colour intervals only",
            "exact_continuous_mmph": False, "transparent_pixels_as_zero": False,
            "odd_zoom_placeholders_are_not_no_rain": True,
            "required_zoom_is_display_validation_not_native_resolution": True,
        },
        "gates": {
            "target_times": True, "png_transport": transport, "official_palette_integrity": palette_integrity,
            "precipitation_palette_observed": palette_observed, "even_zoom8_verified": zoom8_verified,
            "precipitation_class_decode": proven, "continuous_mmph_recovery": False,
            "hirockawa_exact_3h_accumulation": False, "risk_engine_allowed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="reports/scientific/radar_scientific_decode.json")
    args = parser.parse_args(); report = run(); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"execution_ok": report.get("execution_ok"), "scientific_decode_proven": report.get("scientific_decode_proven"), "gates": report.get("gates")}, indent=2)); print(f"report={output}")
    return 0 if report.get("execution_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
