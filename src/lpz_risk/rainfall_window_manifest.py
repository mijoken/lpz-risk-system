"""Build de-duplicated source-native 3-hour rainfall request windows.

The manifest is anchored only to records already assigned to the frozen
DEVELOPMENT split. For each provider, the window end is the latest completed
native interval boundary at or before the JMA analysis time. This guarantees no
future precipitation interval is used and avoids temporal resampling.

Multiple 10-minute JMA detections that map to the same subdivision/provider/window
are collapsed into one request while preserving every anchor/local-episode ID.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

_PROVIDER_INTERVAL_SECONDS = {
    "GSMAP_STANDARD_V8_HISTORICAL": 3600,
    "NASA_IMERG_FINAL_V07": 1800,
    "NOAA_CMORPH_CDR": 1800,
}
TARGET_SECONDS = 10_800


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return dt.astimezone(timezone.utc)


def _floor_epoch(dt: datetime, interval_seconds: int) -> datetime:
    epoch = int(dt.timestamp())
    floored = epoch - (epoch % interval_seconds)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def _stable_window_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "RAIN3H-" + hashlib.sha256(raw).hexdigest()[:16]


def build_development_rainfall_window_manifest(
    positive_episode_registry: dict[str, Any],
    *,
    providers: tuple[str, ...] = tuple(_PROVIDER_INTERVAL_SECONDS),
) -> dict[str, Any]:
    unknown = [p for p in providers if p not in _PROVIDER_INTERVAL_SECONDS]
    if unknown:
        raise ValueError(f"unsupported providers: {unknown}")
    if not providers:
        raise ValueError("at least one provider is required")

    assignments = list(positive_episode_registry.get("anchor_episode_assignments") or [])
    development = [r for r in assignments if str(r.get("temporal_split")) == "DEVELOPMENT"]
    if not development:
        raise ValueError("no DEVELOPMENT anchor assignments found")

    # Key by source/subdivision/native window. A single request can serve many
    # repeated JMA detections from one or more local episodes in the same region.
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    anchor_mapping_rows: list[dict[str, Any]] = []

    for row in development:
        anchor_time = _parse_utc(row["analysis_time_utc"])
        code = str(row["primary_subdivision_code"])
        anchor_id = str(row["anchor_id"])
        episode_id = str(row["local_episode_id"])
        for provider in providers:
            interval = _PROVIDER_INTERVAL_SECONDS[provider]
            window_end = _floor_epoch(anchor_time, interval)
            window_start = window_end - timedelta(seconds=TARGET_SECONDS)
            lag_seconds = int((anchor_time - window_end).total_seconds())
            if lag_seconds < 0 or lag_seconds >= interval:
                raise AssertionError("invalid source-native window lag")
            if window_end > anchor_time:
                raise AssertionError("future rainfall interval boundary selected")
            native_field_count = TARGET_SECONDS // interval
            if native_field_count * interval != TARGET_SECONDS:
                raise AssertionError("target duration is not divisible by native interval")

            start_iso = window_start.isoformat().replace("+00:00", "Z")
            end_iso = window_end.isoformat().replace("+00:00", "Z")
            key = (provider, code, start_iso, end_iso)
            if key not in grouped:
                identity = {
                    "source_id": provider,
                    "primary_subdivision_code": code,
                    "window_start_utc": start_iso,
                    "window_end_utc": end_iso,
                }
                grouped[key] = {
                    "window_id": _stable_window_id(identity),
                    **identity,
                    "target_accumulation_seconds": TARGET_SECONDS,
                    "native_interval_seconds": interval,
                    "native_field_count": native_field_count,
                    "anchor_ids": [],
                    "local_episode_ids": [],
                    "anchor_source_lag_seconds": [],
                    "source_native_only": True,
                    "future_interval_used": False,
                    "candidate_threshold_selected": False,
                    "risk_engine_allowed": False,
                }
            target = grouped[key]
            target["anchor_ids"].append(anchor_id)
            target["local_episode_ids"].append(episode_id)
            target["anchor_source_lag_seconds"].append(lag_seconds)
            anchor_mapping_rows.append({
                "anchor_id": anchor_id,
                "local_episode_id": episode_id,
                "primary_subdivision_code": code,
                "analysis_time_utc": anchor_time.isoformat().replace("+00:00", "Z"),
                "source_id": provider,
                "window_id": target["window_id"],
                "source_native_window_end_utc": end_iso,
                "source_lag_seconds": lag_seconds,
                "future_interval_used": False,
            })

    windows: list[dict[str, Any]] = []
    for row in grouped.values():
        row["anchor_ids"] = sorted(set(row["anchor_ids"]))
        row["local_episode_ids"] = sorted(set(row["local_episode_ids"]))
        lags = row.pop("anchor_source_lag_seconds")
        row["anchor_count"] = len(row["anchor_ids"])
        row["local_episode_count"] = len(row["local_episode_ids"])
        row["minimum_source_lag_seconds"] = min(lags)
        row["maximum_source_lag_seconds"] = max(lags)
        windows.append(row)
    windows.sort(key=lambda r: (r["source_id"], r["window_start_utc"], r["primary_subdivision_code"], r["window_id"]))
    anchor_mapping_rows.sort(key=lambda r: (r["analysis_time_utc"], r["source_id"], r["anchor_id"]))

    expected_mapping_count = len(development) * len(providers)
    if len(anchor_mapping_rows) != expected_mapping_count:
        raise AssertionError("not every DEVELOPMENT anchor mapped exactly once per provider")
    if any(r["future_interval_used"] for r in anchor_mapping_rows):
        raise AssertionError("future rainfall interval entered manifest")

    source_summary: list[dict[str, Any]] = []
    for provider in providers:
        p_windows = [w for w in windows if w["source_id"] == provider]
        p_maps = [m for m in anchor_mapping_rows if m["source_id"] == provider]
        source_summary.append({
            "source_id": provider,
            "native_interval_seconds": _PROVIDER_INTERVAL_SECONDS[provider],
            "native_field_count_per_three_hour_window": TARGET_SECONDS // _PROVIDER_INTERVAL_SECONDS[provider],
            "development_anchor_mapping_count": len(p_maps),
            "unique_request_window_count": len(p_windows),
            "maximum_source_lag_seconds": max(m["source_lag_seconds"] for m in p_maps),
            "future_interval_count": sum(bool(m["future_interval_used"]) for m in p_maps),
        })

    return {
        "schema_version": "0.1.0",
        "phase": "2H-development-source-native-rainfall-window-manifest",
        "split": "DEVELOPMENT",
        "target_accumulation_seconds": TARGET_SECONDS,
        "development_anchor_count": len(development),
        "provider_count": len(providers),
        "anchor_provider_mapping_count": len(anchor_mapping_rows),
        "unique_request_window_count": len(windows),
        "deduplication_key": "SOURCE_ID_X_PRIMARY_SUBDIVISION_X_WINDOW_START_X_WINDOW_END",
        "window_end_policy": "LATEST_COMPLETED_NATIVE_INTERVAL_BOUNDARY_AT_OR_BEFORE_ANCHOR",
        "temporal_resampling_performed": False,
        "cross_source_accumulation_performed": False,
        "future_interval_count": 0,
        "source_summary": source_summary,
        "windows": windows,
        "anchor_window_mappings": anchor_mapping_rows,
        "candidate_threshold_selected": False,
        "validation_data_used": False,
        "retrospective_test_data_used": False,
        "prospective_holdout_data_used": False,
        "hard_negative_label": None,
        "risk_score": None,
        "risk_engine_allowed": False,
    }
