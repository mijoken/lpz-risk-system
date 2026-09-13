#!/usr/bin/env python3
"""Measure replay retention for JMA HRPN analysis frames used by O8.1 catch-up.

This is an operational census. It does not classify LPZs and does not unlock the
Risk Engine. The script measures:
- metadata history in targetTimes_N1.json,
- exact 5-minute continuity,
- 15-minute scientific slots that can be reconstructed from four exact frames,
- direct PNG replay availability for old/middle/new samples,
- a conservative catch-up horizon with an explicit safety margin.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TARGET_TIMES_URL = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"
USER_AGENT = "lpz-risk-system/0.1.0 (+https://github.com/mijoken/lpz-risk-system)"
TIMEOUT_SECONDS = 20
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_TILE_BYTES = 2 * 1024 * 1024
FRAME_STEP_MINUTES = 5
TRACKING_LOOKBACK_MINUTES = 15
SETTLEMENT_LAG_MINUTES = 15
SAFETY_MARGIN_MINUTES = 30
INITIAL_POLICY_CAP_MINUTES = 120
MIN_ACCEPTABLE_CATCHUP_MINUTES = 60
PROBE_ZOOM = 6
PROBE_LON = 139.7671
PROBE_LAT = 35.6812
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_compact(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def compact(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")


def http_get(url: str, max_bytes: int, retries: int = 3) -> tuple[bytes, int, int]:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        started = time.perf_counter()
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Cache-Control": "no-cache"})
            with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
                status = int(getattr(response, "status", 200))
                body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError(f"response exceeded {max_bytes} byte limit")
            latency_ms = int((time.perf_counter() - started) * 1000)
            return body, status, latency_ms
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 4))
    assert last_exc is not None
    raise last_exc


def load_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    body, status, latency = http_get(TARGET_TIMES_URL, MAX_JSON_BYTES)
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("targetTimes payload was not a JSON list")
    rows = [r for r in payload if isinstance(r, dict)]
    return rows, {"http_status": status, "latency_ms": latency, "bytes": len(body)}


def analysis_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_valid: dict[datetime, dict[str, Any]] = {}
    for row in rows:
        elements = row.get("elements") or []
        bt = str(row.get("basetime") or "")
        vt = str(row.get("validtime") or "")
        if "hrpns" not in elements or not bt or not vt or bt != vt:
            continue
        try:
            dt = parse_compact(vt)
        except ValueError:
            continue
        by_valid[dt] = row
    return [by_valid[k] for k in sorted(by_valid)]


def trailing_continuous_times(times: list[datetime]) -> list[datetime]:
    if not times:
        return []
    available = set(times)
    current = max(times)
    out = [current]
    step = timedelta(minutes=FRAME_STEP_MINUTES)
    while current - step in available:
        current -= step
        out.append(current)
    return sorted(out)


def recoverable_slots(times: list[datetime], now: datetime) -> list[datetime]:
    available = set(times)
    settlement_cutoff = now - timedelta(minutes=SETTLEMENT_LAG_MINUTES)
    slots: list[datetime] = []
    for dt in sorted(times):
        if dt > settlement_cutoff:
            continue
        if dt.second != 0 or dt.microsecond != 0 or dt.minute % 15 != 0:
            continue
        required = [dt - timedelta(minutes=m) for m in (15, 10, 5, 0)]
        if all(x in available for x in required):
            slots.append(dt)
    return slots


def lonlat_to_xyz(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat = max(min(lat, 85.05112878), -85.05112878)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def tile_url(row: dict[str, Any], z: int, x: int, y: int) -> str:
    return (
        "https://www.jma.go.jp/bosai/jmatile/data/nowc/"
        f"{row['basetime']}/none/{row['validtime']}/surf/hrpns/{z}/{x}/{y}.png"
    )


def probe_frame(row: dict[str, Any]) -> dict[str, Any]:
    x, y = lonlat_to_xyz(PROBE_LON, PROBE_LAT, PROBE_ZOOM)
    url = tile_url(row, PROBE_ZOOM, x, y)
    out: dict[str, Any] = {
        "valid_time_utc": iso_utc(parse_compact(str(row["validtime"]))),
        "z": PROBE_ZOOM,
        "x": x,
        "y": y,
        "probe_lon": PROBE_LON,
        "probe_lat": PROBE_LAT,
        "url": url,
    }
    try:
        body, status, latency = http_get(url, MAX_TILE_BYTES)
        png_ok = body.startswith(PNG_SIGNATURE)
        out.update({
            "state": "PASS" if status == 200 and png_ok else "FAIL",
            "http_status": status,
            "latency_ms": latency,
            "bytes": len(body),
            "png_signature_ok": png_ok,
        })
    except Exception as exc:
        out.update({"state": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
    return out


def choose_probe_rows(rows: list[dict[str, Any]], continuous: list[datetime]) -> list[dict[str, Any]]:
    if not continuous:
        return []
    by_time = {parse_compact(str(r["validtime"])): r for r in rows}
    candidates = [continuous[0], continuous[len(continuous) // 2], continuous[-1]]
    unique: list[datetime] = []
    for dt in candidates:
        if dt not in unique:
            unique.append(dt)
    return [by_time[dt] for dt in unique if dt in by_time]


def floor_15(value: float) -> int:
    if value <= 0:
        return 0
    return int(value // 15) * 15


def build_report(now: datetime, rows: list[dict[str, Any]], fetch_meta: dict[str, Any]) -> dict[str, Any]:
    filtered = analysis_rows(rows)
    times = [parse_compact(str(r["validtime"])) for r in filtered]
    continuous = trailing_continuous_times(times)
    slots = recoverable_slots(continuous, now)

    latest = continuous[-1] if continuous else None
    oldest = continuous[0] if continuous else None
    metadata_span = ((latest - oldest).total_seconds() / 60.0) if latest and oldest else 0.0
    latest_age = ((now - latest).total_seconds() / 60.0) if latest else None

    oldest_slot = slots[0] if slots else None
    newest_slot = slots[-1] if slots else None
    max_recovery_age = ((now - oldest_slot).total_seconds() / 60.0) if oldest_slot else 0.0
    newest_slot_age = ((now - newest_slot).total_seconds() / 60.0) if newest_slot else None

    probe_rows = choose_probe_rows(filtered, continuous)
    probes = [probe_frame(r) for r in probe_rows]
    probe_pass = bool(probes) and all(p.get("state") == "PASS" for p in probes)

    # Keep a full 30-minute buffer inside the observed recoverable envelope and cap
    # the first production policy at two hours until repeated censuses prove stability.
    safe_by_measurement = floor_15(max_recovery_age - SAFETY_MARGIN_MINUTES)
    recommended = min(INITIAL_POLICY_CAP_MINUTES, safe_by_measurement)

    five_min_continuity_ok = len(continuous) >= 4 and all(
        int((b - a).total_seconds()) == FRAME_STEP_MINUTES * 60
        for a, b in zip(continuous[:-1], continuous[1:])
    )
    source_fresh = latest_age is not None and latest_age <= 30.0
    enough_history = recommended >= MIN_ACCEPTABLE_CATCHUP_MINUTES
    gate_pass = five_min_continuity_ok and probe_pass and source_fresh and enough_history and bool(slots)

    return {
        "schema_version": "1.0.0",
        "phase": "2L-O8.1-A-jma-source-retention-census",
        "generated_at_utc": iso_utc(now),
        "state": "PASS_RETENTION_CANDIDATE" if gate_pass else "WAIT_RETENTION_NOT_PROVEN",
        "risk_engine_allowed": False,
        "scientific_release_changed": False,
        "source": {
            "product": "JMA High-Resolution Precipitation Nowcast analysis (hrpns)",
            "target_times_url": TARGET_TIMES_URL,
            "target_times_fetch": fetch_meta,
            "analysis_rule": "elements includes hrpns AND basetime == validtime",
        },
        "frame_history": {
            "raw_row_count": len(rows),
            "analysis_frame_count": len(filtered),
            "continuous_trailing_frame_count": len(continuous),
            "frame_step_minutes": FRAME_STEP_MINUTES,
            "oldest_continuous_valid_time_utc": iso_utc(oldest),
            "latest_continuous_valid_time_utc": iso_utc(latest),
            "continuous_metadata_span_minutes": metadata_span,
            "latest_frame_age_minutes": latest_age,
            "five_minute_continuity_ok": five_min_continuity_ok,
        },
        "slot_replay": {
            "slot_grid": "UTC HH:00/15/30/45",
            "required_exact_frame_offsets_minutes": [-15, -10, -5, 0],
            "settlement_lag_minutes": SETTLEMENT_LAG_MINUTES,
            "recoverable_slot_count_in_visible_window": len(slots),
            "oldest_recoverable_slot_utc": iso_utc(oldest_slot),
            "newest_recoverable_slot_utc": iso_utc(newest_slot),
            "oldest_recoverable_slot_age_minutes": max_recovery_age if oldest_slot else None,
            "newest_recoverable_slot_age_minutes": newest_slot_age,
        },
        "direct_tile_replay_probes": {
            "all_pass": probe_pass,
            "probe_count": len(probes),
            "probes": probes,
        },
        "policy_candidate": {
            "safety_margin_minutes": SAFETY_MARGIN_MINUTES,
            "initial_policy_cap_minutes": INITIAL_POLICY_CAP_MINUTES,
            "minimum_acceptable_catchup_minutes": MIN_ACCEPTABLE_CATCHUP_MINUTES,
            "safe_horizon_from_measurement_minutes": safe_by_measurement,
            "recommended_catchup_horizon_minutes": recommended,
            "status": "CANDIDATE_ONLY_UNTIL_REPEATED_CENSUS",
        },
        "gates": {
            "source_fresh": source_fresh,
            "continuous_5min_history": five_min_continuity_ok,
            "direct_old_mid_new_tile_replay": probe_pass,
            "at_least_one_exact_15min_slot_recoverable": bool(slots),
            "catchup_horizon_at_least_60min": enough_history,
            "risk_engine_allowed": False,
        },
        "interpretation": (
            "JMA analysis history presently supports bounded self-healing catch-up; use only the "
            "candidate horizon until repeated census observations establish stability."
            if gate_pass else
            "Replay retention is not yet proven strongly enough for O8.1 production catch-up."
        ),
    }


def append_history(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    compact_row = {
        "generated_at_utc": report["generated_at_utc"],
        "state": report["state"],
        "analysis_frame_count": report["frame_history"]["analysis_frame_count"],
        "continuous_trailing_frame_count": report["frame_history"]["continuous_trailing_frame_count"],
        "continuous_metadata_span_minutes": report["frame_history"]["continuous_metadata_span_minutes"],
        "latest_frame_age_minutes": report["frame_history"]["latest_frame_age_minutes"],
        "recoverable_slot_count_in_visible_window": report["slot_replay"]["recoverable_slot_count_in_visible_window"],
        "oldest_recoverable_slot_age_minutes": report["slot_replay"]["oldest_recoverable_slot_age_minutes"],
        "direct_tile_replay_all_pass": report["direct_tile_replay_probes"]["all_pass"],
        "recommended_catchup_horizon_minutes": report["policy_candidate"]["recommended_catchup_horizon_minutes"],
        "risk_engine_allowed": False,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(compact_row, ensure_ascii=False, separators=(",", ":")) + "\n")


def self_test() -> None:
    base = datetime(2026, 9, 13, 6, 0, tzinfo=timezone.utc)
    times = [base + timedelta(minutes=5 * i) for i in range(37)]
    assert trailing_continuous_times(times) == times
    now = base + timedelta(minutes=190)
    slots = recoverable_slots(times, now)
    assert slots
    for slot in slots:
        assert slot.minute % 15 == 0
        required = [slot - timedelta(minutes=m) for m in (15, 10, 5, 0)]
        assert all(x in set(times) for x in required)
    broken = times.copy()
    del broken[-3]
    trailing = trailing_continuous_times(broken)
    assert len(trailing) == 2, trailing
    assert floor_15(134.9) == 120
    assert floor_15(135.0) == 135
    print("O8.1-A deterministic self-test: PASS")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="research/operations/o8_1_jma_retention_latest.json")
    ap.add_argument("--history-output", default="research/operations/o8_1_jma_retention_history.jsonl")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return 0

    now = utc_now()
    try:
        rows, fetch_meta = load_rows()
        report = build_report(now, rows, fetch_meta)
    except Exception as exc:
        report = {
            "schema_version": "1.0.0",
            "phase": "2L-O8.1-A-jma-source-retention-census",
            "generated_at_utc": iso_utc(now),
            "state": "FAIL_TECHNICAL",
            "risk_engine_allowed": False,
            "scientific_release_changed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_history(Path(args.history_output), report) if report.get("state") != "FAIL_TECHNICAL" else None

    print(f"O8.1-A state={report.get('state')}")
    if "frame_history" in report:
        print(f"continuous_span_minutes={report['frame_history']['continuous_metadata_span_minutes']}")
        print(f"recoverable_slots={report['slot_replay']['recoverable_slot_count_in_visible_window']}")
        print(f"tile_replay_all_pass={report['direct_tile_replay_probes']['all_pass']}")
        print(f"recommended_catchup_horizon_minutes={report['policy_candidate']['recommended_catchup_horizon_minutes']}")
    return 1 if report.get("state") == "FAIL_TECHNICAL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
