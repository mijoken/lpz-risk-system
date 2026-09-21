#!/usr/bin/env python3
"""F4-9C prospective frozen head-to-head cohort cycle.

Each invocation performs one deterministic cycle:
1) initialize the 14-day cohort clock if needed;
2) verify matured previously frozen cases without changing predictions;
3) if collection is still open, capture at most one newest truly prospective
   source slot and freeze its F4-9B component forecasts;
4) write cohort status WITHOUT interim skill aggregation.

Run this script repeatedly (e.g. every 15 minutes) in the isolated F4-9B
research environment. It never tunes parameters or changes the frozen model.
"""
from __future__ import annotations

import argparse
import hashlib
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
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from capture_f4_decoded_field_archive import (  # noqa: E402
    REPLAY,
    capture as capture_field_archive,
    compact_utc,
    iso_utc,
)
from run_f4_9b_field_motion import DEFAULT_SPEC, execute as run_f4_9b  # noqa: E402
from lpz_risk.f4_9c_verification import (  # noqa: E402
    advect_component_labels,
    component_label_map,
    score_component_prediction,
)
from lpz_risk.f4_field_motion import latest_definite_ge30  # noqa: E402


TARGET_COMPARISONS = 100
MIN_DISTINCT_SLOTS = 3
MAX_COLLECTION_DAYS = 14
SETTLEMENT_LAG_MINUTES = 15
SOURCE_TARGET_AGE_MINUTES = 15
LEADS_MINUTES = (15, 30)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"expected UTC Z timestamp: {value!r}")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json_new(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2, allow_nan=False)
        fp.write("\n")


