"""Join validated ERA5 request descriptors back to positive-anchor snapshots.

Recent ERA5/ERA5T source latency is treated as a source-availability state, not
as scientific data loss. This module therefore distinguishes:

- available_window_complete: every snapshot whose ERA5 source time is currently
  available has a validated descriptor;
- historical_environment_reconstruction_complete: every requested snapshot,
  including the recent source-lag tail, has been reconstructed.

Risk scoring remains disabled in both cases.
"""

from __future__ import annotations

from typing import Any


def _time_key(code: str, source_time: str) -> tuple[str, str]:
    return str(code), str(source_time)


def build_era5_snapshot_feature_table(
    manifest: dict[str, Any],
    request_descriptors: list[dict[str, Any]],
    *,
    pending_source_availability_indices: list[int] | None = None,
    pending_source_availability_reasons: dict[int, str] | None = None,
) -> dict[str, Any]:
    if not manifest.get("execution_ok", True):
        raise ValueError("ERA5 request manifest is not successful")

    pending_indices = {int(x) for x in (pending_source_availability_indices or [])}
    pending_reasons = {int(k): str(v) for k, v in (pending_source_availability_reasons or {}).items()}
    expected_request_count = int(manifest.get("date_subdivision_request_count", 0))
    requests = list(manifest.get("requests", []))
    if expected_request_count != len(requests):
        raise ValueError("ERA5 manifest request count mismatch")
    if any(index < 0 or index >= expected_request_count for index in pending_indices):
        raise ValueError(f"pending source-availability request index out of range: {sorted(pending_indices)}")

    descriptor_by_index: dict[int, dict[str, Any]] = {}
    time_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    duplicate_time_keys: list[str] = []

    for descriptor in request_descriptors:
        if descriptor.get("phase") != "2B-era5-batch-request":
            continue
        index = int(descriptor["request_index"])
        if index in descriptor_by_index:
            raise ValueError(f"duplicate request descriptor index: {index}")
        if not descriptor.get("multitime_validation", {}).get("multitime_payload_pass"):
            raise ValueError(f"request {index} did not pass multi-time validation")
        descriptor_by_index[index] = descriptor
        code = str(descriptor["primary_subdivision_code"])
        for row in descriptor.get("time_descriptors", []):
            source_time = str(row["era5_source_time_utc"])
            key = _time_key(code, source_time)
            if key in time_lookup:
                duplicate_time_keys.append(f"{code}|{source_time}")
            time_lookup[key] = {
                "request_index": index,
                "request_key": descriptor["request_key"],
                "downloaded_bytes": descriptor.get("downloaded_bytes"),
                "cds_area_north_west_south_east": descriptor.get("cds_area_north_west_south_east"),
                **row,
            }

    if duplicate_time_keys:
        raise ValueError(f"duplicate region/time ERA5 descriptors: {duplicate_time_keys[:10]}")

    expected_indices = set(range(expected_request_count))
    missing_request_indices = sorted(expected_indices - set(descriptor_by_index))
    hard_missing_request_indices = sorted(set(missing_request_indices) - pending_indices)
    unexpected_pending_with_descriptor = sorted(pending_indices & set(descriptor_by_index))
    if unexpected_pending_with_descriptor:
        raise ValueError(f"pending indices unexpectedly have descriptors: {unexpected_pending_with_descriptor}")

    pending_time_keys: set[tuple[str, str]] = set()
    pending_request_records: list[dict[str, Any]] = []
    for index in sorted(pending_indices):
        request = requests[index]
        code = str(request["primary_subdivision_code"])
        date = str(request["date"])
        for hhmm in request.get("times_utc", []):
            pending_time_keys.add(_time_key(code, f"{date}T{hhmm}:00Z"))
        pending_request_records.append({
            "request_index": index,
            "date": date,
            "primary_subdivision_code": code,
            "times_utc": list(request.get("times_utc", [])),
            "reason": pending_reasons.get(index, "ERA5 source data not yet available"),
        })

    snapshot_rows: list[dict[str, Any]] = []
    hard_missing_snapshot_keys: list[str] = []
    pending_snapshot_keys: list[str] = []

    for mapping in manifest.get("snapshot_mappings", []):
        code = str(mapping["primary_subdivision_code"])
        source_time = str(mapping["era5_source_time_utc"])
        key = _time_key(code, source_time)
        source = time_lookup.get(key)
        snapshot_key = f"{mapping['anchor_id']}|{mapping['snapshot_offset_minutes']}|{code}|{source_time}"
        if source is None:
            if key in pending_time_keys:
                pending_snapshot_keys.append(snapshot_key)
            else:
                hard_missing_snapshot_keys.append(snapshot_key)
            continue
        env = source["environment_descriptors"]
        q = env["specific_humidity_mean_kgkg"]
        snapshot_rows.append({
            "anchor_id": mapping["anchor_id"],
            "primary_subdivision_code": code,
            "snapshot_offset_minutes": int(mapping["snapshot_offset_minutes"]),
            "requested_snapshot_time_utc": mapping["requested_snapshot_time_utc"],
            "era5_source_time_utc": source_time,
            "source_lag_minutes": int(mapping["source_lag_minutes"]),
            "future_source_time_used": bool(mapping["future_source_time_used"]),
            "source": "ERA5",
            "exactness": "PROXY_REANALYSIS",
            "request_index": int(source["request_index"]),
            "request_key": source["request_key"],
            "rh500_mean_pct": env["rh500_mean_pct"],
            "rh700_mean_pct": env["rh700_mean_pct"],
            "rh500_rh700_gt60_fraction": env["rh500_rh700_gt60_fraction"],
            "wind600_speed_mean_mps": env["wind600_speed_mean_mps"],
            "wind600_from_direction_median_deg": env["wind600_from_direction_median_deg"],
            "wind850_speed_mean_mps": env["wind850_speed_mean_mps"],
            "wind850_from_direction_median_deg": env["wind850_from_direction_median_deg"],
            "q1000_mean_kgkg": q["1000"],
            "q925_mean_kgkg": q["925"],
            "q850_mean_kgkg": q["850"],
            "spatial_semantics": env["spatial_semantics"],
            "risk_score": None,
        })

    expected_snapshot_count = int(manifest.get("snapshot_mapping_count", 0))
    snapshot_rows.sort(key=lambda r: (r["anchor_id"], r["snapshot_offset_minutes"]))
    future_count = sum(bool(row["future_source_time_used"]) for row in snapshot_rows)
    accounted_snapshot_count = len(snapshot_rows) + len(pending_snapshot_keys) + len(hard_missing_snapshot_keys)
    if accounted_snapshot_count != expected_snapshot_count:
        raise ValueError(
            f"snapshot accounting mismatch: {accounted_snapshot_count} != {expected_snapshot_count}"
        )

    available_window_complete = (
        not hard_missing_request_indices
        and not hard_missing_snapshot_keys
        and future_count == 0
    )
    complete = (
        available_window_complete
        and not pending_indices
        and len(snapshot_rows) == expected_snapshot_count
    )

    return {
        "schema_version": "0.2.0",
        "phase": "2B-era5-positive-snapshot-feature-table",
        "source": "ERA5",
        "exactness": "PROXY_REANALYSIS",
        "expected_request_count": expected_request_count,
        "request_descriptor_count": len(descriptor_by_index),
        "missing_request_indices": missing_request_indices,
        "hard_missing_request_indices": hard_missing_request_indices,
        "pending_source_availability_request_count": len(pending_indices),
        "pending_source_availability_request_indices": sorted(pending_indices),
        "pending_source_availability_requests": pending_request_records,
        "region_time_descriptor_count": len(time_lookup),
        "expected_snapshot_count": expected_snapshot_count,
        "snapshot_feature_row_count": len(snapshot_rows),
        "pending_source_availability_snapshot_count": len(pending_snapshot_keys),
        "pending_source_availability_snapshot_keys": pending_snapshot_keys[:100],
        "hard_missing_snapshot_key_count": len(hard_missing_snapshot_keys),
        "hard_missing_snapshot_keys": hard_missing_snapshot_keys[:100],
        "future_source_time_count": future_count,
        "available_window_complete": available_window_complete,
        "historical_environment_reconstruction_complete": complete,
        "source_availability_tail_open": bool(pending_indices),
        "snapshot_features": snapshot_rows,
        "risk_engine_allowed": False,
    }
