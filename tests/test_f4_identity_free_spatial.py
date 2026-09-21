"""F4-7 identity-free spatial verification unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_f4_identity_free_spatial import (
    _best_spatial_match,
    _horizon_summary,
    _usable_target_components,
)


def _square(lon0: float, lat0: float, size: float = 0.02) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon0, lat0],
            [lon0 + size, lat0],
            [lon0 + size, lat0 + size],
            [lon0, lat0 + size],
            [lon0, lat0],
        ]],
    }


def _component(local_id: int, lon: float, lat: float, *, boundary=False, envelope=True):
    return {
        "local_id": local_id,
        "pixel_count": 10,
        "approx_area_km2": 20.0,
        "centroid": {"lon": lon + 0.01, "lat": lat + 0.01},
        "centroid_pixel": {"row": 10.0, "col": float(local_id)},
        "bbox_pixel": [0, 0, 2, 2],
        "boundary_truncated": boundary,
        "geographic_envelope": (
            {
                "method": "CONVEX_HULL_OF_COMPONENT_PIXEL_CELLS",
                "exact_precipitation_contour": False,
                "geometry": _square(lon, lat),
            }
            if envelope
            else None
        ),
    }


def test_best_spatial_match_does_not_require_identity():
    targets = [
        {
            "component": _component(1, 139.0, 35.0),
            "geometry": _square(139.0, 35.0),
        },
        {
            "component": _component(2, 140.0, 35.0),
            "geometry": _square(140.0, 35.0),
        },
    ]
    result = _best_spatial_match(
        _square(140.0, 35.0),
        [140.01, 35.01],
        targets,
    )

    assert result["any_overlap"] is True
    assert result["best_iou"] == pytest.approx(1.0)
    assert result["best_target_local_id"] == 2
    assert result["nearest_centroid_target_local_id"] == 2
    assert result["nearest_centroid_distance_km"] == pytest.approx(0.0, abs=1e-9)


def test_best_spatial_match_reports_zero_when_future_field_is_elsewhere():
    targets = [{
        "component": _component(7, 141.0, 36.0),
        "geometry": _square(141.0, 36.0),
    }]
    result = _best_spatial_match(
        _square(139.0, 35.0),
        [139.01, 35.01],
        targets,
    )

    assert result["any_overlap"] is False
    assert result["best_iou"] == pytest.approx(0.0)
    assert result["best_predicted_overlap_fraction"] == pytest.approx(0.0)
    assert result["best_observed_coverage_fraction"] == pytest.approx(0.0)
    assert result["nearest_centroid_distance_km"] > 100.0


def test_target_component_filter_excludes_boundary_and_missing_envelope():
    frame = {
        "components": [
            _component(1, 139.0, 35.0),
            _component(2, 139.1, 35.0, boundary=True),
            _component(3, 139.2, 35.0, envelope=False),
        ]
    }
    usable, counts = _usable_target_components(frame)

    assert len(usable) == 1
    assert usable[0]["component"]["local_id"] == 1
    assert counts == {
        "target_component_count": 3,
        "usable_target_component_count": 1,
        "boundary_target_component_count": 1,
        "missing_envelope_target_component_count": 1,
    }


def test_horizon_summary_compares_motion_with_persistence_field_skill():
    rows = [
        {
            "lead_from_as_of_minutes": 15,
            "verification_status": "IDENTITY_FREE_SPATIAL_COMPARISON",
            "motion_spatial": {
                "any_overlap": True,
                "best_iou": 0.4,
                "nearest_centroid_distance_km": 5.0,
            },
            "persistence_spatial": {
                "any_overlap": False,
                "best_iou": 0.0,
                "nearest_centroid_distance_km": 20.0,
            },
        },
        {
            "lead_from_as_of_minutes": 15,
            "verification_status": "IDENTITY_FREE_SPATIAL_COMPARISON",
            "motion_spatial": {
                "any_overlap": False,
                "best_iou": 0.0,
                "nearest_centroid_distance_km": 10.0,
            },
            "persistence_spatial": {
                "any_overlap": True,
                "best_iou": 0.2,
                "nearest_centroid_distance_km": 8.0,
            },
        },
    ]

    summary = _horizon_summary(rows, 15)
    assert summary["comparison_count"] == 2
    assert summary["motion_any_overlap_count"] == 1
    assert summary["persistence_any_overlap_count"] == 1
    assert summary["motion_best_iou_mean"] == pytest.approx(0.2)
    assert summary["persistence_best_iou_mean"] == pytest.approx(0.1)
    assert summary["motion_minus_persistence_best_iou_mean"] == pytest.approx(0.1)
    assert summary["motion_higher_best_iou_count"] == 1
    assert summary["persistence_higher_best_iou_count"] == 1
    assert summary["equal_best_iou_count"] == 0
    assert summary["motion_nearest_centroid_distance_km_median"] == pytest.approx(7.5)
    assert summary["persistence_nearest_centroid_distance_km_median"] == pytest.approx(14.0)