def _write_json_replace(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cohort_paths(root: Path) -> dict[str, Path]:
    return {
        "start": root / "cohort_start.json",
        "status": root / "cohort_status.json",
        "sources": root / "sources",
        "forecasts": root / "forecasts",
        "components": root / "component_forecasts",
        "cases": root / "cases",
        "verifications": root / "verifications",
        "attempts": root / "attempts",
    }


def _initialize_cohort(root: Path, spec_path: Path, now: datetime) -> dict:
    paths = _cohort_paths(root)
    root.mkdir(parents=True, exist_ok=True)
    if paths["start"].exists():
        start = _read_json(paths["start"])
        if start.get("product") != "F4_9C_PROSPECTIVE_COHORT_START":
            raise ValueError("unexpected cohort start product")
        if start.get("spec_sha256") != _sha256(spec_path):
            raise ValueError("F4-9C spec hash changed after cohort start")
        return start

    payload = {
        "schema_version": "1.0.0",
        "product": "F4_9C_PROSPECTIVE_COHORT_START",
        "research_stage": "F4-9C",
        "started_at_utc": iso_utc(now),
        "deadline_utc": iso_utc(now + timedelta(days=MAX_COLLECTION_DAYS)),
        "spec_file": str(spec_path.relative_to(ROOT)),
        "spec_sha256": _sha256(spec_path),
        "stop_rule": {
            "target_exact_future_comparisons": TARGET_COMPARISONS,
            "minimum_distinct_collection_slots": MIN_DISTINCT_SLOTS,
            "maximum_collection_days": MAX_COLLECTION_DAYS,
        },
        "comparison_unit": (
            "one non-boundary source >=30 mm/h component with >=2 pixels "
            "at one lead (+15 or +30 min from prospective as-of)"
        ),
        "interim_skill_summary_allowed": False,
        "parameter_tuning_allowed": False,
        "alternate_model_allowed": False,
        "risk_engine_allowed": False,
    }
    _write_json_new(paths["start"], payload)
    return payload


def _list_json(directory: Path) -> list[dict]:
    if not directory.exists():
        return []
    return [_read_json(path) for path in sorted(directory.glob("*.json"))]


def _case_id_from_slot(slot_utc: str) -> str:
    return _parse_utc(slot_utc).strftime("%Y%m%dT%H%M%SZ")


def _verification_map(paths: dict[str, Path]) -> dict[str, dict]:
    return {
        str(row["case_id"]): row
        for row in _list_json(paths["verifications"])
    }


def _status(root: Path, start: dict, now: datetime) -> dict:
    paths = _cohort_paths(root)
    cases = _list_json(paths["cases"])
    verifications = _verification_map(paths)

    verified_cases = [
        row for row in cases
        if verifications.get(str(row["case_id"]), {}).get("verification_status")
        == "VERIFIED_EXACT_FUTURE"
    ]
    failed_cases = [
        row for row in cases
        if verifications.get(str(row["case_id"]), {}).get("verification_status")
        == "PERMANENT_TECHNICAL_FAILURE"
    ]
    pending_cases = [
        row for row in cases
        if str(row["case_id"]) not in verifications
    ]

    verified_comparisons = sum(
        int(verifications[str(row["case_id"])]["comparison_count"])
        for row in verified_cases
    )
    pending_planned = sum(
        int(row["planned_comparison_count"]) for row in pending_cases
    )
    planned_available = verified_comparisons + pending_planned
    verified_slots = len(verified_cases)
    active_planned_slots = len(verified_cases) + len(pending_cases)

    deadline = _parse_utc(start["deadline_utc"])
    target_planned = (
        planned_available >= TARGET_COMPARISONS
        and active_planned_slots >= MIN_DISTINCT_SLOTS
    )
    verified_target_met = (
        verified_comparisons >= TARGET_COMPARISONS
        and verified_slots >= MIN_DISTINCT_SLOTS
    )
    deadline_reached = now >= deadline

    if verified_target_met:
        state = "READY_FOR_F4_9D_TARGET_MET"
    elif deadline_reached and not pending_cases:
        state = "READY_FOR_F4_9D_DEADLINE"
    elif deadline_reached:
        state = "DEADLINE_STOP_AWAITING_PENDING_VERIFICATION"
    elif target_planned:
        state = "TARGET_PLANNED_AWAITING_VERIFICATION"
    else:
        state = "COLLECTING"

    collection_open = state == "COLLECTING"
    return {
        "schema_version": "1.0.0",
        "product": "F4_9C_PROSPECTIVE_COHORT_STATUS",
        "research_stage": "F4-9C",
        "generated_at_utc": iso_utc(now),
        "cohort_started_at_utc": start["started_at_utc"],
        "deadline_utc": start["deadline_utc"],
        "state": state,
        "collection_open": collection_open,
        "case_count": len(cases),
        "verified_case_count": len(verified_cases),
        "pending_case_count": len(pending_cases),
        "permanent_technical_failure_case_count": len(failed_cases),
        "verified_comparison_count": verified_comparisons,
        "pending_planned_comparison_count": pending_planned,
        "verified_plus_pending_comparison_count": planned_available,
        "verified_distinct_slot_count": verified_slots,
        "verified_plus_pending_distinct_slot_count": active_planned_slots,
        "target_comparisons": TARGET_COMPARISONS,
        "minimum_distinct_slots": MIN_DISTINCT_SLOTS,
        "deadline_reached": deadline_reached,
        "interim_skill_summary_emitted": False,
        "parameter_tuning_performed": False,
        "risk_engine_allowed": False,
    }


def _resolve_latest_prospective_source(now: datetime) -> datetime:
    rows = REPLAY.TRACK.load_json(REPLAY.TRACK.NOWC_TIMES)
    if not isinstance(rows, list):
        raise ValueError("targetTimes_N1.json was not a list")
    row_map = REPLAY.exact_analysis_rows(rows)
    slots = REPLAY.recoverable_slots(row_map, now)
    return REPLAY.resolve_target(
        slots,
        now,
        explicit="",
        target_age_minutes=SOURCE_TARGET_AGE_MINUTES,
    )


def _capture_case(
    root: Path,
    spec_path: Path,
    now: datetime,
) -> dict[str, Any]:
    paths = _cohort_paths(root)
    source_slot = _resolve_latest_prospective_source(now)
    as_of = source_slot + timedelta(minutes=SETTLEMENT_LAG_MINUTES)
    target15 = as_of + timedelta(minutes=15)
    target30 = as_of + timedelta(minutes=30)
    case_id = compact_utc(source_slot)

    case_path = paths["cases"] / f"{case_id}.json"
    if case_path.exists():
        return {"action": "NOOP_ALREADY_CAPTURED", "case_id": case_id}

    if now < as_of:
        raise RuntimeError("source slot is not yet at prospective as-of")
    if now >= target15:
        raise RuntimeError(
            "latest recoverable source is already at/after +15 target; "
            "refusing non-prospective capture"
        )

    capture_started = _utc_now()
    source_manifest = capture_field_archive(
        target_valid_time=iso_utc(source_slot),
        target_age_minutes=SOURCE_TARGET_AGE_MINUTES,
        output_root=paths["sources"],
    )
    source_dir = paths["sources"] / f"{case_id}_z{source_manifest['fixed_mosaic']['zoom']}"
    forecast_dir = paths["forecasts"] / f"{case_id}_z8_f4_9b"
    forecast_manifest = run_f4_9b(source_dir, forecast_dir, spec_path)

    with np.load(source_dir / "decoded_field.npz") as payload:
        class_index = np.asarray(payload["class_index"])
    with np.load(forecast_dir / "field_motion_forecast.npz") as payload:
        velocity = np.asarray(payload["velocity_pixels_per_timestep"])

    source_event = latest_definite_ge30(class_index)
    source_labels, source_components = component_label_map(
        source_event,
        exclude_boundary=True,
        min_pixels=2,
    )

    attempt = {
        "schema_version": "1.0.0",
        "product": "F4_9C_CAPTURE_ATTEMPT",
        "case_id": case_id,
        "source_slot_utc": iso_utc(source_slot),
        "prospective_as_of_utc": iso_utc(as_of),
        "capture_started_at_utc": iso_utc(capture_started),
        "eligible_source_component_count": len(source_components),
        "risk_engine_allowed": False,
    }

    if not source_components:
        attempt["status"] = "NO_ELIGIBLE_SOURCE_COMPONENT"
        attempt["completed_at_utc"] = iso_utc(_utc_now())
        _write_json_new(paths["attempts"] / f"{case_id}_no_event.json", attempt)
        return {"action": "NO_ELIGIBLE_SOURCE_COMPONENT", "case_id": case_id}

    spec = _read_json(spec_path)
    extrap = spec["extrapolation"]
    forecast_labels = advect_component_labels(
        source_labels,
        velocity,
        timesteps=[int(v) for v in extrap["timesteps"]],
        vel_timestep=float(extrap["vel_timestep"]),
        outval=float(extrap["outval"]),
        n_iter=int(extrap["n_iter"]),
        velocity_interp_order=int(extrap["velocity_interp_order"]),
    )

    completed = _utc_now()
    if completed >= target15:
        attempt["status"] = "LATE_CAPTURE_EXCLUDED"
        attempt["completed_at_utc"] = iso_utc(completed)
        _write_json_new(paths["attempts"] / f"{case_id}_late.json", attempt)
        return {"action": "LATE_CAPTURE_EXCLUDED", "case_id": case_id}

    components_path = paths["components"] / f"{case_id}.npz"
    components_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        components_path,
        source_component_labels=source_labels,
        forecast_component_labels=forecast_labels,
        lead_minutes=np.asarray(LEADS_MINUTES, dtype=np.int16),
        target_valid_time_unix_s=np.asarray(
            [int(target15.timestamp()), int(target30.timestamp())],
            dtype=np.int64,
        ),
    )

    component_rows = [
        {
            "component_id": int(row["component_id"]),
            "pixel_count": int(row["pixel_count"]),
            "boundary_truncated": bool(row["boundary_truncated"]),
        }
        for row in source_components
    ]
    case = {
        "schema_version": "1.0.0",
        "product": "F4_9C_PROSPECTIVE_CASE",
        "research_stage": "F4-9C",
        "case_id": case_id,
        "source_slot_utc": iso_utc(source_slot),
        "prospective_as_of_utc": iso_utc(as_of),
        "target_valid_time_utc": [iso_utc(target15), iso_utc(target30)],
        "lead_minutes_from_as_of": list(LEADS_MINUTES),
        "capture_started_at_utc": iso_utc(capture_started),
        "capture_completed_at_utc": iso_utc(completed),
        "captured_before_first_target": True,
        "source_archive_dir": str(source_dir),
        "field_motion_forecast_dir": str(forecast_dir),
        "component_forecast_file": str(components_path),
        "source_decoded_field_sha256": source_manifest["storage"]["sha256"],
        "field_motion_forecast_sha256": forecast_manifest["forecast_sha256"],
        "component_forecast_sha256": _sha256(components_path),
        "spec_sha256": _sha256(spec_path),
        "fixed_mosaic": source_manifest["fixed_mosaic"],
        "discovery_parent": source_manifest["discovery_parent"],
        "source_component_min_pixels": 2,
        "source_boundary_components_excluded": True,
        "source_component_count": len(component_rows),
        "source_components": component_rows,
        "planned_comparison_count": len(component_rows) * len(LEADS_MINUTES),
        "identity_required": False,
        "future_observations_read_at_capture": False,
        "forecast_skill_scored_at_capture": False,
        "parameter_tuning_performed": False,
        "risk_engine_allowed": False,
    }
    _write_json_new(case_path, case)
    attempt["status"] = "PROSPECTIVE_CASE_FROZEN"
    attempt["completed_at_utc"] = iso_utc(completed)
    attempt["planned_comparison_count"] = case["planned_comparison_count"]
    _write_json_new(paths["attempts"] / f"{case_id}_captured.json", attempt)
    return {
        "action": "PROSPECTIVE_CASE_FROZEN",
        "case_id": case_id,
        "planned_comparison_count": case["planned_comparison_count"],
    }


