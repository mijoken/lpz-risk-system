"""F4-6C post-break continuity/ownership audit tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_f4_motion_rescue_postbreak import (
    _follow_primary_chain,
    _incoming_primary_owners,
    _passes_primary_gate,
)
from trace_f4_radar_identity_across_slots import _signature


def _component(local_id: int, col: float) -> dict:
    return {
        "local_id": local_id,
        "lineage_id": f"L{local_id}",
        "pixel_count": 10,
        "approx_area_km2": 10.0,
        "centroid_pixel": {"row": 20.0, "col": col},
        "centroid": {"lon": 139.0 + col * 0.001, "lat": 35.0},
        "bbox_pixel": [int(col) - 1, 19, int(col) + 1, 21],
        "boundary_truncated": False,
        "geographic_envelope": None,
    }


def _frame(time: str, components: list[dict]) -> dict:
    return {"valid_time": time, "components": components}


def _transition(a: str, b: str, matches: list[tuple[int, int]]) -> dict:
    return {
        "from_valid_time": a,
        "to_valid_time": b,
        "elapsed_seconds": 300,
        "primary_matches": [
            {
                "previous_id": previous,
                "current_id": current,
                "lineage_id": f"L{previous}",
            }
            for previous, current in matches
        ],
        "split_candidates": [],
        "merge_candidates": [],
        "births": [],
        "deaths": [],
    }


def _indices():
    t0 = "2026-09-21T07:30:00Z"
    t1 = "2026-09-21T07:35:00Z"
    t2 = "2026-09-21T07:40:00Z"
    t3 = "2026-09-21T07:45:00Z"
    t4 = "2026-09-21T07:50:00Z"

    a = _component(1, 10.0)
    other = _component(2, 30.0)
    candidate = _component(3, 20.0)
    c2 = _component(4, 24.0)
    c3 = _component(5, 28.0)
    c4 = _component(6, 32.0)

    frames_raw = [
        _frame(t0, [a, other]),
        _frame(t1, [candidate]),
        _frame(t2, [c2]),
        _frame(t3, [c3]),
        _frame(t4, [c4]),
    ]
    frames = {
        frame["valid_time"]: {
            _signature(component): component
            for component in frame["components"]
        }
        for frame in frames_raw
    }

    tr01 = _transition(t0, t1, [(2, 3)])
    tr12 = _transition(t1, t2, [(3, 4)])
    tr23 = _transition(t2, t3, [(4, 5)])
    tr34 = _transition(t3, t4, [(5, 6)])

    edges = {
        (t0, t1): [(frames_raw[:2], tr01)],
        (t1, t2): [(frames_raw[1:3], tr12)],
        (t2, t3): [(frames_raw[2:4], tr23)],
        (t3, t4): [(frames_raw[3:5], tr34)],
    }
    return (t0, t1, t2, t3, t4), frames, edges, candidate


def test_primary_gate_is_frozen_d8_m3():
    base = {
        "motion_reference_available": True,
        "previous_component_boundary_truncated": False,
        "candidate_boundary_truncated": False,
        "motion_error_pixels": 8.0,
        "competitor_margin_pixels": 3.0,
    }
    assert _passes_primary_gate(base) is True
    assert _passes_primary_gate({**base, "motion_error_pixels": 8.01}) is False
    assert _passes_primary_gate({**base, "competitor_margin_pixels": 2.99}) is False
    assert _passes_primary_gate({
        **base,
        "previous_component_boundary_truncated": True,
    }) is False


def test_incoming_primary_owner_is_conflict_evidence():
    times, frames, edges, candidate = _indices()
    owners = _incoming_primary_owners(
        frames,
        edges,
        times[0],
        times[1],
        _signature(candidate),
    )
    assert len(owners) == 1
    owner = next(iter(owners))
    assert frames[times[0]][owner]["local_id"] == 2


def test_forward_chain_follows_existing_primary_matches_for_15_minutes():
    times, frames, edges, candidate = _indices()
    result = _follow_primary_chain(
        frames,
        edges,
        times[1],
        _signature(candidate),
    )
    assert result["forward_primary_continuity_steps"] == 3
    assert result["forward_primary_continuity_minutes"] == 15
    assert result["forward_stop_reason"] == "MAX_AUDIT_HORIZON_REACHED"


def test_forward_chain_stops_without_primary_match():
    times, frames, edges, candidate = _indices()
    edges[(times[2], times[3])][0][1]["primary_matches"] = []

    result = _follow_primary_chain(
        frames,
        edges,
        times[1],
        _signature(candidate),
    )
    assert result["forward_primary_continuity_steps"] == 1
    assert result["forward_primary_continuity_minutes"] == 5
    assert result["forward_stop_reason"] == "NO_FORWARD_PRIMARY_MATCH"
