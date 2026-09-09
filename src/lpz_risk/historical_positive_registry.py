"""Normalize audited JMA LPZ detection rows into research-safe entities.

The JMA CSV is a time/region detection table, not a pre-grouped event table.
This module therefore creates two explicit entity types only:

1. DETECTION_ROW: every official CSV row, retaining 0/10/20/30-minute
   criterion-reach flags.
2. REALIZED_POSITIVE_ANCHOR: only rows where the current-time criterion
   (実況基準到達) equals 0.

No temporal/spatial episode grouping is performed here. That is a separate,
future, validated operation.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from typing import Any

JST = timezone(timedelta(hours=9))
EXPECTED_HEADERS = [
    "年", "月", "日", "時", "分", "府県予報区", "一次細分区域", "一次細分区域コード",
    "実況基準到達", "10分先基準到達", "20分先基準到達", "30分先基準到達",
]
HORIZON_COLUMNS = {
    0: "実況基準到達",
    10: "10分先基準到達",
    20: "20分先基準到達",
    30: "30分先基準到達",
}
_CODE_RE = re.compile(r"^\d{6}$")


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _parse_analysis_time(raw: dict[str, str]) -> datetime:
    try:
        dt = datetime(
            int(raw["年"]), int(raw["月"]), int(raw["日"]),
            int(raw["時"]), int(raw["分"]), tzinfo=JST,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid JMA date/time fields: {raw!r}") from exc
    return dt


def _criterion_offsets(raw: dict[str, str]) -> list[int]:
    offsets: list[int] = []
    for expected_offset, column in HORIZON_COLUMNS.items():
        value = str(raw.get(column, "")).strip()
        if not value:
            continue
        try:
            actual = int(value)
        except ValueError as exc:
            raise ValueError(f"non-numeric criterion marker {column}={value!r}") from exc
        if actual != expected_offset:
            raise ValueError(f"criterion marker mismatch: {column} contained {actual}, expected {expected_offset}")
        offsets.append(actual)
    if not offsets:
        raise ValueError("official row contained no criterion-reach marker")
    return sorted(offsets)


def normalize_detection_row(source_block: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    source = source_block["source"]
    parsed = source_block["parsed"]
    if parsed.get("headers") != EXPECTED_HEADERS:
        raise ValueError(f"unexpected JMA headers for {source.get('source_id')}: {parsed.get('headers')!r}")

    raw = {str(k): str(v) for k, v in row["raw"].items()}
    dt_jst = _parse_analysis_time(raw)
    source_year = int(source["year"])
    if dt_jst.year != source_year:
        raise ValueError(f"row year {dt_jst.year} != configured source year {source_year}")

    code = raw["一次細分区域コード"].strip()
    if not _CODE_RE.match(code):
        raise ValueError(f"invalid primary subdivision code: {code!r}")

    offsets = _criterion_offsets(raw)
    id_payload = {
        "source_id": source["source_id"],
        "analysis_time_jst": dt_jst.isoformat(),
        "primary_subdivision_code": code,
        "row_sha256": row["row_sha256"],
    }
    detection_id = _stable_id("JMADET", id_payload)

    return {
        "entity_type": "DETECTION_ROW",
        "detection_id": detection_id,
        "source_id": source["source_id"],
        "source_year": source_year,
        "source_row_number": int(row["row_number"]),
        "source_row_sha256": row["row_sha256"],
        "analysis_time_jst": dt_jst.isoformat(),
        "analysis_time_utc": _iso_utc(dt_jst),
        "forecast_area": raw["府県予報区"],
        "primary_subdivision": raw["一次細分区域"],
        "primary_subdivision_code": code,
        "criterion_reached_offsets_minutes": offsets,
        "realized_current_time_positive": 0 in offsets,
        "future_criterion_reach_present": any(offset > 0 for offset in offsets),
        "raw_criterion_markers": {column: raw[column] for column in HORIZON_COLUMNS.values()},
        "label_provenance": "JMA_OFFICIAL_LPZ_CASE_CSV",
        "event_episode_id": None,
        "risk_score": None,
    }


def build_positive_registry(source_audit_report: dict[str, Any], snapshot_offsets_minutes: list[int]) -> dict[str, Any]:
    if not source_audit_report.get("execution_ok"):
        raise ValueError("source audit report is not successful")

    detections: list[dict[str, Any]] = []
    for source_block in source_audit_report["sources"]:
        for row in source_block["parsed"]["rows"]:
            detections.append(normalize_detection_row(source_block, row))

    detections.sort(key=lambda r: (r["analysis_time_utc"], r["primary_subdivision_code"], r["detection_id"]))
    realized = [row for row in detections if row["realized_current_time_positive"]]

    anchors: list[dict[str, Any]] = []
    for row in realized:
        anchor_dt = datetime.fromisoformat(row["analysis_time_utc"].replace("Z", "+00:00"))
        snapshot_times = [
            _iso_utc(anchor_dt + timedelta(minutes=int(offset)))
            for offset in snapshot_offsets_minutes
        ]
        anchor_id = _stable_id("JMAANCHOR", {
            "detection_id": row["detection_id"],
            "snapshot_offsets_minutes": snapshot_offsets_minutes,
        })
        anchors.append({
            "entity_type": "REALIZED_POSITIVE_ANCHOR",
            "anchor_id": anchor_id,
            "detection_id": row["detection_id"],
            "analysis_time_utc": row["analysis_time_utc"],
            "analysis_time_jst": row["analysis_time_jst"],
            "forecast_area": row["forecast_area"],
            "primary_subdivision": row["primary_subdivision"],
            "primary_subdivision_code": row["primary_subdivision_code"],
            "snapshot_offsets_minutes": list(snapshot_offsets_minutes),
            "snapshot_times_utc": snapshot_times,
            "episode_grouping_status": "NOT_GROUPED",
            "historical_features_reconstructed": False,
        })

    duplicate_detection_ids = len(detections) - len({row["detection_id"] for row in detections})
    duplicate_anchor_ids = len(anchors) - len({row["anchor_id"] for row in anchors})
    if duplicate_detection_ids or duplicate_anchor_ids:
        raise ValueError("stable ID collision or duplicated normalized entity detected")

    return {
        "schema_version": "0.1.0",
        "phase": "2A-positive-registry",
        "detection_row_count": len(detections),
        "realized_positive_anchor_count": len(anchors),
        "forecast_only_detection_row_count": len(detections) - len(anchors),
        "detections": detections,
        "realized_positive_anchors": anchors,
        "episode_grouping_complete": False,
        "hard_negative_registry_complete": False,
        "historical_feature_reconstruction_complete": False,
        "risk_engine_allowed": False,
        "gates": {
            "official_source_header_mapping": True,
            "detection_row_normalization": True,
            "realized_positive_anchor_extraction": True,
            "episode_grouping": False,
            "hard_negative_selection": False,
            "historical_feature_reconstruction": False,
            "risk_engine_allowed": False
        }
    }
