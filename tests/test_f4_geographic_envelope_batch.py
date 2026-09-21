"""F4-4 geographic envelope batch tests with synthetic research inputs only."""
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_f4_geographic_envelope_batch import build_batch


NAME = "20260921T033000Z.json"
SLOT = "2026-09-21T03:30:00Z"
AS_OF = "2026-09-21T03:45:00Z"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _envelope():
    return {
        "method": "CONVEX_HULL_OF_COMPONENT_PIXEL_CELLS",
        "exact_precipitation_contour": False,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [139.0, 35.0],
                [139.2, 35.0],
                [139.2, 35.2],
                [139.0, 35.2],
                [139.0, 35.0],
            ]],
        },
    }


def _make_root(root: Path, *, envelope=True, status="COMPLETE_FEATURES") -> None:
    _write(root / "batch_manifest.json", {
        "run_id": "42",
        "requested_slot_count": 1,
        "risk_engine_allowed": False,
        "slot_results": [{
            "collection_slot_utc": SLOT,
            "collection_status": status,
        }],
    })

    if status == "COMPLETE_FEATURES":
        origin_row = {
            "source_file": NAME,
            "collection_slot_utc": SLOT,
            "source_collection_status": status,
            "join_status": "OBSERVED_INPUT_JOINED",
            "research_object_count": 1,
            "current_origin_count": 1,
            "output_file": f"f4_observed_origins/slots/{NAME}",
            "risk_engine_allowed": False,
            "forecast_generated": False,
        }
        motion_row = {
            "source_file": NAME,
            "collection_slot_utc": SLOT,
            "source_collection_status": status,
            "research_status": "RESEARCH_POINT_BASELINE",
            "research_object_count": 1,
            "projected_object_count": 1,
            "output_file": f"f4_research_motion/slots/{NAME}",
            "risk_engine_allowed": False,
            "lpz_forecast_generated": False,
        }
        origins = {
            "schema_version": "0.1.0",
            "product": "F4_OBSERVED_ORIGIN_JOIN",
            "source_as_of_utc": AS_OF,
            "latest_observation_utc": SLOT,
            "research_object_count": 1,
            "current_origin_count": 1,
            "objects": [{
                "research_object_id": "R1",
                "parent_lineage_id": "T30-L0001",
                "origin_status": "OBSERVED_AT_LATEST_FRAME",
                "observation_valid_time_utc": SLOT,
                "observed_component": {
                    "centroid": {"lon": 139.1, "lat": 35.1},
                    "centroid_pixel": {"row": 5, "col": 7},
                    "bbox_pixel": [1, 2, 9, 10],
                    "approx_area_km2": 100.0,
                    "boundary_truncated": False,
                    "geographic_envelope": _envelope() if envelope else None,
                },
                "geometry_type": (
                    "OBSERVED_THRESHOLD_COMPONENT_GEOGRAPHIC_ENVELOPE"
                    if envelope else "OBSERVED_BBOX_NOT_PRECIPITATION_POLYGON"
                ),
                "forecast_valid_time_utc": None,
                "forecast_probability": None,
                "lpz_classification": None,
            }],
            "risk_engine_allowed": False,
            "official_risk_output": False,
            "forecast_generated": False,
        }
        motion = {
            "schema_version": "0.1.0",
            "product": "F4_RESEARCH_CENTROID_MOTION_BASELINE",
            "source_as_of_utc": AS_OF,
            "latest_observation_utc": SLOT,
            "research_object_count": 1,
            "projected_object_count": 1,
            "horizons_from_as_of_minutes": [15, 30],
            "objects": [{
                "research_object_id": "R1",
                "parent_lineage_id": "T30-L0001",
                "baseline_status": "RESEARCH_POINT_BASELINE_GENERATED",
                "source_observation_valid_time_utc": SLOT,
                "lpz_classification": None,
                "forecast_probability": None,
                "projections": [
                    {
                        "target_valid_time_utc": "2026-09-21T04:00:00Z",
                        "lead_from_as_of_minutes": 15,
                        "lead_from_last_observation_minutes": 30.0,
                        "projected_centroid": {"lon": 139.2, "lat": 35.15},
                        "baseline_method": "LAST_MATCHED_TWO_FRAME_CONSTANT_VELOCITY",
                        "geometry_type": "POINT_ONLY_NOT_PRECIPITATION_FOOTPRINT",
                    },
                    {
                        "target_valid_time_utc": "2026-09-21T04:15:00Z",
                        "lead_from_as_of_minutes": 30,
                        "lead_from_last_observation_minutes": 45.0,
                        "projected_centroid": {"lon": 139.3, "lat": 35.2},
                        "baseline_method": "LAST_MATCHED_TWO_FRAME_CONSTANT_VELOCITY",
                        "geometry_type": "POINT_ONLY_NOT_PRECIPITATION_FOOTPRINT",
                    },
                ],
            }],
            "risk_engine_allowed": False,
            "official_risk_output": False,
            "lpz_forecast_generated": False,
            "research_point_baseline_generated": True,
        }
        _write(root / "f4_observed_origins" / "slots" / NAME, origins)
        _write(root / "f4_research_motion" / "slots" / NAME, motion)

    elif status in {"COMPLETE_NO_TRACKABLE_EVENT", "COMPLETE_NO_EMBEDDED_GENESIS"}:
        origin_row = {
            "source_file": NAME,
            "collection_slot_utc": SLOT,
            "source_collection_status": status,
            "join_status": "NO_F3_DOWNSTREAM_OBJECT",
            "research_object_count": 0,
            "current_origin_count": 0,
            "output_file": None,
            "risk_engine_allowed": False,
            "forecast_generated": False,
        }
        motion_row = {
            "source_file": NAME,
            "collection_slot_utc": SLOT,
            "source_collection_status": status,
            "research_status": "NO_DOWNSTREAM_RESEARCH_OBJECT",
            "research_object_count": 0,
            "projected_object_count": 0,
            "output_file": None,
            "risk_engine_allowed": False,
            "lpz_forecast_generated": False,
        }

    elif status == "TECHNICAL_INCOMPLETE":
        origin_row = {
            "source_file": NAME,
            "collection_slot_utc": SLOT,
            "source_collection_status": status,
            "join_status": "SOURCE_INCOMPLETE",
            "research_object_count": None,
            "current_origin_count": None,
            "output_file": None,
            "risk_engine_allowed": False,
            "forecast_generated": False,
        }
        motion_row = {
            "source_file": NAME,
            "collection_slot_utc": SLOT,
            "source_collection_status": status,
            "research_status": "SOURCE_INCOMPLETE",
            "research_object_count": None,
            "projected_object_count": None,
            "output_file": None,
            "risk_engine_allowed": False,
            "lpz_forecast_generated": False,
        }
    else:
        raise AssertionError(status)

    _write(root / "f4_observed_origins" / "manifest.json", {
        "schema_version": "0.1.0",
        "product": "F4_OBSERVED_ORIGIN_BATCH",
        "source_run_id": "42",
        "source_slot_count": 1,
        "research_object_count": 1 if status == "COMPLETE_FEATURES" else 0,
        "current_origin_count": 1 if status == "COMPLETE_FEATURES" else 0,
        "slot_results": [origin_row],
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "forecast_generated": False,
    })
    _write(root / "f4_research_motion" / "manifest.json", {
        "schema_version": "0.1.0",
        "product": "F4_RESEARCH_POINT_MOTION_BATCH",
        "source_run_id": "42",
        "source_slot_count": 1,
        "research_object_count": 1 if status == "COMPLETE_FEATURES" else 0,
        "projected_object_count": 1 if status == "COMPLETE_FEATURES" else 0,
        "slot_results": [motion_row],
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
    })


