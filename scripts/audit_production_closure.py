#!/usr/bin/env python3
"""Audit whether LPZ production is ready to retire the temporary Windows scheduler.

Phase 2L-O8 is an operational closure gate, not a scientific release gate.  It verifies
that the GitHub-native collector, daily archive, and public Pages production cycles are
actually healthy before the local Windows Task Scheduler is disabled.

The audit never authorizes the Risk Engine.  Scientific release remains governed by the
frozen Phase 2 validation protocol and IMERG Final V08 re-entry rules.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

EXPECTED_CRONS = {
    "collector": (Path(".github/workflows/prospective-feature-collector.yml"), "7,22,37,52 * * * *"),
    "daily_archive": (Path(".github/workflows/prospective-daily-consolidation.yml"), "30 0 * * *"),
    "public_pages": (Path(".github/workflows/public-pages-deploy.yml"), "2,17,32,47 * * * *"),
}

DEFAULT_MIN_ARCHIVE_COVERAGE = 0.90
DEFAULT_REQUIRED_ARCHIVE_DAYS = 2
DEFAULT_MIN_15MIN_RUNS_24H = 80
DEFAULT_MIN_SUCCESS_RATIO = 0.90
DEFAULT_15MIN_FRESHNESS_MINUTES = 60
DEFAULT_DAILY_FRESHNESS_HOURS = 36


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _workflow_schedule_check(root: Path, key: str, rel: Path, cron: str) -> dict[str, Any]:
    path = root / rel
    if not path.is_file():
        return {
            "state": "FAIL",
            "workflow": key,
            "path": str(rel),
            "expected_cron": cron,
            "reason": "WORKFLOW_FILE_MISSING",
        }
    text = path.read_text(encoding="utf-8")
    present = cron in text and "schedule:" in text
    return {
        "state": "PASS" if present else "FAIL",
        "workflow": key,
        "path": str(rel),
        "expected_cron": cron,
        "reason": None if present else "EXPECTED_SCHEDULE_NOT_FOUND",
    }


def _run_health(
    rows: list[dict[str, Any]],
    *,
    now: datetime,
    cadence: str,
    freshness: timedelta,
    lookback: timedelta,
    min_runs: int,
    min_success_ratio: float,
) -> dict[str, Any]:
    scheduled = [r for r in rows if r.get("event") == "schedule"]
    recent = []
    for row in scheduled:
        created = row.get("createdAt")
        if not created:
            continue
        try:
            created_dt = _parse_utc(str(created))
        except Exception:
            continue
        if now - lookback <= created_dt <= now + timedelta(minutes=5):
            recent.append(row)

    completed = [r for r in recent if r.get("conclusion") not in (None, "")]
    successes = [r for r in completed if r.get("conclusion") == "success"]
    success_ratio = (len(successes) / len(completed)) if completed else 0.0

    all_successes = [
        r for r in scheduled
        if r.get("conclusion") == "success" and r.get("createdAt")
    ]
    latest_success: dict[str, Any] | None = None
    latest_success_dt: datetime | None = None
    for row in all_successes:
        try:
            dt = _parse_utc(str(row["createdAt"]))
        except Exception:
            continue
        if latest_success_dt is None or dt > latest_success_dt:
            latest_success = row
            latest_success_dt = dt

    age_minutes = None
    fresh = False
    if latest_success_dt is not None:
        age_minutes = max((now - latest_success_dt).total_seconds() / 60.0, 0.0)
        fresh = now - latest_success_dt <= freshness

    enough_runs = len(recent) >= min_runs
    ratio_ok = success_ratio >= min_success_ratio
    passed = fresh and enough_runs and ratio_ok

    reasons: list[str] = []
    if not fresh:
        reasons.append("LATEST_SUCCESS_STALE_OR_MISSING")
    if not enough_runs:
        reasons.append("INSUFFICIENT_SCHEDULED_RUNS_IN_LOOKBACK")
    if not ratio_ok:
        reasons.append("SCHEDULED_RUN_SUCCESS_RATIO_BELOW_THRESHOLD")

    return {
        "state": "PASS" if passed else "WAIT",
        "cadence": cadence,
        "lookback_hours": lookback.total_seconds() / 3600.0,
        "scheduled_runs_in_lookback": len(recent),
        "completed_runs_in_lookback": len(completed),
        "successful_runs_in_lookback": len(successes),
        "success_ratio": success_ratio,
        "minimum_runs_required": min_runs,
        "minimum_success_ratio": min_success_ratio,
        "latest_success_created_at_utc": _iso_utc(latest_success_dt) if latest_success_dt else None,
        "latest_success_age_minutes": age_minutes,
        "freshness_limit_minutes": freshness.total_seconds() / 60.0,
        "latest_success_run_id": latest_success.get("databaseId") if latest_success else None,
        "latest_success_url": latest_success.get("url") if latest_success else None,
        "reasons": reasons,
    }


def _archive_check(
    root: Path,
    target: date,
    *,
    min_coverage: float,
) -> dict[str, Any]:
    rel = Path("research/prospective") / f"{target:%Y}" / f"{target:%m}" / f"{target:%Y-%m-%d}.manifest.json"
    path = root / rel
    if not path.is_file():
        return {
            "state": "WAIT",
            "date_utc": target.isoformat(),
            "path": str(rel),
            "reason": "DAILY_MANIFEST_MISSING",
        }

    payload = _load_json(path)
    expected = int(payload.get("expected_15min_intervals") or 0)
    bundles = int(payload.get("bundle_count") or 0)
    complete = int(payload.get("complete_bundle_count") or 0)
    parse_errors = int(payload.get("parse_error_count") or 0)
    coverage = float(payload.get("coverage_fraction") or 0.0)
    risk_locked = payload.get("risk_engine_allowed") is False

    checks = {
        "expected_intervals_is_96": expected == 96,
        "coverage_at_or_above_threshold": coverage >= min_coverage,
        "every_archived_bundle_complete": bundles > 0 and complete == bundles,
        "parse_errors_zero": parse_errors == 0,
        "risk_engine_locked": risk_locked,
    }
    passed = all(checks.values())
    reasons = [name for name, ok in checks.items() if not ok]

    return {
        "state": "PASS" if passed else "WAIT",
        "date_utc": target.isoformat(),
        "path": str(rel),
        "expected_15min_intervals": expected,
        "bundle_count": bundles,
        "complete_bundle_count": complete,
        "coverage_fraction": coverage,
        "minimum_coverage_required": min_coverage,
        "collector_gap_count": payload.get("collector_gap_count"),
        "parse_error_count": parse_errors,
        "prospective_day_quality": payload.get("prospective_day_quality"),
        "risk_engine_allowed": payload.get("risk_engine_allowed"),
        "checks": checks,
        "reasons": reasons,
    }


def _scientific_lock_check(root: Path) -> dict[str, Any]:
    charter_path = root / "config/lpz_system_charter.json"
    if not charter_path.is_file():
        return {"state": "FAIL", "reason": "MACHINE_READABLE_CHARTER_MISSING"}
    charter = _load_json(charter_path)
    lock = charter.get("current_scientific_lock") or {}
    checks = {
        "validation_deferred_pending_v08": lock.get("validation_status") == "DEFERRED_PENDING_IMERG_FINAL_V08",
        "era5_2025_primary_sealed": lock.get("validation_2025_era5_outcome_opened") is False,
        "primary_confirmatory_test_not_run": lock.get("primary_confirmatory_test_run") is False,
        "risk_engine_not_allowed": lock.get("risk_engine_allowed") is False,
        "public_validated_risk_not_allowed": lock.get("public_validated_risk_score_allowed") is False,
    }
    passed = all(checks.values())
    return {
        "state": "PASS" if passed else "FAIL",
        "checks": checks,
        "risk_engine_allowed": lock.get("risk_engine_allowed"),
        "validation_status": lock.get("validation_status"),
        "reasons": [name for name, ok in checks.items() if not ok],
    }


def _read_run_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"run history must be a JSON array: {path}")
    return [row for row in payload if isinstance(row, dict)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--collector-runs", required=True)
    ap.add_argument("--public-runs", required=True)
    ap.add_argument("--daily-runs", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--now-utc", default="", help="ISO-8601 override for deterministic tests")
    ap.add_argument("--required-archive-days", type=int, default=DEFAULT_REQUIRED_ARCHIVE_DAYS)
    ap.add_argument("--min-archive-coverage", type=float, default=DEFAULT_MIN_ARCHIVE_COVERAGE)
    ap.add_argument("--min-15min-runs-24h", type=int, default=DEFAULT_MIN_15MIN_RUNS_24H)
    ap.add_argument("--min-success-ratio", type=float, default=DEFAULT_MIN_SUCCESS_RATIO)
    args = ap.parse_args()

    root = Path(args.repo_root).resolve()
    now = _parse_utc(args.now_utc) if args.now_utc else datetime.now(timezone.utc)

    schedules = {
        key: _workflow_schedule_check(root, key, rel, cron)
        for key, (rel, cron) in EXPECTED_CRONS.items()
    }

    collector_runs = _read_run_rows(Path(args.collector_runs))
    public_runs = _read_run_rows(Path(args.public_runs))
    daily_runs = _read_run_rows(Path(args.daily_runs))

    collector_health = _run_health(
        collector_runs,
        now=now,
        cadence="15_MINUTES",
        freshness=timedelta(minutes=DEFAULT_15MIN_FRESHNESS_MINUTES),
        lookback=timedelta(hours=24),
        min_runs=args.min_15min_runs_24h,
        min_success_ratio=args.min_success_ratio,
    )
    public_health = _run_health(
        public_runs,
        now=now,
        cadence="15_MINUTES",
        freshness=timedelta(minutes=DEFAULT_15MIN_FRESHNESS_MINUTES),
        lookback=timedelta(hours=24),
        min_runs=args.min_15min_runs_24h,
        min_success_ratio=args.min_success_ratio,
    )
    daily_health = _run_health(
        daily_runs,
        now=now,
        cadence="DAILY",
        freshness=timedelta(hours=DEFAULT_DAILY_FRESHNESS_HOURS),
        lookback=timedelta(hours=48),
        min_runs=1,
        min_success_ratio=args.min_success_ratio,
    )

    archive_days = [
        _archive_check(
            root,
            now.date() - timedelta(days=offset),
            min_coverage=args.min_archive_coverage,
        )
        for offset in range(1, args.required_archive_days + 1)
    ]

    scientific_lock = _scientific_lock_check(root)

    schedule_pass = all(v["state"] == "PASS" for v in schedules.values())
    runtime_pass = all(
        v["state"] == "PASS"
        for v in (collector_health, public_health, daily_health)
    )
    archive_pass = len(archive_days) == args.required_archive_days and all(
        v["state"] == "PASS" for v in archive_days
    )
    scientific_lock_pass = scientific_lock["state"] == "PASS"
    closure_ready = schedule_pass and runtime_pass and archive_pass and scientific_lock_pass

    blockers: list[str] = []
    if not schedule_pass:
        blockers.append("GITHUB_PRODUCTION_SCHEDULE_CONFIGURATION")
    if collector_health["state"] != "PASS":
        blockers.append("PROSPECTIVE_COLLECTOR_RUNTIME_HEALTH")
    if public_health["state"] != "PASS":
        blockers.append("PUBLIC_PAGES_RUNTIME_HEALTH")
    if daily_health["state"] != "PASS":
        blockers.append("DAILY_ARCHIVE_RUNTIME_HEALTH")
    if not archive_pass:
        blockers.append("CONSECUTIVE_DAILY_ARCHIVE_COVERAGE")
    if not scientific_lock_pass:
        blockers.append("SCIENTIFIC_LOCK_INVARIANT")

    report = {
        "schema_version": "1.0.0",
        "phase": "2L-O8-github-only-production-closure",
        "generated_at_utc": _iso_utc(now),
        "overall_state": "PASS_READY_TO_RETIRE_WINDOWS_TASK" if closure_ready else "WAIT_KEEP_WINDOWS_TASK",
        "closure_ready": closure_ready,
        "windows_task_name": "LPZ-Prospective-Collector-15min",
        "windows_task_recommendation": "DISABLE" if closure_ready else "KEEP_ENABLED",
        "scientific_release_is_separate": True,
        "risk_engine_allowed": False,
        "criteria": {
            "required_consecutive_archive_days": args.required_archive_days,
            "minimum_archive_coverage": args.min_archive_coverage,
            "minimum_15min_scheduled_runs_24h": args.min_15min_runs_24h,
            "minimum_scheduled_run_success_ratio": args.min_success_ratio,
            "15min_latest_success_freshness_minutes": DEFAULT_15MIN_FRESHNESS_MINUTES,
            "daily_latest_success_freshness_hours": DEFAULT_DAILY_FRESHNESS_HOURS,
        },
        "checks": {
            "schedules": schedules,
            "runtime": {
                "prospective_collector": collector_health,
                "public_pages": public_health,
                "daily_archive": daily_health,
            },
            "archives": archive_days,
            "scientific_lock": scientific_lock,
        },
        "blockers": blockers,
        "interpretation": (
            "GitHub-only production has demonstrated enough consecutive operational coverage "
            "to retire the temporary Windows scheduler. This does not unlock LPZ risk output."
            if closure_ready
            else
            "Production closure has not yet met every operational gate. Keep the temporary "
            "Windows scheduler enabled; Risk Engine remains locked independently."
        ),
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"O8 overall_state={report['overall_state']}")
    print(f"closure_ready={closure_ready}")
    print(f"windows_task_recommendation={report['windows_task_recommendation']}")
    print(f"blockers={','.join(blockers) if blockers else 'NONE'}")
    for row in archive_days:
        print(
            "archive "
            f"{row['date_utc']} state={row['state']} "
            f"coverage={row.get('coverage_fraction')} bundles={row.get('bundle_count')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
