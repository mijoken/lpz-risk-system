from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "o8_1_self_healing_batch_collector.py"

spec = importlib.util.spec_from_file_location("o8_1_self_healing_batch_collector", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_floor_quarter_hour() -> None:
    assert module.floor_quarter_hour(dt("2026-09-13T08:14:59Z")) == dt("2026-09-13T08:00:00Z")
    assert module.floor_quarter_hour(dt("2026-09-13T08:45:01Z")) == dt("2026-09-13T08:45:00Z")


def test_expected_slots_are_deterministic_15_minute_grid() -> None:
    now = dt("2026-09-13T08:40:00Z")
    slots = module.expected_slots(now, horizon_minutes=120, settlement_lag_minutes=15)
    assert slots[0] == dt("2026-09-13T06:45:00Z")
    assert slots[-1] == dt("2026-09-13T08:15:00Z")
    assert all((b - a).total_seconds() == 900 for a, b in zip(slots, slots[1:]))
    assert len(slots) == 7


def test_archive_role_separates_native_and_recovered() -> None:
    now = dt("2026-09-13T08:40:00Z")
    assert module.archive_role(dt("2026-09-13T08:15:00Z"), now, 30) == "PROSPECTIVE_NATIVE"
    assert module.archive_role(dt("2026-09-13T08:00:00Z"), now, 30) == "PROSPECTIVE_RECOVERED"


def test_represented_slots_accept_only_complete_locked_rows(tmp_path: Path) -> None:
    manifest = {
        "slot_results": [
            {
                "collection_slot_utc": "2026-09-13T07:00:00Z",
                "collection_status": "COMPLETE_NO_TRACKABLE_EVENT",
                "bundle_complete": True,
                "risk_engine_allowed": False,
            },
            {
                "collection_slot_utc": "2026-09-13T07:15:00Z",
                "collection_status": "TECHNICAL_INCOMPLETE",
                "bundle_complete": False,
                "risk_engine_allowed": False,
            },
            {
                "collection_slot_utc": "2026-09-13T07:30:00Z",
                "collection_status": "COMPLETE_FEATURES",
                "bundle_complete": True,
                "risk_engine_allowed": True,
            },
        ]
    }
    path = tmp_path / "batch_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    represented = module.represented_slots([tmp_path])
    assert represented == {dt("2026-09-13T07:00:00Z")}
