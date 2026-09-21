"""Public F4-4 publisher tests with synthetic artifacts only."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from publish_latest_f4_geographic_research import build_public


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _feature(lead: int, object_id: str = "R1") -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [141.0, 38.0],
                [141.1, 38.0],
                [141.1, 38.1],
                [141.0, 38.1],
                [141.0, 38.0],
            ]],
        },
        "properties": {
            "research_object_id": object_id,
            "parent_lineage_id": "T30-L0001",
            "source_as_of_utc": "2026-09-21T08:15:00Z",
            "source_observation_valid_time_utc": "2026-09-21T08:00:00Z",
            "observed_centroid_lon_lat": [141.05, 38.05],
            "observed_approx_area_km2": 50.0,
            "envelope_method": "CONVEX_HULL_OF_COMPONENT_PIXEL_CELLS",
            "exact_precipitation_contour": False,
            "research_only": True,
            "risk_engine_allowed": False,
            "lpz_forecast_generated": False,
            "probability": None,
            "severity": None,
            "intensity": None,
            "kind": "PROJECTED_RESEARCH_GEOGRAPHIC_ENVELOPE",
            "lead_from_as_of_minutes": lead,
            "lead_from_last_observation_minutes": lead + 15,
            "target_valid_time_utc": (
                "2026-09-21T08:30:00Z" if lead == 15
                else "2026-09-21T08:45:00Z"
            ),
            "projected_centroid_lon_lat": (
                [141.1, 38.1] if lead == 15 else [141.15, 38.15]
            ),
            "projection_method": "LAST_MATCHED_TWO_FRAME_CONSTANT_VELOCITY",
        },
    }


def _observed() -> dict:
    f = _feature(15)
    f["properties"] = dict(f["properties"])
    f["properties"].update({
        "kind": "OBSERVED_THRESHOLD_COMPONENT_ENVELOPE",
        "lead_from_as_of_minutes": 0,
        "target_valid_time_utc": "2026-09-21T08:00:00Z",
        "projection_method": None,
    })
    f["properties"].pop("lead_from_last_observation_minutes", None)
    f["properties"].pop("projected_centroid_lon_lat", None)
    return f


def _make_artifact(root: Path, *, features=None, status="RESEARCH_GEOGRAPHIC_ENVELOPE") -> None:
    artifact = root / "prospective-batch-42"
    batch = artifact
    slot_name = "20260921T080000Z.json"
    row = {
        "source_file": slot_name,
        "collection_slot_utc": "2026-09-21T08:00:00Z",
        "source_collection_status": "COMPLETE_FEATURES",
        "research_status": status,
        "research_object_count": 1 if status == "RESEARCH_GEOGRAPHIC_ENVELOPE" else 0,
        "source_envelope_count": 1 if status == "RESEARCH_GEOGRAPHIC_ENVELOPE" else 0,
        "projected_envelope_count": 2 if status == "RESEARCH_GEOGRAPHIC_ENVELOPE" else 0,
        "missing_envelope_count": 0,
        "feature_count": 3 if status == "RESEARCH_GEOGRAPHIC_ENVELOPE" else 0,
        "output_file": (
            f"f4_geographic_envelopes/slots/{slot_name}"
            if status == "RESEARCH_GEOGRAPHIC_ENVELOPE" else None
        ),
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
    }
    _write(batch / "f4_geographic_envelopes" / "manifest.json", {
        "schema_version": "0.1.0",
        "product": "F4_RESEARCH_GEOGRAPHIC_ENVELOPE_BATCH",
        "source_run_id": "42",
        "source_slot_count": 1,
        "research_object_count": row["research_object_count"],
        "source_envelope_count": row["source_envelope_count"],
        "projected_envelope_count": row["projected_envelope_count"],
        "missing_envelope_count": 0,
        "feature_count": row["feature_count"],
        "slot_results": [row],
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
    })
    if status == "RESEARCH_GEOGRAPHIC_ENVELOPE":
        source_features = features if features is not None else [_observed(), _feature(15), _feature(30)]
        _write(batch / row["output_file"], {
            "type": "FeatureCollection",
            "product": "F4_RESEARCH_GEOGRAPHIC_ENVELOPES",
            "schema_version": "0.1.0",
            "source_as_of_utc": "2026-09-21T08:15:00Z",
            "latest_observation_utc": "2026-09-21T08:00:00Z",
            "source_envelope_count": 1,
            "projected_envelope_count": 2,
            "missing_envelope_count": 0,
            "feature_count": len(source_features),
            "features": source_features,
            "risk_engine_allowed": False,
            "official_risk_output": False,
            "lpz_forecast_generated": False,
            "probability_generated": False,
            "severity_generated": False,
        })


def test_publishes_latest_projected_envelopes_only(tmp_path):
    _make_artifact(tmp_path)
    result = build_public(
        tmp_path,
        now_utc=datetime(2026, 9, 21, 8, 20, tzinfo=timezone.utc),
        max_age_minutes=90,
    )

    assert result["product"] == "LPZ_F4_LIVE_RESEARCH_ENVELOPES"
    assert result["status"] == "AVAILABLE"
    assert result["coverage"] == "SELECTED_FIXED_MOSAIC_NOT_NATIONWIDE"
    assert result["source_run_id"] == "42"
    assert result["source_slot_utc"] == "2026-09-21T08:00:00Z"
    assert result["source_as_of_utc"] == "2026-09-21T08:15:00Z"
    assert result["projected_object_count"] == 1
    assert result["feature_count"] == 2
    assert result["horizons_from_as_of_minutes"] == [15, 30]
    assert result["risk_engine_allowed"] is False
    assert result["validated_forecast"] is False
    assert all(
        f["properties"]["kind"] == "PROJECTED_RESEARCH_GEOGRAPHIC_ENVELOPE"
        for f in result["features"]
    )
    assert all(f["properties"]["public_display_only"] is True for f in result["features"])


def test_stale_geometry_is_suppressed(tmp_path):
    _make_artifact(tmp_path)
    result = build_public(
        tmp_path,
        now_utc=datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc),
        max_age_minutes=90,
    )

    assert result["status"] == "STALE_SUPPRESSED"
    assert result["stale_suppressed"] is True
    assert result["feature_count"] == 0
    assert result["features"] == []
    assert result["risk_engine_allowed"] is False


def test_no_research_slot_publishes_explicit_empty_product(tmp_path):
    _make_artifact(tmp_path, status="NO_DOWNSTREAM_RESEARCH_OBJECT")
    result = build_public(
        tmp_path,
        now_utc=datetime(2026, 9, 21, 8, 20, tzinfo=timezone.utc),
    )

    assert result["status"] == "NO_RESEARCH_SLOT"
    assert result["source_slot_utc"] is None
    assert result["feature_count"] == 0
    assert result["features"] == []


def test_rejects_projected_feature_with_probability(tmp_path):
    bad = _feature(15)
    bad["properties"]["probability"] = 0.8
    _make_artifact(tmp_path, features=[_observed(), bad, _feature(30)])

    with pytest.raises(ValueError, match="research lock"):
        build_public(
            tmp_path,
            now_utc=datetime(2026, 9, 21, 8, 20, tzinfo=timezone.utc),
        )


def test_rejects_multiple_artifact_manifests(tmp_path):
    _make_artifact(tmp_path / "a")
    _make_artifact(tmp_path / "b")

    with pytest.raises(ValueError, match="expected one"):
        build_public(
            tmp_path,
            now_utc=datetime(2026, 9, 21, 8, 20, tzinfo=timezone.utc),
        )
