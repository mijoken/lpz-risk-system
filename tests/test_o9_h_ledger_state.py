from __future__ import annotations

import importlib.util
from pathlib import Path

from scripts import o9_h_ledger_state as state
from scripts import o9_v08_reentry_harness as harness


def _support():
    path = harness.ROOT / "tests/test_o9_h_one_shot_primary_confirmatory.py"
    spec = importlib.util.spec_from_file_location("o9_h_test_support_for_state", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_empty_live_style_evidence_preserves_base_wait_state(tmp_path: Path):
    report = state.evaluate(harness.ROOT, tmp_path)
    assert report["state"] == "WAIT_IMERG_FINAL_V08_NOT_AVAILABLE_OR_NOT_PROVEN"
    assert report["o9_h_ledger_state"] == "NOT_STARTED"
    assert report["confirmatory_run_may_execute"] is False
    assert report["risk_engine_allowed"] is False


def test_g_complete_without_ledger_is_ready_for_single_primary(tmp_path: Path):
    s = _support()
    evidence, g_args = s._make_controlled_ready_chain(tmp_path)
    report = state.evaluate(harness.ROOT, evidence)
    assert report["state"] == "READY_FOR_SINGLE_FROZEN_PRIMARY_CONFIRMATORY_RUN"
    assert report["o9_h_ledger_state"] == "NOT_STARTED"
    assert report["confirmatory_run_may_execute"] is True
    assert report["risk_engine_allowed"] is False


def test_reservation_changes_global_state_and_closes_generic_execute_flag(tmp_path: Path):
    s = _support()
    evidence, g_args = s._make_controlled_ready_chain(tmp_path)
    args = s._h_args(evidence, g_args, attempt_id="run:1:job")
    assert s.runner.reserve(args) == 0
    report = state.evaluate(harness.ROOT, evidence)
    assert report["state"] == "O9_H_PRIMARY_ATTEMPT_RESERVED_AWAITING_SAME_ATTEMPT_SEAL"
    assert report["o9_h_ledger_state"] == "RESERVED_OUTCOME_UNREAD"
    assert report["confirmatory_run_may_execute"] is False
    assert report["o9_h_ledger"]["attempt_id"] == "run:1:job"


def test_execution_seal_is_visible_as_no_automatic_rerun_state(tmp_path: Path):
    s = _support()
    evidence, g_args = s._make_controlled_ready_chain(tmp_path)
    args = s._h_args(evidence, g_args, attempt_id="run:1:job")
    assert s.runner.reserve(args) == 0
    assert s.runner.arm(args) == 0
    report = state.evaluate(harness.ROOT, evidence)
    assert report["state"] == "O9_H_PRIMARY_EXECUTION_SEALED_NO_AUTOMATIC_RERUN"
    assert report["o9_h_ledger_state"] == "SEALED_OUTCOME_NOT_YET_RECORDED"
    assert report["confirmatory_run_may_execute"] is False
    assert "ONLY_ORIGINAL_SEALED_ATTEMPT" in report["next_action"]


def test_seal_without_reservation_is_integrity_violation(tmp_path: Path):
    (tmp_path / state.one_shot.SEAL_FILE).write_text("{}\n", encoding="utf-8")
    report = state.evaluate(harness.ROOT, tmp_path)
    assert report["state"] == "BLOCKED_O9_H_LEDGER_INTEGRITY_VIOLATION"
    assert report["o9_h_ledger_state"] == "INTEGRITY_VIOLATION"
    assert report["confirmatory_run_may_execute"] is False


def test_terminal_one_shot_result_is_ledger_bound_and_locked(tmp_path: Path):
    s = _support()
    evidence, g_args = s._make_controlled_ready_chain(tmp_path, positive_higher=True)
    args = s._h_args(evidence, g_args, attempt_id="run:1:job")
    assert s.runner.reserve(args) == 0
    assert s.runner.arm(args) == 0
    assert s.runner.execute(args) == 0
    report = state.evaluate(harness.ROOT, evidence)
    assert report["state"] == "O9_CONFIRMATORY_COMPLETE_PASS"
    assert report["o9_h_ledger_state"] == "TERMINAL_ONE_SHOT_RESULT_RECORDED"
    assert report["confirmatory_run_count"] == 1
    assert report["confirmatory_run_may_execute"] is False
    assert report["risk_engine_allowed"] is False
    assert report["public_risk_release_allowed"] is False


def test_result_without_reservation_and_seal_is_blocked(tmp_path: Path):
    s = _support()
    evidence, g_args = s._make_controlled_ready_chain(tmp_path, positive_higher=True)
    args = s._h_args(evidence, g_args)
    assert s.runner.reserve(args) == 0
    assert s.runner.arm(args) == 0
    assert s.runner.execute(args) == 0
    args.reservation_output.unlink()
    args.execution_seal_output.unlink()
    report = state.evaluate(harness.ROOT, evidence)
    assert report["state"] == "BLOCKED_O9_H_LEDGER_INTEGRITY_VIOLATION"
    assert report["confirmatory_run_may_execute"] is False


def test_tampered_reservation_is_blocked_by_ledger_overlay(tmp_path: Path):
    s = _support()
    evidence, g_args = s._make_controlled_ready_chain(tmp_path)
    args = s._h_args(evidence, g_args)
    assert s.runner.reserve(args) == 0
    with args.reservation_output.open("a", encoding="utf-8") as f:
        f.write("\n")
    report = state.evaluate(harness.ROOT, evidence)
    assert report["state"] == "BLOCKED_O9_H_LEDGER_INTEGRITY_VIOLATION"
    assert report["confirmatory_run_may_execute"] is False
