from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "consolidate_prospective_feature_bundles.py"
spec = importlib.util.spec_from_file_location("o81d", SCRIPT)
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def slot_payload(slot: str, *, role: str = "PROSPECTIVE_NATIVE", complete: bool = True, run_id: str = "1", generated: str = "2026-09-13T01:00:00Z") -> dict:
    dt = datetime.fromisoformat(slot.replace("Z", "+00:00")).astimezone(timezone.utc)
    asof = (dt.timestamp() + 900)
    asof_s = datetime.fromtimestamp(asof, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "entity_type": "PROSPECTIVE_DERIVED_FEATURE_BUNDLE",
        "collection_slot_utc": slot,
        "prospective_as_of_utc": asof_s,
        "generated_at_utc": generated,
        "github_run_id": run_id,
        "archive_role": role,
        "collection_status": "COMPLETE_NO_TRACKABLE_EVENT" if complete else "TECHNICAL_INCOMPLETE",
        "bundle_complete": complete,
        "as_of_time_guard_pass": True if complete else None,
        "raw_radar_archived": False,
        "raw_grib_archived": False,
        "lpz_classification": None,
        "risk_score": None,
        "risk_engine_allowed": False,
    }


def write_slot(root: Path, name: str, payload: dict) -> None:
    p = root / name / "slots" / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def test_canonical_day_has_exactly_96_slots() -> None:
    slots = m.canonical_slots(m.parse_day("2026-09-13"))
    assert len(slots) == 96
    assert m.iso_utc(slots[0]) == "2026-09-13T00:00:00Z"
    assert m.iso_utc(slots[-1]) == "2026-09-13T23:45:00Z"


def test_collection_slot_not_generated_at_selects_day(tmp_path: Path) -> None:
    p = slot_payload(
        "2026-09-13T23:45:00Z",
        role="PROSPECTIVE_RECOVERED",
        run_id="9",
        generated="2026-09-14T00:30:00Z",
    )
    write_slot(tmp_path, "9", p)
    records, manifest = m.build_daily_records([tmp_path], "2026-09-13")
    assert manifest["represented_slot_count"] == 1
    assert records[-1]["slot_state"] == "COMPLETE"
    assert records[-1]["selected_archive_role"] == "PROSPECTIVE_RECOVERED"


def test_duplicate_prefers_complete_native_then_earliest(tmp_path: Path) -> None:
    slot = "2026-09-13T12:00:00Z"
    write_slot(tmp_path, "1", slot_payload(slot, role="PROSPECTIVE_RECOVERED", run_id="1", generated="2026-09-13T12:20:00Z"))
    write_slot(tmp_path, "2", slot_payload(slot, role="PROSPECTIVE_NATIVE", run_id="2", generated="2026-09-13T12:25:00Z"))
    write_slot(tmp_path, "3", slot_payload(slot, role="PROSPECTIVE_NATIVE", complete=False, run_id="3", generated="2026-09-13T12:10:00Z"))
    records, manifest = m.build_daily_records([tmp_path], "2026-09-13")
    row = records[48]
    assert row["candidate_count"] == 3
    assert row["duplicate_candidate_count"] == 2
    assert row["selected_source_run_id"] == "2"
    assert row["selected_archive_role"] == "PROSPECTIVE_NATIVE"
    assert row["slot_state"] == "COMPLETE"
    assert manifest["duplicate_slot_count"] == 1


def test_gap_and_technical_incomplete_are_distinct(tmp_path: Path) -> None:
    write_slot(tmp_path, "1", slot_payload("2026-09-13T00:00:00Z", complete=False))
    records, manifest = m.build_daily_records([tmp_path], "2026-09-13")
    assert records[0]["slot_state"] == "TECHNICAL_INCOMPLETE"
    assert records[1]["slot_state"] == "EXPLICIT_GAP"
    assert manifest["technical_incomplete_slot_count"] == 1
    assert manifest["explicit_gap_count"] == 95
    assert manifest["closure_eligible_96_of_96"] is False


def test_deterministic_gzip(tmp_path: Path) -> None:
    records, _ = m.build_daily_records([tmp_path], "2026-09-13")
    a = tmp_path / "a.gz"
    b = tmp_path / "b.gz"
    sha_a = m.write_archive(a, records)
    sha_b = m.write_archive(b, records)
    assert sha_a == sha_b
    assert a.read_bytes() == b.read_bytes()
    with gzip.open(a, "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    assert len(rows) == 96
    assert rows[0]["slot_index"] == 0
    assert rows[-1]["slot_index"] == 95
