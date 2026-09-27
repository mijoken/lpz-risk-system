"""Regression checks for the four F4 research dashboard issues."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_f4_archive_is_explicitly_frozen_not_live():
    html = (ROOT / "web/f4-archive.html").read_text(encoding="utf-8")
    app = (ROOT / "web/js/f4-archive.js").read_text(encoding="utf-8")
    assert "35564667965" in html
    assert "ライブ更新ではなく" in html
    assert 'data.source_run_id' in app


def test_f4_archive_map_labels_can_scale_and_not_overlap():
    css = (ROOT / "web/css/f4-archive.css").read_text(encoding="utf-8")
    app = (ROOT / "web/js/f4-archive.js").read_text(encoding="utf-8")
    assert ".f4-city text" in css
    assert ".f4-city text {fill:" in css
    assert ".f4-city text {fill:" in css and "font-size:12px" not in css
    assert ".f4-origin-number {font-size:" not in css
    assert "g.dataset.minScale" in app
    assert "const overlaps = placed.some" in app
    assert 'label.style.display = show ? "" : "none"' in app


def test_f4_archive_selection_is_readable_and_interactive():
    app = (ROOT / "web/js/f4-archive.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/f4-archive.css").read_text(encoding="utf-8")
    assert "setPointerCapture" not in app
    assert "detail.replaceChildren();" in app
    assert "archive-detail-card" in app
    assert "archive-detail-note" in app
    assert ".archive-detail-card" in css


def test_f4_archive_preserves_purple_field_motion_history():
    html = (ROOT / "web/f4-archive.html").read_text(encoding="utf-8")
    app = (ROOT / "web/js/f4-archive.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/f4-archive.css").read_text(encoding="utf-8")
    assert 'id="f4-field-motion-toggle"' in html
    assert 'id="f4-field-motion-focus"' in html
    assert "f4_field_motion_research.geojson" in app
    assert "LPZ_F4_FIELD_MOTION_RESEARCH" in app
    assert "FIELD_MOTION_RESEARCH_ENVELOPE" in app
    assert ".f4-field-motion" in css
    assert "保存済みLucas–Kanade" in html


def test_f4_archive_zoom_keeps_markers_and_arrowheads_readable():
    app = (ROOT / "web/js/f4-archive.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/f4-archive.css").read_text(encoding="utf-8")
    assert "updateArrowHead" in app
    assert 'String(9 / scale)' in app
    assert 'String(4 / scale)' in app
    assert 'String(12 / scale)' in app
    assert ".f4-origin,.f4-end,.f4-city circle {vector-effect:non-scaling-stroke;}" in css
    assert ".f4-arrow-head {fill:none;" in css


def test_f4_archive_default_focus_and_layer_explanation_match_current_layout():
    html = (ROOT / "web/f4-archive.html").read_text(encoding="utf-8")
    app = (ROOT / "web/js/f4-archive.js").read_text(encoding="utf-8")
    assert "Lucas–Kanade field-level motion" in html
    assert "水色点＋黄線" in html
    assert "紫色Lucas–Kanade予測とは別の研究手法です" in html
    assert "function fieldMotionBounds(features)" in app
    assert "const fitX = (W - paddingX * 2) / width;" in app
    assert "const fitY = (H - paddingY * 2) / height;" in app
    assert "const desired = Math.min(12, Math.max(2.5, Math.min(fitX, fitY)));" in app
    assert './js/f4-archive.js?v=20260927c' in html
    assert './css/f4-archive.css?v=20260927c' in html
