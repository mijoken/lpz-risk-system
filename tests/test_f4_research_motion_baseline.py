"""F4-1 tests: synthetic tracked radar observations, no LPZ forecast."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from build_lpz_research_candidates import adapt
from build_f4_research_motion_baseline import project
from test_f4_observed_origin_join import source


def matched_source():
    bundle, _ = source()
    track = bundle["components"]["radar_tracking"]["tracking"]["30"]
    prev = dict(track["frames"][1]["components"][0])
    prev["centroid"] = {"lon": 138.99, "lat": 35.0}
    prev["local_id"] = 4
    track["frames"][0]["components"] = [prev]
    track["frames"][1]["components"][0]["local_id"] = 7
    track["transitions"] = [{
        "from_valid_time": "2026-09-21T03:25:00Z",
        "to_valid_time": "2026-09-21T03:30:00Z",
        "elapsed_seconds": 300.0,
        "primary_matches": [{
            "lineage_id": "T30-L0001", "previous_id": 4, "current_id": 7,
        }],
    }]
    return bundle, adapt(bundle)


def test_projected_targets_strictly_future_from_as_of():
    bundle, f3 = matched_source()
    result = project(bundle, f3)
    assert result["projected_object_count"] == 1
    row = result["objects"][0]
    assert row["baseline_status"] == "RESEARCH_POINT_BASELINE_GENERATED"
    assert [p["target_valid_time_utc"] for p in row["projections"]] == [
        "2026-09-21T04:00:00Z", "2026-09-21T04:15:00Z",
    ]
    assert [p["lead_from_last_observation_minutes"] for p in row["projections"]] == [30, 45]
    assert row["projections"][1]["projected_centroid"]["lon"] > row["projections"][0]["projected_centroid"]["lon"] > 139.0
    assert result["risk_engine_allowed"] is False
    assert result["lpz_forecast_generated"] is False
    assert row["forecast_probability"] is None


def test_new_parent_without_previous_match_is_not_predicted():
    bundle, f3 = source()
    bundle["components"]["radar_tracking"]["tracking"]["30"]["transitions"] = [{
        "from_valid_time": "2026-09-21T03:25:00Z",
        "to_valid_time": "2026-09-21T03:30:00Z",
        "elapsed_seconds": 300.0, "primary_matches": [],
    }]
    result = project(bundle, f3)
    assert result["projected_object_count"] == 0
    assert result["objects"][0]["baseline_status"] == "INSUFFICIENT_MATCHED_MOTION"


def test_bad_match_rejected():
    bundle, f3 = matched_source()
    bundle["components"]["radar_tracking"]["tracking"]["30"]["transitions"][-1]["primary_matches"][0]["current_id"] = 99
    f3 = adapt(bundle)
    with pytest.raises(ValueError, match="primary match"):
        project(bundle, f3)


def test_stale_source_rejected():
    bundle, _ = matched_source()
    bundle["prospective_as_of_utc"] = "2026-09-21T04:30:00Z"
    with pytest.raises(ValueError, match="stale"):
        project(bundle, adapt(bundle))


def test_nonmonotonic_frames_rejected():
    bundle, _ = matched_source()
    bundle["components"]["radar_tracking"]["frame_valid_times"][0] = "2026-09-21T03:30:00Z"
    bundle["components"]["radar_tracking"]["tracking"]["30"]["frames"][0]["valid_time"] = "2026-09-21T03:30:00Z"
    with pytest.raises(ValueError, match="strictly increasing"):
        project(bundle, adapt(bundle))
