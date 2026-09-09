#!/usr/bin/env python3
"""Phase 1C proof for JMA public precipitation PNG scientific class decoding."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.radar_science import (  # noqa: E402
    JMA_PRECIPITATION_CLASSES,
    decode_jma_precipitation_png,
    lonlat_to_xyz,
)

USER_AGENT = "lpz-risk-system/0.1.0 (+https://github.com/mijoken/lpz-risk-system)"
TIMEOUT_SECONDS = 25
MAX_TILE_BYTES = 2 * 1024 * 1024

NOWC_TIMES = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"
RASRF_TIMES = "https://www.jma.go.jp/bosai/jmatile/data/rasrf/targetTimes.json"

# Distributed points are used only to increase the chance of sampling rain
# without downloading a dense national tile set during the proof phase.
SAMPLE_POINTS = (
    (130.4, 33.6, "north_kyushu"),
    (130.6, 31.6, "south_kyushu"),
    (132.5, 34.4, "chugoku"),
    (133.6, 33.6, "shikoku"),
    (135.5, 34.7, "kansai"),
    (136.9, 35.2, "chubu"),
    (139.7, 35.7, "kanto"),
    (140.9, 38.3, "tohoku"),
    (141.4, 43.1, "hokkaido"),
    (127.7, 26.2, "okinawa"),
)


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


def latest_nowc_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [r for r in rows if "hrpns" in r.get("elements", [])]
    if not candidates:
        raise ValueError("no hrpns targetTimes row")
    return max(candidates, key=lambda r: (str(r.get("validtime", "")), str(r.get("basetime", ""))))


def latest_rasrf_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        r
        for r in rows
        if "rasrf" in r.get("elements", [])
        and str(r.get("validtime", "")) == str(r.get("basetime", ""))
    ]
    if not candidates:
        raise ValueError("no current rasrf targetTimes row")
    return max(candidates, key=lambda r: (str(r.get("validtime", "")), str(r.get("basetime", ""))))


def tile_urls() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    nowc_rows = load_json(NOWC_TIMES)
    rasrf_rows = load_json(RASRF_TIMES)
    if not isinstance(nowc_rows, list) or not isinstance(rasrf_rows, list):
        raise ValueError("targetTimes payload was not a list")

    nowc = latest_nowc_row(nowc_rows)
    rasrf = latest_rasrf_row(rasrf_rows)
    metadata = {
        "nowc": nowc,
        "rasrf": rasrf,
    }

    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int, int]] = set()
    zoom = 7
    for lon, lat, label in SAMPLE_POINTS:
        z, x, y = lonlat_to_xyz(lon, lat, zoom)
        for product in ("nowc", "rasrf"):
            dedupe = (product, z, x, y)
            if dedupe in seen:
                continue
            seen.add(dedupe)
            if product == "nowc":
                basetime = str(nowc["basetime"])
                validtime = str(nowc["validtime"])
                member = "none"
                element = "hrpns"
                url = (
                    "https://www.jma.go.jp/bosai/jmatile/data/nowc/"
                    f"{basetime}/{member}/{validtime}/surf/{element}/{z}/{x}/{y}.png"
                )
            else:
                basetime = str(rasrf["basetime"])
                validtime = str(rasrf["validtime"])
                member = str(rasrf.get("member") or "immed")
                element = "rasrf"
                url = (
                    "https://www.jma.go.jp/bosai/jmatile/data/rasrf/"
                    f"{basetime}/{member}/{validtime}/surf/{element}/{z}/{x}/{y}.png"
                )
            entries.append(
                {
                    "product": product,
                    "label": label,
                    "z": z,
                    "x": x,
                    "y": y,
                    "basetime": basetime,
                    "validtime": validtime,
                    "url": url,
                }
            )
    return metadata, entries


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
        metadata, entries = tile_urls()
    except Exception as exc:
        return {
            "schema_version": "0.1.0",
            "phase": "1C-radar-scientific-decode-proof",
            "generated_at": iso_utc(generated),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "official_palette": official_palette,
            "gates": {
                "target_times": False,
                "png_transport": False,
                "official_palette_only": False,
                "continuous_mmph_recovery": False,
                "risk_engine_allowed": False,
            },
        }

    tile_reports: list[dict[str, Any]] = []
    product_success = {"nowc": 0, "rasrf": 0}
    unknown_opaque_total = 0
    known_opaque_total = 0
    observed_classes: set[str] = set()
    transparent_rgbs: set[tuple[int, int, int]] = set()

    for entry in entries:
        report = dict(entry)
        try:
            payload, status, latency = http_get(entry["url"], MAX_TILE_BYTES)
            decoded = decode_jma_precipitation_png(payload)
            summary = decoded.summary()
            report.update(
                {
                    "http_status": status,
                    "bytes": len(payload),
                    "latency_ms": latency,
                    "decode": "PASS",
                    "summary": summary,
                }
            )
            product_success[entry["product"]] += 1
            unknown_opaque_total += decoded.unknown_opaque_pixel_count
            class_counts = decoded.class_counts()
            known_opaque_total += sum(class_counts.values())
            observed_classes.update(class_counts)
            transparent_rgbs.update(decoded.transparent_rgbs)
        except HTTPError as exc:
            report.update({"decode": "MISSING_TILE", "http_status": exc.code, "error": str(exc)})
        except (URLError, TimeoutError, ValueError, OSError) as exc:
            report.update({"decode": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        tile_reports.append(report)

    palette_gate = unknown_opaque_total == 0
    transport_gate = product_success["nowc"] > 0 and product_success["rasrf"] > 0
    scientific_class_gate = transport_gate and palette_gate and known_opaque_total > 0

    nowc_dt = parse_compact(str(metadata["nowc"]["validtime"]))
    rasrf_dt = parse_compact(str(metadata["rasrf"]["validtime"]))

    return {
        "schema_version": "0.1.0",
        "phase": "1C-radar-scientific-decode-proof",
        "generated_at": iso_utc(generated),
        "ok": scientific_class_gate,
        "metadata": {
            "nowc_valid_time": iso_utc(nowc_dt),
            "rasrf_valid_time": iso_utc(rasrf_dt),
            "sample_zoom": 7,
            "sample_point_count": len(SAMPLE_POINTS),
            "tile_attempt_count": len(entries),
        },
        "official_palette": official_palette,
        "results": {
            "successful_tiles_by_product": product_success,
            "known_opaque_pixel_total": known_opaque_total,
            "unknown_opaque_pixel_total": unknown_opaque_total,
            "observed_precipitation_classes": sorted(observed_classes),
            "observed_transparent_rgbs": [list(rgb) for rgb in sorted(transparent_rgbs)],
        },
        "tiles": tile_reports,
        "interpretation": {
            "public_png_semantics": "official precipitation colour intervals only",
            "exact_continuous_mmph": False,
            "transparent_pixels_as_zero": False,
            "reason": (
                "The public PNG is a display-class product. LPZ-RISK preserves bucket bounds and "
                "does not invent a midpoint or treat transparency as measured zero without a separate proof."
            ),
        },
        "gates": {
            "target_times": True,
            "png_transport": transport_gate,
            "official_palette_only": palette_gate,
            "precipitation_class_decode": scientific_class_gate,
            "continuous_mmph_recovery": False,
            "hirockawa_exact_3h_accumulation": False,
            "risk_engine_allowed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="reports/scientific/radar_scientific_decode.json",
    )
    args = parser.parse_args()

    report = run()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": report.get("ok"),
                "results": report.get("results"),
                "gates": report.get("gates"),
            },
            indent=2,
        )
    )
    print(f"report={output}")
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
