#!/usr/bin/env python3
"""O9-C — prove Final V08 half-hour coverage for every frozen rainfall target.

The gate consumes frozen Development/Validation target CSVs and a metadata census
of IMERG granules.  It does not download rainfall payloads and never reads ERA5.
For each target UTC region-day it requires all 58 half-hour starts needed by the
frozen 53 rolling 3-hour windows (previous day 21:30 through next day 02:00).
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

SHORT_NAME = "GPM_3IMERGHH"
VERSION = "08"
EXPECTED_DEV_ROWS = 5943
EXPECTED_VALIDATION_ROWS = 1218
EXPECTED_SLOTS_PER_TARGET_DAY = 58
PASS_GATE = "PASS_O9_C_V08_FULL_REQUIRED_COVERAGE"


def parse_date(value: str) -> datetime:
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def required_slot_starts(date_values: Iterable[str]) -> set[datetime]:
    slots: set[datetime] = set()
    for value in sorted(set(str(x)[:10] for x in date_values)):
        day = parse_date(value)
        first = day - timedelta(hours=2, minutes=30)
        for i in range(EXPECTED_SLOTS_PER_TARGET_DAY):
            slots.add(first + timedelta(minutes=30 * i))
    return slots


def read_target_dates(path: Path) -> tuple[list[str], int]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows or "date_utc" not in rows[0]:
        raise ValueError(f"target CSV requires date_utc and at least one row: {path}")
    keys = set()
    dates: list[str] = []
    for r in rows:
        d = str(r["date_utc"])[:10]
        code = str(r.get("primary_subdivision_code", "")).strip()
        if not code:
            raise ValueError(f"target CSV requires primary_subdivision_code: {path}")
        key = (d, code.zfill(6))
        if key in keys:
            raise ValueError(f"duplicate region-day target {key} in {path}")
        keys.add(key)
        dates.append(d)
    return dates, len(rows)


def load_granules(path: Path) -> list[dict[str, Any]]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    rows = obj.get("granules") if isinstance(obj, dict) else obj
    if not isinstance(rows, list):
        raise ValueError("granule metadata JSON must be a list or {'granules': [...]} object")
    return [r for r in rows if isinstance(r, dict)]


def parse_start(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timezone-aware granule start required: {value}")
    return dt.astimezone(timezone.utc)


def evaluate_coverage(
    *,
    development_dates: list[str],
    validation_dates: list[str],
    development_row_count: int,
    validation_row_count: int,
    granules: list[dict[str, Any]],
    expected_development_rows: int = EXPECTED_DEV_ROWS,
    expected_validation_rows: int = EXPECTED_VALIDATION_ROWS,
) -> dict[str, Any]:
    if development_row_count != expected_development_rows:
        raise ValueError(
            f"Development target row count must be {expected_development_rows}, got {development_row_count}"
        )
    if validation_row_count != expected_validation_rows:
        raise ValueError(
            f"Validation target row count must be {expected_validation_rows}, got {validation_row_count}"
        )

    available: dict[datetime, list[dict[str, Any]]] = {}
    wrong_identity_count = 0
    for row in granules:
        try:
            start = parse_start(row["start_utc"])
        except Exception:
            continue
        if str(row.get("short_name")) != SHORT_NAME or str(row.get("version")).zfill(2) != VERSION:
            wrong_identity_count += 1
            continue
        if row.get("official_final_product") is not True:
            wrong_identity_count += 1
            continue
        available.setdefault(start, []).append(row)

    dev_required = required_slot_starts(development_dates)
    val_required = required_slot_starts(validation_dates)
    dev_missing = sorted(dev_required - set(available))
    val_missing = sorted(val_required - set(available))

    all_covered = not dev_missing and not val_missing
    return {
        "schema_version": "1.0.0",
        "phase": "O9-C-v08-required-coverage",
        "gate": PASS_GATE if all_covered else "WAIT_O9_C_V08_REQUIRED_COVERAGE_INCOMPLETE",
        "short_name": SHORT_NAME,
        "imerg_final_version": VERSION,
        "official_final_product": True,
        "development_region_day_count": development_row_count,
        "validation_region_day_count": validation_row_count,
        "development_unique_target_day_count": len(set(development_dates)),
        "validation_unique_target_day_count": len(set(validation_dates)),
        "development_required_unique_slot_count": len(dev_required),
        "validation_required_unique_slot_count": len(val_required),
        "union_required_unique_slot_count": len(dev_required | val_required),
        "metadata_v08_unique_slot_count": len(available),
        "development_missing_slot_count": len(dev_missing),
        "validation_missing_slot_count": len(val_missing),
        "development_missing_slots": [iso_z(x) for x in dev_missing[:200]],
        "validation_missing_slots": [iso_z(x) for x in val_missing[:200]],
        "missing_slot_lists_truncated_at": 200,
        "wrong_or_nonfinal_metadata_row_count_ignored": wrong_identity_count,
        "all_required_slots_covered": all_covered,
        "coverage_semantics": (
            "ALL_58_EXACT_HALF_HOUR_STARTS_REQUIRED_FOR_EACH_FROZEN_TARGET_REGION_DAY; "
            "NO_INTERPOLATION; SAME_FINAL_V08_PRODUCT_FOR_DEVELOPMENT_AND_VALIDATION"
        ),
        "environment_variables_read": False,
        "validation_era5_environment_read": False,
        "risk_engine_allowed": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--development-targets", required=True, type=Path)
    ap.add_argument("--validation-targets", required=True, type=Path)
    ap.add_argument("--granule-metadata", required=True, type=Path)
    ap.add_argument("--availability-evidence", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    dev_dates, dev_count = read_target_dates(args.development_targets)
    val_dates, val_count = read_target_dates(args.validation_targets)
    granules = load_granules(args.granule_metadata)
    report = evaluate_coverage(
        development_dates=dev_dates,
        validation_dates=val_dates,
        development_row_count=dev_count,
        validation_row_count=val_count,
        granules=granules,
    )

    # Hash-link O9-C to the exact O9-A availability proof.
    import hashlib
    h = hashlib.sha256(args.availability_evidence.read_bytes()).hexdigest()
    report["requires_sha256"] = {args.availability_evidence.name: h}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "gate": report["gate"],
        "dev_missing": report["development_missing_slot_count"],
        "validation_missing": report["validation_missing_slot_count"],
    }))
    return 0 if report["gate"] == PASS_GATE else 3


if __name__ == "__main__":
    raise SystemExit(main())
