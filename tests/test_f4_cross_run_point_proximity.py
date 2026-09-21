"""F4-2 archived cross-run exact-time matching tests."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from verify_f4_cross_run_point_proximity import cross_run
from test_f4_research_point_proximity import scenario


def setup_pair(tmp_path):
    baseline, source, target = scenario()
    a, b = tmp_path / "source", tmp_path / "target"
    name = "20260921T033000Z.json"
    tname = "20260921T040000Z.json"
    for root in (a, b):
        (root / "slots").mkdir(parents=True)
    (a / "f4_research_motion" / "slots").mkdir(parents=True)
    (a / "slots" / name).write_text(json.dumps(source))
    (a / "f4_research_motion" / "slots" / name).write_text(json.dumps(baseline))
    (b / "slots" / tname).write_text(json.dumps(target))
    (a / "batch_manifest.json").write_text(json.dumps({
        "run_id": "source", "risk_engine_allowed": False}))
    (b / "batch_manifest.json").write_text(json.dumps({
        "run_id": "target", "risk_engine_allowed": False,
        "requested_slot_count": 1,
        "slot_results": [{"collection_slot_utc": target["collection_slot_utc"]}]}))
    (a / "f4_research_motion" / "manifest.json").write_text(json.dumps({
        "source_run_id": "source", "risk_engine_allowed": False,
        "lpz_forecast_generated": False, "source_slot_count": 1,
        "slot_results": [{
            "research_status": "RESEARCH_POINT_BASELINE",
            "source_file": name,
            "output_file": "f4_research_motion/slots/" + name}]}))
    return a, b


def test_exact_future_only_and_missing_other_horizon(tmp_path):
    a, b = setup_pair(tmp_path)
    result = cross_run(a, b)
    assert result["result_count"] == 2
    assert result["nearest_component_count"] == 1
    assert result["object_identity_verified"] is False
    assert result["lpz_forecast_generated"] is False
    assert {r["verification_status"] for r in result["results"]} == {
        "NEAREST_COMPONENT_PROXIMITY_ONLY",
        "NO_EXACT_TIME_COMPARABLE_TARGET_IN_PROVIDED_BATCH",
    }


def test_mismatched_footprint_not_comparable(tmp_path):
    a, b = setup_pair(tmp_path)
    path = b / "slots" / "20260921T040000Z.json"
    target = json.loads(path.read_text())
    target["components"]["radar_tracking"]["fixed_mosaic"]["origin_tile_x"] = 99
    path.write_text(json.dumps(target))
    result = cross_run(a, b)
    assert result["nearest_component_count"] == 0
    assert all(r["verification_status"] == "NO_EXACT_TIME_COMPARABLE_TARGET_IN_PROVIDED_BATCH"
               for r in result["results"])


def test_same_run_rejected(tmp_path):
    a, b = setup_pair(tmp_path)
    path = b / "batch_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["run_id"] = "source"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="run"):
        cross_run(a, b)