def test_batch_builds_observed_and_projected_envelopes(tmp_path):
    _make_root(tmp_path)
    result = build_batch(tmp_path)

    assert result["product"] == "F4_RESEARCH_GEOGRAPHIC_ENVELOPE_BATCH"
    assert result["source_slot_count"] == 1
    assert result["research_object_count"] == 1
    assert result["source_envelope_count"] == 1
    assert result["projected_envelope_count"] == 2
    assert result["missing_envelope_count"] == 0
    assert result["feature_count"] == 3
    assert result["risk_engine_allowed"] is False
    assert result["official_risk_output"] is False
    assert result["lpz_forecast_generated"] is False
    assert result["probability_generated"] is False
    assert result["severity_generated"] is False

    payload = json.loads(
        (tmp_path / "f4_geographic_envelopes" / "slots" / NAME).read_text()
    )
    assert payload["feature_count"] == 3
    projected = [
        feature for feature in payload["features"]
        if feature["properties"]["kind"] == "PROJECTED_RESEARCH_GEOGRAPHIC_ENVELOPE"
    ]
    assert {f["properties"]["lead_from_as_of_minutes"] for f in projected} == {15, 30}
    assert all(f["properties"]["probability"] is None for f in projected)
    assert all(f["properties"]["severity"] is None for f in projected)
    assert all(f["properties"]["intensity"] is None for f in projected)


def test_missing_observed_envelope_is_counted_not_invented(tmp_path):
    _make_root(tmp_path, envelope=False)
    result = build_batch(tmp_path)

    assert result["source_envelope_count"] == 0
    assert result["projected_envelope_count"] == 0
    assert result["missing_envelope_count"] == 1
    assert result["feature_count"] == 0

    payload = json.loads(
        (tmp_path / "f4_geographic_envelopes" / "slots" / NAME).read_text()
    )
    assert payload["features"] == []


@pytest.mark.parametrize("status", [
    "COMPLETE_NO_TRACKABLE_EVENT",
    "COMPLETE_NO_EMBEDDED_GENESIS",
    "TECHNICAL_INCOMPLETE",
])
def test_non_feature_states_are_preserved_without_geometry(tmp_path, status):
    _make_root(tmp_path, status=status)
    result = build_batch(tmp_path)
    row = result["slot_results"][0]

    assert row["research_status"] == (
        "SOURCE_INCOMPLETE" if status == "TECHNICAL_INCOMPLETE"
        else "NO_DOWNSTREAM_RESEARCH_OBJECT"
    )
    assert row["output_file"] is None
    assert not (tmp_path / "f4_geographic_envelopes" / "slots").exists()
    assert result["lpz_forecast_generated"] is False


def test_rejects_upstream_run_mismatch_before_writing(tmp_path):
    _make_root(tmp_path)
    path = tmp_path / "f4_research_motion" / "manifest.json"
    payload = json.loads(path.read_text())
    payload["source_run_id"] = "different"
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="run mismatch"):
        build_batch(tmp_path)
    assert not (tmp_path / "f4_geographic_envelopes").exists()


def test_refuses_repeat_without_overwriting(tmp_path):
    _make_root(tmp_path)
    build_batch(tmp_path)
    with pytest.raises(FileExistsError):
        build_batch(tmp_path)
