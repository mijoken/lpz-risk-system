from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_field_motion_dashboard_surface_is_wired():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
    map_js = (ROOT / "web" / "js" / "map.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")

    required_ids = [
        "field-motion-layer-toggle",
        "field-motion-status",
        "field-motion-summary",
        "field-motion-decision",
        "field-motion-asof",
        "field-motion-count",
        "field-motion-selected",
        "field-motion-center",
        "field-motion-area",
        "field-motion-target",
        "field-motion-key",
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in html

    assert 'F4_FIELD_MOTION_URL = "./data/research/f4_field_motion_research.geojson"' in app
    assert "assertFieldMotionResearch" in app
    assert "setupFieldMotionResearch(fieldMotionDoc)" in app
    assert "onFieldMotionSelect: renderFieldMotionSelection" in app
    assert "setFieldMotionEnvelopes" in map_js
    assert "setFieldMotionVisible" in map_js
    assert "selectFieldMotionObject" in map_js
    assert ".field-motion-envelope" in css


def test_field_motion_public_product_is_locked_research_only():
    payload = json.loads(
        (
            ROOT
            / "web"
            / "data"
            / "research"
            / "f4_field_motion_research.geojson"
        ).read_text(encoding="utf-8")
    )

    assert payload["product"] == "LPZ_F4_FIELD_MOTION_RESEARCH"
    assert payload["status"] in {"NOT_PUBLISHED", "AVAILABLE", "ARCHIVED", "NO_PROJECTED_ENVELOPES"}
    assert payload["model_id"] == "LUCAS_KANADE_SEMILAGRANGIAN"
    assert payload["terminal_decision"] in {"PENDING", "GO", "NO_GO"}
    assert payload["f4_closed"] is (payload["terminal_decision"] != "PENDING")
    assert payload["research_only"] is True
    assert payload["validated_forecast"] is False
    assert payload["production_integration_enabled"] is False
    assert payload["risk_engine_allowed"] is False
    assert payload["official_risk_output"] is False
    assert payload["lpz_forecast_generated"] is False
    assert payload["probability_generated"] is False
    assert payload["severity_generated"] is False
    assert payload["feature_count"] == len(payload["features"])
    if payload["status"] == "NOT_PUBLISHED":
        assert payload["terminal_decision"] == "PENDING"
        assert payload["features"] == []
    if payload["status"] in {"AVAILABLE", "ARCHIVED"}:
        assert payload["feature_count"] > 0
        assert payload["source_case_id"]
        assert payload["source_as_of_utc"]
        assert all(f["properties"]["risk_engine_allowed"] is False for f in payload["features"])

def test_archive_is_not_misrepresented_as_live_and_map_clicks_are_preserved():
    app = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
    map_js = (ROOT / "web" / "js" / "map.js").read_text(encoding="utf-8")
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
    assert 'doc.status === "ARCHIVED"' in app
    assert 'doc.status === "STALE_SUPPRESSED"' in app
    assert "enableResearchRefresh();" in app
    assert "liveRevision !== liveResearchRevision" in app
    assert "motionRevision !== fieldMotionRevision" in app
    assert "svg.setPointerCapture(event.pointerId)" not in map_js
    assert 'class="dashboard-main"' in html
    assert ".dashboard-main {" in css
    assert ".dashboard-main > .research-panel" in css
    assert 'grid-template-areas: "map side" "research side"' not in css
    assert html.index('class="map-panel"') < html.index('id="f4-research-panel"') < html.index('class="side"')


def test_archived_field_motion_is_not_drawn_on_live_map():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'const archived = doc.status === "ARCHIVED" || archivedByClock;' in app
    assert 'if (archived && doc.features.length)' in app
    assert 'window.LPZMap.setFieldMotionEnvelopes(null);' in app
    assert "実況降水との時刻混同を防ぐため" in app
    assert './f4-archive.html#field-motion' in html


def test_dashboard_main_stack_does_not_inherit_side_column_height():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")

    assert '<div class="dashboard-main">' in html
    assert "grid-template-columns: minmax(0, 2fr) minmax(310px, .62fr);" in css
    assert ".dashboard-main {" in css
    assert "align-content: start;" in css
    assert "gap: 18px;" in css
    assert ".dashboard-main > .research-panel { min-width: 0; margin-top: 0; }" in css
    assert 'grid-template-areas: "map side" "research side"' not in css
