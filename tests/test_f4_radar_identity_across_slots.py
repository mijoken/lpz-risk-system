"""F4-3 identity continuity across overlapping radar archives."""
import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from trace_f4_radar_identity_across_slots import trace_identity


def _stamp(minute):
    return (datetime(2026, 9, 21, 3, 30, tzinfo=timezone.utc)
            + timedelta(minutes=minute)).isoformat().replace("+00:00", "Z")


def _component(local, lineage):
    return {
        "local_id": local, "lineage_id": lineage, "pixel_count": 10,
        "centroid_pixel": {"row": 20.0, "col": 30.0},
        "centroid": {"lon": 139.0, "lat": 35.0},
        "bbox_pixel": [29, 19, 31, 21], "boundary_truncated": False,
    }


def _bundle(start, lineage):
    frames = []
    transitions = []
    for minute in range(start, start + 16, 5):
        frames.append({"valid_time": _stamp(minute),
                       "components": [_component(minute + 1, lineage)]})
    for prev, curr in zip(frames, frames[1:]):
        transitions.append({
            "from_valid_time": prev["valid_time"],
            "to_valid_time": curr["valid_time"],
            "primary_matches": [{
                "previous_id": prev["components"][0]["local_id"],
                "current_id": curr["components"][0]["local_id"],
                "lineage_id": lineage,
            }],
        })
    return {
        "bundle_complete": True, "as_of_time_guard_pass": True,
        "risk_engine_allowed": False,
        "prospective_as_of_utc": _stamp(start + 20),
        "components": {"radar_tracking": {
            "execution_ok": True, "scientific_tracking_proven": True,
            "fixed_mosaic": {"zoom": 8, "origin_tile_x": 224,
                             "origin_tile_y": 100, "tile_count": 16},
            "tracking": {"30": {"frames": frames, "transitions": transitions}},
        }},
    }


def test_chains_across_local_lineage_reset():
    a, b, c = _bundle(0, "L-A"), _bundle(15, "L-B"), _bundle(30, "L-C")
    # Source ends at 03:45; future 04:00 requires an overlapping archive.
    result = trace_identity(a, "L-A", _stamp(30), [b, c])
    assert result["status"] == "CONTINUOUS_PRIMARY_MATCH_OBSERVED"
    assert result["identity_verified"] is True
    assert result["verified_transition_count"] == 3
    # The exact 04:00 frame is present in both B and C. Their lineage IDs
    # are local to each tracking run, so neither L-B nor L-C is canonical.
    assert result["target_component"]["local_id"] == 31


def test_gap_is_unknown_not_negative():
    a, c = _bundle(0, "L-A"), _bundle(30, "L-C")
    result = trace_identity(a, "L-A", _stamp(30), [c])
    assert result["status"] == "MISSING_INTERMEDIATE_OBSERVATION"
    assert result["identity_verified"] is False


def test_no_primary_match_is_unknown():
    a, b = _bundle(0, "L-A"), _bundle(15, "L-B")
    b["components"]["radar_tracking"]["tracking"]["30"]["transitions"][0]["primary_matches"] = []
    result = trace_identity(a, "L-A", _stamp(30), [b])
    assert result["status"] == "NO_CONTINUOUS_PRIMARY_MATCH"
    assert result["identity_verified"] is False
    assert result["break_diagnostic"]["from_valid_time_utc"] == _stamp(15)
    assert result["break_diagnostic"]["to_valid_time_utc"] == _stamp(20)
    assert result["break_diagnostic"]["available_transition_records"] == 1
    assert result["break_diagnostic"]["previous_id_primary_match_records"] == 0
    assert result["break_diagnostic"]["next_frame_component_count"] == 1
    assert result["break_diagnostic"]["association_category"] == "NO_RECORDED_OVERLAP_CANDIDATE"
    assert result["break_diagnostic"]["previous_component_pixel_count"] == 10
    assert result["break_diagnostic"]["previous_component_boundary_truncated"] is False
    assert result["break_diagnostic"]["nearest_next_frame_component"] == {
        "centroid_displacement_pixels": 0.0,
        "pixel_count": 10,
        "boundary_truncated": False,
        "bbox_intersects": True,
    }


def test_no_overlap_first_break_with_no_next_components_keeps_unknown_identity():
    a, b = _bundle(0, "L-A"), _bundle(15, "L-B")
    b["components"]["radar_tracking"]["tracking"]["30"]["frames"][1]["components"] = []
    b["components"]["radar_tracking"]["tracking"]["30"]["transitions"][0]["primary_matches"] = []
    result = trace_identity(a, "L-A", _stamp(30), [b])
    assert result["identity_verified"] is False
    assert result["break_diagnostic"]["next_frame_component_count"] == 0
    assert result["break_diagnostic"]["nearest_next_frame_component"] is None


@pytest.mark.parametrize(
    ("structure", "entry", "expected"),
    [
        ("split_candidates", {"previous_id": 16, "current_ids": [21, 22]}, "SPLIT_CANDIDATE"),
        ("merge_candidates", {"current_id": 21, "previous_ids": [16, 17]}, "MERGE_CANDIDATE"),
    ],
)
def test_first_break_preserves_archived_split_merge_evidence(structure, entry, expected):
    a, b = _bundle(0, "L-A"), _bundle(15, "L-B")
    transition = b["components"]["radar_tracking"]["tracking"]["30"]["transitions"][0]
    transition["primary_matches"] = []
    transition[structure] = [entry]
    result = trace_identity(a, "L-A", _stamp(30), [b])
    assert result["status"] == "NO_CONTINUOUS_PRIMARY_MATCH"
    assert result["identity_verified"] is False
    assert result["break_diagnostic"]["association_category"] == expected


def test_overlapping_frame_conflict_rejected():
    a, b = _bundle(0, "L-A"), _bundle(15, "L-B")
    b["components"]["radar_tracking"]["tracking"]["30"]["frames"][0]["components"][0]["pixel_count"] = 11
    with pytest.raises(ValueError, match="conflicting overlapping"):
        trace_identity(a, "L-A", _stamp(30), [b])


def test_future_at_or_before_asof_rejected():
    a = _bundle(0, "L-A")
    with pytest.raises(ValueError, match="strictly after"):
        trace_identity(a, "L-A", _stamp(20), [])
