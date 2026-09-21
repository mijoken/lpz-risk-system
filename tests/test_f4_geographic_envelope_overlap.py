"""F4-5 archived prospective envelope-overlap verification tests."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_f4_geographic_envelope_overlap import evaluate


def _stamp(minute: int) -> str:
    return (
        datetime(2026, 9, 21, 3, 30, tzinfo=timezone.utc)
        + timedelta(minutes=minute)
    ).isoformat().replace("+00:00", "Z")


def _name(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime(
        "%Y%m%dT%H%M%SZ.json"
    )


def _geometry(minute: int) -> dict:
    lon = 139.0 + minute * 0.01
    lat = 35.0
    half = 0.02
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon - half, lat - half],
            [lon + half, lat - half],
            [lon + half, lat + half],
            [lon - half, lat + half],
            [lon - half, lat - half],
        ]],
    }


def _component(minute: int, lineage: str, *, boundary=False) -> dict:
    lon = 139.0 + minute * 0.01
    geometry = _geometry(minute)
    return {
        "local_id": minute + 1,
        "lineage_id": lineage,
        "pixel_count": 10,
        "approx_area_km2": 20.0,
        "centroid_pixel": {"row": 20.0, "col": 30.0 + minute},
        "centroid": {"lon": lon, "lat": 35.0},
        "bbox_pixel": [29 + minute, 19, 31 + minute, 21],
        "boundary_truncated": boundary,
        "geographic_envelope": {
            "method": "CONVEX_HULL_OF_COMPONENT_PIXEL_CELLS",
            "exact_precipitation_contour": False,
            "geometry": geometry,
        },
    }


def _bundle(start: int, lineage: str, *, boundary_minutes=()) -> dict:
    boundary_minutes = set(boundary_minutes)
    frames = []
    transitions = []
    for minute in range(start, start + 16, 5):
        frames.append({
            "valid_time": _stamp(minute),
            "components": [
                _component(
                    minute,
                    lineage,
                    boundary=minute in boundary_minutes,
                )
            ],
        })
    for previous, current in zip(frames, frames[1:]):
        transitions.append({
            "from_valid_time": previous["valid_time"],
            "to_valid_time": current["valid_time"],
            "elapsed_seconds": 300,
            "primary_matches": [{
                "previous_id": previous["components"][0]["local_id"],
                "current_id": current["components"][0]["local_id"],
                "lineage_id": lineage,
            }],
            "split_candidates": [],
            "merge_candidates": [],
            "deaths": [],
        })
    slot = frames[-1]["valid_time"]
    return {
        "schema_version": "0.3.0",
        "collection_slot_utc": slot,
        "collection_status": "COMPLETE_FEATURES",
        "bundle_complete": True,
        "as_of_time_guard_pass": True,
        "risk_engine_allowed": False,
        "risk_score": None,
        "lpz_classification": None,
        "prospective_as_of_utc": _stamp(start + 20),
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


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_batch(root: Path, run_id: str, bundles: list[dict]) -> None:
    rows = []
    for bundle in bundles:
        slot = bundle["collection_slot_utc"]
        name = _name(slot)
        _write(root / "slots" / name, bundle)
        rows.append({
            "collection_slot_utc": slot,
            "collection_status": bundle["collection_status"],
        })
    _write(root / "batch_manifest.json", {
        "run_id": run_id,
        "requested_slot_count": len(rows),
        "slot_results": rows,
        "risk_engine_allowed": False,
    })


def _make_source(root: Path) -> tuple[str, dict]:
    source = _bundle(0, "L-A")
    _write_batch(root, "SOURCE", [source])
    name = _name(source["collection_slot_utc"])
    observed_component = source["components"]["radar_tracking"]["tracking"]["30"][
        "frames"
    ][-1]["components"][0]
    source_geometry = observed_component["geographic_envelope"]["geometry"]
    target_geometry = _geometry(35)

    origin_payload = {
        "schema_version": "0.1.0",
        "product": "F4_OBSERVED_ORIGIN_JOIN",
        "source_as_of_utc": source["prospective_as_of_utc"],
        "latest_observation_utc": source["collection_slot_utc"],
        "research_object_count": 1,
        "current_origin_count": 1,
        "objects": [{
            "research_object_id": "R1",
            "parent_lineage_id": "L-A",
            "origin_status": "OBSERVED_AT_LATEST_FRAME",
            "observation_valid_time_utc": source["collection_slot_utc"],
            "observed_component": observed_component,
            "forecast_valid_time_utc": None,
            "forecast_probability": None,
            "lpz_classification": None,
        }],
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "forecast_generated": False,
    }
    origin_path = f"f4_observed_origins/slots/{name}"
    _write(root / origin_path, origin_payload)
    _write(root / "f4_observed_origins" / "manifest.json", {
        "schema_version": "0.1.0",
        "product": "F4_OBSERVED_ORIGIN_BATCH",
        "source_run_id": "SOURCE",
        "source_slot_count": 1,
        "research_object_count": 1,
        "current_origin_count": 1,
        "slot_results": [{
            "source_file": name,
            "collection_slot_utc": source["collection_slot_utc"],
            "source_collection_status": "COMPLETE_FEATURES",
            "join_status": "OBSERVED_INPUT_JOINED",
            "research_object_count": 1,
            "current_origin_count": 1,
            "output_file": origin_path,
            "risk_engine_allowed": False,
            "forecast_generated": False,
        }],
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "forecast_generated": False,
    })

    common = {
        "research_object_id": "R1",
        "parent_lineage_id": "L-A",
        "source_as_of_utc": source["prospective_as_of_utc"],
        "source_observation_valid_time_utc": source["collection_slot_utc"],
        "observed_centroid_lon_lat": [
            observed_component["centroid"]["lon"],
            observed_component["centroid"]["lat"],
        ],
        "observed_approx_area_km2": 20.0,
        "envelope_method": "CONVEX_HULL_OF_COMPONENT_PIXEL_CELLS",
        "exact_precipitation_contour": False,
        "research_only": True,
        "risk_engine_allowed": False,
        "lpz_forecast_generated": False,
        "probability": None,
        "severity": None,
        "intensity": None,
    }
    geo_payload = {
        "type": "FeatureCollection",
        "schema_version": "0.1.0",
        "product": "F4_RESEARCH_GEOGRAPHIC_ENVELOPES",
        "source_as_of_utc": source["prospective_as_of_utc"],
        "latest_observation_utc": source["collection_slot_utc"],
        "source_envelope_count": 1,
        "projected_envelope_count": 1,
        "missing_envelope_count": 0,
        "feature_count": 2,
        "features": [
            {
                "type": "Feature",
                "geometry": source_geometry,
                "properties": {
                    **common,
                    "kind": "OBSERVED_THRESHOLD_COMPONENT_ENVELOPE",
                    "lead_from_as_of_minutes": 0,
                    "target_valid_time_utc": source["collection_slot_utc"],
                    "projection_method": None,
                },
            },
            {
                "type": "Feature",
                "geometry": target_geometry,
                "properties": {
                    **common,
                    "kind": "PROJECTED_RESEARCH_GEOGRAPHIC_ENVELOPE",
                    "lead_from_as_of_minutes": 15,
                    "lead_from_last_observation_minutes": 20,
                    "target_valid_time_utc": _stamp(35),
                    "projected_centroid_lon_lat": [139.35, 35.0],
                    "projection_method": "LAST_MATCHED_TWO_FRAME_CONSTANT_VELOCITY",
                },
            },
        ],
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
    }
    geo_path = f"f4_geographic_envelopes/slots/{name}"
    _write(root / geo_path, geo_payload)
    _write(root / "f4_geographic_envelopes" / "manifest.json", {
        "schema_version": "0.1.0",
        "product": "F4_RESEARCH_GEOGRAPHIC_ENVELOPE_BATCH",
        "source_run_id": "SOURCE",
        "source_slot_count": 1,
        "research_object_count": 1,
        "source_envelope_count": 1,
        "projected_envelope_count": 1,
        "missing_envelope_count": 0,
        "feature_count": 2,
        "slot_results": [{
            "source_file": name,
            "collection_slot_utc": source["collection_slot_utc"],
            "source_collection_status": "COMPLETE_FEATURES",
            "research_status": "RESEARCH_GEOGRAPHIC_ENVELOPE",
            "research_object_count": 1,
            "source_envelope_count": 1,
            "projected_envelope_count": 1,
            "missing_envelope_count": 0,
            "feature_count": 2,
            "output_file": geo_path,
            "risk_engine_allowed": False,
            "official_risk_output": False,
            "lpz_forecast_generated": False,
            "probability_generated": False,
            "severity_generated": False,
        }],
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
    })
    return name, source


def _make_comparison(root: Path, *, boundary_target=False, break_chain=False):
    bridge = _bundle(15, "L-B")
    target = _bundle(
        30,
        "L-C",
        boundary_minutes={35} if boundary_target else set(),
    )
    if break_chain:
        bridge["components"]["radar_tracking"]["tracking"]["30"]["transitions"][0][
            "primary_matches"
        ] = []
    _write_batch(root, "TARGET", [bridge, target])


def test_identity_matched_motion_envelope_beats_persistence(tmp_path):
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    _make_source(source_root)
    _make_comparison(target_root)

    result = evaluate(source_root, [target_root])
    assert result["schema_version"] == "0.2.0"
    assert result["counts"]["projection_count"] == 1
    assert result["counts"]["exact_target_count"] == 1
    assert result["counts"]["identity_verified_count"] == 1
    assert result["counts"]["comparable_envelope_count"] == 1

    row = result["results"][0]
    assert row["verification_status"] == "IDENTITY_MATCHED_ENVELOPE_COMPARISON"
    assert row["motion_envelope"]["iou"] == pytest.approx(1.0)
    assert row["persistence_envelope"]["iou"] == pytest.approx(0.0)
    assert row["motion_minus_persistence_iou"] == pytest.approx(1.0)

    h15 = result["horizons_from_as_of_minutes"]["15"]
    assert h15["projection_count"] == 1
    assert h15["exact_target_count"] == 1
    assert h15["identity_verified_count"] == 1
    assert h15["identity_unresolved_count"] == 0
    assert h15["identity_verification_rate_among_exact_targets"] == pytest.approx(1.0)
    assert h15["identity_status_counts"] == {}
    assert h15["break_association_category_counts"] == {}
    assert h15["comparison_count"] == 1
    assert h15["motion_iou_median"] == pytest.approx(1.0)
    assert h15["persistence_iou_median"] == pytest.approx(0.0)
    assert h15["motion_higher_iou_count"] == 1


def test_unresolved_identity_is_unknown_not_zero_score(tmp_path):
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    _make_source(source_root)
    _make_comparison(target_root, break_chain=True)

    result = evaluate(source_root, [target_root])
    row = result["results"][0]
    assert row["verification_status"] == "IDENTITY_UNRESOLVED_UNKNOWN"
    assert row["identity_verified"] is False
    assert row["motion_envelope"] is None
    assert row["persistence_envelope"] is None
    assert result["counts"]["identity_unresolved_count"] == 1
    assert result["counts"]["comparable_envelope_count"] == 0
    diagnostics = result["identity_diagnostics"]
    assert diagnostics["unresolved_count"] == 1
    assert diagnostics["identity_status_counts"] == {
        "NO_CONTINUOUS_PRIMARY_MATCH": 1
    }
    assert diagnostics["break_association_category_counts"] == {
        "NO_RECORDED_OVERLAP_CANDIDATE": 1
    }
    geometry = diagnostics["all_break_geometry"]
    assert geometry["nearest_component_available_count"] == 1
    assert geometry["nearest_centroid_displacement_pixels"]["median"] == pytest.approx(5.0)
    assert geometry["nearest_centroid_displacement_pixels"]["within_threshold_counts"]["3"] == 0
    assert geometry["nearest_centroid_displacement_pixels"]["within_threshold_counts"]["5"] == 1
    assert geometry["nearest_bbox_intersects_true_count"] == 0
    assert geometry["nearest_bbox_intersects_false_count"] == 1
    assert geometry["nearest_to_previous_pixel_count_ratio"]["median"] == pytest.approx(1.0)
    assert geometry["death_record_count_distribution"] == {"0": 1}
    by_category = diagnostics["break_geometry_by_category"][
        "NO_RECORDED_OVERLAP_CANDIDATE"
    ]
    assert by_category["count"] == 1
    assert by_category["geometry"]["nearest_centroid_displacement_pixels"]["median"] == pytest.approx(5.0)
    h15 = result["horizons_from_as_of_minutes"]["15"]
    assert h15["exact_target_count"] == 1
    assert h15["identity_verified_count"] == 0
    assert h15["identity_unresolved_count"] == 1
    assert h15["identity_verification_rate_among_exact_targets"] == pytest.approx(0.0)
    assert h15["identity_status_counts"] == {"NO_CONTINUOUS_PRIMARY_MATCH": 1}
    assert h15["break_association_category_counts"] == {
        "NO_RECORDED_OVERLAP_CANDIDATE": 1
    }


def test_boundary_truncated_target_is_excluded_not_scored(tmp_path):
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    _make_source(source_root)
    _make_comparison(target_root, boundary_target=True)

    result = evaluate(source_root, [target_root])
    row = result["results"][0]
    assert row["identity_verified"] is True
    assert row["verification_status"] == "BOUNDARY_TRUNCATED_EXCLUDED"
    assert row["target_boundary_truncated"] is True
    assert row["motion_envelope"] is None
    assert result["counts"]["boundary_truncated_excluded_count"] == 1


def test_missing_exact_future_frame_is_explicit_unknown(tmp_path):
    source_root = tmp_path / "source"
    comparison_root = tmp_path / "comparison"
    _make_source(source_root)
    # Bridge only reaches minute 30; the projected exact target is minute 35.
    _write_batch(comparison_root, "TARGET", [_bundle(15, "L-B")])

    result = evaluate(source_root, [comparison_root])
    row = result["results"][0]
    assert row["verification_status"] == "NO_EXACT_FUTURE_TARGET_IN_PROVIDED_ARTIFACTS"
    assert row["target_run_id"] is None
    assert row["motion_envelope"] is None
    assert result["counts"]["no_exact_target_count"] == 1
