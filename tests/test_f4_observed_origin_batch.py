"""F4-0 batch adapter tests: synthetic input, no weather acquisition."""
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from build_lpz_research_candidates import adapt
from build_f4_observed_origin_batch import build_batch


def _make_batch(root, status="COMPLETE_FEATURES"):
    name = "20260921T033000Z.json"
    slot = "2026-09-21T03:30:00Z"
    centroid = {"lon": 139.0, "lat": 35.0}
    descriptor = {"parent_lineage_id": "T30-L0001", "last_frame_index": 1,
                  "last_centroid": centroid}
    component = {"lineage_id": "T30-L0001", "centroid": centroid,
                 "centroid_pixel": {"row": 5, "col": 7},
                 "bbox_pixel": [1, 2, 9, 10], "approx_area_km2": 100,
                 "boundary_truncated": False}
    bundle = {
        "schema_version": "0.3.0", "collection_slot_utc": slot,
        "archive_role": "PROSPECTIVE_NATIVE", "collection_status": status,
        "bundle_complete": True, "as_of_time_guard_pass": True,
        "risk_engine_allowed": False, "risk_score": None, "lpz_classification": None,
        "prospective_as_of_utc": "2026-09-21T03:45:00Z",
        "components": {
            "parent_precursor_features": {
                "execution_ok": True, "risk_engine_allowed": False,
                "risk_score": None, "classification": None,
                "descriptor_count": 1, "descriptors": [descriptor]},
            "radar_tracking": {
                "execution_ok": True, "scientific_tracking_proven": True,
                "frame_valid_times": ["2026-09-21T03:25:00Z", slot],
                "tracking": {"30": {"frames": [
                    {"valid_time": "2026-09-21T03:25:00Z", "components": []},
                    {"valid_time": slot, "components": [component]}]}}},
        },
    }
    f3row = {"source_file": name, "collection_slot_utc": slot,
             "research_status": "DESCRIPTIVE_ONLY", "research_object_count": 1,
             "output_file": "f3_research/slots/" + name}
    if status == "TECHNICAL_INCOMPLETE":
        bundle["bundle_complete"] = False
        f3row.update(research_status="SOURCE_INCOMPLETE",
                     research_object_count=None, output_file=None)
    elif status in {"COMPLETE_NO_TRACKABLE_EVENT", "COMPLETE_NO_EMBEDDED_GENESIS"}:
        f3row.update(research_status="NO_DOWNSTREAM_RESEARCH_OBJECT",
                     research_object_count=0, output_file=None)
    (root / "slots").mkdir(parents=True)
    (root / "f3_research" / "slots").mkdir(parents=True)
    (root / "slots" / name).write_text(json.dumps(bundle))
    if status == "COMPLETE_FEATURES":
        (root / "f3_research" / "slots" / name).write_text(json.dumps(adapt(bundle)))
    (root / "batch_manifest.json").write_text(json.dumps({
        "run_id": "42", "requested_slot_count": 1, "risk_engine_allowed": False,
        "slot_results": [{"collection_slot_utc": slot, "collection_status": status}]}))
    (root / "f3_research" / "manifest.json").write_text(json.dumps({
        "product": "F3_RESEARCH_BATCH", "source_run_id": "42",
        "risk_engine_allowed": False, "forecast_generated": False,
        "slot_results": [f3row]}))
    return name


def test_complete_slot_joined_without_forecast(tmp_path):
    name = _make_batch(tmp_path)
    result = build_batch(tmp_path)
    assert result["source_slot_count"] == 1
    assert result["research_object_count"] == result["current_origin_count"] == 1
    assert result["forecast_generated"] is False
    row = json.loads((tmp_path / "f4_observed_origins" / "slots" / name).read_text())
    assert row["objects"][0]["forecast_probability"] is None
    assert row["objects"][0]["geometry_type"] == "OBSERVED_BBOX_NOT_PRECIPITATION_POLYGON"


@pytest.mark.parametrize("status", [
    "COMPLETE_NO_TRACKABLE_EVENT",
    "COMPLETE_NO_EMBEDDED_GENESIS",
    "TECHNICAL_INCOMPLETE",
])
def test_other_states_preserved_not_negative_label(tmp_path, status):
    _make_batch(tmp_path, status)
    result = build_batch(tmp_path)
    row = result["slot_results"][0]
    assert row["join_status"] == (
        "SOURCE_INCOMPLETE" if status == "TECHNICAL_INCOMPLETE"
        else "NO_F3_DOWNSTREAM_OBJECT")
    assert row["risk_engine_allowed"] is False
    assert row["forecast_generated"] is False
    assert not (tmp_path / "f4_observed_origins" / "slots").exists()


def test_refuses_repeat_without_overwriting(tmp_path):
    _make_batch(tmp_path)
    build_batch(tmp_path)
    with pytest.raises(FileExistsError):
        build_batch(tmp_path)


def test_rejects_different_f3_run_before_writing(tmp_path):
    _make_batch(tmp_path)
    path = tmp_path / "f3_research" / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["source_run_id"] = "different"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="F3 manifest"):
        build_batch(tmp_path)
    assert not (tmp_path / "f4_observed_origins").exists()
