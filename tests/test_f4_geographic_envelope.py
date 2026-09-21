"""F4-4 geographic-envelope tests; research display only."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from build_f4_geographic_envelope import build
from build_f4_observed_origin_join import join
from build_f4_research_motion_baseline import project
from build_lpz_research_candidates import adapt
from test_f4_research_motion_baseline import matched_source


def _envelope():
    return {
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [138.95, 34.95],
                [139.05, 34.95],
                [139.05, 35.05],
                [138.95, 35.05],
                [138.95, 34.95],
            ]],
        },
        "method": "CONVEX_HULL_OF_COMPONENT_PIXEL_CELLS",
        "exact_precipitation_contour": False,
        "source_pixel_count": 20,
        "vertex_count": 4,
        "interpretation": "test",
    }


def products_with_envelope():
    bundle, _ = matched_source()
    current = bundle["components"]["radar_tracking"]["tracking"]["30"]["frames"][-1]["components"][0]
    current["geographic_envelope"] = _envelope()
    f3 = adapt(bundle)
    return join(bundle, f3), project(bundle, f3)


def test_builds_observed_and_projected_envelopes_without_risk_output():
    origins, motion = products_with_envelope()
    result = build(origins, motion)
    assert result["product"] == "F4_RESEARCH_GEOGRAPHIC_ENVELOPES"
    assert result["source_envelope_count"] == 1
    assert result["projected_envelope_count"] == 2
    assert result["feature_count"] == 3
    assert result["risk_engine_allowed"] is False
    assert result["lpz_forecast_generated"] is False
    assert result["probability_generated"] is False
    assert result["severity_generated"] is False
    assert all(f["properties"]["probability"] is None for f in result["features"])
    projected = [f for f in result["features"] if f["properties"]["kind"] == "PROJECTED_RESEARCH_GEOGRAPHIC_ENVELOPE"]
    assert [f["properties"]["lead_from_as_of_minutes"] for f in projected] == [15, 30]
    assert projected[0]["geometry"] != result["features"][0]["geometry"]


def test_missing_observed_envelope_is_explicit_not_invented():
    bundle, f3 = matched_source()
    origins = join(bundle, f3)
    motion = project(bundle, f3)
    result = build(origins, motion)
    assert result["source_envelope_count"] == 0
    assert result["projected_envelope_count"] == 0
    assert result["missing_envelope_count"] == 1
    assert result["features"] == []


def test_asof_mismatch_rejected():
    origins, motion = products_with_envelope()
    motion["source_as_of_utc"] = "2026-09-21T05:00:00Z"
    try:
        build(origins, motion)
    except ValueError as exc:
        assert "as-of mismatch" in str(exc)
    else:
        raise AssertionError("expected ValueError")
