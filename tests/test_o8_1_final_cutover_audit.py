from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts import o8_1_final_cutover_audit as mod

UTC = timezone.utc
NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


def write_json(root: Path, rel: Path, payload: dict) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def seed_evidence(root: Path) -> None:
    write_json(root, mod.PATHS["a"], {
        "phase": "2L-O8.1-A-jma-source-retention-census",
        "state": "PASS_RETENTION_CANDIDATE",
        "risk_engine_allowed": False,
        "direct_tile_replay_probes": {"all_pass": True},
        "policy_candidate": {"recommended_catchup_horizon_minutes": 120},
        "gates": {"continuous_5min_history": True},
    })
    write_json(root, mod.PATHS["b"], {
        "phase": "2L-O8.1-B-slot-addressable-replay-proof",
        "state": "PASS_SLOT_REPLAY",
        "exact_frame_sequence_match": True,
        "gfs_as_of_guard": {"all_candidate_cycles_asof_safe": True},
        "risk_engine_allowed": False,
        "risk_score": None,
        "lpz_classification": None,
    })
    write_json(root, mod.PATHS["c"], {
        "phase": "2L-O8.1-C-self-healing-batch-collector",
        "state": "PASS_PHASE2L_O8_1_C_SELF_HEALING_BATCH",
        "risk_engine_allowed": False,
        "catchup_policy": {"catchup_horizon_minutes": 120, "max_slots_per_run": 8},
        "verified_behaviour": {
            "single_run_multi_slot_recovery": True,
            "complete_slot_deduplication": True,
            "as_of_time_guard_enforced": True,
            "risk_engine_allowed": False,
        },
    })
    write_json(root, mod.PATHS["d"], {
        "phase": "2L-O8.1-D-daily-consolidation-v2",
        "state": "PASS_PHASE2L_O8_1_D_CANONICAL_DAILY_CONSOLIDATION",
        "verified_contract": {
            "canonical_slots_per_utc_day": 96,
            "missing_slots_are_explicit": True,
            "technical_incomplete_is_not_converted_to_gap": True,
            "native_and_recovered_preserved": True,
            "risk_engine_allowed": False,
        },
        "production_schedule": {"utc_cron": "30 2,8 * * *"},
    })
    complete_day = lambda day: {
        "date_utc": day,
        "complete_96_of_96": True,
        "complete_slot_count": 96,
        "technical_incomplete_slot_count": 0,
        "explicit_gap_count": 0,
    }
    write_json(root, mod.PATHS["e"], {
        "phase": "2L-O8.1-E-consecutive-day-completeness-observer",
        "latest_expected_finalized_date_utc": "2026-09-12",
        "required_consecutive_complete_days": 2,
        "current_consecutive_complete_day_streak": 2,
        "gate_passed": True,
        "required_days": [complete_day("2026-09-12"), complete_day("2026-09-11")],
        "safety_invariant_failure_count": 0,
        "structural_error_count": 0,
        "risk_engine_allowed": False,
    })
    write_json(root, mod.PATHS["charter"], {
        "current_scientific_lock": {
            "validation_status": "DEFERRED_PENDING_IMERG_FINAL_V08",
            "validation_2025_era5_outcome_opened": False,
            "primary_confirmatory_test_run": False,
            "risk_engine_allowed": False,
            "public_validated_risk_score_allowed": False,
        }
    })


def runs(at: str, *, conclusion: str = "success", event: str = "schedule") -> list[dict]:
    return [{
        "databaseId": 123,
        "createdAt": at,
        "status": "completed",
        "conclusion": conclusion,
        "event": event,
    }]


def healthy_runtime():
    return (
        runs("2026-09-13T11:30:00Z", event="workflow_run"),
        runs("2026-09-13T03:00:00Z"),
        runs("2026-09-13T11:20:00Z"),
    )


