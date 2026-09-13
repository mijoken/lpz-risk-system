#!/usr/bin/env python3
"""O8.1-F: final GitHub-only operational cutover audit.

This is the only gate allowed to recommend disabling the temporary Windows
Task Scheduler. It replaces the legacy O8 assumption that GitHub cron itself
must fire ~96 times/day. Instead it verifies the O8.1 self-healing design:

A. bounded JMA retention is proven,
B. exact historical-slot replay + model as-of guard are proven,
C. the self-healing collector is production-proven,
D. canonical daily consolidation is production-proven,
E. the latest finalized UTC days are consecutively 96/96 complete,
plus current runtime freshness and the frozen scientific lock.

The audit never enables the LPZ Risk Engine and never disables Windows itself.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
CATCHUP_HORIZON_MINUTES = 120
COLLECTOR_FRESHNESS_MINUTES = 120
PUBLIC_FRESHNESS_MINUTES = 240
DAILY_FRESHNESS_HOURS = 48
EXPECTED_CONSECUTIVE_DAYS = 2

PATHS = {
    "a": Path("research/operations/o8_1_jma_retention_latest.json"),
    "b": Path("research/operations/o8_1_slot_replay_latest.json"),
    "c": Path("research/operations/o8_1_c_self_healing_production_proof.json"),
    "d": Path("research/operations/o8_1_d_daily_consolidation_proof.json"),
    "e": Path("research/operations/o8_1_e_consecutive_day_completeness_latest.json"),
    "charter": Path("config/lpz_system_charter.json"),
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp is not timezone-aware: {value}")
    return dt.astimezone(UTC)


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def latest_success_health(
    rows: list[dict[str, Any]],
    now: datetime,
    *,
    freshness: timedelta,
    name: str,
) -> dict[str, Any]:
    completed = [r for r in rows if r.get("status") == "completed" or r.get("conclusion")]
    parsed: list[tuple[datetime, dict[str, Any]]] = []
    for row in completed:
        raw = row.get("createdAt") or row.get("created_at_utc")
        if not raw:
            continue
        try:
            parsed.append((parse_utc(str(raw)), row))
        except Exception:
            continue
    parsed.sort(key=lambda x: x[0], reverse=True)
    successes = [(dt, row) for dt, row in parsed if row.get("conclusion") == "success"]
    latest_any = parsed[0] if parsed else None
    latest_success = successes[0] if successes else None
    age_minutes = None
    fresh = False
    latest_failure_after_success = False
    if latest_success:
        age_minutes = max((now - latest_success[0]).total_seconds() / 60.0, 0.0)
        fresh = now - latest_success[0] <= freshness
        if latest_any and latest_any[0] > latest_success[0] and latest_any[1].get("conclusion") != "success":
            latest_failure_after_success = True
    passed = bool(latest_success and fresh and not latest_failure_after_success)
    return {
        "name": name,
        "state": "PASS" if passed else "WAIT",
        "latest_success_created_at_utc": iso_utc(latest_success[0]) if latest_success else None,
        "latest_success_run_id": latest_success[1].get("databaseId") if latest_success else None,
        "latest_success_event": latest_success[1].get("event") if latest_success else None,
        "latest_success_age_minutes": age_minutes,
        "freshness_limit_minutes": freshness.total_seconds() / 60.0,
        "latest_completed_conclusion": latest_any[1].get("conclusion") if latest_any else None,
        "latest_failure_after_success": latest_failure_after_success,
        "runs_examined": len(rows),
    }


def check_scientific_lock(charter: dict[str, Any]) -> dict[str, Any]:
    lock = charter.get("current_scientific_lock") or {}
    checks = {
        "validation_deferred_pending_v08": lock.get("validation_status") == "DEFERRED_PENDING_IMERG_FINAL_V08",
        "validation_2025_era5_still_sealed": lock.get("validation_2025_era5_outcome_opened") is False,
        "primary_confirmatory_test_not_run": lock.get("primary_confirmatory_test_run") is False,
        "risk_engine_locked": lock.get("risk_engine_allowed") is False,
        "public_validated_risk_locked": lock.get("public_validated_risk_score_allowed") is False,
    }
    return {
        "state": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "risk_engine_allowed": lock.get("risk_engine_allowed"),
        "validation_status": lock.get("validation_status"),
    }


def check_a(p: dict[str, Any]) -> dict[str, Any]:
    policy = p.get("policy_candidate") or {}
    probes = p.get("direct_tile_replay_probes") or {}
    gates = p.get("gates") or {}
    checks = {
        "phase": p.get("phase") == "2L-O8.1-A-jma-source-retention-census",
        "state_pass": str(p.get("state", "")).startswith("PASS_"),
        "direct_tile_replay_all_pass": probes.get("all_pass") is True,
        "continuous_5min_history": gates.get("continuous_5min_history") is True,
        "recommended_horizon_at_least_120m": int(policy.get("recommended_catchup_horizon_minutes") or 0) >= CATCHUP_HORIZON_MINUTES,
        "risk_engine_locked": p.get("risk_engine_allowed") is False,
    }
    return {"state": "PASS" if all(checks.values()) else "WAIT", "checks": checks}


def check_b(p: dict[str, Any]) -> dict[str, Any]:
    gfs = p.get("gfs_as_of_guard") or {}
    checks = {
        "phase": p.get("phase") == "2L-O8.1-B-slot-addressable-replay-proof",
        "state_pass": p.get("state") == "PASS_SLOT_REPLAY",
        "exact_frame_sequence_match": p.get("exact_frame_sequence_match") is True,
        "gfs_asof_safe": gfs.get("all_candidate_cycles_asof_safe") is True,
        "risk_engine_locked": p.get("risk_engine_allowed") is False,
        "risk_score_absent": p.get("risk_score") is None,
        "classification_absent": p.get("lpz_classification") is None,
    }
    return {"state": "PASS" if all(checks.values()) else "FAIL", "checks": checks}


def check_c(p: dict[str, Any]) -> dict[str, Any]:
    policy = p.get("catchup_policy") or {}
    behavior = p.get("verified_behaviour") or {}
    checks = {
        "phase": p.get("phase") == "2L-O8.1-C-self-healing-batch-collector",
        "state_pass": str(p.get("state", "")).startswith("PASS_PHASE2L_O8_1_C"),
        "catchup_horizon_120m": int(policy.get("catchup_horizon_minutes") or 0) == CATCHUP_HORIZON_MINUTES,
        "max_slots_can_cover_120m_grid": int(policy.get("max_slots_per_run") or 0) >= 8,
        "multi_slot_recovery": behavior.get("single_run_multi_slot_recovery") is True,
        "deduplication": behavior.get("complete_slot_deduplication") is True,
        "as_of_guard": behavior.get("as_of_time_guard_enforced") is True,
        "risk_engine_locked": p.get("risk_engine_allowed") is False and behavior.get("risk_engine_allowed") is False,
    }
    return {"state": "PASS" if all(checks.values()) else "FAIL", "checks": checks}


def check_d(p: dict[str, Any]) -> dict[str, Any]:
    contract = p.get("verified_contract") or {}
    schedule = p.get("production_schedule") or {}
    checks = {
        "phase": p.get("phase") == "2L-O8.1-D-daily-consolidation-v2",
        "state_pass": str(p.get("state", "")).startswith("PASS_PHASE2L_O8_1_D"),
        "canonical_96_slots": contract.get("canonical_slots_per_utc_day") == 96,
        "missing_slots_explicit": contract.get("missing_slots_are_explicit") is True,
        "technical_not_rewritten_as_gap": contract.get("technical_incomplete_is_not_converted_to_gap") is True,
        "native_recovered_preserved": contract.get("native_and_recovered_preserved") is True,
        "production_schedule_redundant": schedule.get("utc_cron") == "30 2,8 * * *",
        "risk_engine_locked": contract.get("risk_engine_allowed") is False,
    }
    return {"state": "PASS" if all(checks.values()) else "FAIL", "checks": checks}


def check_e(p: dict[str, Any], now: datetime) -> dict[str, Any]:
    latest_expected = (now.date() - timedelta(days=1)).isoformat()
    required_rows = p.get("required_days") or []
    row_checks = [
        row.get("complete_96_of_96") is True
        and int(row.get("complete_slot_count") or 0) == 96
        and int(row.get("technical_incomplete_slot_count") or 0) == 0
        and int(row.get("explicit_gap_count") or 0) == 0
        for row in required_rows[:EXPECTED_CONSECUTIVE_DAYS]
    ]
    checks = {
        "phase": p.get("phase") == "2L-O8.1-E-consecutive-day-completeness-observer",
        "latest_expected_matches_today": p.get("latest_expected_finalized_date_utc") == latest_expected,
        "required_days_is_2": int(p.get("required_consecutive_complete_days") or 0) == EXPECTED_CONSECUTIVE_DAYS,
        "gate_passed": p.get("gate_passed") is True,
        "streak_at_least_2": int(p.get("current_consecutive_complete_day_streak") or 0) >= EXPECTED_CONSECUTIVE_DAYS,
        "required_rows_complete": len(row_checks) == EXPECTED_CONSECUTIVE_DAYS and all(row_checks),
        "safety_failures_zero": int(p.get("safety_invariant_failure_count") or 0) == 0,
        "structural_errors_zero": int(p.get("structural_error_count") or 0) == 0,
        "risk_engine_locked": p.get("risk_engine_allowed") is False,
    }
    return {
        "state": "PASS" if all(checks.values()) else "WAIT",
        "checks": checks,
        "current_streak": p.get("current_consecutive_complete_day_streak"),
        "latest_expected_finalized_date_utc": p.get("latest_expected_finalized_date_utc"),
        "required_days": required_rows[:EXPECTED_CONSECUTIVE_DAYS],
    }


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = load_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"run history must be a JSON array: {path}")
    return [r for r in payload if isinstance(r, dict)]


def audit(
    root: Path,
    *,
    now: datetime,
    collector_runs: list[dict[str, Any]],
    daily_runs: list[dict[str, Any]],
    public_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    missing = [str(rel) for rel in PATHS.values() if not (root / rel).is_file()]
    if missing:
        return {
            "schema_version": "1.0.0",
            "phase": "2L-O8.1-F-final-github-only-cutover-audit",
            "generated_at_utc": iso_utc(now),
            "state": "FAIL_REQUIRED_EVIDENCE_MISSING",
            "cutover_ready": False,
            "windows_task_may_be_disabled": False,
            "windows_task_recommendation": "KEEP_ENABLED",
            "missing_evidence": missing,
            "risk_engine_allowed": False,
        }

    a = check_a(load_json(root / PATHS["a"]))
    b = check_b(load_json(root / PATHS["b"]))
    c = check_c(load_json(root / PATHS["c"]))
    d = check_d(load_json(root / PATHS["d"]))
    e = check_e(load_json(root / PATHS["e"]), now)
    lock = check_scientific_lock(load_json(root / PATHS["charter"]))

    runtime = {
        "collector": latest_success_health(
            collector_runs,
            now,
            freshness=timedelta(minutes=COLLECTOR_FRESHNESS_MINUTES),
            name="prospective_self_healing_collector",
        ),
        "daily": latest_success_health(
            daily_runs,
            now,
            freshness=timedelta(hours=DAILY_FRESHNESS_HOURS),
            name="canonical_daily_consolidation",
        ),
        "public": latest_success_health(
            public_runs,
            now,
            freshness=timedelta(minutes=PUBLIC_FRESHNESS_MINUTES),
            name="public_pages_production",
        ),
    }

    implementation_pass = all(x["state"] == "PASS" for x in (a, b, c, d))
    evidence_pass = e["state"] == "PASS"
    runtime_pass = all(x["state"] == "PASS" for x in runtime.values())
    lock_pass = lock["state"] == "PASS"
    cutover_ready = implementation_pass and evidence_pass and runtime_pass and lock_pass

    blockers: list[str] = []
    if not implementation_pass:
        blockers.append("O8_1_IMPLEMENTATION_EVIDENCE")
    if not evidence_pass:
        blockers.append("TWO_CONSECUTIVE_CANONICAL_96_OF_96_DAYS")
    if runtime["collector"]["state"] != "PASS":
        blockers.append("COLLECTOR_FRESHNESS_WITHIN_RECOVERY_HORIZON")
    if runtime["daily"]["state"] != "PASS":
        blockers.append("DAILY_CONSOLIDATION_RUNTIME_FRESHNESS")
    if runtime["public"]["state"] != "PASS":
        blockers.append("PUBLIC_PRODUCTION_RUNTIME_FRESHNESS")
    if not lock_pass:
        blockers.append("SCIENTIFIC_LOCK_INVARIANT")

    hard_fail = any(x["state"] == "FAIL" for x in (b, c, d, lock))
    if cutover_ready:
        state = "PASS_READY_TO_DISABLE_WINDOWS_TASK"
    elif hard_fail:
        state = "FAIL_KEEP_WINDOWS_TASK"
    else:
        state = "WAIT_KEEP_WINDOWS_TASK"

    return {
        "schema_version": "1.0.0",
        "phase": "2L-O8.1-F-final-github-only-cutover-audit",
        "generated_at_utc": iso_utc(now),
        "state": state,
        "cutover_ready": cutover_ready,
        "windows_task_name": "LPZ-Prospective-Collector-15min",
        "windows_task_may_be_disabled": cutover_ready,
        "windows_task_recommendation": "DISABLE_MANUALLY" if cutover_ready else "KEEP_ENABLED",
        "windows_disable_command": "Disable-ScheduledTask -TaskName \"LPZ-Prospective-Collector-15min\"" if cutover_ready else None,
        "old_o8_run_count_requirement_retired": True,
        "github_schedule_is_scientific_clock": False,
        "criteria": {
            "catchup_horizon_minutes": CATCHUP_HORIZON_MINUTES,
            "collector_freshness_must_be_within_catchup_horizon": True,
            "required_consecutive_complete_utc_days": EXPECTED_CONSECUTIVE_DAYS,
            "required_complete_slots_per_day": 96,
            "explicit_gap_required": 0,
            "technical_incomplete_required": 0,
            "scientific_risk_release_separate": True,
        },
        "checks": {
            "o8_1_a_retention": a,
            "o8_1_b_slot_replay": b,
            "o8_1_c_self_healing": c,
            "o8_1_d_daily_canonical": d,
            "o8_1_e_consecutive_days": e,
            "runtime": runtime,
            "scientific_lock": lock,
        },
        "blockers": blockers,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
        "interpretation": (
            "GitHub-only operational cutover is proven. Disable the temporary Windows task manually; this does not unlock LPZ risk output."
            if cutover_ready
            else "Keep the temporary Windows collector enabled until every O8.1-F operational gate passes. Risk Engine remains locked independently."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--collector-runs", required=True)
    ap.add_argument("--daily-runs", required=True)
    ap.add_argument("--public-runs", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--now-utc", default="")
    args = ap.parse_args()

    now = parse_utc(args.now_utc) if args.now_utc else datetime.now(UTC)
    root = Path(args.repo_root).resolve()
    report = audit(
        root,
        now=now,
        collector_runs=load_rows(Path(args.collector_runs)),
        daily_runs=load_rows(Path(args.daily_runs)),
        public_runs=load_rows(Path(args.public_runs)),
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"O8.1-F state={report['state']}")
    print(f"cutover_ready={report['cutover_ready']}")
    print(f"windows_task_recommendation={report['windows_task_recommendation']}")
    print(f"blockers={','.join(report.get('blockers') or []) or 'NONE'}")
    print("Risk Engine remains LOCKED.")
    return 2 if str(report["state"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
