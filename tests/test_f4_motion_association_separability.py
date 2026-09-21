"""F4-6A motion-aware association separability research tests."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_f4_motion_association_separability import evaluate


def _component(local_id, col, *, pixels=10, boundary=False):
    return {
        "local_id": local_id,
        "lineage_id": f"L{local_id}",
        "pixel_count": pixels,
        "approx_area_km2": float(pixels),
        "centroid_pixel": {"row": 20.0, "col": float(col)},
        "centroid": {"lon": 139.0 + float(col) * 0.01, "lat": 35.0},
        "bbox_pixel": [int(col) - 1, 19, int(col) + 1, 21],
        "boundary_truncated": boundary,
        "geographic_envelope": None,
    }


def _bundle(*, merge=False, boundary=False):
    frames = [
        {
            "valid_time": "2026-09-21T03:30:00Z",
            "components": [_component(1, 0)],
        },
        {
            "valid_time": "2026-09-21T03:35:00Z",
            "components": [_component(2, 4)],
        },
        {
            "valid_time": "2026-09-21T03:40:00Z",
            "components": [
                _component(3, 8, boundary=boundary),
                _component(4, 4),
            ],
        },
        {
            "valid_time": "2026-09-21T03:45:00Z",
            "components": [_component(5, 12)],
        },
    ]
    merge_candidates = (
        [{"current_id": 3, "previous_ids": [2, 99]}] if merge else []
    )
    transitions = [
        {
            "from_valid_time": "2026-09-21T03:30:00Z",
            "to_valid_time": "2026-09-21T03:35:00Z",
            "elapsed_seconds": 300,
            "primary_matches": [
                {"previous_id": 1, "current_id": 2, "lineage_id": "L"}
            ],
            "split_candidates": [],
            "merge_candidates": [],
        },
        {
            "from_valid_time": "2026-09-21T03:35:00Z",
            "to_valid_time": "2026-09-21T03:40:00Z",
            "elapsed_seconds": 300,
            "primary_matches": [
                {"previous_id": 2, "current_id": 3, "lineage_id": "L"}
            ],
            "split_candidates": [],
            "merge_candidates": merge_candidates,
        },
        {
            "from_valid_time": "2026-09-21T03:40:00Z",
            "to_valid_time": "2026-09-21T03:45:00Z",
            "elapsed_seconds": 300,
            "primary_matches": [],
            "split_candidates": [],
            "merge_candidates": [],
        },
    ]
    return {
        "collection_slot_utc": "2026-09-21T03:45:00Z",
        "bundle_complete": True,
        "as_of_time_guard_pass": True,
        "risk_engine_allowed": False,
        "prospective_as_of_utc": "2026-09-21T03:50:00Z",
        "components": {
            "radar_tracking": {
                "execution_ok": True,
                "scientific_tracking_proven": True,
                "fixed_mosaic": {
                    "zoom": 8,
                    "origin_tile_x": 224,
                    "origin_tile_y": 100,
                    "tile_count": 16,
                },
                "tracking": {
                    "30": {
                        "frames": frames,
                        "transitions": transitions,
                    }
                },
            }
        },
    }


def _write_batch(root: Path, bundle: dict, run_id="RUN1"):
    name = "20260921T034500Z.json"
    (root / "slots").mkdir(parents=True, exist_ok=True)
    (root / "slots" / name).write_text(json.dumps(bundle), encoding="utf-8")
    (root / "batch_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "requested_slot_count": 1,
                "slot_results": [
                    {
                        "collection_slot_utc": bundle["collection_slot_utc"],
                        "collection_status": "COMPLETE_FEATURES",
                    }
                ],
                "risk_engine_allowed": False,
            }
        ),
        encoding="utf-8",
    )


def test_motion_prediction_recovers_primary_when_persistence_nearest_is_wrong(tmp_path):
    root = tmp_path / "batch"
    _write_batch(root, _bundle())

    result = evaluate([root])
    assert result["product"] == "F4_MOTION_ASSOCIATION_SEPARABILITY_RESEARCH"
    assert result["risk_engine_allowed"] is False
    assert result["tracking_changed"] is False
    assert result["identity_inference_generated"] is False
    assert result["deduplicated_known_match_count"] == 1
    assert result["clean_known_matches"]["sample_count"] == 1

    row = result["samples"][0]
    assert row["motion_true_distance_pixels"] == pytest.approx(0.0)
    assert row["motion_top1_matches_primary"] is True
    assert row["persistence_top1_matches_primary"] is False
    assert row["actual_displacement_pixels"] == pytest.approx(4.0)
    assert row["motion_true_vs_nearest_competitor_margin_pixels"] == pytest.approx(4.0)

    clean = result["clean_known_matches"]
    assert clean["motion_top1_accuracy"] == pytest.approx(1.0)
    assert clean["persistence_top1_accuracy"] == pytest.approx(0.0)
    assert clean["motion_distance_gate_proxy"]["3"]["accepted_count"] == 1
    assert clean["motion_distance_gate_proxy"]["3"]["proxy_precision"] == pytest.approx(1.0)
    assert clean["persistence_distance_gate_proxy"]["3"]["accepted_count"] == 1
    assert clean["persistence_distance_gate_proxy"]["3"]["proxy_precision"] == pytest.approx(0.0)


def test_merge_sample_is_reported_but_excluded_from_clean_calibration(tmp_path):
    root = tmp_path / "batch"
    _write_batch(root, _bundle(merge=True))

    result = evaluate([root])
    assert result["deduplicated_known_match_count"] == 1
    assert result["structured_sample_count"] == 1
    assert result["clean_known_matches"]["sample_count"] == 0
    assert result["all_known_matches"]["sample_count"] == 1
    assert result["samples"][0]["merge_candidate"] is True


def test_boundary_sample_is_excluded_from_clean_calibration(tmp_path):
    root = tmp_path / "batch"
    _write_batch(root, _bundle(boundary=True))

    result = evaluate([root])
    assert result["boundary_sample_count"] == 1
    assert result["clean_known_matches"]["sample_count"] == 0
    assert result["all_known_matches"]["sample_count"] == 1


def test_risk_lock_is_required(tmp_path):
    root = tmp_path / "batch"
    bundle = _bundle()
    _write_batch(root, bundle)
    manifest_path = root / "batch_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["risk_engine_allowed"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="risk lock"):
        evaluate([root])
