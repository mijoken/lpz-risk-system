from __future__ import annotations

import json
from pathlib import Path

import pytest

from lpz_risk.public_web import build_public_products


def _write(path: Path, obj) -> Path:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


def _k2():
    return {
        "gate": "PASS_PHASE2L_K2_V07_BOUNDARY_AND_V08_DEFERRED_VALIDATION_FREEZE",
        "upstream_protocol": {
            "primary_hypothesis": {"id": "H_PRIMARY_Q850_T0H"}
        },
        "validation_state": {
            "status": "DEFERRED_PENDING_IMERG_FINAL_V08",
            "primary_confirmatory_test_run": False,
            "primary_outcome_opened": False,
            "2025_era5_environment_outcomes_may_be_opened_now": False,
            "risk_engine_allowed": False,
        },
    }


def _phase_l():
    return {
        "summary": {
            "research_validation_status": "DEFERRED_PENDING_IMERG_FINAL_V08",
            "2025_era5_environment_opened": False,
            "primary_confirmatory_test_run": False,
            "risk_engine_allowed": False,
        },
        "live_source_health": [
            {
                "source_id": "jma_nowc",
                "source_name": "JMA Nowcast",
                "role": "LIVE_MANDATORY",
                "health": "PASS",
                "probe_status": "PASS",
                "data_time": "2026-09-12T10:00:00Z",
                "data_age_seconds": 300,
                "freshness_limit_seconds": 1800,
                "reason": "STATUS_AND_FRESHNESS_OK",
                "error": None,
            }
        ],
        "earthdata_imerg_research_source": {
            "authentication": "PASS",
            "imerg_final_v08_metadata": "EXPECTED_PENDING",
            "v8_available": False,
        },
    }


def _geometry():
    return {
        "type": "FeatureCollection",
        "schema_version": "1.0.3",
        "features": [
            {
                "type": "Feature",
                "id": "130010",
                "properties": {"region_code": "130010", "name_ja": "東京地方"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[139.0, 35.0], [140.0, 35.0], [140.0, 36.0], [139.0, 35.0]]],
                },
            },
            {
                "type": "Feature",
                "id": "140010",
                "properties": {"region_code": "140010", "name_ja": "東部"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[139.0, 35.0], [140.0, 35.0], [140.0, 36.0], [139.0, 35.0]]],
                },
            },
        ],
    }


def test_locked_public_products_are_schema_valid_and_risk_null(tmp_path: Path):
    products = build_public_products(
        source_health_report_path=_write(tmp_path / "l.json", _phase_l()),
        k2_freeze_path=_write(tmp_path / "k2.json", _k2()),
        geography_path=_write(tmp_path / "g.json", _geometry()),
        generated_at_utc="2026-09-12T10:30:00Z",
        pipeline_state="PASS",
        run_id="TEST",
        commit_sha="abc123",
    )

    status = products["system_status.json"]
    health = products["source_health.json"]
    latest = products["latest.json"]

    assert status["overall_operational_status"] == "ONLINE"
    assert status["scientific_release"]["risk_engine_allowed"] is False
    assert health["overall_status"] == "PASS"
    assert len(latest["regions"]) == 2
    assert all(row["risk"] is None for row in latest["regions"])
    assert all(row["display_state"] == "NO_PUBLIC_RISK" for row in latest["regions"])


def test_phase_l_seal_violation_is_rejected(tmp_path: Path):
    phase_l = _phase_l()
    phase_l["summary"]["risk_engine_allowed"] = True

    with pytest.raises(RuntimeError, match="risk engine"):
        build_public_products(
            source_health_report_path=_write(tmp_path / "l.json", phase_l),
            k2_freeze_path=_write(tmp_path / "k2.json", _k2()),
            geography_path=_write(tmp_path / "g.json", _geometry()),
            generated_at_utc="2026-09-12T10:30:00Z",
        )