def _target_rows(now: datetime) -> tuple[dict[datetime, dict], datetime | None]:
    rows = REPLAY.TRACK.load_json(REPLAY.TRACK.NOWC_TIMES)
    if not isinstance(rows, list):
        raise ValueError("targetTimes_N1.json was not a list")
    row_map = REPLAY.exact_analysis_rows(rows)
    oldest = min(row_map) if row_map else None
    return row_map, oldest


def _target_components(class_index: np.ndarray) -> list[dict[str, Any]]:
    mask = latest_definite_ge30(class_index[None, ...]) if class_index.ndim == 2 else None
    if mask is None:
        raise ValueError("target class_index must be 2-D")
    _labels, rows = component_label_map(
        mask,
        exclude_boundary=True,
        min_pixels=2,
    )
    return rows


def _verify_case(
    case: dict,
    paths: dict[str, Path],
    row_map: dict[datetime, dict],
    oldest_available: datetime | None,
    now: datetime,
) -> dict[str, Any] | None:
    case_id = str(case["case_id"])
    output = paths["verifications"] / f"{case_id}.json"
    if output.exists():
        return None

    targets = [_parse_utc(value) for value in case["target_valid_time_utc"]]
    maturity = targets[-1] + timedelta(minutes=SETTLEMENT_LAG_MINUTES)
    if now < maturity:
        return None

    missing = [target for target in targets if target not in row_map]
    if missing:
        permanently_missing = (
            oldest_available is not None
            and all(target < oldest_available for target in missing)
        )
        if not permanently_missing:
            return None
        failure = {
            "schema_version": "1.0.0",
            "product": "F4_9C_CASE_VERIFICATION",
            "case_id": case_id,
            "verification_status": "PERMANENT_TECHNICAL_FAILURE",
            "reason": "EXACT_FUTURE_FRAME_ROLLED_OUT_OR_MISSING",
            "missing_target_valid_time_utc": [iso_utc(value) for value in missing],
            "comparison_count": 0,
            "risk_engine_allowed": False,
        }
        _write_json_new(output, failure)
        return failure

    source_dir = Path(case["source_archive_dir"])
    with np.load(source_dir / "decoded_field.npz") as source_payload:
        source_shape = np.asarray(source_payload["class_index"]).shape[1:]
    with np.load(Path(case["component_forecast_file"])) as payload:
        source_labels = np.asarray(payload["source_component_labels"])
        forecast_labels = np.asarray(payload["forecast_component_labels"])
        lead_minutes = np.asarray(payload["lead_minutes"]).tolist()

    if tuple(source_labels.shape) != tuple(source_shape):
        raise ValueError("source label map shape mismatch")
    if forecast_labels.shape != (2, *source_labels.shape):
        raise ValueError("forecast component label shape mismatch")
    if lead_minutes != list(LEADS_MINUTES):
        raise ValueError("component forecast lead mismatch")

    fixed = case["fixed_mosaic"]
    parent = case["discovery_parent"]
    target_component_sets: list[list[dict[str, Any]]] = []

    for target in targets:
        row = row_map[target]
        mosaic, meta = REPLAY.TRACK.build_fixed_mosaic(
            row,
            int(parent["x"]),
            int(parent["y"]),
        )
        if tuple(mosaic.shape) != tuple(source_labels.shape):
            raise ValueError("future target mosaic shape mismatch")
        if (
            int(meta["origin_tile_x"]) != int(fixed["origin_tile_x"])
            or int(meta["origin_tile_y"]) != int(fixed["origin_tile_y"])
            or int(meta["tile_count"]) != int(fixed["tile_count"])
        ):
            raise ValueError("future target fixed mosaic geometry mismatch")
        target_component_sets.append(_target_components(mosaic))

    rows = []
    height, width = source_labels.shape
    for source_component in case["source_components"]:
        component_id = int(source_component["component_id"])
        persistence_flat = np.flatnonzero(source_labels == component_id).astype(
            np.int64
        )
        for lead_index, lead in enumerate(LEADS_MINUTES):
            predicted_flat = np.flatnonzero(
                forecast_labels[lead_index] == component_id
            ).astype(np.int64)
            targets_for_lead = target_component_sets[lead_index]
            optical = score_component_prediction(
                predicted_flat,
                targets_for_lead,
                height=height,
                width=width,
                zoom=int(fixed["zoom"]),
                origin_tile_x=int(fixed["origin_tile_x"]),
                origin_tile_y=int(fixed["origin_tile_y"]),
            )
            persistence = score_component_prediction(
                persistence_flat,
                targets_for_lead,
                height=height,
                width=width,
                zoom=int(fixed["zoom"]),
                origin_tile_x=int(fixed["origin_tile_x"]),
                origin_tile_y=int(fixed["origin_tile_y"]),
            )
            rows.append(
                {
                    "source_component_id": component_id,
                    "source_pixel_count": int(source_component["pixel_count"]),
                    "lead_minutes_from_as_of": int(lead),
                    "target_valid_time_utc": case["target_valid_time_utc"][
                        lead_index
                    ],
                    "target_nonboundary_component_count": len(targets_for_lead),
                    "optical_flow": optical,
                    "persistence": persistence,
                    "paired_best_iou_delta": (
                        float(optical["best_iou"])
                        - float(persistence["best_iou"])
                    ),
                    "paired_nearest_centroid_distance_delta_km": (
                        float(optical["nearest_target_centroid_distance_km"])
                        - float(
                            persistence["nearest_target_centroid_distance_km"]
                        )
                    ),
                }
            )

    verification = {
        "schema_version": "1.0.0",
        "product": "F4_9C_CASE_VERIFICATION",
        "research_stage": "F4-9C",
        "case_id": case_id,
        "verification_status": "VERIFIED_EXACT_FUTURE",
        "verified_at_utc": iso_utc(now),
        "source_slot_utc": case["source_slot_utc"],
        "prospective_as_of_utc": case["prospective_as_of_utc"],
        "lead_minutes_from_as_of": list(LEADS_MINUTES),
        "comparison_count": len(rows),
        "comparisons": rows,
        "identity_required": False,
        "interim_skill_summary_emitted": False,
        "parameter_tuning_performed": False,
        "risk_engine_allowed": False,
        "validated_forecast": False,
    }
    _write_json_new(output, verification)
    return verification