def test_all_gates_pass_and_single_recent_run_is_enough(tmp_path: Path):
    seed_evidence(tmp_path)
    collector, daily, public = healthy_runtime()
    report = mod.audit(tmp_path, now=NOW, collector_runs=collector, daily_runs=daily, public_runs=public)
    assert report["state"] == "PASS_READY_TO_DISABLE_WINDOWS_TASK"
    assert report["cutover_ready"] is True
    assert report["windows_task_may_be_disabled"] is True
    assert report["windows_task_recommendation"] == "DISABLE_MANUALLY"
    assert "Disable-ScheduledTask" in report["windows_disable_command"]
    assert report["old_o8_run_count_requirement_retired"] is True
    assert report["risk_engine_allowed"] is False


def test_evidence_gate_waits_until_two_latest_days_are_complete(tmp_path: Path):
    seed_evidence(tmp_path)
    e = json.loads((tmp_path / mod.PATHS["e"]).read_text())
    e["gate_passed"] = False
    e["current_consecutive_complete_day_streak"] = 1
    e["required_days"][1]["complete_96_of_96"] = False
    e["required_days"][1]["complete_slot_count"] = 95
    write_json(tmp_path, mod.PATHS["e"], e)
    collector, daily, public = healthy_runtime()
    report = mod.audit(tmp_path, now=NOW, collector_runs=collector, daily_runs=daily, public_runs=public)
    assert report["state"] == "WAIT_KEEP_WINDOWS_TASK"
    assert report["cutover_ready"] is False
    assert "TWO_CONSECUTIVE_CANONICAL_96_OF_96_DAYS" in report["blockers"]


def test_collector_must_be_fresh_within_recovery_horizon(tmp_path: Path):
    seed_evidence(tmp_path)
    collector = runs("2026-09-13T09:30:00Z")
    _, daily, public = healthy_runtime()
    report = mod.audit(tmp_path, now=NOW, collector_runs=collector, daily_runs=daily, public_runs=public)
    assert report["state"] == "WAIT_KEEP_WINDOWS_TASK"
    assert "COLLECTOR_FRESHNESS_WITHIN_RECOVERY_HORIZON" in report["blockers"]


def test_newer_collector_failure_blocks_cutover(tmp_path: Path):
    seed_evidence(tmp_path)
    collector = runs("2026-09-13T11:20:00Z") + runs("2026-09-13T11:40:00Z", conclusion="failure")
    _, daily, public = healthy_runtime()
    report = mod.audit(tmp_path, now=NOW, collector_runs=collector, daily_runs=daily, public_runs=public)
    assert report["cutover_ready"] is False
    assert report["checks"]["runtime"]["collector"]["latest_failure_after_success"] is True


def test_scientific_lock_violation_is_hard_fail(tmp_path: Path):
    seed_evidence(tmp_path)
    charter = json.loads((tmp_path / mod.PATHS["charter"]).read_text())
    charter["current_scientific_lock"]["risk_engine_allowed"] = True
    write_json(tmp_path, mod.PATHS["charter"], charter)
    collector, daily, public = healthy_runtime()
    report = mod.audit(tmp_path, now=NOW, collector_runs=collector, daily_runs=daily, public_runs=public)
    assert report["state"] == "FAIL_KEEP_WINDOWS_TASK"
    assert report["risk_engine_allowed"] is False
    assert "SCIENTIFIC_LOCK_INVARIANT" in report["blockers"]


def test_stale_e_report_cannot_authorize_cutover(tmp_path: Path):
    seed_evidence(tmp_path)
    e = json.loads((tmp_path / mod.PATHS["e"]).read_text())
    e["latest_expected_finalized_date_utc"] = "2026-09-11"
    write_json(tmp_path, mod.PATHS["e"], e)
    collector, daily, public = healthy_runtime()
    report = mod.audit(tmp_path, now=NOW, collector_runs=collector, daily_runs=daily, public_runs=public)
    assert report["state"] == "WAIT_KEEP_WINDOWS_TASK"
    assert report["checks"]["o8_1_e_consecutive_days"]["checks"]["latest_expected_matches_today"] is False


def test_missing_required_evidence_is_fail_closed(tmp_path: Path):
    report = mod.audit(tmp_path, now=NOW, collector_runs=[], daily_runs=[], public_runs=[])
    assert report["state"] == "FAIL_REQUIRED_EVIDENCE_MISSING"
    assert report["windows_task_may_be_disabled"] is False
