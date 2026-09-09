#!/usr/bin/env python3
"""Build the first canonical live-data snapshot.

This is Phase 1A plumbing, not an LPZ prediction model. It normalizes source
health, radar-frame manifests, and AMeDAS station observations. GFS is kept as
an environment manifest until the required LPZ variables are decoded and
validated numerically.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.canonical import (  # noqa: E402
    CANONICAL_SCHEMA_VERSION,
    RadarFrameManifest,
    normalize_amedas_station,
    source_health_from_probe,
)

USER_AGENT = "lpz-risk-system/0.1.0 (+https://github.com/mijoken/lpz-risk-system)"
TIMEOUT_SECONDS = 25

JMA_NOWC_TIMES = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"
JMA_RASRF_TIMES = "https://www.jma.go.jp/bosai/jmatile/data/rasrf/targetTimes.json"
JMA_AMEDAS_LATEST = "https://www.jma.go.jp/bosai/amedas/data/latest_time.txt"
JMA_AMEDAS_MAP = "https://www.jma.go.jp/bosai/amedas/data/map/{timestamp}.json"
JMA_AMEDAS_TABLE = "https://www.jma.go.jp/bosai/amedas/const/amedastable.json"


def iso_utc(dt: datetime | None = None) -> str:
    value = dt or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_bytes(url: str, max_bytes: int = 8 * 1024 * 1024) -> tuple[bytes, int]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    started = time.perf_counter()
    with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        body = response.read(max_bytes + 1)
    latency_ms = int((time.perf_counter() - started) * 1000)
    if len(body) > max_bytes:
        raise ValueError(f"response exceeded safety limit: {url}")
    return body, latency_ms


def fetch_json(url: str) -> tuple[Any, int]:
    body, latency = fetch_bytes(url)
    return json.loads(body.decode("utf-8")), latency


def latest_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("empty metadata list")
    return max(rows, key=lambda row: str(row.get("validtime") or row.get("basetime") or ""))


def build_radar_manifests() -> list[dict[str, Any]]:
    nowc_rows, nowc_latency = fetch_json(JMA_NOWC_TIMES)
    if not isinstance(nowc_rows, list):
        raise ValueError("nowcast metadata is not a list")
    nowc = latest_row(nowc_rows)

    rasrf_rows, rasrf_latency = fetch_json(JMA_RASRF_TIMES)
    if not isinstance(rasrf_rows, list):
        raise ValueError("rasrf metadata is not a list")
    rasrf_current = [
        row
        for row in rasrf_rows
        if str(row.get("validtime", "")) == str(row.get("basetime", ""))
        and "rasrf" in row.get("elements", [])
    ]
    rasrf = latest_row(rasrf_current if rasrf_current else rasrf_rows)

    frames = [
        RadarFrameManifest(
            source_id="jma_nowc",
            valid_time=str(nowc["validtime"]),
            base_time=str(nowc["basetime"]),
            member=str(nowc.get("member") or "none"),
            element="hrpns",
            details={
                "available_elements": nowc.get("elements", []),
                "metadata_latency_ms": nowc_latency,
                "scientific_decode_state": "PENDING_PIXEL_VALUE_VALIDATION",
            },
        ).to_dict(),
        RadarFrameManifest(
            source_id="jma_rasrf",
            valid_time=str(rasrf["validtime"]),
            base_time=str(rasrf["basetime"]),
            member=str(rasrf.get("member") or "none"),
            element="rasrf",
            details={
                "available_elements": rasrf.get("elements", []),
                "metadata_latency_ms": rasrf_latency,
                "scientific_decode_state": "PENDING_PIXEL_VALUE_VALIDATION",
            },
        ).to_dict(),
    ]
    return frames


def build_amedas_frame() -> dict[str, Any]:
    latest_body, latest_latency = fetch_bytes(JMA_AMEDAS_LATEST, max_bytes=4096)
    latest_text = latest_body.decode("utf-8").strip()
    latest_dt = datetime.fromisoformat(latest_text)
    observation_time = iso_utc(latest_dt)
    timestamp = latest_dt.strftime("%Y%m%d%H%M00")

    observations, obs_latency = fetch_json(JMA_AMEDAS_MAP.format(timestamp=timestamp))
    station_table, table_latency = fetch_json(JMA_AMEDAS_TABLE)
    if not isinstance(observations, dict) or not isinstance(station_table, dict):
        raise ValueError("AMeDAS observations or station table is not an object")

    stations = []
    with_location = 0
    with_wind = 0
    with_humidity = 0
    for station_id, observation in observations.items():
        if not isinstance(observation, dict):
            continue
        normalized = normalize_amedas_station(
            station_id=str(station_id),
            observation=observation,
            station_meta=station_table.get(str(station_id)),
            observation_time=observation_time,
        )
        row = normalized.to_dict()
        if row["latitude_deg"] is not None and row["longitude_deg"] is not None:
            with_location += 1
        if row["wind_speed_ms"] is not None:
            with_wind += 1
        if row["humidity_pct"] is not None:
            with_humidity += 1
        stations.append(row)

    return {
        "frame_type": "surface_station_frame",
        "source_id": "jma_amedas",
        "observation_time": observation_time,
        "station_count": len(stations),
        "coverage": {
            "with_location": with_location,
            "with_wind": with_wind,
            "with_humidity": with_humidity,
        },
        "fetch_latency_ms": {
            "latest_time": latest_latency,
            "observations": obs_latency,
            "station_table": table_latency,
        },
        "stations": stations,
    }


def build_environment_manifest(acquisition_report: dict[str, Any]) -> dict[str, Any]:
    gfs = next(
        (row for row in acquisition_report.get("results", []) if row.get("source_id") == "noaa_gfs"),
        None,
    )
    return {
        "frame_type": "environment_frame",
        "source_id": "noaa_gfs",
        "cycle_time": gfs.get("data_time") if isinstance(gfs, dict) else None,
        "transport_status": gfs.get("status") if isinstance(gfs, dict) else "UNKNOWN",
        "transport_url": gfs.get("url") if isinstance(gfs, dict) else None,
        "validated_variables": ["PRMSL"] if isinstance(gfs, dict) and gfs.get("status") == "PASS" else [],
        "required_lpz_variables": [
            "PWAT",
            "CAPE",
            "CIN",
            "SPFH_925",
            "SPFH_850",
            "UGRD_925",
            "VGRD_925",
            "UGRD_850",
            "VGRD_850",
            "UGRD_700",
            "VGRD_700"
        ],
        "feature_payload_gate": "PENDING",
        "note": "Transport proof exists; LPZ environmental variables must be numerically decoded and validated before risk-engine use."
    }


def build_snapshot(acquisition_report: dict[str, Any]) -> dict[str, Any]:
    source_health = [source_health_from_probe(row).to_dict() for row in acquisition_report.get("results", [])]
    radar_frames = build_radar_manifests()
    amedas_frame = build_amedas_frame()
    environment_frame = build_environment_manifest(acquisition_report)

    mandatory = {"jma_nowc", "jma_rasrf", "jma_amedas", "noaa_gfs"}
    mandatory_health = [row for row in source_health if row["source_id"] in mandatory]
    transport_gate = len(mandatory_health) == 4 and all(row["status"] == "PASS" for row in mandatory_health)
    station_gate = amedas_frame["station_count"] >= 1000 and amedas_frame["coverage"]["with_location"] >= 1000

    return {
        "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
        "snapshot_version": "0.1.0",
        "generated_at": iso_utc(),
        "phase": "1A-canonical-adapter-proof",
        "gates": {
            "mandatory_transport": transport_gate,
            "amedas_station_normalization": station_gate,
            "radar_pixel_scientific_decode": False,
            "gfs_lpz_variable_decode": False,
            "risk_engine_allowed": False,
        },
        "source_health": source_health,
        "radar_frames": radar_frames,
        "surface_station_frame": amedas_frame,
        "environment_frame": environment_frame,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition-report", required=True)
    parser.add_argument("--output", default="reports/canonical/canonical_snapshot.json")
    args = parser.parse_args()

    acquisition_path = Path(args.acquisition_report)
    report = json.loads(acquisition_path.read_text(encoding="utf-8"))
    snapshot = build_snapshot(report)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    compact = {
        "gates": snapshot["gates"],
        "station_count": snapshot["surface_station_frame"]["station_count"],
        "station_coverage": snapshot["surface_station_frame"]["coverage"],
        "radar_frames": len(snapshot["radar_frames"]),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    print(f"snapshot={output}")

    # Phase 1A is expected to be partial. Fail only if already-proven mandatory
    # transport or basic AMeDAS normalization regresses.
    return 0 if snapshot["gates"]["mandatory_transport"] and snapshot["gates"]["amedas_station_normalization"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
