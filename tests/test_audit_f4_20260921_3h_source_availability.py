from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.audit_f4_20260921_3h_source_availability import inventory


BASE = datetime(2026, 9, 21, 13, 0, tzinfo=timezone.utc)
FIXED = {"zoom": 8, "origin_tile_x": 228, "origin_tile_y": 96, "tile_count": 16}


def _utc(t):
    return t.isoformat(timespec="seconds").replace("+00:00", "Z")


def _put(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _case(tmp_path: Path):
    p = tmp_path / "cohort" / "cases" / "20260921T130000Z.json"
    _put(p, {
        "product": "F4_9C_PROSPECTIVE_CASE",
        "source_slot_utc": _utc(BASE),
        "fixed_mosaic": FIXED,
        "risk_engine_allowed": False,
    })
    return p


def _source(tmp_path: Path, name: str, last: datetime, fixed=FIXED):
    source = tmp_path / "cohort" / "sources" / name
    _put(source / "manifest.json", {
        "product": "F4_DECODED_FIELD_RESEARCH_ARCHIVE",
        "fixed_mosaic": fixed,
        "frame_valid_times": [_utc(last - timedelta(minutes=5*i)) for i in (3,2,1,0)],
        "storage": {"file": "decoded_field.npz"},
    })
    (source / "decoded_field.npz").write_bytes(b"fake-source-not-read")


def test_census_does_not_count_future_or_switching_mosaics(tmp_path: Path):
    case = _case(tmp_path)
    start = BASE - timedelta(hours=3)
    for idx in range(13):
        _source(tmp_path, f"source-{idx}", start + timedelta(minutes=15*idx))
    _source(tmp_path, "future-should-not-be-read", BASE+timedelta(minutes=15))
    _source(tmp_path, "different-mosaic", BASE,
            {"zoom":8,"origin_tile_x":224,"origin_tile_y":100,"tile_count":16})

    result = inventory(tmp_path / "cohort", case)
    event = result["matching_event_mosaic_coverage"]
    assert event["unique_five_minute_frames_of_37"] == 37
    assert event["missing_frame_count"] == 0
    assert event["metadata_full_window"] is True
    assert event["source_npz_present_count"] == 13
    assert result["manifests_skipped_because_source_after_event"] == 1
    assert len(result["source_domain_inventory"]) == 2
    assert result["read_f4_9c_verifications"] is False
    assert result["read_future_observations"] is False
    assert result["read_radar_npz_bytes"] is False


def test_census_identifies_unavailable_3h_if_only_last_source(tmp_path: Path):
    case = _case(tmp_path)
    _source(tmp_path, "only-last-source", BASE)
    result = inventory(tmp_path / "cohort", case)
    event = result["matching_event_mosaic_coverage"]
    assert event["unique_five_minute_frames_of_37"] == 4
    assert event["missing_frame_count"] == 33
    assert event["metadata_full_window"] is False
