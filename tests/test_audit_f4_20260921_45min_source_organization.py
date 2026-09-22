from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from scripts.audit_f4_20260921_45min_source_organization import audit

BASE = datetime(2026, 9, 21, 13, 0, tzinfo=timezone.utc)
FIXED = {"zoom": 8, "origin_tile_x": 228, "origin_tile_y": 96, "tile_count": 16}


def _iso(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case(tmp_path: Path):
    p = tmp_path / "cohort" / "cases" / "20260921T130000Z.json"
    _write_json(p, {
        "product": "F4_9C_PROSPECTIVE_CASE",
        "case_id": "20260921T130000Z",
        "source_slot_utc": _iso(BASE),
        "fixed_mosaic": FIXED,
        "future_observations_read_at_capture": False,
        "forecast_skill_scored_at_capture": False,
        "risk_engine_allowed": False,
    })
    return p


def _source(tmp_path: Path, name: str, last: datetime, frames: list[np.ndarray]):
    source = tmp_path / "cohort" / "sources" / name
    source.mkdir(parents=True, exist_ok=True)
    npz = source / "decoded_field.npz"
    np.savez_compressed(npz, class_index=np.stack(frames))
    times = [last - timedelta(minutes=15-i*5) for i in range(4)]
    _write_json(source / "manifest.json", {
        "product": "F4_DECODED_FIELD_RESEARCH_ARCHIVE",
        "frame_valid_times": [_iso(x) for x in times],
        "fixed_mosaic": FIXED,
        "storage": {"file": "decoded_field.npz", "sha256": _sha(npz)},
    })


def _ten_frames():
    rows = []
    for i in range(10):
        a = np.zeros((1024, 1024), dtype=np.int8)
        a[100:104, 100+i:106+i] = 5
        a[200:202, 300:304] = 6
        a[400, 500] = 7
        a[:10, :10] = -1
        rows.append(a)
    return rows


def test_45min_audit_deduplicates_identical_overlap_and_never_reads_future(tmp_path: Path):
    case = _case(tmp_path)
    frames = _ten_frames()
    # 21:15–21:30, 21:30–21:45, 21:45–22:00 JST.
    _source(tmp_path, "a", BASE-timedelta(minutes=30), frames[0:4])
    _source(tmp_path, "b", BASE-timedelta(minutes=15), frames[3:7])
    _source(tmp_path, "c", BASE, frames[6:10])

    result = audit(tmp_path / "cohort", case)
    assert result["five_minute_frame_count"] == 10
    assert result["window_minutes"] == 45
    assert result["provenance"]["duplicate_timestamps_verified_identical"] == [
        "2026-09-21T12:30:00Z", "2026-09-21T12:45:00Z"
    ]
    assert result["fixed_coordinate_occurrence"]["known_all_ge30_in_at_least_10_of_10"] > 0
    assert result["read_future_observations"] is False
    assert result["read_f4_9c_verifications"] is False
    assert result["forecast_skill_scored"] is False
    assert result["risk_engine_allowed"] is False


def test_45min_audit_rejects_conflicting_duplicate_source_frame(tmp_path: Path):
    case = _case(tmp_path)
    frames = _ten_frames()
    _source(tmp_path, "a", BASE-timedelta(minutes=30), frames[0:4])
    changed = [x.copy() for x in frames[3:7]]
    changed[0][50, 50] = 7
    _source(tmp_path, "b", BASE-timedelta(minutes=15), changed)
    _source(tmp_path, "c", BASE, frames[6:10])

    with pytest.raises(ValueError, match="duplicate source frame mismatch"):
        audit(tmp_path / "cohort", case)
