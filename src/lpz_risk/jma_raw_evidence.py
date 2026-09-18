"""Reusable JMA HRPN public-PNG raw-evidence primitives.

Research evidence only.

The original PNG bytes are archived without alteration together with
transport/provenance metadata and SHA256 hashes. This module does not convert
public PNG classes into continuous rainfall rates and does not authorize Risk
Engine or production integration.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lpz_risk.radar_science import lonlat_to_xyz


TIMES_URL = (
    "https://www.jma.go.jp/bosai/jmatile/data/nowc/"
    "targetTimes_N1.json"
)

DEFAULT_BBOX = {
    "west": 122.0,
    "east": 154.0,
    "south": 20.0,
    "north": 46.0,
}

DEFAULT_ZOOM = 6
DEFAULT_FRAME_COUNT = 7
FRAME_STEP_MINUTES = 5
DEFAULT_SETTLEMENT_MINUTES = 15

TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
WORKERS = 6

USER_AGENT = "lpz-risk-system-jma-raw-evidence/0.1.0"


def parse_jma_time(value: str) -> datetime:
    return datetime.strptime(
        value,
        "%Y%m%d%H%M%S",
    ).replace(tzinfo=timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_bytes(
    url: str,
    *,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> tuple[bytes, int, str | None]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        },
    )

    with urlopen(
        request,
        timeout=TIMEOUT_SECONDS,
    ) as response:
        body = response.read(max_bytes + 1)
        status = getattr(response, "status", 200)
        content_type = response.headers.get("Content-Type")

    if len(body) > max_bytes:
        raise ValueError("response too large")

    return body, status, content_type


def analysis_row_map(
    rows: list[dict[str, Any]],
) -> dict[datetime, dict[str, Any]]:
    out: dict[datetime, dict[str, Any]] = {}

    for row in rows:
        if "hrpns" not in (row.get("elements") or []):
            continue

        basetime = row.get("basetime")
        validtime = row.get("validtime")

        if not basetime or basetime != validtime:
            continue

        try:
            out[parse_jma_time(str(validtime))] = row
        except ValueError:
            continue

    return out


def exact_sequence(
    row_map: dict[datetime, dict[str, Any]],
    target_end: datetime,
    *,
    frame_count: int = DEFAULT_FRAME_COUNT,
) -> list[dict[str, Any]]:
    if frame_count < 1:
        raise ValueError("frame_count must be >= 1")

    target_end = target_end.astimezone(timezone.utc)

    times = [
        target_end
        - timedelta(
            minutes=FRAME_STEP_MINUTES * i
        )
        for i in range(frame_count - 1, -1, -1)
    ]

    missing = [
        iso_utc(t)
        for t in times
        if t not in row_map
    ]

    if missing:
        raise ValueError(
            "requested exact JMA frame sequence is not available: "
            + ", ".join(missing)
        )

    return [row_map[t] for t in times]


def latest_settled_sequence(
    row_map: dict[datetime, dict[str, Any]],
    now: datetime,
    *,
    frame_count: int = DEFAULT_FRAME_COUNT,
    settlement_minutes: int = DEFAULT_SETTLEMENT_MINUTES,
) -> list[dict[str, Any]]:
    cutoff = now.astimezone(timezone.utc) - timedelta(
        minutes=settlement_minutes
    )

    candidates = sorted(
        (t for t in row_map if t <= cutoff),
        reverse=True,
    )

    for target_end in candidates:
        try:
            return exact_sequence(
                row_map,
                target_end,
                frame_count=frame_count,
            )
        except ValueError:
            continue

    raise RuntimeError(
        "no settled contiguous JMA HRPN sequence available"
    )


def tile_coordinates(
    bbox: dict[str, float],
    zoom: int,
) -> list[tuple[int, int]]:
    _, x0, y0 = lonlat_to_xyz(
        bbox["west"],
        bbox["north"],
        zoom,
    )
    _, x1, y1 = lonlat_to_xyz(
        bbox["east"],
        bbox["south"],
        zoom,
    )

    xa, xb = sorted((x0, x1))
    ya, yb = sorted((y0, y1))

    return [
        (x, y)
        for y in range(ya, yb + 1)
        for x in range(xa, xb + 1)
    ]


def tile_url(
    row: dict[str, Any],
    zoom: int,
    x: int,
    y: int,
) -> str:
    basetime = str(row["basetime"])
    validtime = str(row["validtime"])

    return (
        "https://www.jma.go.jp/bosai/jmatile/data/nowc/"
        f"{basetime}/none/{validtime}/surf/hrpns/"
        f"{zoom}/{x}/{y}.png"
    )


def capture_sequence(
    sequence: list[dict[str, Any]],
    output_root: Path,
    *,
    bbox: dict[str, float] | None = None,
    zoom: int = DEFAULT_ZOOM,
) -> dict[str, Any]:
    if not sequence:
        raise ValueError("sequence must not be empty")

    bbox = dict(bbox or DEFAULT_BBOX)

    start = parse_jma_time(str(sequence[0]["validtime"]))
    end = parse_jma_time(str(sequence[-1]["validtime"]))

    capture_dir = (
        output_root
        / f"{start:%Y%m%dT%H%M%SZ}_{end:%Y%m%dT%H%M%SZ}_z{zoom}"
    )

    capture_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    xy = tile_coordinates(bbox, zoom)

    def capture_one(
        item: tuple[dict[str, Any], int, int],
    ) -> dict[str, Any]:
        row, x, y = item

        validtime = str(row["validtime"])
        basetime = str(row["basetime"])
        url = tile_url(row, zoom, x, y)

        relative_path = (
            Path(validtime)
            / f"z{zoom}_{x}_{y}.png"
        )
        path = capture_dir / relative_path

        try:
            body, status, content_type = fetch_bytes(url)

            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            path.write_bytes(body)

            return {
                "basetime": basetime,
                "validtime": validtime,
                "valid_time_utc": iso_utc(
                    parse_jma_time(validtime)
                ),
                "z": zoom,
                "x": x,
                "y": y,
                "source_url": url,
                "ok": True,
                "http_status": status,
                "content_type": content_type,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "relative_path": str(relative_path),
            }

        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            ValueError,
        ) as exc:
            return {
                "basetime": basetime,
                "validtime": validtime,
                "valid_time_utc": iso_utc(
                    parse_jma_time(validtime)
                ),
                "z": zoom,
                "x": x,
                "y": y,
                "source_url": url,
                "ok": False,
                "error": (
                    f"{type(exc).__name__}: {exc}"
                ),
            }

    jobs = [
        (row, x, y)
        for row in sequence
        for x, y in xy
    ]

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=WORKERS
    ) as pool:
        results = list(
            pool.map(capture_one, jobs)
        )

    failures = [
        row
        for row in results
        if not row["ok"]
    ]

    frames: list[dict[str, Any]] = []

    for row in sequence:
        validtime = str(row["validtime"])

        frame_rows = [
            item
            for item in results
            if item["validtime"] == validtime
        ]

        frames.append(
            {
                "basetime": str(row["basetime"]),
                "validtime": validtime,
                "valid_time_utc": iso_utc(
                    parse_jma_time(validtime)
                ),
                "tile_count": len(frame_rows),
                "tiles_ok": sum(
                    item["ok"]
                    for item in frame_rows
                ),
                "tiles_failed": sum(
                    not item["ok"]
                    for item in frame_rows
                ),
            }
        )

    captured_at = datetime.now(timezone.utc)

    manifest = {
        "schema_version": "0.1.0-jma-raw-evidence",
        "role": "RESEARCH_ONLY_PROSPECTIVE_RAW_EVIDENCE",
        "source": "JMA_HRPN_ANALYSIS_PUBLIC_PNG",
        "risk_engine_allowed": False,
        "production_integration_allowed": False,
        "raw_radar_archived": len(failures) == 0,
        "raw_grib_archived": False,
        "raw_retention_policy": "RESEARCH_EVIDENCE",
        "captured_at_utc": iso_utc(captured_at),
        "bbox": bbox,
        "zoom": zoom,
        "frame_step_minutes": FRAME_STEP_MINUTES,
        "frame_count": len(sequence),
        "support": {
            "start_utc": iso_utc(start),
            "end_utc": iso_utc(end),
            "span_minutes": int(
                (end - start).total_seconds() / 60
            ),
        },
        "tile_count_per_frame": len(xy),
        "expected_downloads": len(jobs),
        "successful_downloads": sum(
            item["ok"]
            for item in results
        ),
        "failed_downloads": len(failures),
        "frames": frames,
        "tiles": results,
        "scientific_policy": {
            "original_png_bytes_preserved": True,
            "sha256_per_tile": True,
            "jma_png_is_interval_valued_display_product": True,
            "continuous_mmph_reconstruction_allowed": False,
            "midpoint_fabrication_allowed": False,
            "transparent_pixels_rewritten_to_zero": False,
        },
        "pairing_policy": {
            "imerg_product": "GPM_3IMERGHHE V07",
            "imerg_native_grid_preserved": True,
            "imerg_spatial_upsampling_allowed": False,
            "direct_continuous_rate_comparison_allowed": False,
        },
        "result": (
            "PASS_JMA_RAW_EVIDENCE_CAPTURE"
            if not failures
            else "FAIL_JMA_RAW_EVIDENCE_TRANSPORT"
        ),
    }

    manifest_path = capture_dir / "manifest.json"

    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "capture_dir": str(capture_dir),
        "manifest_path": str(manifest_path),
        "manifest": manifest,
    }
