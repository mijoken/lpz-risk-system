from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from lpz_risk.o9_primary_confirmatory import (
    ALPHA,
    PRIMARY_CONFIRMATION_RULE,
    exact_one_sided_sign_test_gt_zero,
    primary_passes,
)
from scripts import o9_h_one_shot_primary_confirmatory as runner
from scripts import o9_v08_reentry_harness as harness


def _g_support():
    path = harness.ROOT / "tests/test_o9_g_era5_reconstruction.py"
    spec = importlib.util.spec_from_file_location("o9_g_recon_test_support_for_h", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_controlled_ready_chain(tmp_path: Path, *, positive_higher: bool = True):
    support = _g_support()
    population, evidence, auth_args = support._build_real_style_authorization(tmp_path)
    g_args = support._runner_args(tmp_path, population, evidence, auth_args)
    support._seed_all_descriptors(g_args)

    class Bomb:
        def __call__(self):
            raise AssertionError("pre-seeded O9-G completion must not create CDS client")

    assert support.runner.run(g_args, client_factory=Bomb()) == 0
    # Harness canonical chain expects the authorization receipt inside evidence_dir.
    (evidence / g_args.authorization_receipt.name).write_bytes(g_args.authorization_receipt.read_bytes())

    frame = pd.read_csv(g_args.snapshot_csv_output)
    if positive_higher:
        frame["q850_mean_kgkg"] = frame["match_rank"].astype(int).map(lambda x: 0.010 if x == 0 else 0.008)
    else:
        frame["q850_mean_kgkg"] = frame["match_rank"].astype(int).map(lambda x: 0.007 if x == 0 else 0.008)
    frame.to_csv(g_args.snapshot_csv_output, index=False)

    snapshot_json = json.loads(g_args.snapshot_json_output.read_text(encoding="utf-8"))
    for row in snapshot_json["snapshot_features"]:
        row["q850_mean_kgkg"] = 0.010 if (positive_higher and int(row["match_rank"]) == 0) else (
            0.007 if (not positive_higher and int(row["match_rank"]) == 0) else 0.008
        )
    _write_json(g_args.snapshot_json_output, snapshot_json)

    completion = json.loads(g_args.completion_receipt_output.read_text(encoding="utf-8"))
    completion["snapshot_feature_csv_sha256"] = runner.sha256_file(g_args.snapshot_csv_output)
    completion["snapshot_feature_json_sha256"] = runner.sha256_file(g_args.snapshot_json_output)
    _write_json(g_args.completion_receipt_output, completion)

    state = harness.evaluate_chain(harness.ROOT, evidence)
    assert state["state"] == "READY_FOR_SINGLE_FROZEN_PRIMARY_CONFIRMATORY_RUN", state
    return evidence, g_args


def _h_args(
    evidence: Path,
    g_args,
    *,
    attempt_id: str = "synthetic-run-1:attempt-1:o9-h",
    repo_root: Path = harness.ROOT,
) -> argparse.Namespace:
    return argparse.Namespace(
        repo_root=repo_root,
        evidence_dir=evidence,
        snapshot_csv=g_args.snapshot_csv_output,
        snapshot_json=g_args.snapshot_json_output,
        attempt_id=attempt_id,
        reservation_output=evidence / runner.RESERVATION_FILE,
        execution_seal_output=evidence / runner.SEAL_FILE,
        result_output=evidence / runner.RESULT_FILE,
        pair_output=evidence / runner.PAIR_FILE,
        cluster_output=evidence / runner.CLUSTER_FILE,
    )


def test_exact_one_sided_sign_test_known_values_and_zeros_ignored():
    r5 = exact_one_sided_sign_test_gt_zero([1, 2, 3, 4, 5])
    assert r5["positive_count"] == 5
    assert r5["negative_count"] == 0
    assert r5["p_value_one_sided"] == pytest.approx(1 / 32)

    r4 = exact_one_sided_sign_test_gt_zero([1, 2, 3, 4])
    assert r4["p_value_one_sided"] == pytest.approx(1 / 16)

    rz = exact_one_sided_sign_test_gt_zero([1, 1, 0, 0, -1])
    assert rz["positive_count"] == 2
    assert rz["negative_count"] == 1
    assert rz["zero_count"] == 2
    assert rz["nonzero_count"] == 3
    assert rz["p_value_one_sided"] == pytest.approx(0.5)


def test_primary_decision_is_strict_and_cannot_pass_at_alpha_boundary():
    assert primary_passes(effect=0.001, p_value=0.049999) is True
    assert primary_passes(effect=0.001, p_value=ALPHA) is False
    assert primary_passes(effect=0.0, p_value=0.001) is False
    assert primary_passes(effect=-0.001, p_value=0.001) is False


def test_reserve_and_arm_do_not_read_snapshot_values(tmp_path: Path, monkeypatch):
    evidence, g_args = _make_controlled_ready_chain(tmp_path)
    args = _h_args(evidence, g_args)

    def bomb(*_a, **_kw):
        raise AssertionError("reserve/arm must not interpret snapshot values")

    monkeypatch.setattr(runner, "read_snapshot_csv", bomb)
    assert runner.reserve(args) == 0
    reservation = json.loads(args.reservation_output.read_text(encoding="utf-8"))
    assert reservation["outcome_values_read"] is False
    assert reservation["primary_confirmatory_test_run"] is False
    assert reservation["automatic_rerun_allowed"] is False
    assert runner.arm(args) == 0
    seal = json.loads(args.execution_seal_output.read_text(encoding="utf-8"))
    assert seal["outcome_values_read"] is False
    assert seal["automatic_rerun_after_this_seal_allowed"] is False


def test_synthetic_pass_executes_once_and_second_invocation_is_blocked_before_reader(tmp_path: Path):
    evidence, g_args = _make_controlled_ready_chain(tmp_path, positive_higher=True)
    args = _h_args(evidence, g_args)
    assert runner.reserve(args) == 0
    assert runner.arm(args) == 0
    assert runner.execute(args) == 0

    result = json.loads(args.result_output.read_text(encoding="utf-8"))
    assert result["gate"] == runner.RESULT_GATE
    assert result["confirmatory_run_count"] == 1
    assert result["metric"] == "q850_mean_kgkg"
    assert result["contrast"] == "t+0h"
    assert result["primary_confirmation_rule"] == PRIMARY_CONFIRMATION_RULE
    assert result["primary_effect_estimate"] > 0
    assert result["sign_test"]["p_value_one_sided"] < 0.05
    assert result["primary_outcome"] == "PASS"
    assert result["retuned_after_result"] is False
    assert result["secondary_hypotheses_used_to_rescue_primary"] is False
    assert result["robustness_used_to_rescue_primary"] is False
    assert result["risk_engine_allowed"] is False
    assert result["public_risk_release_allowed"] is False

    calls = {"reader": 0}

    def bomb_reader(_path):
        calls["reader"] += 1
        raise AssertionError("second invocation must block before outcome reader")

    with pytest.raises(ValueError, match="already exists"):
        runner.execute(args, snapshot_reader=bomb_reader)
    assert calls["reader"] == 0


def test_synthetic_primary_failure_is_valid_irreversible_result_not_workflow_error(tmp_path: Path):
    evidence, g_args = _make_controlled_ready_chain(tmp_path, positive_higher=False)
    args = _h_args(evidence, g_args)
    assert runner.reserve(args) == 0
    assert runner.arm(args) == 0
    assert runner.execute(args) == 0
    result = json.loads(args.result_output.read_text(encoding="utf-8"))
    assert result["primary_effect_estimate"] < 0
    assert result["primary_outcome"] == "FAIL"
    assert result["confirmatory_run_count"] == 1
    assert result["risk_engine_allowed"] is False
    assert result["public_risk_release_allowed"] is False


def test_preexisting_reservation_blocks_new_attempt(tmp_path: Path):
    evidence, g_args = _make_controlled_ready_chain(tmp_path)
    first = _h_args(evidence, g_args, attempt_id="run:1:job")
    assert runner.reserve(first) == 0
    second = _h_args(evidence, g_args, attempt_id="run:2:job")
    with pytest.raises(ValueError, match="reservation already exists"):
        runner.reserve(second)


def test_different_github_run_attempt_cannot_arm_existing_reservation(tmp_path: Path):
    evidence, g_args = _make_controlled_ready_chain(tmp_path)
    first = _h_args(evidence, g_args, attempt_id="34790000000:1:o9-h")
    assert runner.reserve(first) == 0
    rerun = _h_args(evidence, g_args, attempt_id="34790000000:2:o9-h")
    with pytest.raises(ValueError, match="attempt identity"):
        runner.arm(rerun)
    assert not rerun.execution_seal_output.exists()


def test_different_github_run_attempt_cannot_execute_existing_seal_before_reader(tmp_path: Path):
    evidence, g_args = _make_controlled_ready_chain(tmp_path)
    first = _h_args(evidence, g_args, attempt_id="34790000000:1:o9-h")
    assert runner.reserve(first) == 0
    assert runner.arm(first) == 0
    rerun = _h_args(evidence, g_args, attempt_id="34790000000:2:o9-h")
    calls = {"reader": 0}

    def bomb_reader(_path):
        calls["reader"] += 1
        raise AssertionError

    with pytest.raises(ValueError, match="attempt identity"):
        runner.execute(rerun, snapshot_reader=bomb_reader)
    assert calls["reader"] == 0


def test_tampered_g_completion_blocks_before_reservation(tmp_path: Path):
    evidence, g_args = _make_controlled_ready_chain(tmp_path)
    args = _h_args(evidence, g_args)
    g_path = evidence / harness.STAGE_BY_KEY["era5_reconstruction"].filename
    obj = json.loads(g_path.read_text(encoding="utf-8"))
    obj["missing_snapshot_count"] = 1
    _write_json(g_path, obj)
    with pytest.raises(ValueError):
        runner.reserve(args)
    assert not args.reservation_output.exists()


def test_tampered_snapshot_csv_blocks_before_reservation(tmp_path: Path):
    evidence, g_args = _make_controlled_ready_chain(tmp_path)
    args = _h_args(evidence, g_args)
    with args.snapshot_csv.open("a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(ValueError, match="snapshot CSV SHA"):
        runner.reserve(args)
    assert not args.reservation_output.exists()


def test_tampered_phase_h_freeze_blocks_before_reservation(tmp_path: Path):
    evidence, g_args = _make_controlled_ready_chain(tmp_path)
    fake_root = tmp_path / "repo-root"
    h_rel = harness.H_FREEZE.relative_to(harness.ROOT)
    k_rel = harness.K2_FREEZE.relative_to(harness.ROOT)
    (fake_root / h_rel).parent.mkdir(parents=True, exist_ok=True)
    (fake_root / k_rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(harness.H_FREEZE, fake_root / h_rel)
    shutil.copy2(harness.K2_FREEZE, fake_root / k_rel)
    h = json.loads((fake_root / h_rel).read_text(encoding="utf-8"))
    h["primary_hypothesis"]["metric"] = "q925_mean_kgkg"
    _write_json(fake_root / h_rel, h)
    args = _h_args(evidence, g_args, repo_root=fake_root)
    with pytest.raises(ValueError, match="frozen protocol integrity"):
        runner.reserve(args)
    assert not args.reservation_output.exists()


def test_post_reservation_evidence_mutation_blocks_arm(tmp_path: Path):
    evidence, g_args = _make_controlled_ready_chain(tmp_path)
    args = _h_args(evidence, g_args)
    assert runner.reserve(args) == 0
    g_path = evidence / harness.STAGE_BY_KEY["era5_reconstruction"].filename
    obj = json.loads(g_path.read_text(encoding="utf-8"))
    obj["tampered_after_reservation"] = True
    _write_json(g_path, obj)
    with pytest.raises(ValueError, match="reserved O9 evidence changed"):
        runner.arm(args)
    assert not args.execution_seal_output.exists()


def test_support_artifacts_do_not_rescue_primary(tmp_path: Path):
    evidence, g_args = _make_controlled_ready_chain(tmp_path, positive_higher=False)
    args = _h_args(evidence, g_args)
    assert runner.reserve(args) == 0
    assert runner.arm(args) == 0
    assert runner.execute(args) == 0
    result = json.loads(args.result_output.read_text(encoding="utf-8"))
    assert result["primary_outcome"] == "FAIL"
    assert result["robustness"]["status"] == "SUPPORT_ONLY_CANNOT_RESCUE_PRIMARY"
    assert result["robustness_used_to_rescue_primary"] is False
    assert result["secondary_hypotheses_used_to_rescue_primary"] is False
