#!/usr/bin/env python3
"""Build lightweight public rain-overlay frames from JMA HRPN display tiles.

The product is DISPLAY ONLY. It uses the official JMA precipitation colour
classes already validated by the project, preserves them as categorical colour
intervals, and never feeds the scientific LPZ model.

Default policy:
- JMA High-Resolution Precipitation Nowcast (hrpns)
- settled frame lag: 15 minutes
- national display zoom: z=6 (49 tiles over the configured Japan view)
- five frames at >=15-minute spacing (~1 hour)
- transparent categorical PNGs aligned to the public map Mercator viewport
"""
from __future__ import annotations

import argparse
import concurrent.futures
import io
import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.radar_science import JMA_PRECIPITATION_CLASSES, decode_jma_precipitation_png  # noqa: E402

USER_AGENT = "lpz-risk-system/0.1.0 (+https://github.com/mijoken/lpz-risk-system)"
TARGET_TIMES = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"
ZOOM = 6
TILE_SIZE = 256
TIMEOUT_SECONDS = 20
MAX_TILE_BYTES = 2 * 1024 * 1024
MAX_WORKERS = 8
RETRIES = 2

# Must match web/js/map.js VIEW geographic bounds. The overlay image covers
# only the inner geographic viewport; SVG padding is applied by JavaScript.
BOUNDS = {
    "west": 122.0,
    "east": 154.5,
    "south": 20.0,
    "north": 46.5,
}
OUTPUT_WIDTH = 1144
OUTPUT_HEIGHT = 704

# Weak precipitation stays translucent; intense precipitation remains vivid.
CLASS_ALPHA = np.asarray([70, 105, 130, 155, 185, 205, 225, 240], dtype=np.uint8)


def utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_compact(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def http_get(url: str, max_bytes: int) -> bytes:
    last_error: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "*/*",
                    "Cache-Control": "no-cache",
                },
            )
            with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
                body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError(f"response exceeded {max_bytes} bytes")
            return body
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
            if attempt < RETRIES:
                time.sleep(0.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


def load_target_times() -> list[dict[str, Any]]:
    payload = http_get(TARGET_TIMES, 2 * 1024 * 1024)
    rows = json.loads(payload.decode("utf-8"))
    if not isinstance(rows, list):
        raise ValueError("JMA targetTimes_N1.json was not a list")
    usable = [
        row
        for row in rows
        if isinstance(row, dict) and "hrpns" in row.get("elements", [])
    ]
    if not usable:
        raise ValueError("JMA targetTimes_N1.json contained no hrpns rows")
    return usable


def select_frames(
    rows: list[dict[str, Any]],
    *,
    now: datetime,
    settled_lag_minutes: int,
    frame_count: int,
    frame_spacing_minutes: int,
) -> list[dict[str, Any]]:
    cutoff = now - timedelta(minutes=settled_lag_minutes)
    ordered = sorted(
        rows,
        key=lambda row: str(row.get("validtime") or row.get("basetime") or ""),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    previous_dt: datetime | None = None
    spacing = timedelta(minutes=frame_spacing_minutes)

    for row in ordered:
        raw = str(row.get("validtime") or row.get("basetime") or "")
        if not raw:
            continue
        dt = parse_compact(raw)
        if dt > cutoff:
            continue
        if previous_dt is not None and previous_dt - dt < spacing:
            continue
        selected.append(row)
        previous_dt = dt
        if len(selected) >= frame_count:
            break

    # Public animation should run oldest -> newest.
    selected.reverse()
    return selected


def global_pixel(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    n = 2**zoom
    x = (lon + 180.0) / 360.0 * n * TILE_SIZE
    lat_rad = math.radians(max(-85.05112878, min(85.05112878, lat)))
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n * TILE_SIZE
    return x, y


def tile_bounds(zoom: int) -> tuple[int, int, int, int]:
    left, top = global_pixel(BOUNDS["west"], BOUNDS["north"], zoom)
    right, bottom = global_pixel(BOUNDS["east"], BOUNDS["south"], zoom)
    return (
        int(math.floor(left / TILE_SIZE)),
        int(math.floor(right / TILE_SIZE)),
        int(math.floor(top / TILE_SIZE)),
        int(math.floor(bottom / TILE_SIZE)),
    )


def tile_url(row: dict[str, Any], z: int, x: int, y: int) -> str:
    basetime = str(row["basetime"])
    validtime = str(row["validtime"])
    return (
        "https://www.jma.go.jp/bosai/jmatile/data/nowc/"
        f"{basetime}/none/{validtime}/surf/hrpns/{z}/{x}/{y}.png"
    )


def display_tile(payload: bytes) -> tuple[Image.Image, int, int]:
    decoded = decode_jma_precipitation_png(payload)
    known = decoded.class_index >= 0
    rgba = np.zeros((decoded.height, decoded.width, 4), dtype=np.uint8)
    if np.any(known):
        rgba[:, :, :3][known] = decoded.rgba[:, :, :3][known]
        idx = decoded.class_index[known].astype(np.int64)
        rgba[:, :, 3][known] = CLASS_ALPHA[idx]
    image = Image.fromarray(rgba, mode="RGBA")
    return image, int(np.count_nonzero(known)), decoded.unknown_opaque_pixel_count


def fetch_tile(row: dict[str, Any], x: int, y: int) -> dict[str, Any]:
    url = tile_url(row, ZOOM, x, y)
    try:
        payload = http_get(url, MAX_TILE_BYTES)
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("tile did not contain PNG signature")
        image, precip_pixels, unknown = display_tile(payload)
        return {
            "x": x,
            "y": y,
            "status": "PASS",
            "image": image,
            "precip_pixels": precip_pixels,
            "unknown_opaque_pixels": unknown,
        }
    except Exception as exc:
        return {
            "x": x,
            "y": y,
            "status": "FAIL",
            "image": None,
            "precip_pixels": 0,
            "unknown_opaque_pixels": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }


def render_frame(row: dict[str, Any], output: Path) -> dict[str, Any]:
    x0, x1, y0, y1 = tile_bounds(ZOOM)
    coordinates = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        reports = list(pool.map(lambda xy: fetch_tile(row, xy[0], xy[1]), coordinates))

    mosaic = Image.new(
        "RGBA",
        ((x1 - x0 + 1) * TILE_SIZE, (y1 - y0 + 1) * TILE_SIZE),
        (0, 0, 0, 0),
    )
    for report in reports:
        image = report.get("image")
        if image is None:
            continue
        mosaic.alpha_composite(
            image,
            dest=((int(report["x"]) - x0) * TILE_SIZE, (int(report["y"]) - y0) * TILE_SIZE),
        )

    left_global, top_global = global_pixel(BOUNDS["west"], BOUNDS["north"], ZOOM)
    right_global, bottom_global = global_pixel(BOUNDS["east"], BOUNDS["south"], ZOOM)
    origin_x = x0 * TILE_SIZE
    origin_y = y0 * TILE_SIZE
    crop = (
        max(0, int(math.floor(left_global - origin_x))),
        max(0, int(math.floor(top_global - origin_y))),
        min(mosaic.width, int(math.ceil(right_global - origin_x))),
        min(mosaic.height, int(math.ceil(bottom_global - origin_y))),
    )
    image = mosaic.crop(crop).resize(
        (OUTPUT_WIDTH, OUTPUT_HEIGHT),
        resample=Image.Resampling.NEAREST,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)

    passed = sum(report["status"] == "PASS" for report in reports)
    expected = len(reports)
    completion = passed / expected if expected else 0.0
    precip_pixels = sum(int(report["precip_pixels"]) for report in reports)
    unknown = sum(int(report["unknown_opaque_pixels"]) for report in reports)
    errors = [report.get("error") for report in reports if report["status"] != "PASS"]

    return {
        "tiles_expected": expected,
        "tiles_pass": passed,
        "tile_completion_ratio": round(completion, 6),
        "precipitation_pixels_at_source_zoom": precip_pixels,
        "unknown_opaque_pixels": unknown,
        "errors": errors[:8],
    }


def legend() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in JMA_PRECIPITATION_CLASSES:
        if item.upper_mmph is None:
            label = f"{item.lower_mmph:g}+ mm/h"
        else:
            label = f"{item.lower_mmph:g}–{item.upper_mmph:g} mm/h"
        result.append(
            {
                "class_id": item.class_id,
                "lower_mmph": item.lower_mmph,
                "upper_mmph": item.upper_mmph,
                "rgb": list(item.rgb),
                "label": label,
            }
        )
    return result


def unavailable_manifest(generated: datetime, message: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "product": "LPZ_PUBLIC_RAIN_OVERLAY",
        "generated_at_utc": iso_utc(generated),
        "status": "UNAVAILABLE",
        "source": {
            "provider": "Japan Meteorological Agency",
            "product": "High-Resolution Precipitation Nowcast",
            "element": "hrpns",
            "display_mode": "settled observation/analysis display frame",
            "source_url": TARGET_TIMES,
            "attribution": "気象庁 高解像度降水ナウキャストを表示用に加工",
        },
        "display_only": True,
        "scientific_input_allowed": False,
        "message": message,
        "bounds": dict(BOUNDS),
        "image_viewport": {"width": OUTPUT_WIDTH, "height": OUTPUT_HEIGHT},
        "legend": legend(),
        "frames": [],
        "latest_index": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "web" / "data" / "rain",
    )
    parser.add_argument("--settled-lag-minutes", type=int, default=15)
    parser.add_argument("--frame-count", type=int, default=5)
    parser.add_argument("--frame-spacing-minutes", type=int, default=15)
    args = parser.parse_args()

    generated = utc_now_dt()
    outdir = args.output_dir.resolve()
    frames_dir = outdir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for stale in frames_dir.glob("frame_*.png"):
        stale.unlink(missing_ok=True)

    try:
        rows = load_target_times()
        selected = select_frames(
            rows,
            now=generated,
            settled_lag_minutes=max(0, args.settled_lag_minutes),
            frame_count=max(1, args.frame_count),
            frame_spacing_minutes=max(1, args.frame_spacing_minutes),
        )
        if not selected:
            raise RuntimeError("no settled JMA hrpns frame was available")

        frames: list[dict[str, Any]] = []
        for row in selected:
            valid = parse_compact(str(row["validtime"]))
            filename = f"frame_{valid.strftime('%Y%m%d%H%M')}.png"
            path = frames_dir / filename
            stats = render_frame(row, path)
            relative = f"data/rain/frames/{filename}"
            frames.append(
                {
                    "valid_time_utc": iso_utc(valid),
                    "age_seconds_at_build": max(0, int((generated - valid).total_seconds())),
                    "image_path": relative,
                    "basetime": str(row.get("basetime")),
                    "validtime": str(row.get("validtime")),
                    "zoom": ZOOM,
                    **stats,
                }
            )

        latest_index = len(frames) - 1
        latest = frames[latest_index]
        status = "AVAILABLE" if latest["tile_completion_ratio"] >= 0.95 else "DEGRADED"
        manifest = {
            "schema_version": "1.0.0",
            "product": "LPZ_PUBLIC_RAIN_OVERLAY",
            "generated_at_utc": iso_utc(generated),
            "status": status,
            "source": {
                "provider": "Japan Meteorological Agency",
                "product": "High-Resolution Precipitation Nowcast",
                "element": "hrpns",
                "display_mode": "settled observation/analysis display frame",
                "source_url": TARGET_TIMES,
                "attribution": "気象庁 高解像度降水ナウキャストを表示用に加工",
            },
            "display_only": True,
            "scientific_input_allowed": False,
            "settled_lag_minutes": max(0, args.settled_lag_minutes),
            "frame_spacing_minutes": max(1, args.frame_spacing_minutes),
            "message": (
                "Latest settled JMA precipitation display frame. "
                "This layer is observational/analysis context, not LPZ prediction output."
            ),
            "bounds": dict(BOUNDS),
            "image_viewport": {"width": OUTPUT_WIDTH, "height": OUTPUT_HEIGHT},
            "legend": legend(),
            "frames": frames,
            "latest_index": latest_index,
        }
    except Exception as exc:
        manifest = unavailable_manifest(generated, f"{type(exc).__name__}: {exc}")

    outdir.mkdir(parents=True, exist_ok=True)
    manifest_path = outdir / "latest.json"
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    json.loads(text)
    manifest_path.write_text(text, encoding="utf-8")

    print("=" * 96)
    print("LPZ PUBLIC JMA RAIN OVERLAY")
    print("=" * 96)
    print(f"Status           : {manifest['status']}")
    print(f"Frames           : {len(manifest['frames'])}")
    if manifest["frames"]:
        latest = manifest["frames"][int(manifest["latest_index"])]
        print(f"Latest valid UTC : {latest['valid_time_utc']}")
        print(f"Latest age        : {latest['age_seconds_at_build']}s")
        print(f"Tile completion   : {latest['tile_completion_ratio']:.3f}")
    print("Display only     : YES")
    print("Scientific input : NO")
    print(f"Manifest         : {manifest_path}")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
