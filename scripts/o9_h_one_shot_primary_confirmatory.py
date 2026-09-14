#!/usr/bin/env python3
"""O9-H one-shot frozen Primary executor / immutable ledger.

This runner deliberately splits the irreversible validation read into three
separate commands:

1. ``reserve`` validates the real O9 chain through O9-G and writes an immutable
   attempt reservation.  It hashes the O9-G snapshot artifacts but does not
   interpret q850 values.
2. ``arm`` validates that the exact same attempt and evidence are still
   present and writes an immutable execution seal.  It still does not read the
   Primary outcome values.
3. ``execute`` is allowed to read q850 values only when both immutable files
   exist and the current attempt identity exactly matches the seal.  It writes
   the frozen Primary result exactly once.

The intended GitHub workflow commits/pushes the reservation and execution seal
before ``execute``.  A later GitHub re-run receives a different run-attempt
identity and therefore cannot reuse an already sealed attempt.  There is no
reset/overwrite flag.  A crash after sealing is a manual forensic-review state,
not permission to run the Primary again.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from lpz_risk.o9_primary_confirmatory import (
    ALPHA,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CLUSTER_UNIT,
    MATCH_SET_DIFFERENCE,
    PRIMARY_ALTERNATIVE,
    PRIMARY_CONFIRMATION_RULE,
    PRIMARY_CONTRAST,
    PRIMARY_DIRECTIONAL_ALTERNATIVE,
    PRIMARY_EFFECT_ESTIMATE,
    PRIMARY_METRIC,
    PRIMARY_PRESSURE_LEVEL_HPA,
    PRIMARY_SNAPSHOT_OFFSET_HOURS,
    PRIMARY_TEST,
    WITHIN_CLUSTER_AGGREGATION,
    ZEROS_POLICY,
    analyze_primary,
    read_snapshot_csv,
)
from scripts import o9_v08_reentry_harness as harness

ROOT = Path(__file__).resolve().parents[1]
RESERVATION_FILE = "o9_h_primary_attempt_reservation.json"
SEAL_FILE = "o9_h_primary_execution_seal.json"
RESULT_FILE = "o9_h_primary_confirmatory_result.json"
PAIR_FILE = "o9_h_primary_match_set_differences.csv"
CLUSTER_FILE = "o9_h_primary_positive_date_clusters.csv"

RESERVATION_PHASE = "O9-H-primary-attempt-reservation"
RESERVATION_GATE = "PASS_O9_H_SINGLE_ATTEMPT_RESERVED_BEFORE_PRIMARY_OUTCOME_READ"
SEAL_PHASE = "O9-H-primary-execution-seal"
SEAL_GATE = "PASS_O9_H_EXECUTION_SEALED_BEFORE_PRIMARY_OUTCOME_READ"
RESULT_PHASE = "O9-H-one-shot-frozen-primary-confirmatory-result"
RESULT_GATE = "PASS_O9_H_ONE_SHOT_FROZEN_PRIMARY_EXECUTION_INTEGRITY"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha256(obj: Any) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"JSON object required: {path}")
    return obj


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _require_sha(value: Any, *, name: str) -> str:
    text = str(value or "")
    _require(len(text) == 64 and all(c in "0123456789abcdef" for c in text.lower()), f"{name} must be a SHA-256 hex digest")
    return text.lower()


def exclusive_write_json(path: Path, obj: dict[str, Any]) -> None:
    """Create a JSON file exactly once.  Never overwrites an existing ledger."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb", closefd=True) as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        # A partial file is intentionally left in place: its existence blocks
        # automatic rerun and forces forensic review rather than outcome peek.
        raise


