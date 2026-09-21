"""Contract tests for F4 archived public research: no invented live/risk output."""
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publish_f4_archived_research_summary import publish


def _summary():
    return {
        "source_run_id": "35564667965", "target_run_id": "35565907043",
        "risk_engine_allowed": False, "lpz_forecast_generated": False,
        "counts": {
            "source_research_objects": 1536, "current_origin_objects": 466,
            "projected_objects": 106, "comparable_projections": 58,
            "no_exact_comparable_target": 154,
            "identity_matched_projections": 6, "identity_unresolved_projections": 52,
        },
        "identity_status_counts": {
            "CONTINUOUS_PRIMARY_MATCH_OBSERVED": 6,
            "NOT_EVALUATED_NO_EXACT_TARGET": 154, "NO_CONTINUOUS_PRIMARY_MATCH": 52,
        },
        "no_continuous_match_association_categories": {
            "MERGE_CANDIDATE": 12, "NO_RECORDED_OVERLAP_CANDIDATE": 39,
            "SPLIT_AND_MERGE_CANDIDATES": 1,
        },
        "no_overlap_geometry_diagnostics": {"nearest_component_is_not_object_identity": True},
        "horizons_from_as_of_minutes": {
            "15": {"identity_matched_count": 3, "motion_median_km": 5.1050842406120065,
                   "persistence_median_km": 13.831491214490015},
            "30": {"identity_matched_count": 3, "motion_median_km": 9.016153359497016,
                   "persistence_median_km": 21.280073545510078},
        },
    }


def test_archived_summary_not_forecast():
    out = publish(_summary())
    assert out["product"] == "LPZ_F4_ARCHIVED_RESEARCH_PUBLIC_SUMMARY"
    assert out["archived_research_only"] is True
    assert out["risk_engine_allowed"] is False
    assert out["lpz_forecast_generated"] is False


@pytest.mark.parametrize("change", [
    lambda r: r.update(source_run_id="another"),
    lambda r: r.update(risk_engine_allowed=True),
    lambda r: r.update(lpz_forecast_generated=True),
    lambda r: r["counts"].update(identity_unresolved_projections=51),
    lambda r: r["no_continuous_match_association_categories"].update(MERGE_CANDIDATE=11),
])
def test_refuses_unlocked_or_inconsistent_source(change):
    r = deepcopy(_summary())
    change(r)
    with pytest.raises(ValueError):
        publish(r)
