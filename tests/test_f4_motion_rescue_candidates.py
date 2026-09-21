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
    _unique_break_events,
)


def test_margin_none_means_no_competitor_and_passes_gate():
    assert _margin_passes(None, 8) is True
    assert _margin_passes(3.0, 3) is True
    assert _margin_passes(2.99, 3) is False


def test_joint_calibration_gate_counts_wrong_close_competitor():
    rows = [
        {
            "motion_nearest_distance_pixels": 4.0,
            "motion_top1_to_second_margin_pixels": 4.0,
            "motion_top1_matches_primary": True,
        },
        {
            "motion_nearest_distance_pixels": 4.5,
            "motion_top1_to_second_margin_pixels": 1.0,
            "motion_top1_matches_primary": False,
        },
        {
            "motion_nearest_distance_pixels": 7.0,
            "motion_top1_to_second_margin_pixels": None,
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
            "source_slot_utc": "S1",
            "research_object_id": "R1",
            "break_from_valid_time_utc": "A1",
            "break_to_valid_time_utc": "B1",
            "motion_reference_available": True,
            "lead_from_as_of_minutes": 15,
            "previous_component_boundary_truncated": False,
            "candidate_boundary_truncated": False,
            "motion_error_pixels": 6.0,
            "competitor_margin_pixels": 4.0,
            "candidate_pixel_count_ratio_to_current": 1.1,
        },
        {
            "source_slot_utc": "S2",
            "research_object_id": "R2",
            "break_from_valid_time_utc": "A2",
            "break_to_valid_time_utc": "B2",
            "motion_reference_available": True,
            "lead_from_as_of_minutes": 30,
            "previous_component_boundary_truncated": False,
            "candidate_boundary_truncated": False,
            "motion_error_pixels": 9.0,
            "competitor_margin_pixels": 2.0,
            "candidate_pixel_count_ratio_to_current": 0.8,
        },
        {
            "source_slot_utc": "S3",
            "research_object_id": "R3",
            "break_from_valid_time_utc": "A3",
            "break_to_valid_time_utc": "B3",
            "motion_reference_available": True,
            "lead_from_as_of_minutes": 15,
            "previous_component_boundary_truncated": True,
            "candidate_boundary_truncated": False,
            "motion_error_pixels": 3.0,
            "competitor_margin_pixels": 9.0,
            "candidate_pixel_count_ratio_to_current": 1.0,
        },
        {
            "source_slot_utc": "S4",
            "research_object_id": "R4",
            "break_from_valid_time_utc": "A4",
            "break_to_valid_time_utc": "B4",
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
    assert d8m3["unique_break_candidate_count"] == 1
    assert d8m3["projection_candidate_count"] == 1
    assert d8m3["lead_15_candidate_count"] == 1
    assert d8m3["lead_30_candidate_count"] == 0
    assert d8m3["candidate_fraction_of_unique_no_overlap_breaks"] == pytest.approx(0.25)
    assert d8m3["candidate_pixel_count_ratio"]["median"] == pytest.approx(1.1)

    d10m1 = table["d10_m1"]
    assert d10m1["unique_break_candidate_count"] == 2
    assert d10m1["projection_candidate_count"] == 2
    assert d10m1["lead_15_candidate_count"] == 1
    assert d10m1["lead_30_candidate_count"] == 1
    assert d10m1["candidate_pixel_count_ratio"]["median"] == pytest.approx(0.95)



def test_duplicate_projection_rows_collapse_to_one_physical_break():
    base = {
        "source_slot_utc": "2026-09-21T07:30:00Z",
        "research_object_id": "R1",
        "break_from_valid_time_utc": "2026-09-21T07:50:00Z",
        "break_to_valid_time_utc": "2026-09-21T07:55:00Z",
        "motion_reference_available": True,
        "previous_component_boundary_truncated": False,
        "candidate_boundary_truncated": False,
        "motion_error_pixels": 3.16,
        "competitor_margin_pixels": 33.99,
        "candidate_count": 4,
        "candidate_pixel_count_ratio_to_current": 0.30,
        "candidate_local_id": 7,
    }
    rows = [
        {**base, "lead_from_as_of_minutes": 15},
        {**base, "lead_from_as_of_minutes": 30},
    ]

    events = _unique_break_events(rows)
    assert len(events) == 1
    assert events[0]["projection_row_count"] == 2
    assert events[0]["projection_leads_from_as_of_minutes"] == [15, 30]

    table = _rescue_gate_table(rows)
    gate = table["d5_m3"]
    assert gate["unique_break_candidate_count"] == 1
    assert gate["projection_candidate_count"] == 2
    assert gate["lead_15_candidate_count"] == 1
    assert gate["lead_30_candidate_count"] == 1
    assert gate["candidate_fraction_of_unique_no_overlap_breaks"] == pytest.approx(1.0)


def test_duplicate_break_with_inconsistent_candidate_is_rejected():
    base = {
        "source_slot_utc": "S",
        "research_object_id": "R",
        "break_from_valid_time_utc": "A",
        "break_to_valid_time_utc": "B",
        "motion_reference_available": True,
        "previous_component_boundary_truncated": False,
        "candidate_boundary_truncated": False,
        "motion_error_pixels": 3.0,
        "competitor_margin_pixels": 4.0,
        "candidate_count": 3,
        "candidate_pixel_count_ratio_to_current": 1.0,
        "candidate_local_id": 10,
    }
    rows = [
        {**base, "lead_from_as_of_minutes": 15},
        {**base, "lead_from_as_of_minutes": 30, "candidate_local_id": 11},
    ]
    with pytest.raises(ValueError, match="inconsistent duplicate break field"):
        _unique_break_events(rows)
