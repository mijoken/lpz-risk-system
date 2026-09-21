"""F4-6B motion rescue candidate screening tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_f4_motion_rescue_candidates import (
    _calibration_gate_table,
    _margin_passes,
    _rescue_gate_table,
)


def test_margin_none_means_no_competitor_and_passes_gate():
    assert _margin_passes(None, 8) is True
    assert _margin_passes(3.0, 3) is True
    assert _margin_passes(2.99, 3) is False


def test_joint_calibration_gate_counts_wrong_close_competitor():
    rows = [
        {
            "motion_nearest_distance_pixels": 4.0,
            "motion_true_vs_nearest_competitor_margin_pixels": 4.0,
            "motion_top1_matches_primary": True,
        },
        {
            "motion_nearest_distance_pixels": 4.5,
            "motion_true_vs_nearest_competitor_margin_pixels": 1.0,
            "motion_top1_matches_primary": False,
        },
        {
            "motion_nearest_distance_pixels": 7.0,
            "motion_true_vs_nearest_competitor_margin_pixels": None,
            "motion_top1_matches_primary": True,
        },
    ]
    table = _calibration_gate_table(rows)

    d5m0 = table["d5_m0"]
    assert d5m0["accepted_count"] == 2
    assert d5m0["correct_count"] == 1
    assert d5m0["wrong_count"] == 1
    assert d5m0["proxy_precision"] == pytest.approx(0.5)

    d5m2 = table["d5_m2"]
    assert d5m2["accepted_count"] == 1
    assert d5m2["correct_count"] == 1
    assert d5m2["proxy_precision"] == pytest.approx(1.0)

    d8m8 = table["d8_m8"]
    assert d8m8["accepted_count"] == 1
    assert d8m8["correct_count"] == 1
    assert d8m8["correct_coverage_of_all_clean_samples"] == pytest.approx(1 / 3)


def test_rescue_gate_excludes_boundary_and_reports_candidate_counts():
    rows = [
        {
            "motion_reference_available": True,
            "lead_from_as_of_minutes": 15,
            "previous_component_boundary_truncated": False,
            "candidate_boundary_truncated": False,
            "motion_error_pixels": 6.0,
            "competitor_margin_pixels": 4.0,
            "candidate_pixel_count_ratio_to_current": 1.1,
        },
        {
            "motion_reference_available": True,
            "lead_from_as_of_minutes": 30,
            "previous_component_boundary_truncated": False,
            "candidate_boundary_truncated": False,
            "motion_error_pixels": 9.0,
            "competitor_margin_pixels": 2.0,
            "candidate_pixel_count_ratio_to_current": 0.8,
        },
        {
            "motion_reference_available": True,
            "lead_from_as_of_minutes": 15,
            "previous_component_boundary_truncated": True,
            "candidate_boundary_truncated": False,
            "motion_error_pixels": 3.0,
            "competitor_margin_pixels": 9.0,
            "candidate_pixel_count_ratio_to_current": 1.0,
        },
        {
            "motion_reference_available": False,
            "lead_from_as_of_minutes": 30,
            "previous_component_boundary_truncated": False,
            "candidate_boundary_truncated": None,
            "motion_error_pixels": None,
            "competitor_margin_pixels": None,
            "candidate_pixel_count_ratio_to_current": None,
        },
    ]
    table = _rescue_gate_table(rows)

    d8m3 = table["d8_m3"]
    assert d8m3["candidate_count"] == 1
    assert d8m3["lead_15_candidate_count"] == 1
    assert d8m3["lead_30_candidate_count"] == 0
    assert d8m3["candidate_fraction_of_all_no_overlap_breaks"] == pytest.approx(0.25)
    assert d8m3["candidate_pixel_count_ratio"]["median"] == pytest.approx(1.1)

    d10m1 = table["d10_m1"]
    assert d10m1["candidate_count"] == 2
    assert d10m1["lead_15_candidate_count"] == 1
    assert d10m1["lead_30_candidate_count"] == 1
    assert d10m1["candidate_pixel_count_ratio"]["median"] == pytest.approx(0.95)
