#!/usr/bin/env python3
"""Phase 1C proof: embedded-core genesis relative to time-aligned GFS 850-hPa inflow.

This consumes the already-derived radar genesis geometry report, selects a
conservative GFS forecast valid time close to the event window, samples local
850-hPa wind at each parent centroid, and projects each child-core genesis
location onto the meteorological wind-FROM (upstream) axis.

No upstream fraction or distance threshold is an LPZ/back-building gate.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.gfs_science import FieldKey, build_science_subset_url, cycle_candidates, decode_pressure_fields  # noqa: E402
from lpz_risk.orientation_science import nearest_local_wind  # noqa: E402
from lpz_risk.radar_inflow_geometry import enrich_genesis_with_inflow  # noqa: E402

USER_AGENT = "lpz-risk-system/0.1.0 (+https://github.com/mijoken/lpz-risk-system)"
TIMEOUT_SECONDS = 50
MAX_BYTES = 32 * 1024 * 1024
MIN_CYCLE_AGE_HOURS_AT_EVENT_TIME = 4
MAX_FORECAST_HOUR = 18


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def download_grib(url: str, target: Path) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream,*/*"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        status = int(getattr(response, "status", 200))
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("GFS subset exceeded byte safety limit")
    if not body.startswith(b"GRIB"):
        raise ValueError(f"response did not begin with GRIB: {body[:24]!r}")
    target.write_bytes(body)
    return {"http_status": status, "bytes": len(body)}


def candidate_cycle_hours(event_time: datetime) -> list[tuple[datetime, int, datetime, float]]:
    cutoff = event_time - timedelta(hours=MIN_CYCLE_AGE_HOURS_AT_EVENT_TIME)
    candidates: list[tuple[datetime, int, datetime, float]] = []
    for cycle in cycle_candidates(now=event_time, count=8):
        if cycle > cutoff:
            continue
        delta_h = (event_time - cycle).total_seconds() / 3600.0
        fh = int(round(delta_h))
        if not (1 <= fh <= MAX_FORECAST_HOUR):
            continue
        valid = cycle + timedelta(hours=fh)
        error_min = abs((valid - event_time).total_seconds()) / 60.0
        candidates.append((cycle, fh, valid, error_min))
    return sorted(candidates, key=lambda item: (item[3], -item[0].timestamp()))


def summarize(rows: list[dict[str, Any]], threshold: int) -> dict[str, Any]:
    usable = [
        row for row in rows
        if int(row["threshold_mmph"]) == threshold
        and row.get("along_inflow_km") is not None
        and not row.get("parent_boundary_truncated")
    ]
    along = [float(row["along_inflow_km"]) for row in usable]
    angle = [float(row["genesis_vs_inflow_from_angle_deg"]) for row in usable]
    return {
        "threshold_mmph": threshold,
        "usable_event_count": len(usable),
        "upstream_side_count": sum(value > 0.0 for value in along),
        "downwind_side_count": sum(value < 0.0 for value in along),
        "upstream_fraction": None if not along else sum(value > 0.0 for value in along) / len(along),
        "median_along_inflow_km": None if not along else statistics.median(along),
        "min_along_inflow_km": None if not along else min(along),
        "max_along_inflow_km": None if not along else max(along),
        "median_genesis_vs_inflow_from_angle_deg": None if not angle else statistics.median(angle),
    }


def run(genesis_path: Path) -> dict[str, Any]:
    base = {
        "schema_version": "0.1.0",
        "phase": "1C-radar-genesis-vs-850hpa-inflow",
        "feature_id": "embedded_core_genesis_relative_850hpa_inflow",
        "operational_gate": False,
        "backbuilding_classification": None,
        "historical_validation": False,
        "risk_engine_allowed": False,
    }
    genesis = json.loads(genesis_path.read_text(encoding="utf-8"))
    if not genesis.get("execution_ok"):
        return {**base, "execution_ok": False, "reason": "genesis geometry report is not valid"}

    events = list(genesis.get("events", []))
    if not events:
        return {**base, "execution_ok": True, "scientific_inflow_geometry_proven": False, "reason": "no genesis events"}

    event_times = [parse_iso(str(row["valid_time"])) for row in events]
    representative = min(event_times) + (max(event_times) - min(event_times)) / 2
    latest_event = max(event_times)

    # Enforce conservative cycle age at the latest event in the window so one
    # file cannot accidentally use information unavailable to later events.
    candidates = []
    cutoff = latest_event - timedelta(hours=MIN_CYCLE_AGE_HOURS_AT_EVENT_TIME)
    for cycle, fh, valid, error_min in candidate_cycle_hours(representative):
        if cycle <= cutoff:
            candidates.append((cycle, fh, valid, error_min))

    attempts: list[dict[str, Any]] = []
    fields = None
    selected = None
    transport = None
    with tempfile.TemporaryDirectory(prefix="lpz-inflow850-") as temp:
        target = Path(temp) / "gfs.grib2"
        for cycle, fh, valid, error_min in candidates:
            url = build_science_subset_url(cycle, forecast_hour=fh)
            try:
                transport = download_grib(url, target)
                decoded = decode_pressure_fields(target)
                if FieldKey("u", 850) not in decoded or FieldKey("v", 850) not in decoded:
                    raise ValueError("850-hPa U/V missing")
                fields = decoded
                selected = {"cycle": cycle, "forecast_hour": fh, "valid": valid, "error_min": error_min, "url": url}
                break
            except (HTTPError, URLError, TimeoutError, ValueError, OSError, RuntimeError) as exc:
                attempts.append({
                    "cycle": iso_utc(cycle),
                    "forecast_hour": fh,
                    "valid_time": iso_utc(valid),
                    "valid_time_error_minutes": error_min,
                    "error": f"{type(exc).__name__}: {exc}",
                })

    if fields is None or selected is None:
        return {**base, "execution_ok": False, "scientific_inflow_geometry_proven": False, "attempts": attempts}

    winds: list[dict[str, Any]] = []
    for event in events:
        parent = event["parent_centroid"]
        local = nearest_local_wind(
            fields,
            level_hpa=850,
            lon=float(parent["lon"]),
            lat=float(parent["lat"]),
        )
        event_time = parse_iso(str(event["valid_time"]))
        wind = local.to_dict()
        wind["gfs_valid_time_error_minutes_for_event"] = abs((selected["valid"] - event_time).total_seconds()) / 60.0
        winds.append(wind)

    enriched = enrich_genesis_with_inflow(events, winds)
    return {
        **base,
        "execution_ok": True,
        "scientific_inflow_geometry_proven": bool(enriched),
        "event_window": {
            "first_valid_time": iso_utc(min(event_times)),
            "last_valid_time": iso_utc(max(event_times)),
            "representative_time": iso_utc(representative),
        },
        "gfs_selection_policy": {
            "minimum_cycle_age_hours_at_latest_event": MIN_CYCLE_AGE_HOURS_AT_EVENT_TIME,
            "selection": "minimum absolute forecast-valid-time mismatch to event-window midpoint among conservative-cycle candidates",
        },
        "gfs": {
            "cycle": iso_utc(selected["cycle"]),
            "forecast_hour": selected["forecast_hour"],
            "valid_time": iso_utc(selected["valid"]),
            "representative_valid_time_error_minutes": selected["error_min"],
            "transport": transport,
            "source_url": selected["url"],
        },
        "attempts_before_success": attempts,
        "event_count": len(enriched),
        "events": enriched,
        "summary": {str(threshold): summarize(enriched, threshold) for threshold in (50, 80)},
        "interpretation": "Positive along_inflow_km means genesis toward the local 850-hPa meteorological wind-FROM/upstream side. This is not a back-building classification.",
        "gates": {
            "genesis_relative_motion_geometry": True,
            "time_aligned_gfs850": True,
            "local_850hpa_sampling": True,
            "inflow_relative_genesis_geometry": bool(enriched),
            "backbuilding_classification": False,
            "historical_validation": False,
            "risk_engine_allowed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--genesis", default="reports/scientific/radar_genesis_geometry.json")
    parser.add_argument("--output", default="reports/scientific/radar_inflow_geometry.json")
    args = parser.parse_args()
    try:
        report = run(Path(args.genesis))
    except Exception as exc:
        report = {
            "schema_version": "0.1.0",
            "phase": "1C-radar-genesis-vs-850hpa-inflow",
            "execution_ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "risk_engine_allowed": False,
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "execution_ok": report.get("execution_ok"),
        "scientific_inflow_geometry_proven": report.get("scientific_inflow_geometry_proven"),
        "gfs": report.get("gfs"),
        "summary": report.get("summary"),
        "gates": report.get("gates"),
    }, indent=2))
    print(f"report={output}")
    return 0 if report.get("execution_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
