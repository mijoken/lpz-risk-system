"""Tests for frozen F4-9D terminal decision."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from finalize_f4_9d import evaluate


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _comparison(lead: int, optical_iou: float, persistence_iou: float, optical_overlap: bool, persistence_overlap: bool, optical_dist: float, persistence_dist: float) -> dict:
    return {
        "lead_minutes_from_as_of": lead,
        "optical_flow": {
            "best_iou": optical_iou,
            "any_overlap": optical_overlap,
            "nearest_target_centroid_distance_km": optical_dist,
        },
        "persistence": {
            "best_iou": persistence_iou,
            "any_overlap": persistence_overlap,
            "nearest_target_centroid_distance_km": persistence_dist,
        },
        "paired_best_iou_delta": optical_iou - persistence_iou,
    }


def _case() -> dict:
    return {
        "captured_before_first_target": True,
        "future_observations_read_at_capture": False,
        "forecast_skill_scored_at_capture": False,
        "parameter_tuning_performed": False,
        "risk_engine_allowed": False,
    }


def _ready_status() -> dict:
    return {
        "state": "READY_FOR_F4_9D_TARGET_MET",
        "verified_comparison_count": 4,
        "verified_distinct_slot_count": 3,
    }


def test_terminal_go_requires_all_frozen_conditions(tmp_path):
    root = tmp_path / "cohort"
    _write(root / "cohort_status.json", _ready_status())
    _write(root / "cases" / "C1.json", _case())
    _write(
        root / "verifications" / "C1.json",
        {
            "verification_status": "VERIFIED_EXACT_FUTURE",
            "risk_engine_allowed": False,
            "parameter_tuning_performed": False,
            "validated_forecast": False,
            "comparisons": [
                _comparison(15, 0.3, 0.2, True, True, 5.0, 6.0),
                _comparison(15, 0.2, 0.1, True, False, 4.0, 5.0),
                _comparison(30, 0.2, 0.1, True, True, 7.0, 8.0),
                _comparison(30, 0.1, 0.0, True, False, 6.0, 7.0),
            ],
        },
    )

    result = evaluate(root)
    assert result["decision"] == "GO"
    assert result["f4_closed"] is True
    assert result["production_integration_enabled"] is False
    assert all(result["go_checks"].values())
    assert result["next_step"] == "NEW_SEPARATELY_SCOPED_INTEGRATION_PHASE"


def test_terminal_no_go_on_single_failed_primary_condition(tmp_path):
    root = tmp_path / "cohort"
    _write(root / "cohort_status.json", _ready_status())
    _write(root / "cases" / "C1.json", _case())
    _write(
        root / "verifications" / "C1.json",
        {
            "verification_status": "VERIFIED_EXACT_FUTURE",
            "risk_engine_allowed": False,
            "parameter_tuning_performed": False,
            "validated_forecast": False,
            "comparisons": [
                _comparison(15, 0.3, 0.2, True, True, 5.0, 6.0),
                _comparison(30, 0.0, 0.1, False, True, 9.0, 8.0),
            ],
        },
    )

    result = evaluate(root)
    assert result["decision"] == "NO_GO"
    assert result["f4_closed"] is True
    assert result["posthoc_retuning_allowed"] is False
    assert result["next_step"] == "KEEP_PERSISTENCE_BASELINE_AND_END_F4"


def test_terminal_refuses_before_cohort_ready(tmp_path):
    root = tmp_path / "cohort"
    _write(
        root / "cohort_status.json",
        {
            "state": "COLLECTING",
            "verified_comparison_count": 0,
            "verified_distinct_slot_count": 0,
        },
    )

    with pytest.raises(ValueError, match="not ready"):
        evaluate(root)


def test_invariant_violation_forces_no_go(tmp_path):
    root = tmp_path / "cohort"
    _write(root / "cohort_status.json", _ready_status())
    bad_case = _case()
    bad_case["future_observations_read_at_capture"] = True
    _write(root / "cases" / "C1.json", bad_case)
    _write(
        root / "verifications" / "C1.json",
        {
            "verification_status": "VERIFIED_EXACT_FUTURE",
            "risk_engine_allowed": False,
            "parameter_tuning_performed": False,
            "validated_forecast": False,
            "comparisons": [
                _comparison(15, 0.3, 0.2, True, True, 5.0, 6.0),
                _comparison(30, 0.3, 0.2, True, True, 5.0, 6.0),
            ],
        },
    )

    result = evaluate(root)
    assert result["decision"] == "NO_GO"
    assert result["go_checks"]["scientific_invariants_ok"] is False
