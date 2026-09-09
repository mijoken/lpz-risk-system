#!/usr/bin/env python3
"""Phase 0.5 acquisition proof.

This program intentionally separates:
- PAYLOAD proof: an actual observation payload was downloaded and parsed.
- METADATA proof: current upstream metadata was downloaded and parsed.
- SERVICE proof: the upstream service endpoint answered, but a scientific
  payload has not yet been validated.

A source is promoted to operational CORE only after repeated evidence.
"""

from __future__ import annotations

import argparse
import json
import math
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

from lpz_risk.schemas import ProbeResult  # noqa: E402

USER_AGENT = "lpz-risk-system/0.0.1 (+https://github.com/mijoken/lpz-risk-system)"
TIMEOUT_SECONDS = 25
MAX_READ_BYTES = 8 * 1024 * 1024

JMA_NOWC_TIMES = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"
JMA_RASRF_TIMES = "https://www.jma.go.jp/bosai/jmatile/data/rasrf/targetTimes.json"
JMA_AMEDAS_LATEST = "https://www.jma.go.jp/bosai/amedas/data/latest_time.txt"
JMA_AMEDAS_MAP = "https://www.jma.go.jp/bosai/amedas/data/map/{timestamp}.json"
JMA_HIMAWARI_TIMES = "https://www.jma.go.jp/bosai/himawari/data/satimg/targetTimes_fd.json"
NOAA_GFS_SERVICE = "https://nomads.ncep.noaa.gov/gribfilter.php?ds=gfs_0p25"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime | None = None) -> str:
    value = dt or utc_now()
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_jma_compact(value: str) -> datetime:
    """JMA jmatile compact timestamps are UTC."""
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def age_seconds(data_time: datetime | None, now: datetime | None = None) -> int | None:
    if data_time is None:
        return None
    ref = now or utc_now()
    return max(0, int((ref - data_time.astimezone(timezone.utc)).total_seconds()))


def http_get(url: str, *, max_bytes: int = MAX_READ_BYTES) -> tuple[bytes, int, int]:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        },
    )
    started = time.perf_counter()
    with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        status = int(getattr(response, "status", 200))
        body = response.read(max_bytes + 1)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if len(body) > max_bytes:
        raise ValueError(f"response exceeded safety limit of {max_bytes} bytes")
    return body, status, elapsed_ms


def load_json(url: str) -> tuple[Any, int, int, int]:
    body, status, latency_ms = http_get(url)
    return json.loads(body.decode("utf-8")), status, latency_ms, len(body)


def error_result(
    source_id: str,
    source_name: str,
    probe_type: str,
    checked_at: str,
    url: str,
    exc: Exception,
) -> ProbeResult:
    status = exc.code if isinstance(exc, HTTPError) else None
    return ProbeResult(
        source_id=source_id,
        source_name=source_name,
        status="FAIL",
        probe_type=probe_type,
        checked_at=checked_at,
        url=url,
        http_status=status,
        parse_status="FAIL",
        error=f"{type(exc).__name__}: {exc}",
    )


def lonlat_to_xyz(lon: float, lat: float, zoom: int) -> tuple[int, int, int]:
    """Convert lon/lat to a slippy-map tile index."""
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(max(-85.05112878, min(85.05112878, lat)))
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return zoom, x, y


