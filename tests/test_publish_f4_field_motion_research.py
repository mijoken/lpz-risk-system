from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from scripts.publish_f4_field_motion_research import build_public


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _cohort(tmp_path: Path) -> Path:
    root = tmp_path / "cohort"
    case_id = "20260921T124500Z"
    case = {
        "schema_version": "1.0.0",
        "product": "F4_9C_PROSPECTIVE_CASE",
        "research_stage": "F4-9C",
        "case_id": case_id,
        "source_slot_utc": "2026-09-21T12:45:00Z",
        "prospective_as_of_utc": "2026-09-21T13:00:00Z",
        "target_valid_time_utc": [
            "2026-09-21T13:15:00Z",
            "2026-09-21T13:30:00Z",
        ],
        "lead_minutes_from_as_of": [15, 30],
        "captured_before_first_target": True,
        "future_observations_read_at_capture": False,
        "forecast_skill_scored_at_capture": False,
        "parameter_tuning_performed": False,
        "risk_engine_allowed": False,
        "fixed_mosaic": {
            "zoom": 8,
            "origin_tile_x": 228,
            "origin_tile_y": 96,
            "tile_count": 16,
        },
        "source_components": [
            {
                "component_id": 1,
                "pixel_count": 9,
                "boundary_truncated": False,
            }
        ],
    }
    _write_json(root / "cases" / f"{case_id}.json", case)

    forecast = np.zeros((2, 32, 32), dtype=np.uint16)
    forecast[0, 10:13, 12:15] = 1
    forecast[1, 10:13, 15:18] = 1

    target_unix = np.asarray(
        [
            int(datetime(2026, 9, 21, 13, 15, tzinfo=timezone.utc).timestamp()),
            int(datetime(2026, 9, 21, 13, 30, tzinfo=timezone.utc).timestamp()),
        ],
        dtype=np.int64,
    )
    path = root / "component_forecasts" / f"{case_id}.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        forecast_component_labels=forecast,
        lead_minutes=np.asarray([15, 30], dtype=np.int16),
        target_valid_time_unix_s=target_unix,
    )
    return root


def test_field_motion_public_product_is_research_only(tmp_path: Path):
    root = _cohort(tmp_path)
    result = build_public(
        root,
        now_utc=datetime(2026, 9, 21, 13, 5, tzinfo=timezone.utc),
    )

    assert result["product"] == "LPZ_F4_FIELD_MOTION_RESEARCH"
    assert result["status"] == "AVAILABLE"
    assert result["terminal_decision"] == "PENDING"
    assert result["f4_closed"] is False
    assert result["research_only"] is True
    assert result["validated_forecast"] is False
    assert result["production_integration_enabled"] is False
    assert result["risk_engine_allowed"] is False
    assert result["lpz_forecast_generated"] is False
    assert result["feature_count"] == 2
    assert result["projected_component_count"] == 1
    assert result["horizons_from_as_of_minutes"] == [15, 30]

    leads = {
        int(feature["properties"]["lead_from_as_of_minutes"])
        for feature in result["features"]
    }
    assert leads == {15, 30}
    for feature in result["features"]:
        props = feature["properties"]
        assert feature["geometry"]["type"] == "Polygon"
        assert props["kind"] == "FIELD_MOTION_RESEARCH_ENVELOPE"
        assert props["model_id"] == "LUCAS_KANADE_SEMILAGRANGIAN"
        assert props["terminal_decision"] == "PENDING"
        assert props["risk_engine_allowed"] is False
        assert props["probability"] is None
        assert props["severity"] is None
        assert props["intensity"] is None
        assert props["exact_precipitation_contour"] is False


def test_terminal_decision_changes_label_not_geometry(tmp_path: Path):
    root = _cohort(tmp_path)
    now = datetime(2026, 9, 21, 13, 5, tzinfo=timezone.utc)
    pending = build_public(root, now_utc=now)

    decision = tmp_path / "f4_9d.json"
    _write_json(
        decision,
        {
            "product": "F4_9D_TERMINAL_DECISION",
            "decision": "NO_GO",
            "f4_closed": True,
            "risk_engine_allowed": False,
            "validated_forecast": False,
        },
    )
    decided = build_public(root, decision_path=decision, now_utc=now)

    assert decided["terminal_decision"] == "NO_GO"
    assert decided["f4_closed"] is True
    assert [row["geometry"] for row in decided["features"]] == [
        row["geometry"] for row in pending["features"]
    ]
    assert all(
        row["properties"]["terminal_decision"] == "NO_GO"
        for row in decided["features"]
    )


def test_stale_geometry_is_suppressed(tmp_path: Path):
    root = _cohort(tmp_path)
    result = build_public(
        root,
        now_utc=datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc),
        max_age_minutes=90,
    )

    assert result["status"] == "STALE_SUPPRESSED"
    assert result["feature_count"] == 0
    assert result["features"] == []


def test_no_cases_returns_not_published(tmp_path: Path):
    result = build_public(
        tmp_path / "empty",
        now_utc=datetime(2026, 9, 21, 13, 5, tzinfo=timezone.utc),
    )

    assert result["status"] == "NOT_PUBLISHED"
    assert result["terminal_decision"] == "PENDING"
    assert result["feature_count"] == 0
