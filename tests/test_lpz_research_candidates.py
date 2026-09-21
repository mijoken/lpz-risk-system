"""F3 adapter contract tests: synthetic inputs only, no weather acquisition."""
import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_lpz_research_candidates.py"
spec = importlib.util.spec_from_file_location("lpz_f3_adapter", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def bundle(rows=None):
    rows = [{"some_existing_key": 12, "nested": {"other": 3}}] if rows is None else rows
    return {
        "schema_version": "0.3.0", "risk_engine_allowed": False,
        "risk_score": None, "lpz_classification": None,
        "bundle_complete": True, "collection_status": "COMPLETE_FEATURES",
        "as_of_time_guard_pass": True, "prospective_as_of_utc": "2026-09-21T00:15:00Z",
        "archive_role": "PROSPECTIVE_NATIVE",
        "components": {"parent_precursor_features": {
            "execution_ok": True, "risk_engine_allowed": False,
            "risk_score": None, "classification": None,
            "descriptor_count": len(rows), "descriptors": rows,
        }},
    }


def test_preserves_source_without_forecast():
    src = bundle()
    result = module.adapt(src)
    assert result["research_object_count"] == 1
    assert result["research_objects"][0]["source_descriptor"] == src["components"]["parent_precursor_features"]["descriptors"][0]
    assert result["research_objects"][0]["geometry"] is None
    assert result["research_objects"][0]["forecast_probability"] is None
    assert result["forecast_generated"] is False
    assert result["risk_engine_allowed"] is False
    assert module.adapt(src) == result


def test_empty_descriptors_are_not_predictions():
    result = module.adapt(bundle([]))
    assert result["research_object_count"] == 0
    assert result["status"] == "DESCRIPTIVE_ONLY"


@pytest.mark.parametrize("field,value", [
    ("risk_engine_allowed", True), ("risk_score", 0.8),
    ("lpz_classification", "POSITIVE"), ("bundle_complete", False),
    ("collection_status", "COMPLETE_NO_TRACKABLE_EVENT"),
    ("as_of_time_guard_pass", False), ("prospective_as_of_utc", None),
])
def test_rejects_unsafe_source(field, value):
    src = bundle()
    src[field] = value
    with pytest.raises(ValueError):
        module.adapt(src)


def test_rejects_descriptor_count_mismatch():
    src = bundle()
    src["components"]["parent_precursor_features"]["descriptor_count"] = 2
    with pytest.raises(ValueError, match="descriptor_count"):
        module.adapt(src)


def test_rejects_parent_report_risk_score():
    src = bundle()
    src["components"]["parent_precursor_features"]["risk_score"] = 0.4
    with pytest.raises(ValueError):
        module.adapt(src)
