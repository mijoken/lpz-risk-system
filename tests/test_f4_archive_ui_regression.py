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
