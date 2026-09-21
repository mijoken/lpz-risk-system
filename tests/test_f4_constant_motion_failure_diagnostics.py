"""Tests for F4-8 constant-motion failure diagnostics."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from diagnose_f4_constant_motion_failure import (
    _group_summary,
    _pearson,
    _quartile_label,
    _quantile_edges,
    _rank,
    _spearman,
)


def test_rank_uses_average_ranks_for_ties():
    assert _rank([10.0, 20.0, 20.0, 40.0]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_detects_monotonic_direction():
    x = [1.0, 2.0, 3.0, 4.0]
    assert _spearman(x, [10.0, 20.0, 30.0, 40.0]) == pytest.approx(1.0)
    assert _spearman(x, [40.0, 30.0, 20.0, 10.0]) == pytest.approx(-1.0)


def test_pearson_returns_none_for_constant_input():
    assert _pearson([1.0, 1.0], [1.0, 2.0]) is None


def test_quartile_edges_and_labels_are_descriptive_not_filters():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    edges = _quantile_edges(values)
    assert edges == pytest.approx([2.75, 4.5, 6.25])
    assert _quartile_label(2.0, edges) == "Q1"
    assert _quartile_label(4.0, edges) == "Q2"
    assert _quartile_label(6.0, edges) == "Q3"
    assert _quartile_label(8.0, edges) == "Q4"


def test_group_summary_preserves_motion_vs_persistence_direction():
    rows = [
        {
            "motion_minus_persistence_best_iou": 0.2,
            "motion_minus_persistence_nearest_distance_km": -3.0,
            "motion_spatial": {"any_overlap": True},
            "persistence_spatial": {"any_overlap": False},
            "implied_motion_speed_mps": 8.0,
            "source_area_km2": 20.0,
            "projected_translation_km": 6.0,
        },
        {
            "motion_minus_persistence_best_iou": -0.1,
            "motion_minus_persistence_nearest_distance_km": 2.0,
            "motion_spatial": {"any_overlap": False},
            "persistence_spatial": {"any_overlap": True},
            "implied_motion_speed_mps": 12.0,
            "source_area_km2": 40.0,
            "projected_translation_km": 9.0,
        },
        {
            "motion_minus_persistence_best_iou": 0.0,
            "motion_minus_persistence_nearest_distance_km": 1.0,
            "motion_spatial": {"any_overlap": False},
            "persistence_spatial": {"any_overlap": False},
            "implied_motion_speed_mps": 10.0,
            "source_area_km2": 30.0,
            "projected_translation_km": 7.5,
        },
    ]

    summary = _group_summary(rows)
    assert summary["count"] == 3
    assert summary["motion_higher_iou_count"] == 1
    assert summary["persistence_higher_iou_count"] == 1
    assert summary["equal_iou_count"] == 1
    assert summary["motion_minus_persistence_best_iou_mean"] == pytest.approx(
        1.0 / 30.0
    )
    assert summary["motion_any_overlap_rate"] == pytest.approx(1 / 3)
    assert summary["persistence_any_overlap_rate"] == pytest.approx(1 / 3)
    assert summary["implied_motion_speed_mps_median"] == pytest.approx(10.0)
    assert summary["source_area_km2_median"] == pytest.approx(30.0)
