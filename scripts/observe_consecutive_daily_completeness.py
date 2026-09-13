#!/usr/bin/env python3
"""O8.1-E: observe consecutive complete canonical prospective UTC days.

This is an operational observation gate. It reads O8.1-D canonical daily
manifests and decides whether the most recent finalized UTC days are truly
96/96 complete. It never authorizes the scientific Risk Engine and never
disables the temporary Windows scheduler; O8.1-F owns the final cutover audit.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
EXPECTED_PHASE = "2L-O8.1-D-daily-consolidation-v2"
EXPECTED_SLOTS = 96
DEFAULT_REQUIRED_DAYS = 2
DEFAULT_HISTORY_DAYS = 14


def parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp is not timezone-aware: {value}")
    return dt.astimezone(UTC)


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def manifest_relpath(target: date) -> Path:
    return (
        Path("research/prospective")
        / f"{target:%Y}"
        / f"{target:%m}"
        / f"{target:%Y-%m-%d}.manifest.json"
    )


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest root is not a JSON object")
    return payload


def check_day(root: Path, target: date) -> dict[str, Any]:
    rel = manifest_relpath(target)
    path = root / rel
    base: dict[str, Any] = {
        "date_utc": target.isoformat(),
        "path": str(rel).replace("\\", "/"),
    }
    if not path.is_file():
        return {
            **base,
            "state": "WAIT_MISSING",
            "complete_96_of_96": False,
            "reason": "DAILY_MANIFEST_MISSING",
            "checks": {},
        }

    try:
        p = _load_json(path)
    except Exception as exc:
        return {
            **base,
            "state": "ERROR_STRUCTURAL",
            "complete_96_of_96": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "checks": {},
        }

    safety_checks = {
        "risk_engine_locked": p.get("risk_engine_allowed") is False,
        "risk_score_absent": p.get("risk_score") is None,
        "lpz_classification_absent": p.get("lpz_classification") is None,
        "raw_radar_not_archived": p.get("raw_radar_archived") is False,
        "raw_grib_not_archived": p.get("raw_grib_archived") is False,
    }
    if not all(safety_checks.values()):
        return {
            **base,
            "state": "FAIL_SAFETY_INVARIANT",
            "complete_96_of_96": False,
            "reason": "SAFETY_INVARIANT_VIOLATION",
            "checks": safety_checks,
        }

    phase_ok = p.get("phase") == EXPECTED_PHASE
    if not phase_ok:
        return {
            **base,
            "state": "WAIT_NONCANONICAL_OR_LEGACY",
            "complete_96_of_96": False,
            "reason": "O8_1_D_CANONICAL_MANIFEST_REQUIRED",
            "phase": p.get("phase"),
            "schema_version": p.get("schema_version"),
            "checks": {
                **safety_checks,
                "phase_is_o8_1_d": False,
            },
        }

    expected = int(p.get("expected_15min_intervals") or 0)
    canonical = int(p.get("canonical_slot_count") or 0)
    complete = int(p.get("complete_slot_count") or 0)
    native = int(p.get("native_complete_slot_count") or 0)
    recovered = int(p.get("recovered_complete_slot_count") or 0)
    technical = int(p.get("technical_incomplete_slot_count") or 0)
    gaps = int(p.get("explicit_gap_count") or 0)
    parse_errors = int(p.get("parse_error_count") or 0)
    coverage = float(p.get("coverage_fraction") or 0.0)

    checks = {
        **safety_checks,
        "phase_is_o8_1_d": True,
        "manifest_date_matches_path": str(p.get("date_utc") or "") == target.isoformat(),
        "scientific_clock_is_collection_slot_utc": p.get("scientific_clock") == "collection_slot_utc",
        "expected_intervals_is_96": expected == EXPECTED_SLOTS,
        "canonical_slot_count_is_96": canonical == EXPECTED_SLOTS,
        "complete_slot_count_is_96": complete == EXPECTED_SLOTS,
        "native_plus_recovered_is_96": native + recovered == EXPECTED_SLOTS,
        "technical_incomplete_zero": technical == 0,
        "explicit_gap_zero": gaps == 0,
        "parse_errors_zero": parse_errors == 0,
        "coverage_is_one": abs(coverage - 1.0) < 1e-12,
        "canonical_quality_complete": p.get("canonical_day_quality") == "COMPLETE_96_OF_96",
        "closure_eligible_flag_true": p.get("closure_eligible_96_of_96") is True,
        "archive_role_canonical_daily": p.get("archive_role") == "PROSPECTIVE_CANONICAL_DAILY",
    }
    passed = all(checks.values())
    return {
        **base,
        "state": "PASS_COMPLETE_96_OF_96" if passed else "WAIT_INCOMPLETE",
        "complete_96_of_96": passed,
        "reason": None if passed else "ONE_OR_MORE_CANONICAL_COMPLETENESS_CHECKS_FAILED",
        "schema_version": p.get("schema_version"),
        "phase": p.get("phase"),
        "expected_15min_intervals": expected,
        "canonical_slot_count": canonical,
        "complete_slot_count": complete,
        "native_complete_slot_count": native,
        "recovered_complete_slot_count": recovered,
        "technical_incomplete_slot_count": technical,
        "explicit_gap_count": gaps,
        "duplicate_slot_count": int(p.get("duplicate_slot_count") or 0),
        "coverage_fraction": coverage,
        "parse_error_count": parse_errors,
        "canonical_day_quality": p.get("canonical_day_quality"),
        "checks": checks,
    }


def observe(
    root: Path,
    *,
    as_of: datetime,
    required_days: int = DEFAULT_REQUIRED_DAYS,
    history_days: int = DEFAULT_HISTORY_DAYS,
) -> dict[str, Any]:
    if required_days < 1:
        raise ValueError("required_days must be >= 1")
    if history_days < required_days:
        raise ValueError("history_days must be >= required_days")

    latest_expected_day = as_of.date() - timedelta(days=1)
    history: list[dict[str, Any]] = []
    for offset in range(history_days):
        history.append(check_day(root, latest_expected_day - timedelta(days=offset)))

    streak = 0
    for row in history:
        if row.get("complete_96_of_96") is True:
            streak += 1
        else:
            break

    required_rows = history[:required_days]
    gate_passed = (
        len(required_rows) == required_days
        and streak >= required_days
        and all(row.get("complete_96_of_96") is True for row in required_rows)
    )
    structural_errors = [row for row in history if row.get("state") == "ERROR_STRUCTURAL"]
    safety_failures = [row for row in history if row.get("state") == "FAIL_SAFETY_INVARIANT"]

    if safety_failures:
        state = "FAIL_SAFETY_INVARIANT"
    elif structural_errors:
        state = "ERROR_STRUCTURAL"
    elif gate_passed:
        state = "PASS_REQUIRED_CONSECUTIVE_COMPLETE_DAYS"
    else:
        state = "WAIT_REQUIRED_CONSECUTIVE_COMPLETE_DAYS"

    return {
        "schema_version": "1.0.0",
        "phase": "2L-O8.1-E-consecutive-day-completeness-observer",
        "generated_at_utc": iso_utc(as_of),
        "latest_expected_finalized_date_utc": latest_expected_day.isoformat(),
        "required_consecutive_complete_days": required_days,
        "history_days_examined": history_days,
        "current_consecutive_complete_day_streak": streak,
        "gate_passed": gate_passed,
        "state": state,
        "required_days": required_rows,
        "history": history,
        "ready_for_o8_1_f_final_cutover_audit": gate_passed,
        "windows_task_may_be_disabled": False,
        "windows_task_recommendation": "KEEP_ENABLED_PENDING_O8_1_F",
        "scientific_release_is_separate": True,
        "risk_engine_allowed": False,
        "lpz_classification": None,
        "risk_score": None,
        "structural_error_count": len(structural_errors),
        "safety_invariant_failure_count": len(safety_failures),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--as-of-utc", default="", help="ISO-8601 override for deterministic tests")
    ap.add_argument("--required-days", type=int, default=DEFAULT_REQUIRED_DAYS)
    ap.add_argument("--history-days", type=int, default=DEFAULT_HISTORY_DAYS)
    args = ap.parse_args()

    as_of = parse_utc(args.as_of_utc) if args.as_of_utc else datetime.now(UTC)
    report = observe(
        Path(args.repo_root).resolve(),
        as_of=as_of,
        required_days=args.required_days,
        history_days=args.history_days,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"O8.1-E state={report['state']}")
    print(f"gate_passed={report['gate_passed']}")
    print(f"streak={report['current_consecutive_complete_day_streak']}")
    print(f"latest_expected={report['latest_expected_finalized_date_utc']}")
    for row in report["required_days"]:
        print(
            f"day {row['date_utc']} state={row['state']} "
            f"complete={row.get('complete_slot_count')} "
            f"technical={row.get('technical_incomplete_slot_count')} "
            f"gaps={row.get('explicit_gap_count')}"
        )

    if report["structural_error_count"] or report["safety_invariant_failure_count"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
