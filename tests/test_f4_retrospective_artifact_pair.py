"""F4 retrospective archive-pair bridge tests; no weather download."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from build_lpz_research_candidates import adapt
from verify_f4_retrospective_artifact_pair import evaluate
from test_f4_research_point_proximity import scenario


def pair(tmp_path):
    _, source, target = scenario()
    a, b = tmp_path / "source", tmp_path / "target"
    name = "20260921T033000Z.json"
    target_name = "20260921T040000Z.json"
    (a / "slots").mkdir(parents=True)
    (a / "f3_research" / "slots").mkdir(parents=True)
    (b / "slots").mkdir(parents=True)
    (a / "slots" / name).write_text(json.dumps(source))
    (a / "f3_research" / "slots" / name).write_text(json.dumps(adapt(source)))
    (b / "slots" / target_name).write_text(json.dumps(target))
    (a / "batch_manifest.json").write_text(json.dumps({
        "run_id": "source", "risk_engine_allowed": False}))
    (b / "batch_manifest.json").write_text(json.dumps({
        "run_id": "target", "risk_engine_allowed": False,
        "slot_results": [{"collection_slot_utc": target["collection_slot_utc"]}]}))
    (a / "f3_research" / "manifest.json").write_text(json.dumps({
        "source_run_id": "source", "risk_engine_allowed": False,
        "forecast_generated": False, "slot_results": [{
            "research_status": "DESCRIPTIVE_ONLY", "source_file": name,
            "collection_slot_utc": source["collection_slot_utc"],
            "output_file": "f3_research/slots/" + name}]}))
    return a, b


def test_real_future_exact_time_retrospective_not_prospective(tmp_path):
    a, b = pair(tmp_path)
    result = evaluate(a, b)
    assert result["research_mode"] == "RETROSPECTIVE_DERIVATIVE_NOT_PROSPECTIVE_VALIDATION"
    assert result["counts"]["comparable_projections"] == 1
    row = next(r for r in result["results"]
               if r["verification_status"] == "NEAREST_COMPONENT_PROXIMITY_ONLY")
    assert row["nearest_component_distance_km"] >= 0
    assert row["persistence_nearest_component_distance_km"] >= 0
    assert result["object_identity_verified"] is False
    assert result["lpz_forecast_generated"] is False


def test_mismatched_grid_has_no_comparable_pair(tmp_path):
    a, b = pair(tmp_path)
    path = b / "slots" / "20260921T040000Z.json"
    target = json.loads(path.read_text())
    target["components"]["radar_tracking"]["fixed_mosaic"]["zoom"] = 99
    path.write_text(json.dumps(target))
    result = evaluate(a, b)
    assert result["counts"]["comparable_projections"] == 0
    assert result["counts"]["no_exact_comparable_target"] >= 1


def test_same_run_rejected(tmp_path):
    a, b = pair(tmp_path)
    path = b / "batch_manifest.json"
    data = json.loads(path.read_text())
    data["run_id"] = "source"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="distinct"):
        evaluate(a, b)
