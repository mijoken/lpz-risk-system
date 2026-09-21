"""F4-2 verifies only genuinely future exact-time observations."""
import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from build_lpz_research_candidates import adapt
from build_f4_research_motion_baseline import project
from verify_f4_research_point_proximity import verify
from test_f4_research_motion_baseline import matched_source


def scenario():
    src, f3 = matched_source()
    src["collection_slot_utc"] = "2026-09-21T03:30:00Z"
    src["components"]["radar_tracking"]["fixed_mosaic"] = {
        "zoom": 8, "origin_tile_x": 1, "origin_tile_y": 2, "tile_count": 16}
    f3 = adapt(src)
    baseline = project(src, f3)
    target = copy.deepcopy(src)
    target["collection_slot_utc"] = "2026-09-21T04:00:00Z"
    target["prospective_as_of_utc"] = "2026-09-21T04:05:00Z"
    target["components"]["radar_tracking"]["tracking"]["30"]["frames"] = [{
        "valid_time": "2026-09-21T04:00:00Z",
        "components": [{"centroid": {"lat": 35.0, "lon": 139.03}}]}]
    return baseline, src, target


def test_exact_future_nearest_proximity_not_identity():
    baseline, src, target = scenario()
    result = verify(baseline, src, target)
    assert result["result_count"] == 2
    assert result["nearest_component_count"] == 1
    assert result["results"][0]["verification_status"] == "NEAREST_COMPONENT_PROXIMITY_ONLY"
    assert result["results"][0]["nearest_observed_component_distance_km"] >= 0
    assert result["results"][1]["verification_status"] == "TARGET_FRAME_NOT_AVAILABLE"
    assert result["object_identity_verified"] is False
    assert result["lpz_forecast_generated"] is False


def test_no_components_not_negative_label():
    baseline, src, target = scenario()
    target["components"]["radar_tracking"]["tracking"]["30"]["frames"][0]["components"] = []
    result = verify(baseline, src, target)
    assert result["results"][0]["verification_status"] == "NO_30MMPH_COMPONENT_IN_SAMPLED_MOSAIC"
    assert result["results"][0]["nearest_observed_component_distance_km"] is None
    assert result["results"][0]["lpz_classification"] is None


def test_rejects_future_leakage():
    baseline, src, target = scenario()
    target["prospective_as_of_utc"] = "2026-09-21T03:50:00Z"
    with pytest.raises(ValueError, match="future observation"):
        verify(baseline, src, target)


def test_rejects_different_mosaic():
    baseline, src, target = scenario()
    target["components"]["radar_tracking"]["fixed_mosaic"]["origin_tile_x"] = 99
    with pytest.raises(ValueError, match="mosaics differ"):
        verify(baseline, src, target)


def test_rejects_same_or_earlier_target_as_of():
    baseline, src, target = scenario()
    target["prospective_as_of_utc"] = baseline["source_as_of_utc"]
    with pytest.raises(ValueError, match="later as-of"):
        verify(baseline, src, target)
