"""Historical environmental reconstruction planning.

This module is intentionally conservative. It does not download ERA5 by itself.
It converts normalized positive/negative snapshot times into de-duplicated ERA5
source times and a reproducible request manifest while preventing future-time
source leakage.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timezone-aware UTC timestamp required: {value!r}")
    return dt.astimezone(UTC)


def floor_to_hour(snapshot_time_utc: str) -> dict[str, Any]:
    """Map a requested snapshot to the latest ERA5 whole hour not after it."""
    requested = _parse_utc(snapshot_time_utc)
    source = requested.replace(minute=0, second=0, microsecond=0)
    lag_minutes = int((requested - source).total_seconds() // 60)
    if source > requested:
        raise AssertionError("future ERA5 time selected")
    if not 0 <= lag_minutes <= 59:
        raise AssertionError(f"unexpected ERA5 source lag: {lag_minutes}")
    return {
        "requested_snapshot_time_utc": requested.isoformat().replace("+00:00", "Z"),
        "era5_source_time_utc": source.isoformat().replace("+00:00", "Z"),
        "source_lag_minutes": lag_minutes,
        "future_source_time_used": False,
        "time_alignment": "FLOOR_TO_AVAILABLE_HOUR",
    }


def build_anchor_snapshot_map(positive_registry: dict[str, Any]) -> list[dict[str, Any]]:
    if not positive_registry.get("execution_ok", True):
        raise ValueError("positive registry is not successful")
    anchors = positive_registry.get("realized_positive_anchors")
    if anchors is None:
        raise ValueError("realized_positive_anchors missing")

    rows: list[dict[str, Any]] = []
    for anchor in anchors:
        times = list(anchor.get("snapshot_times_utc") or [])
        offsets = list(anchor.get("snapshot_offsets_minutes") or [])
        if len(times) != len(offsets):
            raise ValueError(f"snapshot length mismatch for {anchor.get('anchor_id')}")
        for offset, snapshot_time in zip(offsets, times):
            aligned = floor_to_hour(snapshot_time)
            rows.append({
                "anchor_id": anchor["anchor_id"],
                "primary_subdivision_code": anchor["primary_subdivision_code"],
                "snapshot_offset_minutes": int(offset),
                **aligned,
            })
    rows.sort(key=lambda r: (r["era5_source_time_utc"], r["anchor_id"], r["snapshot_offset_minutes"]))
    return rows


def build_era5_request_manifest(
    positive_registry: dict[str, Any],
    era5_config: dict[str, Any],
) -> dict[str, Any]:
    rows = build_anchor_snapshot_map(positive_registry)
    grouped: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        dt = _parse_utc(row["era5_source_time_utc"])
        grouped[dt.strftime("%Y-%m-%d")].add(dt.strftime("%H:00"))

    requests = [
        {
            "date": date,
            "times_utc": sorted(times),
            "pressure_levels_hpa": list(era5_config["pressure_levels_hpa"]),
            "variables": list(era5_config["variables"]),
            "spatial_subset_status": era5_config["spatial_sampling"]["status"],
            "download_allowed": False,
            "block_reason": "Validated JMA primary-subdivision geometry / event ROI has not yet been attached.",
        }
        for date, times in sorted(grouped.items())
    ]

    unique_source_times = sorted({row["era5_source_time_utc"] for row in rows})
    max_lag = max((row["source_lag_minutes"] for row in rows), default=0)
    return {
        "schema_version": "0.1.0",
        "phase": "2B-era5-request-manifest",
        "provider": era5_config["provider"],
        "dataset": era5_config["dataset"],
        "snapshot_mapping_count": len(rows),
        "unique_era5_source_time_count": len(unique_source_times),
        "request_day_count": len(requests),
        "maximum_source_lag_minutes": max_lag,
        "future_source_time_count": sum(bool(row["future_source_time_used"]) for row in rows),
        "snapshot_mappings": rows,
        "requests": requests,
        "spatial_sampling_gate": era5_config["spatial_sampling"]["status"],
        "authenticated_download_gate": "BLOCKED_PENDING_SPATIAL_GEOMETRY_AND_CDS_CREDENTIAL",
        "historical_environment_reconstruction_complete": False,
        "risk_engine_allowed": False,
    }
