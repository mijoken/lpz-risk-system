"""Convex geographic envelope overlap metrics."""
from __future__ import annotations

import pytest

from lpz_risk.polygon_overlap import convex_polygon_overlap_metrics


def _box(lon0, lat0, lon1, lat1, *, reverse=False):
    ring = [
        [lon0, lat0],
        [lon1, lat0],
        [lon1, lat1],
        [lon0, lat1],
        [lon0, lat0],
    ]
    if reverse:
        ring = list(reversed(ring))
    return {"type": "Polygon", "coordinates": [ring]}


def test_identical_envelopes_have_unit_overlap():
    result = convex_polygon_overlap_metrics(
        _box(139.0, 35.0, 140.0, 36.0),
        _box(139.0, 35.0, 140.0, 36.0),
    )
    assert result["iou"] == pytest.approx(1.0)
    assert result["predicted_overlap_fraction"] == pytest.approx(1.0)
    assert result["observed_coverage_fraction"] == pytest.approx(1.0)


def test_half_shifted_equal_boxes_have_expected_overlap_ratios():
    result = convex_polygon_overlap_metrics(
        _box(139.0, 35.0, 140.0, 36.0),
        _box(139.5, 35.0, 140.5, 36.0),
    )
    assert result["iou"] == pytest.approx(1 / 3, rel=2e-4)
    assert result["predicted_overlap_fraction"] == pytest.approx(0.5, rel=2e-4)
    assert result["observed_coverage_fraction"] == pytest.approx(0.5, rel=2e-4)


def test_disjoint_envelopes_have_zero_overlap():
    result = convex_polygon_overlap_metrics(
        _box(139.0, 35.0, 140.0, 36.0),
        _box(141.0, 35.0, 142.0, 36.0),
    )
    assert result["iou"] == pytest.approx(0.0)
    assert result["intersection_area_km2"] == pytest.approx(0.0)


def test_ring_orientation_does_not_change_result():
    result = convex_polygon_overlap_metrics(
        _box(139.0, 35.0, 140.0, 36.0, reverse=True),
        _box(139.0, 35.0, 140.0, 36.0),
    )
    assert result["iou"] == pytest.approx(1.0)


def test_non_convex_geometry_is_rejected():
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [139.0, 35.0],
            [140.0, 35.0],
            [139.4, 35.4],
            [140.0, 36.0],
            [139.0, 36.0],
            [139.0, 35.0],
        ]],
    }
    with pytest.raises(ValueError, match="not convex"):
        convex_polygon_overlap_metrics(
            geometry,
            _box(139.0, 35.0, 140.0, 36.0),
        )


def test_holes_are_rejected_for_f4_convex_envelope_contract():
    geometry = _box(139.0, 35.0, 140.0, 36.0)
    geometry["coordinates"].append([
        [139.2, 35.2],
        [139.3, 35.2],
        [139.3, 35.3],
        [139.2, 35.3],
        [139.2, 35.2],
    ])
    with pytest.raises(ValueError, match="one outer ring"):
        convex_polygon_overlap_metrics(
            geometry,
            _box(139.0, 35.0, 140.0, 36.0),
        )
