#!/usr/bin/env python3
"""O8.1-C self-healing prospective batch collector.

GitHub Actions is a wake-up mechanism, not the scientific clock. This collector
builds deterministic UTC 15-minute slots from JMA HRPN analysis history, skips
slots already represented by successful prior batch manifests, and reconstructs
missing slots inside the audited catch-up horizon.

Each slot reuses the exact-slot O8.1-B radar replay primitives and then executes
the existing downstream descriptive feature pipeline. Raw radar PNG and GRIB
payloads are never archived. No LPZ classification or risk score is produced.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CATCHUP_HORIZON_MINUTES = 120
SETTLEMENT_LAG_MINUTES = 15
NATIVE_MAX_AGE_MINUTES = 30
MAX_SLOTS_PER_RUN = 8


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load script module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REPLAY = _load_script("lpz_o81_replay", ROOT / "scripts" / "o8_1_slot_replay_proof.py")
BUNDLE = _load_script("lpz_o81_bundle", ROOT / "scripts" / "build_prospective_feature_bundle.py")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def compact_slot(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def floor_quarter_hour(dt: datetime) -> datetime:
    dt = dt.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return dt.replace(minute=(dt.minute // 15) * 15)


def expected_slots(now: datetime, horizon_minutes: int, settlement_lag_minutes: int) -> list[datetime]:
    if horizon_minutes < 15:
        raise ValueError("catch-up horizon must be at least 15 minutes")
    newest = floor_quarter_hour(now - timedelta(minutes=settlement_lag_minutes))
    oldest_allowed = now - timedelta(minutes=horizon_minutes)
    slots: list[datetime] = []
    cursor = newest
    while cursor >= oldest_allowed:
        slots.append(cursor)
        cursor -= timedelta(minutes=15)
    return sorted(slots)


def archive_role(slot: datetime, now: datetime, native_max_age_minutes: int) -> str:
    age = (now - slot).total_seconds() / 60.0
    return "PROSPECTIVE_NATIVE" if age <= native_max_age_minutes else "PROSPECTIVE_RECOVERED"


def _safe_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def represented_slots(roots: Iterable[Path]) -> set[datetime]:
    """Read lightweight prior batch indexes and/or full slot bundles.

    Only complete, scientifically locked slots count as represented. Technical
    failures and explicit gaps remain eligible for retry while source retention
    still permits reconstruction.
    """
    represented: set[datetime] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.json"):
            payload = _safe_json(path)
            if not payload:
                continue

            slot = payload.get("collection_slot_utc")
            if (
                isinstance(slot, str)
                and payload.get("bundle_complete") is True
                and payload.get("risk_engine_allowed") is False
                and str(payload.get("collection_status", "")).startswith("COMPLETE_")
            ):
                try:
                    represented.add(parse_iso(slot))
                except ValueError:
                    pass

            for row in payload.get("slot_results") or []:
                if not isinstance(row, dict):
                    continue
                slot = row.get("collection_slot_utc")
                if (
                    isinstance(slot, str)
                    and row.get("bundle_complete") is True
                    and row.get("risk_engine_allowed") is False
                    and str(row.get("collection_status", "")).startswith("COMPLETE_")
                ):
                    try:
                        represented.add(parse_iso(slot))
                    except ValueError:
                        pass
    return represented


def write_json(path: Path, payload: dict[str, Any], *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def run_script(script: str, *args: str, timeout_seconds: int = 180) -> None:
    cmd = [sys.executable, str(ROOT / "scripts" / script), *map(str, args)]
    completed = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        stdout = completed.stdout[-4000:]
        stderr = completed.stderr[-4000:]
        raise RuntimeError(
            f"{script} failed rc={completed.returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )


def exact_decode_report(slot: datetime, morphology: dict[str, Any], tracking: dict[str, Any]) -> dict[str, Any]:
    """Record the exact HRPN decode integrity already exercised by replay.

    morphology_for_target() raises on national tile transport failures or unknown
    opaque colours; tracking_for_sequence() raises on any required z8 tile decode
    failure. This report makes that per-slot integrity explicit for the existing
    bundle contract without claiming a separate RASRF proof.
    """
    return {
        "schema_version": "0.1.0-o8.1",
        "phase": "2L-O8.1-C-exact-hrpn-decode-integrity",
        "generated_at": iso_utc(utc_now()),
        "execution_ok": morphology.get("execution_ok") is True and tracking.get("execution_ok") is True,
        "scientific_decode_proven": morphology.get("execution_ok") is True and tracking.get("execution_ok") is True,
        "target_valid_time_utc": iso_utc(slot),
        "source_product": "JMA_HRPN_ANALYSIS",
        "exact_slot_only": True,
        "rasrf_not_required_for_slot_bundle": True,
        "gates": {
            "target_frame_exact": True,
            "national_reference_scan_complete": bool((morphology.get("gates") or {}).get("national_reference_scan_complete")),
            "exact_four_frame_sequence": bool((tracking.get("gates") or {}).get("exact_four_frame_sequence")),
            "unknown_palette_colour_guard": True,
            "risk_engine_allowed": False,
        },
        "risk_engine_allowed": False,
    }


def selected_model_cycles(components: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for component_name in ("radar_wind_orientation", "radar_inflow_geometry"):
        component = components.get(component_name)
        if not isinstance(component, dict):
            continue
        gfs = component.get("gfs")
        if not isinstance(gfs, dict) or not gfs.get("cycle"):
            continue
        rows.append(
            {
                "component": component_name,
                "cycle_utc": gfs.get("cycle"),
                "forecast_hour": gfs.get("forecast_hour"),
                "forecast_valid_time_utc": gfs.get("valid_time"),
            }
        )
    return rows


def process_slot(
    *,
    slot: datetime,
    row_map: dict[datetime, dict[str, Any]],
    now: datetime,
    run_id: str,
    commit_sha: str,
    native_max_age_minutes: int,
) -> dict[str, Any]:
    sequence = REPLAY.exact_sequence(row_map, slot)
    role = archive_role(slot, now, native_max_age_minutes)
    prospective_as_of = slot + timedelta(minutes=SETTLEMENT_LAG_MINUTES)
    recovery_age = (now - slot).total_seconds() / 60.0

    with tempfile.TemporaryDirectory(prefix=f"lpz-o81-{compact_slot(slot)}-") as temp_name:
        work = Path(temp_name)
        scientific = work / "scientific"
        scientific.mkdir(parents=True, exist_ok=True)

        morphology, parent = REPLAY.morphology_for_target(sequence[-1])
        tracking = REPLAY.tracking_for_sequence(sequence, parent)
        write_json(scientific / "radar_morphology.json", morphology)
        write_json(scientific / "radar_tracking.json", tracking)
        write_json(scientific / "radar_scientific_decode.json", exact_decode_report(slot, morphology, tracking))

        run_script(
            "radar_wind_orientation_probe.py",
            "--morphology", str(scientific / "radar_morphology.json"),
            "--output", str(scientific / "radar_wind_orientation.json"),
        )

        if tracking.get("scientific_tracking_proven") is True:
            run_script(
                "radar_hierarchy_probe.py",
                "--tracking", str(scientific / "radar_tracking.json"),
                "--output", str(scientific / "radar_hierarchy.json"),
            )
            hierarchy = _safe_json(scientific / "radar_hierarchy.json") or {}
            if hierarchy.get("execution_ok") is not True or hierarchy.get("scientific_hierarchy_proven") is not True:
                raise RuntimeError("exact-slot hierarchy failed integrity checks")

            run_script(
                "radar_temporal_descriptor.py",
                "--tracking", str(scientific / "radar_tracking.json"),
                "--hierarchy", str(scientific / "radar_hierarchy.json"),
                "--output", str(scientific / "radar_temporal.json"),
            )

            if int(hierarchy.get("embedded_core_genesis_event_count") or 0) > 0:
                run_script(
                    "radar_genesis_geometry_report.py",
                    "--tracking", str(scientific / "radar_tracking.json"),
                    "--hierarchy", str(scientific / "radar_hierarchy.json"),
                    "--output", str(scientific / "radar_genesis_geometry.json"),
                )
                run_script(
                    "radar_inflow_geometry_probe.py",
                    "--genesis", str(scientific / "radar_genesis_geometry.json"),
                    "--output", str(scientific / "radar_inflow_geometry.json"),
                )
                run_script(
                    "build_parent_precursor_report.py",
                    "--temporal", str(scientific / "radar_temporal.json"),
                    "--inflow", str(scientific / "radar_inflow_geometry.json"),
                    "--output", str(scientific / "parent_precursor_features.json"),
                    "--csv-output", str(work / "parent_precursor_features.csv"),
                )

        bundle = BUNDLE.build_bundle(
            scientific_dir=scientific,
            run_id=run_id,
            commit_sha=commit_sha,
            generated_at_utc=iso_utc(now),
        )

        guard = REPLAY.gfs_asof_guard(slot)
        cycles = selected_model_cycles(bundle.get("components") or {})
        selected_cycle_guard = True
        for row in cycles:
            try:
                selected_cycle_guard = selected_cycle_guard and parse_iso(str(row["cycle_utc"])) <= prospective_as_of
            except (ValueError, TypeError):
                selected_cycle_guard = False
        as_of_pass = bool(guard.get("all_candidate_cycles_asof_safe")) and selected_cycle_guard

        if not as_of_pass:
            bundle["bundle_complete"] = False
            bundle["collection_status"] = "TECHNICAL_INCOMPLETE"
            failed = list(bundle.get("failed_components") or [])
            if "as_of_time_guard" not in failed:
                failed.append("as_of_time_guard")
            bundle["failed_components"] = sorted(failed)

        bundle.update(
            {
                "schema_version": "0.4.0",
                "phase": "2L-O8.1-C-self-healing-prospective-slot",
                "collection_slot_utc": iso_utc(slot),
                "prospective_as_of_utc": iso_utc(prospective_as_of),
                "archive_role": role,
                "recovery_age_minutes": recovery_age,
                "radar_frame_valid_times": [iso_utc(slot - timedelta(minutes=m)) for m in (15, 10, 5, 0)],
                "model_cycles": cycles,
                "as_of_time_guard_pass": as_of_pass,
                "o8_1_gfs_guard": guard,
                "raw_radar_archived": False,
                "raw_grib_archived": False,
                "lpz_classification": None,
                "risk_score": None,
                "risk_engine_allowed": False,
            }
        )

        if bundle.get("risk_engine_allowed") is not False or bundle.get("risk_score") is not None or bundle.get("lpz_classification") is not None:
            raise RuntimeError("Risk Engine lock invariant violated")

        return bundle


def technical_failure_bundle(slot: datetime, now: datetime, exc: Exception) -> dict[str, Any]:
    return {
        "schema_version": "0.4.0",
        "phase": "2L-O8.1-C-self-healing-prospective-slot",
        "generated_at_utc": iso_utc(now),
        "collection_slot_utc": iso_utc(slot),
        "prospective_as_of_utc": iso_utc(slot + timedelta(minutes=SETTLEMENT_LAG_MINUTES)),
        "archive_role": archive_role(slot, now, NATIVE_MAX_AGE_MINUTES),
        "recovery_age_minutes": (now - slot).total_seconds() / 60.0,
        "collection_status": "TECHNICAL_INCOMPLETE",
        "bundle_complete": False,
        "error": f"{type(exc).__name__}: {exc}",
        "candidate_structure_is_lpz_classification": False,
        "no_event_state_is_negative_label": False,
        "raw_radar_archived": False,
        "raw_grib_archived": False,
        "lpz_classification": None,
        "risk_score": None,
        "risk_engine_allowed": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-root", default="reports/prospective/o8_1_batch")
    ap.add_argument("--represented-root", action="append", default=[])
    ap.add_argument("--run-id", default="")
    ap.add_argument("--commit-sha", default="")
    ap.add_argument("--trigger-type", default="unknown")
    ap.add_argument("--catchup-horizon-minutes", type=int, default=CATCHUP_HORIZON_MINUTES)
    ap.add_argument("--settlement-lag-minutes", type=int, default=SETTLEMENT_LAG_MINUTES)
    ap.add_argument("--native-max-age-minutes", type=int, default=NATIVE_MAX_AGE_MINUTES)
    ap.add_argument("--max-slots", type=int, default=MAX_SLOTS_PER_RUN)
    args = ap.parse_args()

    if args.catchup_horizon_minutes > 120:
        raise SystemExit("O8.1-C catch-up horizon may not exceed the currently audited 120-minute policy candidate")
    if args.settlement_lag_minutes != SETTLEMENT_LAG_MINUTES:
        raise SystemExit("settlement lag is frozen at 15 minutes for O8.1-C")
    if args.max_slots < 1:
        raise SystemExit("max-slots must be >= 1")

    now = utc_now()
    out_root = Path(args.output_root)
    slots_dir = out_root / "slots"
    slots_dir.mkdir(parents=True, exist_ok=True)

    rows = REPLAY.TRACK.load_json(REPLAY.TRACK.NOWC_TIMES)
    if not isinstance(rows, list):
        raise SystemExit("targetTimes_N1.json was not a list")
    row_map = REPLAY.exact_analysis_rows(rows)
    source_times = sorted(row_map)
    recoverable = set(REPLAY.recoverable_slots(row_map, now))
    expected = expected_slots(now, args.catchup_horizon_minutes, args.settlement_lag_minutes)
    represented = represented_slots([Path(p) for p in args.represented_root])

    explicit_gap_slots = [slot for slot in expected if slot not in recoverable and slot not in represented]
    missing_recoverable = [slot for slot in expected if slot in recoverable and slot not in represented]
    selected = missing_recoverable[: args.max_slots]

    slot_results: list[dict[str, Any]] = []
    native_count = recovered_count = technical_failure_count = 0

    for slot in selected:
        try:
            bundle = process_slot(
                slot=slot,
                row_map=row_map,
                now=now,
                run_id=str(args.run_id),
                commit_sha=str(args.commit_sha),
                native_max_age_minutes=args.native_max_age_minutes,
            )
        except Exception as exc:
            bundle = technical_failure_bundle(slot, now, exc)

        write_json(slots_dir / f"{compact_slot(slot)}.json", bundle, compact=True)
        if bundle.get("archive_role") == "PROSPECTIVE_NATIVE":
            native_count += 1
        elif bundle.get("archive_role") == "PROSPECTIVE_RECOVERED":
            recovered_count += 1
        if bundle.get("bundle_complete") is not True:
            technical_failure_count += 1

        slot_results.append(
            {
                "collection_slot_utc": bundle.get("collection_slot_utc"),
                "archive_role": bundle.get("archive_role"),
                "collection_status": bundle.get("collection_status"),
                "bundle_complete": bundle.get("bundle_complete"),
                "as_of_time_guard_pass": bundle.get("as_of_time_guard_pass"),
                "recovery_age_minutes": bundle.get("recovery_age_minutes"),
                "risk_engine_allowed": False,
                "error": bundle.get("error"),
            }
        )

    manifest = {
        "schema_version": "1.0.0",
        "phase": "2L-O8.1-C-self-healing-batch-collector",
        "run_id": str(args.run_id),
        "commit_sha": str(args.commit_sha),
        "trigger_type": str(args.trigger_type),
        "wake_time_utc": iso_utc(now),
        "source_window_start_utc": iso_utc(source_times[0]) if source_times else None,
        "source_window_end_utc": iso_utc(source_times[-1]) if source_times else None,
        "catchup_horizon_minutes": args.catchup_horizon_minutes,
        "settlement_lag_minutes": args.settlement_lag_minutes,
        "native_max_age_minutes": args.native_max_age_minutes,
        "expected_slot_count_in_horizon": len(expected),
        "recoverable_slot_count_in_horizon": sum(slot in recoverable for slot in expected),
        "represented_slot_count_in_horizon": sum(slot in represented for slot in expected),
        "missing_recoverable_before_run": len(missing_recoverable),
        "requested_slot_count": len(selected),
        "native_slot_count": native_count,
        "recovered_slot_count": recovered_count,
        "explicit_gap_count": len(explicit_gap_slots),
        "technical_failure_count": technical_failure_count,
        "deferred_due_run_cap_count": max(0, len(missing_recoverable) - len(selected)),
        "explicit_gap_slots": [iso_utc(slot) for slot in explicit_gap_slots],
        "slot_ids": [row.get("collection_slot_utc") for row in slot_results],
        "slot_results": slot_results,
        "raw_radar_archived": False,
        "raw_grib_archived": False,
        "risk_engine_allowed": False,
        "state": (
            "PASS_SELF_HEALING_BATCH"
            if technical_failure_count == 0 and not explicit_gap_slots and len(missing_recoverable) <= len(selected)
            else "DEGRADED_SELF_HEALING_BATCH"
        ),
    }
    write_json(out_root / "batch_manifest.json", manifest)

    print(
        json.dumps(
            {
                "state": manifest["state"],
                "expected_slots": manifest["expected_slot_count_in_horizon"],
                "represented_before": manifest["represented_slot_count_in_horizon"],
                "processed": manifest["requested_slot_count"],
                "native": native_count,
                "recovered": recovered_count,
                "gaps": manifest["explicit_gap_count"],
                "technical_failures": technical_failure_count,
                "deferred_due_run_cap": manifest["deferred_due_run_cap_count"],
                "risk_engine_allowed": False,
                "output": str(out_root / "batch_manifest.json"),
            },
            indent=2,
        )
    )
    # The workflow's explicit assertion step decides operational pass/fail. The
    # collector itself returns success whenever it produced an auditable manifest.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
