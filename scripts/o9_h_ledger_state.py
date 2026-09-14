#!/usr/bin/env python3
"""Ledger-aware O9-H state overlay for the O9 Final-V08 re-entry harness.

The base O9 harness owns the immutable A->G scientific order.  O9-H adds two
pre-outcome immutable files (reservation and execution seal) that are not
scientific evidence stages themselves.  This overlay makes those intermediate
one-shot states visible and fail-closed without changing the already-frozen
A->G state machine.

Important: a persisted execution seal does *not* authorize a new workflow run
to execute the Primary.  Only the exact attempt identity written into that seal
may continue.  From any later observer/re-run, the sealed/no-result state is a
forensic-review state with confirmatory_run_may_execute=false.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from lpz_risk.o9_primary_confirmatory import (
    ALPHA,
    CLUSTER_UNIT,
    MATCH_SET_DIFFERENCE,
    PRIMARY_ALTERNATIVE,
    PRIMARY_CONFIRMATION_RULE,
    PRIMARY_CONTRAST,
    PRIMARY_EFFECT_ESTIMATE,
    PRIMARY_METRIC,
    PRIMARY_PRESSURE_LEVEL_HPA,
    PRIMARY_SNAPSHOT_OFFSET_HOURS,
    PRIMARY_TEST,
    WITHIN_CLUSTER_AGGREGATION,
    ZEROS_POLICY,
)
from scripts import o9_h_one_shot_primary_confirmatory as one_shot
from scripts import o9_v08_reentry_harness as harness

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_CSV_FILE = "o9_g_era5_snapshot_features.csv"
SNAPSHOT_JSON_FILE = "o9_g_era5_snapshot_features.json"


def _blocked(base: dict[str, Any], message: str) -> dict[str, Any]:
    out = dict(base)
    out.update({
        "state": "BLOCKED_O9_H_LEDGER_INTEGRITY_VIOLATION",
        "next_stage_key": "primary_confirmatory",
        "next_action": "MANUAL_FORENSIC_REVIEW;_DO_NOT_RERUN_PRIMARY",
        "blockers": [message],
        "confirmatory_run_may_execute": False,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
        "o9_h_ledger_state": "INTEGRITY_VIOLATION",
    })
    return out


def _runner_args(repo_root: Path, evidence_dir: Path, attempt_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        repo_root=repo_root,
        evidence_dir=evidence_dir,
        snapshot_csv=evidence_dir / SNAPSHOT_CSV_FILE,
        snapshot_json=evidence_dir / SNAPSHOT_JSON_FILE,
        attempt_id=attempt_id,
        reservation_output=evidence_dir / one_shot.RESERVATION_FILE,
        execution_seal_output=evidence_dir / one_shot.SEAL_FILE,
        result_output=evidence_dir / one_shot.RESULT_FILE,
        pair_output=evidence_dir / one_shot.PAIR_FILE,
        cluster_output=evidence_dir / one_shot.CLUSTER_FILE,
    )


def _validate_terminal_result_summary(
    result: dict[str, Any],
    *,
    reservation: dict[str, Any],
    reservation_sha: str,
    seal: dict[str, Any],
    seal_sha: str,
) -> list[str]:
    e: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            e.append(message)

    check(result.get("phase") == one_shot.RESULT_PHASE, "terminal result phase invalid")
    check(result.get("gate") == one_shot.RESULT_GATE, "terminal result gate invalid")
    check(result.get("attempt_id") == reservation.get("attempt_id") == seal.get("attempt_id"), "attempt identity differs across reservation/seal/result")
    check(result.get("reservation_sha256") == reservation_sha, "terminal result reservation SHA binding invalid")
    check(result.get("execution_seal_sha256") == seal_sha, "terminal result execution-seal SHA binding invalid")
    check(int(result.get("confirmatory_run_count", -1)) == 1, "confirmatory_run_count must equal one")
    check(result.get("metric") == PRIMARY_METRIC, f"metric must be {PRIMARY_METRIC}")
    check(int(result.get("pressure_level_hpa", -1)) == PRIMARY_PRESSURE_LEVEL_HPA, "pressure_level_hpa must be 850")
    check(result.get("contrast") == PRIMARY_CONTRAST, f"contrast must be {PRIMARY_CONTRAST}")
    check(int(result.get("snapshot_offset_hours", 999)) == PRIMARY_SNAPSHOT_OFFSET_HOURS, "snapshot_offset_hours must be 0")
    check(result.get("match_set_difference") == MATCH_SET_DIFFERENCE, "match-set estimand changed")
    check(result.get("cluster_unit") == CLUSTER_UNIT, "cluster unit changed")
    check(result.get("within_cluster_aggregation") == WITHIN_CLUSTER_AGGREGATION, "within-cluster aggregation changed")
    check(result.get("primary_effect_estimate_definition") == PRIMARY_EFFECT_ESTIMATE, "Primary effect definition changed")
    check(result.get("test") == PRIMARY_TEST, f"test must be {PRIMARY_TEST}")
    check(result.get("alternative") == PRIMARY_ALTERNATIVE, "Primary alternative changed")
    check(result.get("zeros") == ZEROS_POLICY, "zero policy changed")
    try:
        check(float(result.get("alpha", -1)) == ALPHA, "alpha must be 0.05")
    except Exception:  # noqa: BLE001
        e.append("alpha must be numeric 0.05")
    check(result.get("primary_confirmation_rule") == PRIMARY_CONFIRMATION_RULE, "Primary confirmation rule changed")
    for key, expected in {
        "matched_case_count": 92,
        "positive_case_count": 23,
        "comparison_case_count": 69,
        "match_set_count": 23,
    }.items():
        try:
            check(int(result.get(key, -1)) == expected, f"{key} must be {expected}")
        except Exception:  # noqa: BLE001
            e.append(f"{key} must be {expected}")

    check(result.get("outcome_values_read") is True, "terminal result must record outcome read")
    check(result.get("primary_confirmatory_test_run") is True, "terminal result must record Primary execution")
    check(result.get("confirmatory_run_may_execute") is False, "terminal result must close Primary execution gate")
    check(result.get("retuned_after_result") is False, "post-result retuning forbidden")
    check(result.get("secondary_hypotheses_used_to_rescue_primary") is False, "secondary rescue forbidden")
    check(result.get("robustness_used_to_rescue_primary") is False, "robustness rescue forbidden")
    check(result.get("new_feature_created_after_validation_open") is False, "new validation feature forbidden")
    check(result.get("new_time_offset_created_after_validation_open") is False, "new validation offset forbidden")
    check(result.get("threshold_search_after_validation_open") is False, "validation threshold search forbidden")
    check(result.get("automatic_rerun_allowed") is False, "automatic rerun must remain forbidden")
    check(result.get("risk_engine_allowed") is False, "Risk Engine unexpectedly unlocked")
    check(result.get("public_risk_release_allowed") is False, "public risk unexpectedly unlocked")

    for key in (
        "o9_g_completion_sha256",
        "snapshot_feature_csv_sha256",
        "snapshot_feature_json_sha256",
        "phase_h_freeze_sha256",
        "phase_k2_freeze_sha256",
        "primary_definition_sha256",
    ):
        check(result.get(key) == reservation.get(key), f"terminal result {key} differs from reservation")

    outcome = result.get("primary_outcome")
    check(outcome in {"PASS", "FAIL"}, "primary_outcome must be PASS or FAIL")
    try:
        effect = float(result.get("primary_effect_estimate"))
        p_value = float((result.get("sign_test") or {}).get("p_value_one_sided"))
        check(math.isfinite(effect), "Primary effect must be finite")
        check(math.isfinite(p_value) and 0.0 <= p_value <= 1.0, "sign-test p-value must be finite in [0,1]")
        expected_outcome = "PASS" if effect > 0.0 and p_value < ALPHA else "FAIL"
        check(outcome == expected_outcome, "terminal PASS/FAIL violates frozen effect>0 and p<0.05 rule")
    except Exception:  # noqa: BLE001
        e.append("terminal Primary effect/sign-test p-value invalid")

    return e


def evaluate(repo_root: Path, evidence_dir: Path) -> dict[str, Any]:
    base = harness.evaluate_chain(repo_root, evidence_dir)
    reservation_path = evidence_dir / one_shot.RESERVATION_FILE
    seal_path = evidence_dir / one_shot.SEAL_FILE
    result_path = evidence_dir / one_shot.RESULT_FILE
    reservation_exists = reservation_path.exists()
    seal_exists = seal_path.exists()
    result_exists = result_path.exists()

    base = dict(base)
    base["o9_h_ledger"] = {
        "reservation_exists": reservation_exists,
        "execution_seal_exists": seal_exists,
        "result_exists": result_exists,
    }

    if not reservation_exists and not seal_exists and not result_exists:
        base["o9_h_ledger_state"] = "NOT_STARTED"
        return base
    if seal_exists and not reservation_exists:
        return _blocked(base, "execution seal exists without immutable O9-H reservation")
    if result_exists and (not reservation_exists or not seal_exists):
        return _blocked(base, "Primary result exists without complete reservation+execution-seal ledger")

    try:
        reservation = one_shot.read_json(reservation_path)
        attempt_id = str(reservation.get("attempt_id") or "")
        if not attempt_id:
            raise ValueError("reservation attempt_id missing")
        args = _runner_args(repo_root, evidence_dir, attempt_id)
        one_shot._validate_reservation_against_current_context(args, reservation, require_attempt_match=False)
        reservation_sha = one_shot.sha256_file(reservation_path)
    except Exception as exc:  # noqa: BLE001
        return _blocked(base, f"reservation integrity failure: {type(exc).__name__}: {exc}")

    base["o9_h_ledger"].update({
        "attempt_id": attempt_id,
        "reservation_sha256": reservation_sha,
    })

    if not seal_exists:
        if result_exists:
            return _blocked(base, "Primary result exists before execution seal")
        if base.get("state") != "READY_FOR_SINGLE_FROZEN_PRIMARY_CONFIRMATORY_RUN":
            return _blocked(base, f"reservation exists outside exact G-complete readiness state: {base.get('state')}")
        base.update({
            "state": "O9_H_PRIMARY_ATTEMPT_RESERVED_AWAITING_SAME_ATTEMPT_SEAL",
            "next_stage_key": "primary_confirmatory",
            "next_action": "ONLY_RESERVED_ATTEMPT_MAY_ARM;_OTHER_RUNS_REQUIRE_FORENSIC_REVIEW",
            "blockers": [],
            "confirmatory_run_may_execute": False,
            "risk_engine_allowed": False,
            "public_risk_release_allowed": False,
            "o9_h_ledger_state": "RESERVED_OUTCOME_UNREAD",
        })
        return base

    try:
        seal, seal_sha = one_shot.validate_execution_seal(args, reservation, reservation_sha)
    except Exception as exc:  # noqa: BLE001
        return _blocked(base, f"execution-seal integrity failure: {type(exc).__name__}: {exc}")

    base["o9_h_ledger"].update({
        "execution_seal_sha256": seal_sha,
    })

    if not result_exists:
        if base.get("state") != "READY_FOR_SINGLE_FROZEN_PRIMARY_CONFIRMATORY_RUN":
            return _blocked(base, f"sealed attempt exists outside exact G-complete readiness state: {base.get('state')}")
        base.update({
            "state": "O9_H_PRIMARY_EXECUTION_SEALED_NO_AUTOMATIC_RERUN",
            "next_stage_key": "primary_confirmatory",
            "next_action": "ONLY_ORIGINAL_SEALED_ATTEMPT_MAY_CONTINUE;_OTHERWISE_MANUAL_FORENSIC_REVIEW",
            "blockers": [],
            "confirmatory_run_may_execute": False,
            "risk_engine_allowed": False,
            "public_risk_release_allowed": False,
            "o9_h_ledger_state": "SEALED_OUTCOME_NOT_YET_RECORDED",
        })
        return base

    try:
        result = one_shot.read_json(result_path)
        errors = _validate_terminal_result_summary(
            result,
            reservation=reservation,
            reservation_sha=reservation_sha,
            seal=seal,
            seal_sha=seal_sha,
        )
        if errors:
            raise ValueError("; ".join(errors))
    except Exception as exc:  # noqa: BLE001
        return _blocked(base, f"terminal result/ledger integrity failure: {type(exc).__name__}: {exc}")

    if base.get("state") not in {"O9_CONFIRMATORY_COMPLETE_PASS", "O9_CONFIRMATORY_COMPLETE_FAIL"}:
        return _blocked(base, f"result ledger exists but base O9 chain is not terminal: {base.get('state')}")
    if base.get("primary_outcome") != result.get("primary_outcome"):
        return _blocked(base, "base O9 terminal outcome differs from immutable O9-H result")

    base.update({
        "confirmatory_run_may_execute": False,
        "confirmatory_run_count": 1,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
        "o9_h_ledger_state": "TERMINAL_ONE_SHOT_RESULT_RECORDED",
    })
    return base


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=ROOT)
    ap.add_argument("--evidence-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    report = evaluate(args.repo_root, args.evidence_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": report["state"],
        "o9_h_ledger_state": report.get("o9_h_ledger_state"),
        "confirmatory_run_may_execute": report.get("confirmatory_run_may_execute", False),
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
    }))
    return 2 if report["state"].startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
