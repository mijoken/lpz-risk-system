#!/usr/bin/env python3
"""O8.1-D: consolidate self-healing prospective slots into a canonical UTC day.

The GitHub Actions run clock is not the scientific clock.  This consolidator keys
all records by ``collection_slot_utc`` and always emits exactly 96 canonical
15-minute slot records for the requested UTC date.  Native and recovered slots
remain distinguishable, duplicate candidates are resolved deterministically,
and missing/failed slots remain explicit.

No LPZ classification or risk score is produced or accepted.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

UTC = timezone.utc
EXPECTED_SLOTS = 96
COMPLETE_PREFIX = "COMPLETE_"
VALID_ARCHIVE_ROLES = {"PROSPECTIVE_NATIVE", "PROSPECTIVE_RECOVERED"}


def parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp is not timezone-aware: {value}")
    return dt.astimezone(UTC)


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def canonical_slots(day: date) -> list[datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return [start + timedelta(minutes=15 * i) for i in range(EXPECTED_SLOTS)]


def _infer_run_id(path: Path, payload: dict[str, Any]) -> str:
    direct = str(payload.get("github_run_id") or payload.get("run_id") or "")
    if direct:
        return direct
    for part in reversed(path.parts):
        if part.isdigit():
            return part
    return ""


def _is_complete_locked(payload: dict[str, Any]) -> bool:
    return (
        payload.get("bundle_complete") is True
        and str(payload.get("collection_status", "")).startswith(COMPLETE_PREFIX)
        and payload.get("as_of_time_guard_pass") is True
        and payload.get("risk_engine_allowed") is False
        and payload.get("risk_score") is None
        and payload.get("lpz_classification") is None
        and payload.get("raw_radar_archived") is False
        and payload.get("raw_grib_archived") is False
    )


def _validate_candidate(path: Path, payload: dict[str, Any]) -> tuple[datetime, dict[str, Any]]:
    slot_raw = payload.get("collection_slot_utc")
    if not isinstance(slot_raw, str):
        raise ValueError("collection_slot_utc missing")
    slot = parse_utc(slot_raw)
    if slot.second != 0 or slot.microsecond != 0 or slot.minute not in {0, 15, 30, 45}:
        raise ValueError(f"collection slot is not on the canonical 15-minute grid: {slot_raw}")

    role = payload.get("archive_role")
    if role not in VALID_ARCHIVE_ROLES:
        raise ValueError(f"unexpected archive_role={role!r}")
    if payload.get("risk_engine_allowed") is not False:
        raise ValueError("risk_engine_allowed must remain false")
    if payload.get("risk_score") is not None or payload.get("lpz_classification") is not None:
        raise ValueError("risk/classification leaked into prospective archive")
    if payload.get("raw_radar_archived") is not False or payload.get("raw_grib_archived") is not False:
        raise ValueError("raw payload archival invariant violated")

    if payload.get("bundle_complete") is True:
        if not str(payload.get("collection_status", "")).startswith(COMPLETE_PREFIX):
            raise ValueError("complete bundle does not have COMPLETE_* collection_status")
        if payload.get("as_of_time_guard_pass") is not True:
            raise ValueError("complete bundle failed/missed as-of-time guard")
        as_of = parse_utc(str(payload.get("prospective_as_of_utc")))
        if as_of != slot + timedelta(minutes=15):
            raise ValueError("prospective_as_of_utc is not collection_slot_utc + 15 minutes")

    candidate = {
        "payload": payload,
        "source_path": str(path),
        "source_run_id": _infer_run_id(path, payload),
        "complete_locked": _is_complete_locked(payload),
    }
    return slot, candidate


def load_candidates(input_roots: Iterable[Path], target_day: date) -> tuple[dict[datetime, list[dict[str, Any]]], list[str]]:
    grouped: dict[datetime, list[dict[str, Any]]] = {}
    errors: list[str] = []
    seen_paths: set[str] = set()

    for root in input_roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("slots/*.json")):
            key = str(path.resolve())
            if key in seen_paths:
                continue
            seen_paths.add(key)
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("slot file is not a JSON object")
                slot, candidate = _validate_candidate(path, raw)
                if slot.date() != target_day:
                    continue
                grouped.setdefault(slot, []).append(candidate)
            except Exception as exc:  # preserve structural failures in manifest
                errors.append(f"{path}:{type(exc).__name__}:{exc}")

    return grouped, errors


def _candidate_rank(candidate: dict[str, Any]) -> tuple[Any, ...]:
    payload = candidate["payload"]
    complete_rank = 0 if candidate["complete_locked"] else 1
    role_rank = 0 if payload.get("archive_role") == "PROSPECTIVE_NATIVE" else 1
    generated = str(payload.get("generated_at_utc") or "9999-12-31T23:59:59Z")
    run_id = str(candidate.get("source_run_id") or "~")
    return (complete_rank, role_rank, generated, run_id, str(candidate.get("source_path") or ""))


def canonical_record(slot: datetime, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(candidates, key=_candidate_rank)
    complete = [c for c in ordered if c["complete_locked"]]
    selected = complete[0] if complete else (ordered[0] if ordered else None)

    if selected is None:
        state = "EXPLICIT_GAP"
        selected_payload = None
        selected_role = None
        selected_run = None
    elif selected["complete_locked"]:
        state = "COMPLETE"
        selected_payload = selected["payload"]
        selected_role = selected_payload.get("archive_role")
        selected_run = selected.get("source_run_id") or None
    else:
        state = "TECHNICAL_INCOMPLETE"
        selected_payload = selected["payload"]
        selected_role = selected_payload.get("archive_role")
        selected_run = selected.get("source_run_id") or None

    source_runs = sorted({str(c.get("source_run_id")) for c in ordered if c.get("source_run_id")})
    return {
        "schema_version": "1.0.0",
        "entity_type": "PROSPECTIVE_CANONICAL_15MIN_SLOT",
        "collection_slot_utc": iso_utc(slot),
        "slot_index": slot.hour * 4 + slot.minute // 15,
        "slot_state": state,
        "candidate_count": len(ordered),
        "complete_candidate_count": len(complete),
        "duplicate_candidate_count": max(0, len(ordered) - 1),
        "candidate_source_run_ids": source_runs,
        "selected_source_run_id": selected_run,
        "selected_archive_role": selected_role,
        "bundle": selected_payload,
        "risk_engine_allowed": False,
    }


def build_daily_records(input_roots: Iterable[Path], date_utc: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target_day = parse_day(date_utc)
    grouped, errors = load_candidates(input_roots, target_day)
    records = [canonical_record(slot, grouped.get(slot, [])) for slot in canonical_slots(target_day)]

    complete = [r for r in records if r["slot_state"] == "COMPLETE"]
    technical = [r for r in records if r["slot_state"] == "TECHNICAL_INCOMPLETE"]
    gaps = [r for r in records if r["slot_state"] == "EXPLICIT_GAP"]
    native = [r for r in complete if r.get("selected_archive_role") == "PROSPECTIVE_NATIVE"]
    recovered = [r for r in complete if r.get("selected_archive_role") == "PROSPECTIVE_RECOVERED"]
    duplicate_slots = [r for r in records if r["candidate_count"] > 1]
    candidate_count = sum(r["candidate_count"] for r in records)
    source_run_ids = sorted({rid for r in records for rid in r.get("candidate_source_run_ids", [])})

    if errors:
        canonical_quality = "STRUCTURAL_ERROR"
    elif len(complete) == EXPECTED_SLOTS:
        canonical_quality = "COMPLETE_96_OF_96"
    elif technical and gaps:
        canonical_quality = "INCOMPLETE_GAPS_AND_TECHNICAL"
    elif technical:
        canonical_quality = "INCOMPLETE_TECHNICAL"
    else:
        canonical_quality = "INCOMPLETE_EXPLICIT_GAPS"

    manifest = {
        "schema_version": "2.0.0",
        "phase": "2L-O8.1-D-daily-consolidation-v2",
        "date_utc": date_utc,
        "scientific_clock": "collection_slot_utc",
        "cadence_minutes": 15,
        "expected_15min_intervals": EXPECTED_SLOTS,
        "canonical_slot_count": len(records),
        "candidate_bundle_count": candidate_count,
        "represented_slot_count": sum(r["candidate_count"] > 0 for r in records),
        "complete_slot_count": len(complete),
        "native_complete_slot_count": len(native),
        "recovered_complete_slot_count": len(recovered),
        "technical_incomplete_slot_count": len(technical),
        "explicit_gap_count": len(gaps),
        "duplicate_slot_count": len(duplicate_slots),
        "duplicate_candidate_excess_count": sum(r["duplicate_candidate_count"] for r in records),
        "source_run_ids": source_run_ids,
        "coverage_fraction": len(complete) / EXPECTED_SLOTS,
        "parse_error_count": len(errors),
        "parse_errors": errors[:100],
        "canonical_day_quality": canonical_quality,
        # Backward-compatible aliases retained for existing audit readers.
        "bundle_count": sum(r["candidate_count"] > 0 for r in records),
        "complete_bundle_count": len(complete),
        "collector_gap_count": len(gaps),
        "prospective_day_quality": "COMPLETE" if canonical_quality == "COMPLETE_96_OF_96" else "INCOMPLETE_EXPLICIT_GAPS",
        "closure_eligible_96_of_96": canonical_quality == "COMPLETE_96_OF_96",
        "contains_recovered_slots": bool(recovered),
        "archive_role": "PROSPECTIVE_CANONICAL_DAILY",
        "raw_radar_archived": False,
        "raw_grib_archived": False,
        "lpz_classification": None,
        "risk_score": None,
        "risk_engine_allowed": False,
    }
    return records, manifest


def write_archive(path: Path, records: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256()
    with path.open("wb") as raw:
        # mtime=0 plus filename="" makes identical inputs byte-for-byte reproducible.
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
            for record in records:
                line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                encoded = line.encode("utf-8")
                gz.write(encoded)
                sha.update(encoded)
    return sha.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input-root", action="append", required=True, help="May be supplied more than once")
    ap.add_argument("--date-utc", required=True, help="YYYY-MM-DD")
    ap.add_argument("--output-gz", required=True)
    ap.add_argument("--manifest-output", required=True)
    args = ap.parse_args()

    records, manifest = build_daily_records([Path(p) for p in args.input_root], args.date_utc)
    out = Path(args.output_gz)
    digest = write_archive(out, records)
    manifest["uncompressed_jsonl_sha256"] = digest
    manifest["archive_file"] = str(out)

    mp = Path(args.manifest_output)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

    # Partial days are valid auditable products. Structural corruption fails the workflow.
    return 2 if manifest["parse_error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
