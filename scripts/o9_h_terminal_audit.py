#!/usr/bin/env python3
"""Strict terminal audit for the immutable O9-H one-shot Primary result.

This audit runs only after the irreversible result exists.  It does not grant
permission to execute the Primary and cannot create/repair/reset any O9-H
ledger artifact.  It independently verifies reservation/seal/result bindings,
support-artifact hashes, the frozen decision rule, and that risk remains locked.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from lpz_risk.o9_primary_confirmatory import (
    ALPHA,
    BOOTSTRAP_RESAMPLES,
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
    exact_one_sided_sign_test_gt_zero,
)
from scripts import o9_h_one_shot_primary_confirmatory as one_shot
from scripts import o9_v08_reentry_harness as harness

PASS_GATE = "PASS_O9_H_TERMINAL_LEDGER_AND_RESULT_AUDIT"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def audit(args: argparse.Namespace) -> dict[str, Any]:
    _require(args.reservation.exists(), "O9-H reservation missing")
    _require(args.execution_seal.exists(), "O9-H execution seal missing")
    _require(args.result.exists(), "O9-H result missing")
    _require(args.pair_artifact.exists(), "O9-H pair artifact missing")
    _require(args.cluster_artifact.exists(), "O9-H cluster artifact missing")

    result = one_shot.read_json(args.result)
    reservation = one_shot.read_json(args.reservation)
    seal = one_shot.read_json(args.execution_seal)
    reservation_sha = one_shot.sha256_file(args.reservation)
    seal_sha = one_shot.sha256_file(args.execution_seal)

    _require(result.get("phase") == one_shot.RESULT_PHASE, "O9-H result phase invalid")
    _require(result.get("gate") == one_shot.RESULT_GATE, "O9-H result integrity gate invalid")
    _require(int(result.get("confirmatory_run_count", -1)) == 1, "confirmatory_run_count must equal one")
    _require(result.get("attempt_id") == reservation.get("attempt_id") == seal.get("attempt_id"), "attempt identity differs across ledger")
    _require(result.get("reservation_sha256") == reservation_sha, "result/reservation SHA binding invalid")
    _require(result.get("execution_seal_sha256") == seal_sha, "result/seal SHA binding invalid")
    _require(seal.get("reservation_sha256") == reservation_sha, "seal/reservation SHA binding invalid")

    frozen = harness.verify_frozen_protocol(args.repo_root)
    _require(frozen["state"] == "PASS", f"frozen protocol integrity failed: {frozen['errors']}")
    _require(result.get("phase_h_freeze_sha256") == frozen["h_sha256"], "result Phase H freeze SHA invalid")
    _require(result.get("phase_k2_freeze_sha256") == frozen["k2_sha256"], "result K2 freeze SHA invalid")

    expected_fields = {
        "metric": PRIMARY_METRIC,
        "pressure_level_hpa": PRIMARY_PRESSURE_LEVEL_HPA,
        "contrast": PRIMARY_CONTRAST,
        "snapshot_offset_hours": PRIMARY_SNAPSHOT_OFFSET_HOURS,
        "match_set_difference": MATCH_SET_DIFFERENCE,
        "cluster_unit": CLUSTER_UNIT,
        "within_cluster_aggregation": WITHIN_CLUSTER_AGGREGATION,
        "primary_effect_estimate_definition": PRIMARY_EFFECT_ESTIMATE,
        "test": PRIMARY_TEST,
        "alternative": PRIMARY_ALTERNATIVE,
        "zeros": ZEROS_POLICY,
        "alpha": ALPHA,
        "matched_case_count": 92,
        "positive_case_count": 23,
        "comparison_case_count": 69,
        "match_set_count": 23,
    }
    for key, expected in expected_fields.items():
        _require(result.get(key) == expected, f"O9-H result {key} changed: {result.get(key)!r}")
    _require(result.get("primary_confirmation_rule") == PRIMARY_CONFIRMATION_RULE, "Primary confirmation rule changed")
    _require(result.get("primary_outcome") in {"PASS", "FAIL"}, "Primary outcome invalid")
    _require(result.get("outcome_values_read") is True, "terminal result must record outcome read")
    _require(result.get("primary_confirmatory_test_run") is True, "terminal result must record Primary execution")
    _require(result.get("confirmatory_run_may_execute") is False, "terminal result must close execution gate")
    _require(result.get("retuned_after_result") is False, "post-result retuning is forbidden")
    _require(result.get("secondary_hypotheses_used_to_rescue_primary") is False, "secondary rescue is forbidden")
    _require(result.get("robustness_used_to_rescue_primary") is False, "robustness rescue is forbidden")
    _require(result.get("new_feature_created_after_validation_open") is False, "new validation feature is forbidden")
    _require(result.get("new_time_offset_created_after_validation_open") is False, "new validation offset is forbidden")
    _require(result.get("threshold_search_after_validation_open") is False, "validation threshold search is forbidden")
    _require(result.get("risk_engine_allowed") is False, "Risk Engine unexpectedly unlocked")
    _require(result.get("public_risk_release_allowed") is False, "public risk unexpectedly unlocked")
    _require(result.get("automatic_rerun_allowed") is False, "automatic rerun unexpectedly allowed")

    pair_meta = result.get("pair_artifact") or {}
    cluster_meta = result.get("cluster_artifact") or {}
    _require(one_shot.sha256_file(args.pair_artifact) == pair_meta.get("sha256"), "pair artifact SHA mismatch")
    _require(one_shot.sha256_file(args.cluster_artifact) == cluster_meta.get("sha256"), "cluster artifact SHA mismatch")
    pairs = _read_csv(args.pair_artifact)
    clusters = _read_csv(args.cluster_artifact)
    _require(len(pairs) == 23 == int(pair_meta.get("rows", -1)), "pair artifact must contain 23 match sets")
    _require(1 <= len(clusters) <= 23, "invalid Positive-date cluster count")
    _require(len(clusters) == int(cluster_meta.get("rows", -1)), "cluster artifact row metadata mismatch")
    _require(len(clusters) == int(result.get("positive_date_cluster_count", -1)), "result cluster count mismatch")
    _require(sum(int(x["match_set_count"]) for x in clusters) == 23, "cluster artifact does not cover all 23 match sets")

    cluster_means = [float(x["cluster_mean_difference"]) for x in clusters]
    _require(all(math.isfinite(x) for x in cluster_means), "cluster artifact contains non-finite mean")
    effect = sum(cluster_means) / len(cluster_means)
    _require(effect == pytest_approx_free(float(result["primary_effect_estimate"])), "Primary effect does not match cluster artifact")
    sign = exact_one_sided_sign_test_gt_zero(cluster_means)
    reported_sign = result.get("sign_test") or {}
    for key in ("positive_count", "negative_count", "zero_count", "nonzero_count"):
        _require(int(reported_sign.get(key, -1)) == int(sign[key]), f"reported sign statistic {key} mismatch")
    _require(abs(float(reported_sign.get("p_value_one_sided", -1)) - float(sign["p_value_one_sided"])) <= 1e-15, "one-sided sign-test p mismatch")
    expected_outcome = "PASS" if effect > 0.0 and sign["p_value_one_sided"] < ALPHA else "FAIL"
    _require(result.get("primary_outcome") == expected_outcome, "Primary PASS/FAIL violates frozen rule")

    robustness = result.get("robustness") or {}
    _require(robustness.get("status") == "SUPPORT_ONLY_CANNOT_RESCUE_PRIMARY", "robustness status changed")
    boot = robustness.get("cluster_bootstrap") or {}
    _require(int(boot.get("resamples", -1)) == BOOTSTRAP_RESAMPLES, "bootstrap resample count changed")

    g_path = args.evidence_dir / harness.STAGE_BY_KEY["era5_reconstruction"].filename
    _require(g_path.exists(), "O9-G completion disappeared")
    g_sha = one_shot.sha256_file(g_path)
    _require(result.get("o9_g_completion_sha256") == g_sha, "result/O9-G completion SHA mismatch")
    _require((result.get("requires_sha256") or {}).get(g_path.name) == g_sha, "result predecessor hash chain invalid")
    g = one_shot.read_json(g_path)
    _require(g.get("snapshot_feature_csv_sha256") == result.get("snapshot_feature_csv_sha256"), "result snapshot CSV binding differs from O9-G")
    _require(g.get("snapshot_feature_json_sha256") == result.get("snapshot_feature_json_sha256"), "result snapshot JSON binding differs from O9-G")

    chain = harness.evaluate_chain(args.repo_root, args.evidence_dir)
    _require(chain.get("state") in {"O9_CONFIRMATORY_COMPLETE_PASS", "O9_CONFIRMATORY_COMPLETE_FAIL"}, f"global O9 harness not terminal: {chain}")
    _require(chain.get("confirmatory_run_count") == 1, "global harness run count changed")
    _require(chain.get("risk_engine_allowed") is False, "global harness Risk Engine unlocked")
    _require(chain.get("public_risk_release_allowed") is False, "global harness public risk unlocked")

    return {
        "schema_version": "1.0.0",
        "phase": "O9-H-terminal-ledger-and-result-audit",
        "gate": PASS_GATE,
        "primary_outcome": expected_outcome,
        "confirmatory_run_count": 1,
        "reservation_sha256": reservation_sha,
        "execution_seal_sha256": seal_sha,
        "result_sha256": one_shot.sha256_file(args.result),
        "pair_artifact_sha256": one_shot.sha256_file(args.pair_artifact),
        "cluster_artifact_sha256": one_shot.sha256_file(args.cluster_artifact),
        "primary_effect_estimate": effect,
        "one_sided_sign_test_p_value": sign["p_value_one_sided"],
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
    }


def pytest_approx_free(value: float) -> float:
    """Normalize tiny CSV/JSON decimal round-trips without importing pytest."""
    return value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=harness.ROOT)
    ap.add_argument("--evidence-dir", type=Path, required=True)
    ap.add_argument("--reservation", type=Path, required=True)
    ap.add_argument("--execution-seal", type=Path, required=True)
    ap.add_argument("--result", type=Path, required=True)
    ap.add_argument("--pair-artifact", type=Path, required=True)
    ap.add_argument("--cluster-artifact", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        report = audit(args)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"state": "BLOCKED_O9_H_TERMINAL_AUDIT", "error": str(exc), "risk_engine_allowed": False}))
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