def probe_jma_nowc() -> ProbeResult:
    checked = iso_utc()
    try:
        rows, status, latency, size = load_json(JMA_NOWC_TIMES)
        if not isinstance(rows, list) or not rows:
            raise ValueError("targetTimes_N1.json was empty or not a list")
        current = rows[0]
        basetime = str(current["basetime"])
        validtime = str(current["validtime"])
        elements = current.get("elements", [])
        data_dt = parse_jma_compact(validtime)

        # Sample one tile near central Japan. This is an acquisition proof only;
        # scientific processing will later request the complete ROI tile set.
        z, x, y = lonlat_to_xyz(135.0, 35.0, 6)
        tile_url = (
            "https://www.jma.go.jp/bosai/jmatile/data/nowc/"
            f"{basetime}/none/{validtime}/surf/hrpns/{z}/{x}/{y}.png"
        )
        tile_body, tile_status, tile_latency = http_get(tile_url, max_bytes=2 * 1024 * 1024)
        png_ok = tile_body.startswith(b"\x89PNG\r\n\x1a\n")
        if not png_ok:
            raise ValueError("sample nowcast tile did not contain a PNG signature")

        return ProbeResult(
            source_id="jma_nowc",
            source_name="JMA High-Resolution Precipitation Nowcast",
            status="PASS",
            probe_type="PAYLOAD",
            checked_at=checked,
            url=tile_url,
            http_status=tile_status,
            bytes_received=len(tile_body),
            latency_ms=latency + tile_latency,
            data_time=iso_utc(data_dt),
            data_age_seconds=age_seconds(data_dt),
            parse_status="PASS",
            records=1,
            details={
                "metadata_http_status": status,
                "metadata_bytes": size,
                "metadata_latency_ms": latency,
                "basetime": basetime,
                "validtime": validtime,
                "elements": elements,
                "sample_tile": {"z": z, "x": x, "y": y},
            },
        )
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return error_result(
            "jma_nowc",
            "JMA High-Resolution Precipitation Nowcast",
            "PAYLOAD",
            checked,
            JMA_NOWC_TIMES,
            exc,
        )


def probe_jma_rasrf() -> ProbeResult:
    checked = iso_utc()
    try:
        rows, status, latency, size = load_json(JMA_RASRF_TIMES)
        if not isinstance(rows, list) or not rows:
            raise ValueError("rasrf targetTimes.json was empty or not a list")

        candidates = [
            row
            for row in rows
            if str(row.get("validtime", "")) == str(row.get("basetime", ""))
            and "rasrf" in row.get("elements", [])
        ]
        current = candidates[0] if candidates else rows[0]
        validtime = str(current["validtime"])
        data_dt = parse_jma_compact(validtime)
        return ProbeResult(
            source_id="jma_rasrf",
            source_name="JMA analyzed precipitation / precipitation metadata",
            status="META_PASS",
            probe_type="METADATA",
            checked_at=checked,
            url=JMA_RASRF_TIMES,
            http_status=status,
            bytes_received=size,
            latency_ms=latency,
            data_time=iso_utc(data_dt),
            data_age_seconds=age_seconds(data_dt),
            parse_status="PASS",
            records=len(rows),
            details={
                "basetime": current.get("basetime"),
                "validtime": current.get("validtime"),
                "member": current.get("member"),
                "elements": current.get("elements", []),
                "note": "Scientific raster payload validation remains pending.",
            },
        )
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return error_result(
            "jma_rasrf",
            "JMA analyzed precipitation / precipitation metadata",
            "METADATA",
            checked,
            JMA_RASRF_TIMES,
            exc,
        )


def probe_jma_amedas() -> ProbeResult:
    checked = iso_utc()
    try:
        latest_body, latest_status, latest_latency = http_get(JMA_AMEDAS_LATEST, max_bytes=4096)
        latest_text = latest_body.decode("utf-8").strip()
        latest_dt = datetime.fromisoformat(latest_text)
        stamp = latest_dt.strftime("%Y%m%d%H%M00")
        map_url = JMA_AMEDAS_MAP.format(timestamp=stamp)

        payload, map_status, map_latency, map_size = load_json(map_url)
        if not isinstance(payload, dict) or not payload:
            raise ValueError("AMeDAS map payload was empty or not an object")

        return ProbeResult(
            source_id="jma_amedas",
            source_name="JMA AMeDAS",
            status="PASS",
            probe_type="PAYLOAD",
            checked_at=checked,
            url=map_url,
            http_status=map_status,
            bytes_received=map_size,
            latency_ms=latest_latency + map_latency,
            data_time=iso_utc(latest_dt),
            data_age_seconds=age_seconds(latest_dt),
            parse_status="PASS",
            records=len(payload),
            details={
                "latest_time_http_status": latest_status,
                "latest_time": latest_text,
            },
        )
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return error_result(
            "jma_amedas",
            "JMA AMeDAS",
            "PAYLOAD",
            checked,
            JMA_AMEDAS_LATEST,
            exc,
        )


