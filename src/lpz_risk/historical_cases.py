"""Historical case-registry primitives.

This module intentionally separates source ingestion from semantic labeling.
JMA CSV rows are first preserved losslessly with stable hashes and only then
promoted into normalized positive cases after their actual columns have been
observed and mapped. This prevents guessed column meanings from entering the
research database.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

JST = timezone(timedelta(hours=9))
_COMPACT14 = re.compile(r"^\d{14}$")
_COMPACT12 = re.compile(r"^\d{12}$")


@dataclass(frozen=True)
class SourceRow:
    source_id: str
    source_year: int
    row_number: int
    raw: dict[str, str]
    row_sha256: str
    datetime_candidates: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_year": self.source_year,
            "row_number": self.row_number,
            "raw": self.raw,
            "row_sha256": self.row_sha256,
            "datetime_candidates": list(self.datetime_candidates),
        }


def decode_csv_bytes(payload: bytes) -> tuple[str, str]:
    """Decode JMA CSV bytes without silently replacing invalid bytes."""
    if not payload:
        raise ValueError("empty CSV payload")
    for encoding in ("utf-8-sig", "cp932", "shift_jis"):
        try:
            return payload.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV payload was neither UTF-8 nor Japanese legacy encoding")


def parse_csv_text(text: str) -> tuple[list[str], list[dict[str, str]]]:
    if not text.strip():
        raise ValueError("CSV text is blank")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [str(h).strip() for h in (reader.fieldnames or []) if h is not None]
    if not headers:
        raise ValueError("CSV has no header row")
    rows: list[dict[str, str]] = []
    for row in reader:
        normalized = {str(k).strip(): "" if v is None else str(v).strip() for k, v in row.items() if k is not None}
        if any(normalized.values()):
            rows.append(normalized)
    return headers, rows


def stable_row_hash(source_id: str, row: dict[str, str]) -> str:
    canonical = json.dumps({"source_id": source_id, "row": row}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_datetime_value(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    candidates = [value]
    if _COMPACT14.match(value):
        candidates.insert(0, f"{value[0:4]}-{value[4:6]}-{value[6:8]} {value[8:10]}:{value[10:12]}:{value[12:14]}")
    elif _COMPACT12.match(value):
        candidates.insert(0, f"{value[0:4]}-{value[4:6]}-{value[6:8]} {value[8:10]}:{value[10:12]}")
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
    )
    for candidate in candidates:
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt).replace(tzinfo=JST)
            except ValueError:
                pass
    return None


def datetime_candidates(row: dict[str, str]) -> tuple[str, ...]:
    found: list[str] = []
    for key, value in row.items():
        parsed = _parse_datetime_value(value)
        if parsed is not None:
            found.append(f"{key}={parsed.isoformat()}")
    return tuple(found)


def ingest_source_rows(source_id: str, source_year: int, payload: bytes) -> dict[str, Any]:
    text, encoding = decode_csv_bytes(payload)
    headers, raw_rows = parse_csv_text(text)
    rows = [
        SourceRow(
            source_id=source_id,
            source_year=source_year,
            row_number=i + 2,
            raw=row,
            row_sha256=stable_row_hash(source_id, row),
            datetime_candidates=datetime_candidates(row),
        )
        for i, row in enumerate(raw_rows)
    ]
    hashes = [row.row_sha256 for row in rows]
    return {
        "source_id": source_id,
        "source_year": source_year,
        "encoding": encoding,
        "headers": headers,
        "row_count": len(rows),
        "duplicate_row_hash_count": len(hashes) - len(set(hashes)),
        "rows_with_datetime_candidates": sum(bool(row.datetime_candidates) for row in rows),
        "rows": [row.to_dict() for row in rows],
        "semantic_mapping_status": "PENDING_HEADER_AUDIT",
    }


def snapshot_times(anchor: datetime, offsets_minutes: list[int]) -> list[str]:
    if anchor.tzinfo is None:
        raise ValueError("anchor datetime must be timezone-aware")
    return [(anchor + timedelta(minutes=int(offset))).astimezone(timezone.utc).isoformat().replace("+00:00", "Z") for offset in offsets_minutes]
