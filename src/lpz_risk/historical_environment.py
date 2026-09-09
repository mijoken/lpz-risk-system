"""Historical environmental reconstruction planning.

This module converts normalized LPZ snapshot times into reproducible ERA5
requests while enforcing two leakage guards:

1. source time is always the latest whole ERA5 hour <= requested snapshot;
2. spatial retrieval is tied to the official JMA primary-subdivision bbox,
   never an invented prefectural or hand-written centroid.

Actual CDS retrieval remains a separate authenticated step.
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
    rows.sort(key=lambda r: (r["era5_source_time_utc"], r["primary_subdivision_code"], r["anchor_id"], r["snapshot_offset_minutes"]))
    return rows


def _geometry_map(geometry_registry: dict[str, Any]) -> dict[str, list[float]]:
    if not geometry_registry.get("geometry_complete_for_required_codes"):
        raise ValueError("official primary-subdivision geometry registry is incomplete")
    result: dict[str, list[float]] = {}
    for region in geometry_registry.get("regions", []):
        code = str(region["primary_subdivision_code"])
        bbox = [float(x) for x in region["bbox"]]
        if len(bbox) != 4:
            raise ValueError(f"invalid bbox for {code}: {bbox}")
        result[code] = bbox
    if not result:
        raise ValueError("geometry registry contained no regions")
    return result


def _pad_bbox(bbox: list[float], padding: float) -> list[float]:
    west, south, east, north = bbox
    west = max(-180.0, west - padding)
    south = max(-90.0, south - padding)
    east = min(180.0, east + padding)
    north = min(90.0, north + padding)
    if west >= east or south >= north:
        raise ValueError(f"invalid padded bbox: {[west, south, east, north]}")
    return [west, south, east, north]


def build_era5_request_manifest(
    positive_registry: dict[str, Any],
    era5_config: dict[str, Any],
    geometry_registry: dict[str, Any],
) -> dict[str, Any]:
    rows = build_anchor_snapshot_map(positive_registry)
    geometry = _geometry_map(geometry_registry)
    padding = float(era5_config["spatial_sampling"].get("bbox_padding_degrees", 0.0))

    missing_codes = sorted({row["primary_subdivision_code"] for row in rows} - set(geometry))
    if missing_codes:
        raise ValueError(f"snapshot codes missing from official geometry registry: {missing_codes}")

    # Group by UTC source date AND official JMA primary subdivision. This avoids
    # a wasteful Japan-wide union bbox on days when distant regions have events.
    grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        dt = _parse_utc(row["era5_source_time_utc"])
        grouped[(dt.strftime("%Y-%m-%d"), row["primary_subdivision_code"])].add(dt.strftime("%H:00"))

    requests: list[dict[str, Any]] = []
    for (date, code), times in sorted(grouped.items()):
        raw_bbox = geometry[code]
        west, south, east, north = _pad_bbox(raw_bbox, padding)
        requests.append({
            "date": date,
            "primary_subdivision_code": code,
            "times_utc": sorted(times),
            "pressure_levels_hpa": list(era5_config["pressure_levels_hpa"]),
            "variables": list(era5_config["variables"]),
            "source_bbox_west_south_east_north": raw_bbox,
            "padded_bbox_west_south_east_north": [west, south, east, north],
            "cds_area_north_west_south_east": [north, west, south, east],
            "bbox_padding_degrees": padding,
            "spatial_subset_status": era5_config["spatial_sampling"]["status"],
            "download_allowed_in_ordinary_ci": False,
            "download_block_reason": "Ordinary CI is dry-run only; authenticated CDS retrieval requires a configured CDS API key.",
        })

    unique_source_times = sorted({row["era5_source_time_utc"] for row in rows})
    unique_dates = sorted({_parse_utc(t).strftime("%Y-%m-%d") for t in unique_source_times})
    max_lag = max((row["source_lag_minutes"] for row in rows), default=0)
    request_time_counts = [len(r["times_utc"]) for r in requests]

    return {
        "schema_version": "0.2.0",
        "phase": "2B-era5-request-manifest",
        "provider": era5_config["provider"],
        "dataset": era5_config["dataset"],
        "snapshot_mapping_count": len(rows),
        "unique_era5_source_time_count": len(unique_source_times),
        "request_day_count": len(unique_dates),
        "date_subdivision_request_count": len(requests),
        "unique_primary_subdivision_count": len({r["primary_subdivision_code"] for r in requests}),
        "maximum_source_lag_minutes": max_lag,
        "future_source_time_count": sum(bool(row["future_source_time_used"]) for row in rows),
        "maximum_times_per_request": max(request_time_counts, default=0),
        "mean_times_per_request": (sum(request_time_counts) / len(request_time_counts)) if request_time_counts else 0.0,
        "snapshot_mappings": rows,
        "requests": requests,
        "spatial_sampling_gate": era5_config["spatial_sampling"]["status"],
        "geometry_missing_code_count": len(missing_codes),
        "authenticated_download_gate": "BLOCKED_PENDING_CDS_CREDENTIAL",
        "historical_environment_reconstruction_complete": False,
        "risk_engine_allowed": False,
    }