def exclusive_write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    _require(bool(rows), f"cannot write empty {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="", closefd=True) as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        raise


def frozen_primary_definition(h: dict[str, Any]) -> dict[str, Any]:
    primary = h.get("primary_hypothesis") or {}
    estimand = h.get("primary_validation_estimand") or {}
    test = h.get("primary_validation_test") or {}
    robustness = h.get("pre_specified_robustness_checks") or {}
    secondary_policy = h.get("secondary_analysis_policy") or {}

    checks = {
        "id": primary.get("id") == "H_PRIMARY_Q850_T0H",
        "metric": primary.get("metric") == PRIMARY_METRIC,
        "pressure_level": int(primary.get("pressure_level_hpa", -1)) == PRIMARY_PRESSURE_LEVEL_HPA,
        "contrast": primary.get("contrast") == PRIMARY_CONTRAST,
        "offset": int(primary.get("era5_snapshot_offset_hours", 999)) == PRIMARY_SNAPSHOT_OFFSET_HOURS,
        "spatial_semantics": primary.get("spatial_semantics") == "ERA5_REQUEST_BBOX_CONTEXT_NOT_SUBDIVISION_POLYGON_MEAN",
        "direction": primary.get("directional_alternative") == PRIMARY_DIRECTIONAL_ALTERNATIVE,
        "sole_primary": primary.get("confirmatory_status") == "ONLY_PRIMARY_CONFIRMATORY_HYPOTHESIS",
        "match_set_difference": estimand.get("match_set_difference") == MATCH_SET_DIFFERENCE,
        "cluster_unit": estimand.get("cluster_unit") == CLUSTER_UNIT,
        "within_cluster": estimand.get("within_cluster_aggregation") == WITHIN_CLUSTER_AGGREGATION,
        "effect": estimand.get("primary_effect_estimate") == PRIMARY_EFFECT_ESTIMATE,
        "test": test.get("test") == PRIMARY_TEST,
        "alternative": test.get("alternative") == PRIMARY_ALTERNATIVE,
        "zeros": test.get("zeros") == ZEROS_POLICY,
        "alpha": float(test.get("alpha", -1)) == ALPHA,
        "multiplicity": test.get("multiplicity_correction") == "NONE_REQUIRED_FOR_SINGLE_PRE_SPECIFIED_PRIMARY_HYPOTHESIS",
        "rule": test.get("primary_confirmation_rule") == PRIMARY_CONFIRMATION_RULE,
        "bootstrap_resamples": int(((robustness.get("cluster_bootstrap") or {}).get("resamples", -1))) == BOOTSTRAP_RESAMPLES,
        "bootstrap_ci": float(((robustness.get("cluster_bootstrap") or {}).get("ci", -1))) == 0.95,
        "secondary_cannot_rescue": secondary_policy.get("cannot_override_primary_failure") is True,
        "risk_locked": h.get("risk_engine_allowed") is False,
    }
    bad = [k for k, ok in checks.items() if not ok]
    if bad:
        raise ValueError(f"authoritative Phase H frozen Primary contract changed: {bad}")

    return {
        "id": "H_PRIMARY_Q850_T0H",
        "metric": PRIMARY_METRIC,
        "pressure_level_hpa": PRIMARY_PRESSURE_LEVEL_HPA,
        "contrast": PRIMARY_CONTRAST,
        "snapshot_offset_hours": PRIMARY_SNAPSHOT_OFFSET_HOURS,
        "spatial_semantics": "ERA5_REQUEST_BBOX_CONTEXT_NOT_SUBDIVISION_POLYGON_MEAN",
        "directional_alternative": PRIMARY_DIRECTIONAL_ALTERNATIVE,
        "match_set_difference": MATCH_SET_DIFFERENCE,
        "cluster_unit": CLUSTER_UNIT,
        "within_cluster_aggregation": WITHIN_CLUSTER_AGGREGATION,
        "primary_effect_estimate": PRIMARY_EFFECT_ESTIMATE,
        "test": PRIMARY_TEST,
        "alternative": PRIMARY_ALTERNATIVE,
        "zeros": ZEROS_POLICY,
        "alpha": ALPHA,
        "primary_confirmation_rule": list(PRIMARY_CONFIRMATION_RULE),
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "bootstrap_seed_implementation": BOOTSTRAP_SEED,
        "secondary_or_robustness_may_rescue_primary": False,
    }


def _validate_layout(args: argparse.Namespace) -> None:
    evidence = args.evidence_dir.resolve()
    expected = {
        args.reservation_output.resolve(): evidence / RESERVATION_FILE,
        args.execution_seal_output.resolve(): evidence / SEAL_FILE,
        args.result_output.resolve(): evidence / RESULT_FILE,
        args.pair_output.resolve(): evidence / PAIR_FILE,
        args.cluster_output.resolve(): evidence / CLUSTER_FILE,
    }
    for actual, wanted in expected.items():
        _require(actual == wanted, f"O9-H immutable output path must be {wanted}, got {actual}")


def verify_reservation_preconditions(args: argparse.Namespace) -> dict[str, Any]:
    """Verify chain and hashes without interpreting any Primary q850 values."""
    _validate_layout(args)
    frozen = harness.verify_frozen_protocol(args.repo_root)
    _require(frozen["state"] == "PASS", f"frozen protocol integrity failed: {frozen['errors']}")
    h_path = args.repo_root / harness.H_FREEZE.relative_to(harness.ROOT)
    h = read_json(h_path)
    primary_definition = frozen_primary_definition(h)

    chain = harness.evaluate_chain(args.repo_root, args.evidence_dir)
    _require(
        chain.get("state") == "READY_FOR_SINGLE_FROZEN_PRIMARY_CONFIRMATORY_RUN",
        f"O9-H reservation requires exact G-complete readiness state, got {chain.get('state')}: {chain.get('blockers')}",
    )
    _require(chain.get("confirmatory_run_may_execute") is True, "O9-H Primary is not eligible")
    _require(chain.get("risk_engine_allowed") is False, "Risk Engine must remain locked")
    _require(chain.get("public_risk_release_allowed") is False, "public risk must remain locked")

    g_path = args.evidence_dir / harness.STAGE_BY_KEY["era5_reconstruction"].filename
    g = read_json(g_path)
    g_errors = harness.validate_era5_completion(g)
    _require(not g_errors, f"O9-G completion receipt invalid: {g_errors}")
    _require(g.get("gate") == harness.G_COMPLETE_GATE, "O9-G completion gate changed")
    _require(g.get("confirmatory_run_may_execute") is True, "O9-G completion does not allow Primary eligibility")

    _require(args.snapshot_csv.exists(), f"missing O9-G snapshot CSV: {args.snapshot_csv}")
    _require(args.snapshot_json.exists(), f"missing O9-G snapshot JSON: {args.snapshot_json}")
    csv_sha = sha256_file(args.snapshot_csv)
    json_sha = sha256_file(args.snapshot_json)
    _require(csv_sha == g.get("snapshot_feature_csv_sha256"), "O9-G snapshot CSV SHA does not match completion receipt")
    _require(json_sha == g.get("snapshot_feature_json_sha256"), "O9-G snapshot JSON SHA does not match completion receipt")

    stage_hashes = {str(x["filename"]): str(x["sha256"]) for x in chain.get("stages", [])}
    _require(g_path.name in stage_hashes, "G completion hash missing from chain report")
    return {
        "frozen": frozen,
        "primary_definition": primary_definition,
        "primary_definition_sha256": canonical_sha256(primary_definition),
        "g_completion": g,
        "g_completion_path": g_path,
        "g_completion_sha256": sha256_file(g_path),
        "snapshot_csv_sha256": csv_sha,
        "snapshot_json_sha256": json_sha,
        "evidence_chain_sha256": stage_hashes,
    }


def _validate_reservation_against_current_context(
    args: argparse.Namespace,
    reservation: dict[str, Any],
    *,
    require_attempt_match: bool = True,
) -> dict[str, Any]:
    frozen = harness.verify_frozen_protocol(args.repo_root)
    _require(frozen["state"] == "PASS", f"frozen protocol integrity failed: {frozen['errors']}")
    h_path = args.repo_root / harness.H_FREEZE.relative_to(harness.ROOT)
    definition = frozen_primary_definition(read_json(h_path))
    _require(reservation.get("phase") == RESERVATION_PHASE, "O9-H reservation phase invalid")
    _require(reservation.get("gate") == RESERVATION_GATE, "O9-H reservation gate invalid")
    _require(int(reservation.get("confirmatory_run_count", -1)) == 1, "O9-H reservation run count must equal one")
    if require_attempt_match:
        _require(reservation.get("attempt_id") == args.attempt_id, "O9-H attempt identity does not match immutable reservation")
    _require(reservation.get("outcome_values_read") is False, "reservation must precede outcome read")
    _require(reservation.get("primary_confirmatory_test_run") is False, "reservation incorrectly marks Primary executed")
    _require(reservation.get("risk_engine_allowed") is False, "reservation must keep Risk Engine locked")
    _require(reservation.get("public_risk_release_allowed") is False, "reservation must keep public risk locked")
    _require(reservation.get("phase_h_freeze_sha256") == frozen["h_sha256"], "Phase H freeze SHA changed after reservation")
    _require(reservation.get("phase_k2_freeze_sha256") == frozen["k2_sha256"], "K2 freeze SHA changed after reservation")
    _require(reservation.get("primary_definition_sha256") == canonical_sha256(definition), "frozen Primary definition changed after reservation")

    chain_hashes = reservation.get("evidence_chain_sha256")
    _require(isinstance(chain_hashes, dict) and chain_hashes, "reservation missing evidence-chain hashes")
    for filename, expected_sha in chain_hashes.items():
        path = args.evidence_dir / str(filename)
        _require(path.exists(), f"reserved O9 evidence disappeared: {filename}")
        _require(sha256_file(path) == expected_sha, f"reserved O9 evidence changed: {filename}")

    g_path = args.evidence_dir / harness.STAGE_BY_KEY["era5_reconstruction"].filename
    g = read_json(g_path)
    errors = harness.validate_era5_completion(g)
    _require(not errors and g.get("gate") == harness.G_COMPLETE_GATE, f"current O9-G completion invalid: {errors}")
    _require(sha256_file(g_path) == reservation.get("o9_g_completion_sha256"), "O9-G completion changed after reservation")
    _require(args.snapshot_csv.exists() and args.snapshot_json.exists(), "reserved O9-G snapshot artifacts are missing")
    _require(sha256_file(args.snapshot_csv) == reservation.get("snapshot_feature_csv_sha256"), "snapshot CSV changed after reservation")
    _require(sha256_file(args.snapshot_json) == reservation.get("snapshot_feature_json_sha256"), "snapshot JSON changed after reservation")
    _require(g.get("snapshot_feature_csv_sha256") == reservation.get("snapshot_feature_csv_sha256"), "G receipt/snapshot CSV binding changed")
    _require(g.get("snapshot_feature_json_sha256") == reservation.get("snapshot_feature_json_sha256"), "G receipt/snapshot JSON binding changed")
    return {
        "frozen": frozen,
        "definition": definition,
        "g": g,
        "g_path": g_path,
    }


def validate_reservation_file(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    _require(args.reservation_output.exists(), "O9-H reservation is missing")
    reservation = read_json(args.reservation_output)
    _validate_reservation_against_current_context(args, reservation)
    return reservation, sha256_file(args.reservation_output)


def validate_execution_seal(
    args: argparse.Namespace,
    reservation: dict[str, Any],
    reservation_sha: str,
) -> tuple[dict[str, Any], str]:
    _require(args.execution_seal_output.exists(), "O9-H execution seal is missing")
    seal = read_json(args.execution_seal_output)
    checks = {
        "phase": seal.get("phase") == SEAL_PHASE,
        "gate": seal.get("gate") == SEAL_GATE,
        "attempt": seal.get("attempt_id") == args.attempt_id,
        "run_count": int(seal.get("confirmatory_run_count", -1)) == 1,
        "reservation_sha": seal.get("reservation_sha256") == reservation_sha,
        "g_sha": seal.get("o9_g_completion_sha256") == reservation.get("o9_g_completion_sha256"),
        "csv_sha": seal.get("snapshot_feature_csv_sha256") == reservation.get("snapshot_feature_csv_sha256"),
        "json_sha": seal.get("snapshot_feature_json_sha256") == reservation.get("snapshot_feature_json_sha256"),
        "primary_def": seal.get("primary_definition_sha256") == reservation.get("primary_definition_sha256"),
        "outcome_unread": seal.get("outcome_values_read") is False,
        "may_begin": seal.get("primary_outcome_read_may_begin") is True,
        "no_rerun": seal.get("automatic_rerun_after_this_seal_allowed") is False,
        "primary_unrun": seal.get("primary_confirmatory_test_run") is False,
        "risk_locked": seal.get("risk_engine_allowed") is False,
        "public_locked": seal.get("public_risk_release_allowed") is False,
    }
    bad = [k for k, ok in checks.items() if not ok]
    _require(not bad, f"O9-H execution seal invalid: {bad}")
    return seal, sha256_file(args.execution_seal_output)


def reserve(args: argparse.Namespace) -> int:
    _validate_layout(args)
    _require(bool(str(args.attempt_id).strip()), "attempt_id is required")
    for path, label in (
        (args.reservation_output, "reservation"),
        (args.execution_seal_output, "execution seal"),
        (args.result_output, "Primary result"),
        (args.pair_output, "Primary pair artifact"),
        (args.cluster_output, "Primary cluster artifact"),
    ):
        _require(not path.exists(), f"O9-H {label} already exists; automatic/repeated Primary execution is forbidden")

    context = verify_reservation_preconditions(args)
    reservation = {
        "schema_version": "1.0.0",
        "phase": RESERVATION_PHASE,
        "gate": RESERVATION_GATE,
        "reserved_at_utc": utc_now(),
        "attempt_id": args.attempt_id,
        "confirmatory_run_count": 1,
        "validation_year": 2025,
        "o9_g_completion_sha256": context["g_completion_sha256"],
        "snapshot_feature_csv_sha256": context["snapshot_csv_sha256"],
        "snapshot_feature_json_sha256": context["snapshot_json_sha256"],
        "phase_h_freeze_sha256": context["frozen"]["h_sha256"],
        "phase_k2_freeze_sha256": context["frozen"]["k2_sha256"],
        "primary_definition": context["primary_definition"],
        "primary_definition_sha256": context["primary_definition_sha256"],
        "evidence_chain_sha256": context["evidence_chain_sha256"],
        "outcome_values_read": False,
        "primary_confirmatory_test_run": False,
        "automatic_rerun_allowed": False,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
        "requires_sha256": {
            context["g_completion_path"].name: context["g_completion_sha256"],
        },
        "next_required_action": "PERSIST_THIS_RESERVATION_THEN_CREATE_AND_PERSIST_EXECUTION_SEAL",
    }
    exclusive_write_json(args.reservation_output, reservation)
    print(json.dumps({"gate": RESERVATION_GATE, "attempt_id": args.attempt_id, "outcome_values_read": False}))
    return 0


def arm(args: argparse.Namespace) -> int:
    _validate_layout(args)
    _require(not args.result_output.exists(), "O9-H Primary result already exists; a second execution is forbidden")
    _require(not args.execution_seal_output.exists(), "O9-H execution seal already exists; automatic re-arming is forbidden")
    _require(not args.pair_output.exists() and not args.cluster_output.exists(), "O9-H outcome artifacts already exist; manual forensic review required")
    reservation, reservation_sha = validate_reservation_file(args)
    seal = {
        "schema_version": "1.0.0",
        "phase": SEAL_PHASE,
        "gate": SEAL_GATE,
        "sealed_at_utc": utc_now(),
        "attempt_id": args.attempt_id,
        "confirmatory_run_count": 1,
        "reservation_sha256": reservation_sha,
        "o9_g_completion_sha256": reservation["o9_g_completion_sha256"],
        "snapshot_feature_csv_sha256": reservation["snapshot_feature_csv_sha256"],
        "snapshot_feature_json_sha256": reservation["snapshot_feature_json_sha256"],
        "phase_h_freeze_sha256": reservation["phase_h_freeze_sha256"],
        "phase_k2_freeze_sha256": reservation["phase_k2_freeze_sha256"],
        "primary_definition_sha256": reservation["primary_definition_sha256"],
        "outcome_values_read": False,
        "primary_outcome_read_may_begin": True,
        "primary_confirmatory_test_run": False,
        "automatic_rerun_after_this_seal_allowed": False,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
        "next_required_action": "EXECUTE_FROZEN_PRIMARY_IN_THIS_EXACT_ATTEMPT_ONLY",
    }
    exclusive_write_json(args.execution_seal_output, seal)
    print(json.dumps({"gate": SEAL_GATE, "attempt_id": args.attempt_id, "outcome_values_read": False}))
    return 0


def _finite(value: Any, *, name: str) -> float:
    out = float(value)
    _require(math.isfinite(out), f"{name} must be finite")
    return out


def execute(
    args: argparse.Namespace,
    *,
    snapshot_reader: Callable[[Path], list[dict[str, Any]]] = read_snapshot_csv,
    analyzer: Callable[[list[dict[str, Any]]], dict[str, Any]] = analyze_primary,
) -> int:
    _validate_layout(args)
    # These checks are intentionally before snapshot_reader: any prior result or
    # outcome artifact blocks a repeated outcome read.
    _require(not args.result_output.exists(), "O9-H Primary result already exists; Primary may never execute twice")
    _require(not args.pair_output.exists(), "O9-H pair outcome artifact already exists; automatic rerun forbidden")
    _require(not args.cluster_output.exists(), "O9-H cluster outcome artifact already exists; automatic rerun forbidden")
    reservation, reservation_sha = validate_reservation_file(args)
    seal, seal_sha = validate_execution_seal(args, reservation, reservation_sha)
    _validate_reservation_against_current_context(args, reservation)

    # IRREVERSIBLE BOUNDARY: q850 outcome values are interpreted only below.
    rows = snapshot_reader(args.snapshot_csv)
    analysis = analyzer(rows)
    _require(analysis.get("metric") == PRIMARY_METRIC, "analyzer changed frozen Primary metric")
    _require(analysis.get("contrast") == PRIMARY_CONTRAST, "analyzer changed frozen Primary contrast")
    _require(analysis.get("test") == PRIMARY_TEST, "analyzer changed frozen Primary test")
    _require(analysis.get("alternative") == PRIMARY_ALTERNATIVE, "analyzer changed frozen alternative")
    _require(float(analysis.get("alpha", -1)) == ALPHA, "analyzer changed frozen alpha")
    _require(analysis.get("primary_confirmation_rule") == PRIMARY_CONFIRMATION_RULE, "analyzer changed frozen confirmation rule")
    _require(analysis.get("primary_outcome") in {"PASS", "FAIL"}, "invalid Primary outcome")

    pair_rows = list(analysis.pop("pair_rows"))
    cluster_rows = list(analysis.pop("cluster_rows"))
    exclusive_write_csv(args.pair_output, pair_rows)
    exclusive_write_csv(args.cluster_output, cluster_rows)

    effect = _finite(analysis["primary_effect_estimate"], name="primary_effect_estimate")
    p_value = _finite((analysis.get("sign_test") or {}).get("p_value_one_sided"), name="one-sided sign-test p")
    expected_outcome = "PASS" if effect > 0.0 and p_value < ALPHA else "FAIL"
    _require(analysis["primary_outcome"] == expected_outcome, "reported Primary outcome violates frozen confirmation rule")

    result = {
        "schema_version": "1.0.0",
        "phase": RESULT_PHASE,
        "gate": RESULT_GATE,
        "generated_at_utc": utc_now(),
        "validation_year": 2025,
        "attempt_id": args.attempt_id,
        "confirmatory_run_count": 1,
        "reservation_sha256": reservation_sha,
        "execution_seal_sha256": seal_sha,
        "o9_g_completion_sha256": reservation["o9_g_completion_sha256"],
        "snapshot_feature_csv_sha256": reservation["snapshot_feature_csv_sha256"],
        "snapshot_feature_json_sha256": reservation["snapshot_feature_json_sha256"],
        "phase_h_freeze_sha256": reservation["phase_h_freeze_sha256"],
        "phase_k2_freeze_sha256": reservation["phase_k2_freeze_sha256"],
        "primary_definition_sha256": reservation["primary_definition_sha256"],
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
        "primary_confirmation_rule": list(PRIMARY_CONFIRMATION_RULE),
        "matched_case_count": 92,
        "positive_case_count": 23,
        "comparison_case_count": 69,
        "match_set_count": 23,
        **analysis,
        "pair_artifact": {
            "path": str(args.pair_output),
            "rows": len(pair_rows),
            "sha256": sha256_file(args.pair_output),
        },
        "cluster_artifact": {
            "path": str(args.cluster_output),
            "rows": len(cluster_rows),
            "sha256": sha256_file(args.cluster_output),
        },
        "outcome_values_read": True,
        "primary_confirmatory_test_run": True,
        "confirmatory_run_may_execute": False,
        "retuned_after_result": False,
        "secondary_hypotheses_used_to_rescue_primary": False,
        "robustness_used_to_rescue_primary": False,
        "new_feature_created_after_validation_open": False,
        "new_time_offset_created_after_validation_open": False,
        "threshold_search_after_validation_open": False,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
        "automatic_rerun_allowed": False,
        "requires_sha256": {
            harness.STAGE_BY_KEY["era5_reconstruction"].filename: reservation["o9_g_completion_sha256"],
        },
        "interpretation": (
            "This artifact records the sole pre-specified 2025 Primary confirmatory run. "
            "PASS/FAIL is determined only by effect>0 and the exact one-sided sign-test p<0.05. "
            "Robustness checks are support-only and cannot rescue a failed Primary. "
            "Neither outcome unlocks the Risk Engine or public LPZ risk."
        ),
    }
    exclusive_write_json(args.result_output, result)
    print(json.dumps({
        "gate": RESULT_GATE,
        "primary_outcome": result["primary_outcome"],
        "primary_effect_estimate": result["primary_effect_estimate"],
        "p_value_one_sided": result["sign_test"]["p_value_one_sided"],
        "confirmatory_run_count": 1,
        "risk_engine_allowed": False,
    }))
    return 0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("reserve", "arm", "execute"))
    ap.add_argument("--repo-root", type=Path, default=ROOT)
    ap.add_argument("--evidence-dir", type=Path, required=True)
    ap.add_argument("--snapshot-csv", type=Path, required=True)
    ap.add_argument("--snapshot-json", type=Path, required=True)
    ap.add_argument("--attempt-id", required=True)
    ap.add_argument("--reservation-output", type=Path, required=True)
    ap.add_argument("--execution-seal-output", type=Path, required=True)
    ap.add_argument("--result-output", type=Path, required=True)
    ap.add_argument("--pair-output", type=Path, required=True)
    ap.add_argument("--cluster-output", type=Path, required=True)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "reserve":
            return reserve(args)
        if args.command == "arm":
            return arm(args)
        return execute(args)
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps({
                "state": "BLOCKED_O9_H_ONE_SHOT_GUARD",
                "command": args.command,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "risk_engine_allowed": False,
                "public_risk_release_allowed": False,
            }),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
