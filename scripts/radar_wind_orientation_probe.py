#!/usr/bin/env python3
"""Phase 1C proof: radar-object axis versus time-aligned GFS 600-hPa wind.

Inputs:
- radar morphology JSON produced earlier in the same workflow
- a GFS pressure-level subset whose model cycle is conservatively at least four
  hours older than the radar valid time, reducing historical availability
  leakage risk

This produces a scientific comparison feature only. No mismatch threshold is
promoted to an LPZ prediction gate.
"""

from __future__ import annotations

import argparse
import json
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

from lpz_risk.gfs_science import (  # noqa: E402
    build_science_subset_url,
    cycle_candidates,
    decode_pressure_fields,
    FieldKey,
)
from lpz_risk.orientation_science import (  # noqa: E402
    nearest_local_wind,
    orientation_consistency,
)

USER_AGENT = "lpz-risk-system/0.1.0 (+https://github.com/mijoken/lpz-risk-system)"
TIMEOUT_SECONDS = 50
MAX_BYTES = 32 * 1024 * 1024
MIN_CYCLE_AGE_HOURS_AT_RADAR_TIME = 4
MAX_FORECAST_HOUR = 18


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def download_grib(url: str, target: Path) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream,*/*"})
    with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        status = int(getattr(response, "status", 200))
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("GFS subset exceeded byte safety limit")
    if not body.startswith(b"GRIB"):
        raise ValueError(f"response did not begin with GRIB: {body[:24]!r}")
    target.write_bytes(body)
    return {"http_status": status, "bytes": len(body)}


def candidate_cycle_hours(radar_time: datetime) -> list[tuple[datetime, int, datetime, float]]:
    cutoff = radar_time - timedelta(hours=MIN_CYCLE_AGE_HOURS_AT_RADAR_TIME)
    candidates: list[tuple[datetime, int, datetime, float]] = []
    for cycle in cycle_candidates(now=radar_time, count=8):
        if cycle > cutoff:
            continue
        delta_h = (radar_time - cycle).total_seconds() / 3600.0
        fh = int(round(delta_h))
        if not (1 <= fh <= MAX_FORECAST_HOUR):
            continue
        valid = cycle + timedelta(hours=fh)
        error_min = abs((valid - radar_time).total_seconds()) / 60.0
        candidates.append((cycle, fh, valid, error_min))
    return sorted(candidates, key=lambda item: (item[3], -item[0].timestamp()))


def choose_objects(morphology: dict[str, Any]) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    for threshold in (30, 50, 80):
        block = morphology.get("threshold_results", {}).get(str(threshold), {})
        for obj in block.get("objects", []):
            if obj.get("orientation_deg") is None:
                continue
            centroid = obj.get("centroid") or {}
            if centroid.get("lon") is None or centroid.get("lat") is None:
                continue
            chosen.append({"threshold_mmph": threshold, **obj})
    return chosen


def run(morphology_path: Path) -> dict[str, Any]:
    morphology = json.loads(morphology_path.read_text(encoding="utf-8"))
    base = {
        "schema_version": "0.1.0",
        "phase": "1C-radar-wind-orientation-proof",
        "feature_id": "rainband_vs_600hpa_wind_orientation",
        "evidence_id": "SHIMAMURA2025_ORIENTATION600",
        "operational_gate": False,
        "risk_engine_allowed": False,
    }
    if not morphology.get("scientific_morphology_proven"):
        return {**base, "execution_ok": True, "scientific_orientation_proven": False, "reason": "morphology sample unavailable"}

    radar_time = parse_iso(str(morphology["frame"]["valid_time_utc"]))
    objects = choose_objects(morphology)
    if not objects:
        return {**base, "execution_ok": True, "scientific_orientation_proven": False, "reason": "no oriented radar objects"}

    attempts: list[dict[str, Any]] = []
    fields = None
    selected = None
    transport = None
    with tempfile.TemporaryDirectory(prefix="lpz-orientation-") as temp:
        target = Path(temp) / "gfs.grib2"
        for cycle, fh, valid, error_min in candidate_cycle_hours(radar_time):
            url = build_science_subset_url(cycle, forecast_hour=fh)
            try:
                transport = download_grib(url, target)
                decoded = decode_pressure_fields(target)
                if FieldKey("u", 600) not in decoded or FieldKey("v", 600) not in decoded:
                    raise ValueError("600-hPa U/V missing")
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
        return {**base, "execution_ok": False, "scientific_orientation_proven": False, "attempts": attempts}

    comparisons: list[dict[str, Any]] = []
    for obj in objects:
        centroid = obj["centroid"]
        local = nearest_local_wind(
            fields,
            level_hpa=600,
            lon=float(centroid["lon"]),
            lat=float(centroid["lat"]),
        )
        consistency = orientation_consistency(float(obj["orientation_deg"]), local.meteorological_from_deg)
        comparisons.append({
            "threshold_mmph": obj["threshold_mmph"],
            "object_id": obj["object_id"],
            "area_km2": obj["area_km2"],
            "aspect_ratio": obj["aspect_ratio"],
            "boundary_truncated": obj["boundary_truncated"],
            "centroid": centroid,
            "local_wind_600hpa": local.to_dict(),
            **consistency,
        })

    untruncated = [r for r in comparisons if not r["boundary_truncated"]]
    most_elongated = max(untruncated, key=lambda r: float(r.get("aspect_ratio") or 0.0)) if untruncated else None
    largest = max(untruncated, key=lambda r: float(r["area_km2"])) if untruncated else None

    return {
        **base,
        "execution_ok": True,
        "scientific_orientation_proven": bool(comparisons),
        "radar_valid_time": iso_utc(radar_time),
        "gfs_selection_policy": {
            "minimum_cycle_age_hours_at_radar_time": MIN_CYCLE_AGE_HOURS_AT_RADAR_TIME,
            "selection": "minimum absolute forecast-valid-time mismatch among available conservative-cycle candidates",
        },
        "gfs": {
            "cycle": iso_utc(selected["cycle"]),
            "forecast_hour": selected["forecast_hour"],
            "valid_time": iso_utc(selected["valid"]),
            "valid_time_error_minutes": selected["error_min"],
            "transport": transport,
            "source_url": selected["url"],
        },
        "attempts_before_success": attempts,
        "comparison_count": len(comparisons),
        "largest_untruncated_object": largest,
        "most_elongated_untruncated_object": most_elongated,
        "comparisons": comparisons,
        "interpretation": "Descriptive radar-axis versus local 600-hPa wind-axis consistency. No mismatch threshold is an operational LPZ gate.",
        "gates": {
            "radar_morphology": True,
            "time_aligned_gfs600": True,
            "local_wind_sampling": True,
            "orientation_comparison": bool(comparisons),
            "historical_validation": False,
            "risk_engine_allowed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--morphology", default="reports/scientific/radar_morphology.json")
    parser.add_argument("--output", default="reports/scientific/radar_wind_orientation.json")
    args = parser.parse_args()
    report = run(Path(args.morphology))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "execution_ok": report.get("execution_ok"),
        "scientific_orientation_proven": report.get("scientific_orientation_proven"),
        "gfs": report.get("gfs"),
        "gates": report.get("gates"),
    }, indent=2))
    print(f"report={output}")
    return 0 if report.get("execution_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