def _verify_matured(root: Path, now: datetime) -> dict[str, int]:
    paths = _cohort_paths(root)
    cases = _list_json(paths["cases"])
    if not cases:
        return {"verified_now": 0, "failed_now": 0}

    row_map, oldest = _target_rows(now)
    verified_now = 0
    failed_now = 0
    for case in cases:
        result = _verify_case(case, paths, row_map, oldest, now)
        if result is None:
            continue
        if result["verification_status"] == "VERIFIED_EXACT_FUTURE":
            verified_now += 1
        else:
            failed_now += 1
    return {"verified_now": verified_now, "failed_now": failed_now}


def run_cycle(root: Path, spec_path: Path) -> dict[str, Any]:
    now = _utc_now()
    start = _initialize_cohort(root, spec_path, now)
    verification_actions = _verify_matured(root, now)
    status_before = _status(root, start, now)

    capture_action: dict[str, Any] = {"action": "COLLECTION_CLOSED"}
    if status_before["collection_open"]:
        capture_action = _capture_case(root, spec_path, _utc_now())

    final_now = _utc_now()
    status = _status(root, start, final_now)
    _write_json_replace(_cohort_paths(root)["status"], status)
    return {
        "verification_actions": verification_actions,
        "capture_action": capture_action,
        "status": status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-root", required=True, type=Path)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    args = parser.parse_args()

    result = run_cycle(args.cohort_root, args.spec)
    print(
        json.dumps(
            {
                "verification_actions": result["verification_actions"],
                "capture_action": result["capture_action"],
                "status": result["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
