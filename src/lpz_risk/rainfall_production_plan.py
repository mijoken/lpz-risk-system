"""Normalize DEVELOPMENT 3-hour windows into reusable native-field/payload tasks.

This is planning only. It never selects rainfall thresholds or labels cases.
The key optimization is to deduplicate provider payloads by native valid time,
independent of primary-subdivision code, because the satellite products are
spatial fields that can serve multiple polygons at the same timestamp.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

UTC = timezone.utc


def _parse(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return dt.astimezone(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _payload_key(source_id: str, valid_start: datetime) -> tuple[str, str]:
    if source_id == "GSMAP_STANDARD_V8_HISTORICAL":
        return source_id, valid_start.strftime("%Y%m%d%H")
    if source_id == "NASA_IMERG_FINAL_V07":
        return source_id, valid_start.strftime("%Y%m%d%H%M")
    if source_id == "NOAA_CMORPH_CDR":
        # One CMORPH hourly NetCDF contains two 30-minute canonical fields.
        return source_id, valid_start.strftime("%Y%m%d%H")
    raise ValueError(f"unsupported source_id: {source_id}")


def _task_id(source_id: str, day: str) -> str:
    raw = f"{source_id}|{day}".encode("utf-8")
    return "RAINPROD-" + hashlib.sha256(raw).hexdigest()[:14]


def build_development_rainfall_production_plan(window_manifest: dict[str, Any]) -> dict[str, Any]:
    if window_manifest.get("split") != "DEVELOPMENT":
        raise ValueError("production plan accepts DEVELOPMENT manifest only")
    if window_manifest.get("future_interval_count") != 0:
        raise ValueError("manifest contains future precipitation intervals")
    if window_manifest.get("candidate_threshold_selected") is not False:
        raise ValueError("candidate threshold must remain unselected")

    windows = list(window_manifest.get("windows") or [])
    if not windows:
        raise ValueError("window manifest contains no windows")

    unique_fields: dict[tuple[str, str], dict[str, Any]] = {}
    unique_payloads: dict[tuple[str, str], dict[str, Any]] = {}
    window_to_fields: dict[str, list[str]] = {}
    window_to_payloads: dict[str, list[str]] = {}

    for w in windows:
        source = str(w["source_id"])
        interval = int(w["native_interval_seconds"])
        count = int(w["native_field_count"])
        start = _parse(w["window_start_utc"])
        end = _parse(w["window_end_utc"])
        if end <= start or int((end - start).total_seconds()) != 10800:
            raise ValueError("window must be exactly 3 hours")
        if count * interval != 10800:
            raise ValueError("native field count does not span exactly 3 hours")

        field_ids: list[str] = []
        payload_ids: list[str] = []
        for i in range(count):
            valid_start = start + timedelta(seconds=i * interval)
            valid_end = valid_start + timedelta(seconds=interval)
            if valid_end > end:
                raise AssertionError("native field exceeds window end")
            field_key = (source, _iso(valid_start))
            field_id = "FIELD-" + hashlib.sha256((source + "|" + field_key[1]).encode()).hexdigest()[:16]
            unique_fields.setdefault(field_key, {
                "field_id": field_id,
                "source_id": source,
                "valid_start_utc": field_key[1],
                "valid_end_utc": _iso(valid_end),
                "accumulation_seconds": interval,
            })
            field_ids.append(field_id)

            pk = _payload_key(source, valid_start)
            payload_id = "PAYLOAD-" + hashlib.sha256((pk[0] + "|" + pk[1]).encode()).hexdigest()[:16]
            unique_payloads.setdefault(pk, {
                "payload_id": payload_id,
                "source_id": source,
                "payload_time_key": pk[1],
                "contains_native_field_ids": [],
            })
            if field_id not in unique_payloads[pk]["contains_native_field_ids"]:
                unique_payloads[pk]["contains_native_field_ids"].append(field_id)
            payload_ids.append(payload_id)

        window_to_fields[str(w["window_id"])] = field_ids
        window_to_payloads[str(w["window_id"])] = sorted(set(payload_ids))

    field_rows = sorted(unique_fields.values(), key=lambda r: (r["source_id"], r["valid_start_utc"]))
    payload_rows = sorted(unique_payloads.values(), key=lambda r: (r["source_id"], r["payload_time_key"]))

    # Task by provider and window-end UTC day. A task carries only the payloads
    # needed by its windows; midnight overlap is allowed but is counted explicitly.
    task_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for w in windows:
        day = _parse(w["window_end_utc"]).strftime("%Y-%m-%d")
        task_groups[(str(w["source_id"]), day)].append(w)

    payload_by_id = {r["payload_id"]: r for r in payload_rows}
    tasks: list[dict[str, Any]] = []
    payload_task_uses = 0
    for (source, day), ws in sorted(task_groups.items()):
        payload_ids = sorted({pid for w in ws for pid in window_to_payloads[str(w["window_id"])]})
        field_ids = sorted({fid for w in ws for fid in window_to_fields[str(w["window_id"])]})
        payload_task_uses += len(payload_ids)
        tasks.append({
            "task_id": _task_id(source, day),
            "source_id": source,
            "window_end_utc_day": day,
            "window_ids": sorted(str(w["window_id"]) for w in ws),
            "window_count": len(ws),
            "native_field_ids": field_ids,
            "native_field_count": len(field_ids),
            "payload_ids": payload_ids,
            "payload_count": len(payload_ids),
            "primary_subdivision_codes": sorted({str(w["primary_subdivision_code"]) for w in ws}),
            "risk_engine_allowed": False,
        })

    source_summary: list[dict[str, Any]] = []
    for source in sorted({w["source_id"] for w in windows}):
        p_fields = [r for r in field_rows if r["source_id"] == source]
        p_payloads = [r for r in payload_rows if r["source_id"] == source]
        p_tasks = [r for r in tasks if r["source_id"] == source]
        p_windows = [r for r in windows if r["source_id"] == source]
        source_summary.append({
            "source_id": source,
            "unique_window_count": len(p_windows),
            "unique_native_field_count": len(p_fields),
            "unique_payload_count": len(p_payloads),
            "production_task_count": len(p_tasks),
            "payload_task_use_count": sum(t["payload_count"] for t in p_tasks),
        })

    return {
        "schema_version": "0.1.0",
        "phase": "2I-development-rainfall-production-plan",
        "split": "DEVELOPMENT",
        "input_unique_window_count": len(windows),
        "unique_native_field_count": len(field_rows),
        "unique_payload_count": len(payload_rows),
        "production_task_count": len(tasks),
        "payload_task_use_count": payload_task_uses,
        "payload_deduplication_key": "SOURCE_ID_X_PROVIDER_NATIVE_PAYLOAD_TIME",
        "task_grouping": "SOURCE_ID_X_WINDOW_END_UTC_DAY",
        "native_fields": field_rows,
        "payloads": payload_rows,
        "tasks": tasks,
        "window_to_native_field_ids": window_to_fields,
        "window_to_payload_ids": window_to_payloads,
        "source_summary": source_summary,
        "temporal_resampling_performed": False,
        "cross_source_accumulation_performed": False,
        "validation_data_used": False,
        "retrospective_test_data_used": False,
        "prospective_holdout_data_used": False,
        "candidate_threshold_selected": False,
        "hard_negative_label": None,
        "risk_score": None,
        "risk_engine_allowed": False,
    }
