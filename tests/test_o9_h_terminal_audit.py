from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest

from scripts import o9_h_terminal_audit as audit
from scripts import o9_v08_reentry_harness as harness


def _support():
    path = harness.ROOT / "tests/test_o9_h_one_shot_primary_confirmatory.py"
    spec = importlib.util.spec_from_file_location("o9_h_test_support_for_audit", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _completed(tmp_path: Path, *, positive_higher: bool = True):
    s = _support()
    evidence, g_args = s._make_controlled_ready_chain(tmp_path, positive_higher=positive_higher)
    h_args = s._h_args(evidence, g_args)
    assert s.runner.reserve(h_args) == 0
    assert s.runner.arm(h_args) == 0
    assert s.runner.execute(h_args) == 0
    args = argparse.Namespace(
        repo_root=harness.ROOT,
        evidence_dir=evidence,
        reservation=h_args.reservation_output,
        execution_seal=h_args.execution_seal_output,
        result=h_args.result_output,
        pair_artifact=h_args.pair_output,
        cluster_artifact=h_args.cluster_output,
        output=tmp_path / "terminal_audit.json",
    )
    return args


def test_terminal_audit_passes_valid_one_shot_result(tmp_path: Path):
    args = _completed(tmp_path, positive_higher=True)
    report = audit.audit(args)
    assert report["gate"] == audit.PASS_GATE
    assert report["primary_outcome"] == "PASS"
    assert report["confirmatory_run_count"] == 1
    assert report["risk_engine_allowed"] is False
    assert report["public_risk_release_allowed"] is False


def test_terminal_audit_accepts_valid_scientific_fail_but_keeps_locks(tmp_path: Path):
    args = _completed(tmp_path, positive_higher=False)
    report = audit.audit(args)
    assert report["gate"] == audit.PASS_GATE
    assert report["primary_outcome"] == "FAIL"
    assert report["risk_engine_allowed"] is False


def test_terminal_audit_rejects_result_outcome_tamper(tmp_path: Path):
    args = _completed(tmp_path, positive_higher=False)
    result = json.loads(args.result.read_text(encoding="utf-8"))
    result["primary_outcome"] = "PASS"
    args.result.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="PASS/FAIL"):
        audit.audit(args)


def test_terminal_audit_rejects_support_artifact_tamper(tmp_path: Path):
    args = _completed(tmp_path, positive_higher=True)
    with args.cluster_artifact.open("a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(ValueError, match="cluster artifact SHA"):
        audit.audit(args)


def test_terminal_audit_rejects_second_run_count_claim(tmp_path: Path):
    args = _completed(tmp_path, positive_higher=True)
    result = json.loads(args.result.read_text(encoding="utf-8"))
    result["confirmatory_run_count"] = 2
    args.result.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="confirmatory_run_count"):
        audit.audit(args)
