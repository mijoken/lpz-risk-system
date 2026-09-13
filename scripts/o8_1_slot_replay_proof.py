#!/usr/bin/env python3
"""O8.1-B proof that a historical 15-minute slot can be replayed deterministically.

The proof reuses the audited radar morphology/tracking primitives but replaces their
"pick latest settled rainy frame" policy with an exact slot contract:

    slot-15m, slot-10m, slot-5m, slot

No newer radar frame may substitute for a missing requested frame. The proof also
audits the existing conservative GFS cycle policy against a prospective as-of time.
This is operational replay evidence only; Risk Engine remains locked.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.radar_morphology import ALLOWED_EXACT_THRESHOLDS_MMPH, extract_objects_from_mosaic

SETTLEMENT_LAG_MINUTES = 15
DEFAULT_TARGET_AGE_MINUTES = 60


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load script module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MORPH = _load_script("lpz_o81_morph_probe", ROOT / "scripts" / "radar_morphology_probe.py")
TRACK = _load_script("lpz_o81_tracking_probe", ROOT / "scripts" / "radar_tracking_probe.py")
ORIENT = _load_script("lpz_o81_orientation_probe", ROOT / "scripts" / "radar_wind_orientation_probe.py")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z") or "T" in value:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def exact_analysis_rows(rows: list[dict[str, Any]]) -> dict[datetime, dict[str, Any]]:
    out: dict[datetime, dict[str, Any]] = {}
    for row in rows:
        bt = str(row.get("basetime") or "")
        vt = str(row.get("validtime") or "")
        if "hrpns" not in (row.get("elements") or []) or not bt or bt != vt:
            continue
        try:
            out[TRACK.parse_compact(vt)] = row
        except ValueError:
            continue
    return out


def recoverable_slots(row_map: dict[datetime, dict[str, Any]], now: datetime) -> list[datetime]:
    settled = now - timedelta(minutes=SETTLEMENT_LAG_MINUTES)
    out: list[datetime] = []
    for slot in sorted(row_map):
        if slot > settled or slot.minute % 15 != 0 or slot.second != 0:
            continue
        required = [slot - timedelta(minutes=m) for m in (15, 10, 5, 0)]
        if all(dt in row_map for dt in required):
            out.append(slot)
    return out


def resolve_target(slots: list[datetime], now: datetime, explicit: str, target_age_minutes: int) -> datetime:
    if explicit:
        target = parse_time(explicit)
        if target not in slots:
            raise ValueError(f"requested target slot is not exactly recoverable from current source window: {iso_utc(target)}")
        return target
    cutoff = now - timedelta(minutes=target_age_minutes)
    eligible = [slot for slot in slots if slot <= cutoff]
    if not eligible:
        raise ValueError(f"no recoverable slot at least {target_age_minutes} minutes old")
    return max(eligible)


def exact_sequence(row_map: dict[datetime, dict[str, Any]], slot: datetime) -> list[dict[str, Any]]:
    required = [slot - timedelta(minutes=m) for m in (15, 10, 5, 0)]
    missing = [dt for dt in required if dt not in row_map]
    if missing:
        raise ValueError(f"exact slot sequence missing frames: {[iso_utc(x) for x in missing]}")
    return [row_map[dt] for dt in required]


def morphology_for_target(target_row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    tiles = MORPH.japan_tiles(MORPH.DISCOVERY_ZOOM)
    inspected = MORPH.inspect_many(target_row, MORPH.DISCOVERY_ZOOM, tiles)
    failures = [r for r in inspected if not r.get("ok")]
    good = [r for r in inspected if r.get("ok")]
    if failures:
        raise RuntimeError(f"national target-frame discovery had {len(failures)} tile failures")
    unknown = sum(int(r.get("unknown_opaque_pixels", 0)) for r in good)
    if unknown:
        raise RuntimeError(f"national target-frame discovery had {unknown} unknown opaque pixels")
    rainy = [r for r in good if int(r.get("precipitation_pixels", 0)) > 0]
    if not rainy:
        return {
            "execution_ok": True,
            "scientific_morphology_proven": False,
            "sample_status": "NO_PRECIPITATION_AT_TARGET",
            "frame": {
                "basetime": target_row["basetime"],
                "validtime": target_row["validtime"],
                "valid_time_utc": iso_utc(TRACK.parse_compact(str(target_row["validtime"]))),
            },
            "national_discovery": {
                "tiles_attempted": len(inspected),
                "tiles_ok": len(good),
                "tiles_with_precipitation": 0,
            },
            "threshold_results": {},
            "gates": {
                "target_frame_exact": True,
                "national_reference_scan_complete": True,
                "object_geometry": False,
                "risk_engine_allowed": False,
            },
        }, None

    parent = max(rainy, key=lambda r: (int(r["max_class_index"]), int(r["precipitation_pixels"])))
    mosaic, meta = MORPH.build_z8_mosaic(target_row, parent)
    threshold_results: dict[str, Any] = {}
    any_object = False
    for threshold in ALLOWED_EXACT_THRESHOLDS_MMPH:
        objects = extract_objects_from_mosaic(
            mosaic,
            zoom=MORPH.MORPHOLOGY_ZOOM,
            origin_tile_x=int(meta["origin_tile_x"]),
            origin_tile_y=int(meta["origin_tile_y"]),
            threshold_mmph=threshold,
            min_pixels=2,
        )
        any_object = any_object or bool(objects)
        threshold_results[str(int(threshold))] = {
            "object_count": len(objects),
            "objects": [obj.to_dict() for obj in objects[:25]],
        }

    report = {
        "execution_ok": True,
        "scientific_morphology_proven": any_object,
        "sample_status": "OBJECTS_EXTRACTED" if any_object else "RAIN_PRESENT_BUT_NO_30PLUS_OBJECT",
        "frame": {
            "basetime": target_row["basetime"],
            "validtime": target_row["validtime"],
            "valid_time_utc": iso_utc(TRACK.parse_compact(str(target_row["validtime"]))),
        },
        "national_discovery": {
            "tiles_attempted": len(inspected),
            "tiles_ok": len(good),
            "tiles_with_precipitation": len(rainy),
        },
        "discovery_parent": {
            "z": MORPH.DISCOVERY_ZOOM,
            "x": int(parent["x"]),
            "y": int(parent["y"]),
            "precipitation_pixels": int(parent["precipitation_pixels"]),
            "max_class_index": int(parent["max_class_index"]),
        },
        "mosaic": meta,
        "threshold_results": threshold_results,
        "gates": {
            "target_frame_exact": True,
            "national_reference_scan_complete": True,
            "z8_mosaic": True,
            "object_geometry": any_object,
            "risk_engine_allowed": False,
        },
    }
    return report, report["discovery_parent"]


def tracking_for_sequence(sequence: list[dict[str, Any]], parent: dict[str, Any] | None) -> dict[str, Any]:
    frame_times = [TRACK.parse_compact(str(r["validtime"])) for r in sequence]
    if parent is None:
        return {
            "execution_ok": True,
            "scientific_tracking_proven": False,
            "sample_status": "NO_PRECIPITATION_AT_TARGET",
            "frame_valid_times": [iso_utc(dt) for dt in frame_times],
            "tracking": {},
            "gates": {
                "exact_four_frame_sequence": True,
                "national_reference_scan_complete": True,
                "fixed_multiframe_mosaic": False,
                "component_tracking": False,
                "risk_engine_allowed": False,
            },
        }

    parent_x = int(parent["x"])
    parent_y = int(parent["y"])
    frames: list[dict[str, Any]] = []
    origin_x = origin_y = None
    for row in sequence:
        mosaic, meta = TRACK.build_fixed_mosaic(row, parent_x, parent_y)
        if origin_x is None:
            origin_x = int(meta["origin_tile_x"])
            origin_y = int(meta["origin_tile_y"])
        elif int(meta["origin_tile_x"]) != origin_x or int(meta["origin_tile_y"]) != origin_y:
            raise RuntimeError("fixed z8 mosaic origin changed across exact replay frames")
        frames.append({"row": row, "valid_dt": TRACK.parse_compact(str(row["validtime"])), "mosaic": mosaic, "meta": meta})

    assert origin_x is not None and origin_y is not None
    tracking = {
        str(int(threshold)): TRACK.track_threshold(frames, threshold, origin_x, origin_y)
        for threshold in ALLOWED_EXACT_THRESHOLDS_MMPH
    }
    any_match = any(
        any(t["primary_match_count"] > 0 for t in block["transitions"])
        for block in tracking.values()
    )
    return {
        "execution_ok": True,
        "scientific_tracking_proven": any_match,
        "sample_status": "TRACKABLE_COMPONENT_PRESENT" if any_match else "COMPLETE_NO_TRACKABLE_EVENT_CANDIDATE",
        "frame_valid_times": [iso_utc(f["valid_dt"]) for f in frames],
        "frame_interval_seconds": 300,
        "tracking": tracking,
        "fixed_mosaic": {
            "zoom": TRACK.TRACKING_ZOOM,
            "origin_tile_x": origin_x,
            "origin_tile_y": origin_y,
            "tile_count": 16,
        },
        "gates": {
            "exact_four_frame_sequence": True,
            "fixed_multiframe_mosaic": True,
            "component_tracking": any_match,
            "risk_engine_allowed": False,
        },
    }


def summarize_morphology(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_ok": report.get("execution_ok"),
        "scientific_morphology_proven": report.get("scientific_morphology_proven"),
        "sample_status": report.get("sample_status"),
        "frame": report.get("frame"),
        "national_discovery": report.get("national_discovery"),
        "object_counts": {
            key: int((block or {}).get("object_count") or 0)
            for key, block in (report.get("threshold_results") or {}).items()
        },
        "gates": report.get("gates"),
    }


def summarize_tracking(report: dict[str, Any]) -> dict[str, Any]:
    match_counts: dict[str, int] = {}
    for key, block in (report.get("tracking") or {}).items():
        match_counts[key] = sum(int(t.get("primary_match_count") or 0) for t in block.get("transitions", []))
    return {
        "execution_ok": report.get("execution_ok"),
        "scientific_tracking_proven": report.get("scientific_tracking_proven"),
        "sample_status": report.get("sample_status"),
        "frame_valid_times": report.get("frame_valid_times"),
        "primary_match_counts": match_counts,
        "gates": report.get("gates"),
    }


def gfs_asof_guard(slot: datetime) -> dict[str, Any]:
    prospective_as_of = slot + timedelta(minutes=SETTLEMENT_LAG_MINUTES)
    candidates = ORIENT.candidate_cycle_hours(slot)
    rows = []
    for cycle, fh, valid, error_min in candidates:
        conservative_age_ok = cycle <= slot - timedelta(hours=ORIENT.MIN_CYCLE_AGE_HOURS_AT_RADAR_TIME)
        as_of_ok = cycle <= prospective_as_of
        rows.append({
            "cycle_utc": iso_utc(cycle),
            "forecast_hour": fh,
            "forecast_valid_time_utc": iso_utc(valid),
            "valid_time_error_minutes": error_min,
            "conservative_cycle_age_guard_pass": conservative_age_ok,
            "prospective_as_of_guard_pass": as_of_ok,
        })
    return {
        "prospective_as_of_utc": iso_utc(prospective_as_of),
        "minimum_cycle_age_hours_at_slot": ORIENT.MIN_CYCLE_AGE_HOURS_AT_RADAR_TIME,
        "candidate_count": len(rows),
        "all_candidate_cycles_asof_safe": bool(rows) and all(r["conservative_cycle_age_guard_pass"] and r["prospective_as_of_guard_pass"] for r in rows),
        "candidates": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target-valid-time", default="")
    ap.add_argument("--target-age-minutes", type=int, default=DEFAULT_TARGET_AGE_MINUTES)
    ap.add_argument("--output", default="research/operations/o8_1_slot_replay_latest.json")
    ap.add_argument("--detail-dir", default="reports/operations/o8_1_slot_replay")
    args = ap.parse_args()

    now = utc_now()
    detail_dir = Path(args.detail_dir)
    detail_dir.mkdir(parents=True, exist_ok=True)
    try:
        rows = TRACK.load_json(TRACK.NOWC_TIMES)
        if not isinstance(rows, list):
            raise ValueError("targetTimes_N1.json was not a list")
        row_map = exact_analysis_rows(rows)
        slots = recoverable_slots(row_map, now)
        target = resolve_target(slots, now, args.target_valid_time, args.target_age_minutes)
        sequence = exact_sequence(row_map, target)

        morphology, parent = morphology_for_target(sequence[-1])
        tracking = tracking_for_sequence(sequence, parent)
        guard = gfs_asof_guard(target)

        (detail_dir / "morphology.json").write_text(json.dumps(morphology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (detail_dir / "tracking.json").write_text(json.dumps(tracking, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        expected_times = [iso_utc(target - timedelta(minutes=m)) for m in (15, 10, 5, 0)]
        exact_match = tracking.get("frame_valid_times") == expected_times
        target_age = (now - target).total_seconds() / 60.0
        role = "PROSPECTIVE_RECOVERED" if target_age > 30.0 else "PROSPECTIVE_NATIVE"
        pass_gate = (
            morphology.get("execution_ok") is True
            and tracking.get("execution_ok") is True
            and exact_match
            and guard["all_candidate_cycles_asof_safe"] is True
        )
        report = {
            "schema_version": "1.0.0",
            "phase": "2L-O8.1-B-slot-addressable-replay-proof",
            "generated_at_utc": iso_utc(now),
            "state": "PASS_SLOT_REPLAY" if pass_gate else "FAIL_SLOT_REPLAY",
            "collection_slot_utc": iso_utc(target),
            "prospective_as_of_utc": guard["prospective_as_of_utc"],
            "archive_role_candidate": role,
            "recovery_age_minutes": target_age,
            "requested_exact_frame_times": expected_times,
            "exact_frame_sequence_match": exact_match,
            "morphology": summarize_morphology(morphology),
            "tracking": summarize_tracking(tracking),
            "gfs_as_of_guard": guard,
            "raw_radar_archived": False,
            "raw_grib_archived": False,
            "lpz_classification": None,
            "risk_score": None,
            "risk_engine_allowed": False,
            "interpretation": "Exact historical-slot replay proof only. No newer radar frame or future model cycle may substitute for the requested slot.",
        }
    except Exception as exc:
        report = {
            "schema_version": "1.0.0",
            "phase": "2L-O8.1-B-slot-addressable-replay-proof",
            "generated_at_utc": iso_utc(now),
            "state": "FAIL_TECHNICAL",
            "error": f"{type(exc).__name__}: {exc}",
            "lpz_classification": None,
            "risk_score": None,
            "risk_engine_allowed": False,
        }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": report.get("state"),
        "collection_slot_utc": report.get("collection_slot_utc"),
        "archive_role_candidate": report.get("archive_role_candidate"),
        "exact_frame_sequence_match": report.get("exact_frame_sequence_match"),
        "gfs_as_of_safe": (report.get("gfs_as_of_guard") or {}).get("all_candidate_cycles_asof_safe"),
        "risk_engine_allowed": report.get("risk_engine_allowed"),
    }, indent=2))
    return 0 if report.get("state") == "PASS_SLOT_REPLAY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