def probe_jma_windas() -> ProbeResult:
    # The official product is accepted as a candidate, but the stable machine
    # acquisition route must be separately verified before we automate it.
    return ProbeResult(
        source_id="jma_windas",
        source_name="JMA WINDAS / wind profiler",
        status="PENDING",
        probe_type="DISCOVERY_PENDING",
        checked_at=iso_utc(),
        parse_status="NOT_ATTEMPTED",
        details={
            "reason": (
                "Candidate retained as LIVE_SUPPLEMENTARY. "
                "Stable machine-readable acquisition endpoint is intentionally "
                "not guessed; it will be verified from official delivery assets."
            )
        },
    )


def probe_jma_himawari() -> ProbeResult:
    checked = iso_utc()
    try:
        rows, status, latency, size = load_json(JMA_HIMAWARI_TIMES)
        if not isinstance(rows, list) or not rows:
            raise ValueError("Himawari targetTimes metadata was empty or not a list")
        current = rows[0]
        validtime = str(current.get("validtime") or current.get("basetime"))
        data_dt = parse_jma_compact(validtime)
        return ProbeResult(
            source_id="jma_himawari",
            source_name="JMA Himawari imagery",
            status="META_PASS",
            probe_type="METADATA",
            checked_at=checked,
            url=JMA_HIMAWARI_TIMES,
            http_status=status,
            bytes_received=size,
            latency_ms=latency,
            data_time=iso_utc(data_dt),
            data_age_seconds=age_seconds(data_dt),
            parse_status="PASS",
            records=len(rows),
            details={
                "basetime": current.get("basetime"),
                "validtime": current.get("validtime"),
                "note": "Image payload and channel selection remain pending.",
            },
        )
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return error_result(
            "jma_himawari",
            "JMA Himawari imagery",
            "METADATA",
            checked,
            JMA_HIMAWARI_TIMES,
            exc,
        )


def probe_noaa_gfs() -> ProbeResult:
    checked = iso_utc()
    try:
        body, status, latency = http_get(NOAA_GFS_SERVICE, max_bytes=3 * 1024 * 1024)
        text = body.decode("utf-8", errors="replace")
        markers = ("NCEP GFS Forecasts", "0.25 degree grid")
        if not all(marker in text for marker in markers):
            raise ValueError("GFS grib-filter service markers were not found")
        return ProbeResult(
            source_id="noaa_gfs",
            source_name="NOAA/NCEP GFS 0.25 degree",
            status="SERVICE_PASS",
            probe_type="SERVICE",
            checked_at=checked,
            url=NOAA_GFS_SERVICE,
            http_status=status,
            bytes_received=len(body),
            latency_ms=latency,
            parse_status="PASS",
            details={
                "note": (
                    "Service availability confirmed. Actual Japan-subset GRIB2 "
                    "download and variable/level validation remain pending."
                )
            },
        )
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return error_result(
            "noaa_gfs",
            "NOAA/NCEP GFS 0.25 degree",
            "SERVICE",
            checked,
            NOAA_GFS_SERVICE,
            exc,
        )


def build_summary(results: list[ProbeResult]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1

    mandatory_ids = {"jma_nowc", "jma_rasrf", "jma_amedas", "noaa_gfs"}
    mandatory = [r for r in results if r.source_id in mandatory_ids]
    mandatory_payload_pass = sum(r.status == "PASS" for r in mandatory)

    return {
        "counts": counts,
        "mandatory_sources": len(mandatory),
        "mandatory_payload_pass": mandatory_payload_pass,
        "phase0_5_complete": all(r.status == "PASS" for r in mandatory),
        "interpretation": (
            "Phase 0.5 is complete only when every mandatory source has an "
            "actual scientific payload proof. META_PASS and SERVICE_PASS are "
            "useful evidence but are not equivalent to payload acceptance."
        ),
    }


def run() -> dict[str, Any]:
    results = [
        probe_jma_nowc(),
        probe_jma_rasrf(),
        probe_jma_amedas(),
        probe_jma_windas(),
        probe_jma_himawari(),
        probe_noaa_gfs(),
    ]
    return {
        "schema_version": "0.1.0",
        "system_version": "0.0.1",
        "phase": "0.5-data-acquisition-proof",
        "generated_at": iso_utc(),
        "results": [result.to_dict() for result in results],
        "summary": build_summary(results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="reports/acquisition/acquisition_report.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    report = run()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report={output}")

    has_fail = any(row["status"] == "FAIL" for row in report["results"])
    return 1 if has_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
