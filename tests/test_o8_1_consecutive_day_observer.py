from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "o81e_observer", ROOT / "scripts" / "observe_consecutive_daily_completeness.py"
)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def write_manifest(
    root: Path,
    day: str,
    *,
    complete: int = 96,
    native: int = 96,
    recovered: int = 0,
    technical: int = 0,
    gaps: int = 0,
    phase: str = "2L-O8.1-D-daily-consolidation-v2",
    risk_engine_allowed: bool = False,
) -> Path:
    y, mon, _ = day.split("-")
    path = root / "research" / "prospective" / y / mon / f"{day}.manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "2.0.0",
        "phase": phase,
        "date_utc": day,
        "scientific_clock": "collection_slot_utc",
        "expected_15min_intervals": 96,
        "canonical_slot_count": 96,
        "complete_slot_count": complete,
        "native_complete_slot_count": native,
        "recovered_complete_slot_count": recovered,
        "technical_incomplete_slot_count": technical,
        "explicit_gap_count": gaps,
        "duplicate_slot_count": 0,
        "coverage_fraction": complete / 96,
        "parse_error_count": 0,
        "canonical_day_quality": "COMPLETE_96_OF_96" if complete == 96 and technical == 0 and gaps == 0 else "INCOMPLETE_EXPLICIT_GAPS",
        "closure_eligible_96_of_96": complete == 96 and technical == 0 and gaps == 0,
        "archive_role": "PROSPECTIVE_CANONICAL_DAILY",
        "raw_radar_archived": False,
        "raw_grib_archived": False,
        "lpz_classification": None,
        "risk_score": None,
        "risk_engine_allowed": risk_engine_allowed,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def as_of() -> datetime:
    return datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)


def test_two_latest_complete_days_pass(tmp_path: Path) -> None:
    write_manifest(tmp_path, "2026-09-13")
    write_manifest(tmp_path, "2026-09-12")
    report = m.observe(tmp_path, as_of=as_of(), required_days=2, history_days=4)
    assert report["gate_passed"] is True
    assert report["current_consecutive_complete_day_streak"] == 2
    assert report["state"] == "PASS_REQUIRED_CONSECUTIVE_COMPLETE_DAYS"
    assert report["ready_for_o8_1_f_final_cutover_audit"] is True
    assert report["windows_task_may_be_disabled"] is False
    assert report["risk_engine_allowed"] is False


def test_95_of_96_is_not_good_enough(tmp_path: Path) -> None:
    write_manifest(tmp_path, "2026-09-13", complete=95, native=95, gaps=1)
    write_manifest(tmp_path, "2026-09-12")
    report = m.observe(tmp_path, as_of=as_of(), required_days=2, history_days=4)
    assert report["gate_passed"] is False
    assert report["current_consecutive_complete_day_streak"] == 0
    assert report["required_days"][0]["state"] == "WAIT_INCOMPLETE"
    assert report["required_days"][0]["explicit_gap_count"] == 1


def test_missing_latest_day_breaks_gate_even_if_older_days_pass(tmp_path: Path) -> None:
    write_manifest(tmp_path, "2026-09-12")
    write_manifest(tmp_path, "2026-09-11")
    report = m.observe(tmp_path, as_of=as_of(), required_days=2, history_days=4)
    assert report["gate_passed"] is False
    assert report["current_consecutive_complete_day_streak"] == 0
    assert report["required_days"][0]["date_utc"] == "2026-09-13"
    assert report["required_days"][0]["state"] == "WAIT_MISSING"


def test_native_and_recovered_mix_is_accepted(tmp_path: Path) -> None:
    write_manifest(tmp_path, "2026-09-13", native=20, recovered=76)
    write_manifest(tmp_path, "2026-09-12", native=0, recovered=96)
    report = m.observe(tmp_path, as_of=as_of(), required_days=2, history_days=2)
    assert report["gate_passed"] is True
    assert report["required_days"][0]["recovered_complete_slot_count"] == 76
    assert report["required_days"][1]["recovered_complete_slot_count"] == 96


def test_legacy_manifest_cannot_satisfy_gate(tmp_path: Path) -> None:
    write_manifest(tmp_path, "2026-09-13", phase="2E-prospective-daily-consolidation")
    write_manifest(tmp_path, "2026-09-12")
    report = m.observe(tmp_path, as_of=as_of(), required_days=2, history_days=2)
    assert report["gate_passed"] is False
    assert report["required_days"][0]["state"] == "WAIT_NONCANONICAL_OR_LEGACY"


def test_safety_invariant_failure_is_hard_fail(tmp_path: Path) -> None:
    write_manifest(tmp_path, "2026-09-13", risk_engine_allowed=True)
    write_manifest(tmp_path, "2026-09-12")
    report = m.observe(tmp_path, as_of=as_of(), required_days=2, history_days=2)
    assert report["gate_passed"] is False
    assert report["state"] == "FAIL_SAFETY_INVARIANT"
    assert report["safety_invariant_failure_count"] == 1


def test_technical_incomplete_is_distinct_from_gap(tmp_path: Path) -> None:
    write_manifest(tmp_path, "2026-09-13", complete=95, native=95, technical=1, gaps=0)
    write_manifest(tmp_path, "2026-09-12")
    report = m.observe(tmp_path, as_of=as_of(), required_days=2, history_days=2)
    row = report["required_days"][0]
    assert row["state"] == "WAIT_INCOMPLETE"
    assert row["technical_incomplete_slot_count"] == 1
    assert row["explicit_gap_count"] == 0
