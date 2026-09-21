"""F4-9C frozen prospective cohort tests."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from lpz_risk.f4_9c_verification import (
    advect_component_labels,
    component_label_map,
    score_component_prediction,
)
from run_f4_9c_cycle import (
    _cohort_paths,
    _status,
    _write_json_new,
)


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def test_component_label_map_excludes_boundary_and_tiny_objects():
    mask = np.zeros((12, 12), dtype=bool)
    mask[3:5, 3:5] = True
    mask[0, 7:9] = True
    mask[8, 8] = True

    labels, rows = component_label_map(
        mask,
        exclude_boundary=True,
        min_pixels=2,
    )

    assert len(rows) == 1
    assert rows[0]["pixel_count"] == 4
    assert rows[0]["boundary_truncated"] is False
    assert set(np.unique(labels)) == {0, 1}


def test_component_best_iou_is_identity_free():
    predicted = np.array([10, 11, 20, 21], dtype=np.int64)
    targets = [
        {
            "component_id": 1,
            "flat_indices": np.array([100, 101], dtype=np.int64),
        },
        {
            "component_id": 2,
            "flat_indices": np.array([10, 11, 20, 22], dtype=np.int64),
        },
    ]
    result = score_component_prediction(
        predicted,
        targets,
        height=32,
        width=32,
        zoom=8,
        origin_tile_x=228,
        origin_tile_y=96,
    )

    assert result["best_target_component_id"] == 2
    assert result["best_intersection_pixel_count"] == 3
    assert result["best_iou"] == pytest.approx(3 / 5)
    assert result["any_overlap"] is True


def test_no_target_uses_same_deterministic_distance_penalty():
    predicted = np.array([10, 11, 20, 21], dtype=np.int64)
    result = score_component_prediction(
        predicted,
        [],
        height=32,
        width=32,
        zoom=8,
        origin_tile_x=228,
        origin_tile_y=96,
    )

    assert result["best_iou"] == 0.0
    assert result["any_overlap"] is False
    assert result["no_target_component_penalty_applied"] is True
    assert result["nearest_target_centroid_distance_km"] > 0.0


def test_component_label_advection_preserves_integer_ids():
    source = np.zeros((32, 32), dtype=np.uint16)
    source[10:13, 10:13] = 1
    source[20:23, 20:23] = 2

    velocity = np.zeros((2, 32, 32), dtype=np.float32)
    velocity[0, :, :] = 1.0

    forecast = advect_component_labels(
        source,
        velocity,
        timesteps=[3, 6],
        vel_timestep=1.0,
        outval=0.0,
        n_iter=1,
        velocity_interp_order=1,
    )

    assert forecast.shape == (2, 32, 32)
    assert set(np.unique(forecast)).issubset({0, 1, 2})
    assert forecast[0, 11, 14] == 1
    assert forecast[1, 11, 17] == 1


def _case(case_id: str, planned: int) -> dict:
    return {
        "case_id": case_id,
        "planned_comparison_count": planned,
    }


def _verification(case_id: str, comparisons: int, status="VERIFIED_EXACT_FUTURE") -> dict:
    return {
        "case_id": case_id,
        "verification_status": status,
        "comparison_count": comparisons,
    }


def test_status_stops_new_collection_when_target_is_already_planned(tmp_path):
    root = tmp_path / "cohort"
    paths = _cohort_paths(root)
    start_time = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)
    start = {
        "started_at_utc": _z(start_time),
        "deadline_utc": _z(start_time + timedelta(days=14)),
    }

    for index, planned in enumerate((40, 40, 24), start=1):
        _write_json_new(
            paths["cases"] / f"C{index}.json",
            _case(f"C{index}", planned),
        )

    _write_json_new(
        paths["verifications"] / "C1.json",
        _verification("C1", 40),
    )

    status = _status(
        root,
        start,
        start_time + timedelta(hours=2),
    )
    assert status["verified_comparison_count"] == 40
    assert status["pending_planned_comparison_count"] == 64
    assert status["verified_plus_pending_comparison_count"] == 104
    assert status["verified_plus_pending_distinct_slot_count"] == 3
    assert status["state"] == "TARGET_PLANNED_AWAITING_VERIFICATION"
    assert status["collection_open"] is False
    assert status["interim_skill_summary_emitted"] is False


def test_status_ready_for_9d_only_after_verified_target(tmp_path):
    root = tmp_path / "cohort"
    paths = _cohort_paths(root)
    start_time = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)
    start = {
        "started_at_utc": _z(start_time),
        "deadline_utc": _z(start_time + timedelta(days=14)),
    }

    for index, comparisons in enumerate((40, 40, 24), start=1):
        _write_json_new(
            paths["cases"] / f"C{index}.json",
            _case(f"C{index}", comparisons),
        )
        _write_json_new(
            paths["verifications"] / f"C{index}.json",
            _verification(f"C{index}", comparisons),
        )

    status = _status(root, start, start_time + timedelta(hours=3))
    assert status["verified_comparison_count"] == 104
    assert status["verified_distinct_slot_count"] == 3
    assert status["state"] == "READY_FOR_F4_9D_TARGET_MET"
    assert status["collection_open"] is False


def test_deadline_stops_collection_but_waits_for_pending(tmp_path):
    root = tmp_path / "cohort"
    paths = _cohort_paths(root)
    start_time = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    deadline = start_time + timedelta(days=14)
    start = {
        "started_at_utc": _z(start_time),
        "deadline_utc": _z(deadline),
    }

    _write_json_new(paths["cases"] / "C1.json", _case("C1", 10))
    status = _status(root, start, deadline + timedelta(minutes=1))
    assert status["state"] == "DEADLINE_STOP_AWAITING_PENDING_VERIFICATION"
    assert status["collection_open"] is False

    _write_json_new(
        paths["verifications"] / "C1.json",
        _verification("C1", 0, status="PERMANENT_TECHNICAL_FAILURE"),
    )
    status = _status(root, start, deadline + timedelta(hours=1))
    assert status["state"] == "READY_FOR_F4_9D_DEADLINE"
    assert status["collection_open"] is False
