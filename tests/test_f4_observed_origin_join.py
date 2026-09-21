"""F4-0 join tests; no weather acquisition and no prediction."""
import importlib.util
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from build_lpz_research_candidates import adapt

spec = importlib.util.spec_from_file_location("f4_observed_join", SCRIPTS / "build_f4_observed_origin_join.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def source():
    centroid = {"lon": 139.0, "lat": 35.0}
    descriptor = {"parent_lineage_id": "T30-L0001", "last_frame_index": 1, "last_centroid": centroid}
    component = {"lineage_id": "T30-L0001", "centroid": centroid,
                 "centroid_pixel": {"row": 5, "col": 7},
                 "bbox_pixel": [1, 2, 9, 10], "approx_area_km2": 100,
                 "boundary_truncated": False}
    bundle = {
        "schema_version": "0.3.0", "archive_role": "PROSPECTIVE_NATIVE",
        "collection_status": "COMPLETE_FEATURES", "bundle_complete": True,
        "as_of_time_guard_pass": True, "risk_engine_allowed": False,
        "risk_score": None, "lpz_classification": None,
        "prospective_as_of_utc": "2026-09-21T03:45:00Z",
        "components": {
            "parent_precursor_features": {
                "execution_ok": True, "risk_engine_allowed": False,
                "risk_score": None, "classification": None,
                "descriptor_count": 1, "descriptors": [descriptor]},
            "radar_tracking": {
                "execution_ok": True, "scientific_tracking_proven": True,
                "frame_valid_times": ["2026-09-21T03:25:00Z", "2026-09-21T03:30:00Z"],
                "tracking": {"30": {"frames": [
                    {"valid_time": "2026-09-21T03:25:00Z", "components": []},
                    {"valid_time": "2026-09-21T03:30:00Z", "components": [component]},
                ]}},
            },
        },
    }
    return bundle, adapt(bundle)


def test_existing_parent_join_is_observed_only():
    bundle, f3 = source()
    out = module.join(bundle, f3)
    assert out["current_origin_count"] == 1
    assert out["objects"][0]["observed_component"]["bbox_pixel"] == [1, 2, 9, 10]
    assert out["objects"][0]["geometry_type"] == "OBSERVED_BBOX_NOT_PRECIPITATION_POLYGON"
    assert out["forecast_generated"] is False
    assert out["risk_engine_allowed"] is False


def test_lineage_absent_in_last_frame_is_not_negative_label():
    bundle, f3 = source()
    bundle["components"]["radar_tracking"]["tracking"]["30"]["frames"][-1]["components"] = []
    f3 = adapt(bundle)
    out = module.join(bundle, f3)
    assert out["current_origin_count"] == 0
    assert out["objects"][0]["origin_status"] == "NOT_PRESENT_AT_LATEST_FRAME"
    assert out["objects"][0]["lpz_classification"] is None


def test_rejects_wrong_bundle():
    bundle, f3 = source()
    bundle["prospective_as_of_utc"] = "2026-09-21T04:00:00Z"
    with pytest.raises(ValueError, match="mismatch"):
        module.join(bundle, f3)


def test_rejects_wrong_centroid():
    bundle, f3 = source()
    bundle["components"]["radar_tracking"]["tracking"]["30"]["frames"][-1]["components"][0]["centroid"] = {"lon": 140, "lat": 35}
    f3 = adapt(bundle)
    with pytest.raises(ValueError, match="centroid"):
        module.join(bundle, f3)


def test_rejects_future_frame():
    bundle, f3 = source()
    bundle["components"]["radar_tracking"]["frame_valid_times"][-1] = "2026-09-21T04:00:00Z"
    bundle["components"]["radar_tracking"]["tracking"]["30"]["frames"][-1]["valid_time"] = "2026-09-21T04:00:00Z"
    f3 = adapt(bundle)
    with pytest.raises(ValueError, match="future"):
        module.join(bundle, f3)
