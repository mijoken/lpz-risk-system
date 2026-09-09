#!/usr/bin/env python3
"""Checkpointed authenticated ERA5 batch reconstruction.

Downloads a frozen slice of the ERA5 request manifest, preserves every valid
hour inside each GRIB payload, scientifically validates each valid time, writes
compact JSON descriptors, and removes the temporary GRIB. Designed for both
small pilots and chunked full reconstruction.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import cdsapi

from lpz_risk.era5_multitime import (
    build_time_descriptors,
    decode_era5_pressure_fields_by_time,
    validate_era5_multitime_payload,
)

CDS_URL = "https://cds.climate.copernicus.eu/api"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def request_key(index: int, row: dict) -> str:
    return f"{index:04d}_{row['date']}_{row['primary_subdivision_code']}"


def build_cds_request(row: dict) -> dict:
    year, month, day = row["date"].split("-")
    return {
        "product_type": ["reanalysis"],
        "variable": list(row["variables"]),
        "pressure_level": [str(x) for x in row["pressure_levels_hpa"]],
        "year": [year],
        "month": [month],
        "day": [day],
        "time": list(row["times_utc"]),
        "area": list(row["cds_area_north_west_south_east"]),
        "data_format": "grib",
    }


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def expected_valid_times(row: dict) -> list[str]:
    return [f"{row['date']}T{hhmm}:00Z" for hhmm in row["times_utc"]]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", default="reports/historical/era5_request_manifest.json")
    p.add_argument("--start-index", type=int, default=0)
    p.add_argument("--count", type=int, default=3)
    p.add_argument("--output-dir", default="reports/historical/era5_batch_pilot")
    p.add_argument("--summary", default="reports/historical/era5_batch_pilot_summary.json")
    a = p.parse_args()

    key = os.environ.get("CDSAPI_KEY", "").strip()
    if not key:
        raise SystemExit("CDSAPI_KEY is required")

    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    requests = manifest.get("requests", [])
    if a.start_index < 0 or a.count < 1 or a.start_index >= len(requests):
        raise SystemExit("invalid start/count for manifest")
    stop = min(len(requests), a.start_index + a.count)

    output_dir = Path(a.output_dir)
    summary_path = Path(a.summary)
    checkpoint = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {
        "schema_version": "0.2.0",
        "phase": "2B-era5-batch-reconstruction",
        "created_at": utc_now_iso(),
        "requests": {},
        "risk_engine_allowed": False,
    }
    checkpoint.update({
        "manifest_request_count": len(requests),
        "selected_index_range": [a.start_index, stop - 1],
        "source": "ERA5",
        "exactness": "PROXY_REANALYSIS",
        "time_preservation": "VALID_TIME_FIRST_CLASS_KEY",
    })
    client = cdsapi.Client(url=CDS_URL, key=key, quiet=False)

    for index in range(a.start_index, stop):
        row = requests[index]
        rkey = request_key(index, row)
        if checkpoint["requests"].get(rkey, {}).get("status") == "SUCCESS":
            continue

        grib_path = output_dir / f"{rkey}.grib"
        descriptor_path = output_dir / f"{rkey}.json"
        record = {
            "request_index": index,
            "request_key": rkey,
            "date": row["date"],
            "primary_subdivision_code": row["primary_subdivision_code"],
            "times_utc": row["times_utc"],
            "status": "RUNNING",
            "started_at": utc_now_iso(),
            "risk_engine_allowed": False,
        }
        checkpoint["requests"][rkey] = record
        save_json(summary_path, checkpoint)

        try:
            grib_path.parent.mkdir(parents=True, exist_ok=True)
            client.retrieve(manifest["dataset"], build_cds_request(row), str(grib_path))
            size = grib_path.stat().st_size if grib_path.exists() else 0
            if size <= 0:
                raise RuntimeError("empty ERA5 GRIB payload")

            fields_by_time = decode_era5_pressure_fields_by_time(grib_path)
            expected = expected_valid_times(row)
            multitime_validation = validate_era5_multitime_payload(fields_by_time, expected)
            if not multitime_validation["multitime_payload_pass"]:
                raise ValueError(f"ERA5 multi-time validation failed: {multitime_validation}")
            time_descriptors = build_time_descriptors(fields_by_time)
            descriptor = {
                "schema_version": "0.2.0",
                "phase": "2B-era5-batch-request",
                "source": "ERA5",
                "exactness": "PROXY_REANALYSIS",
                "request_index": index,
                "request_key": rkey,
                "date": row["date"],
                "primary_subdivision_code": row["primary_subdivision_code"],
                "times_utc": row["times_utc"],
                "cds_area_north_west_south_east": row["cds_area_north_west_south_east"],
                "downloaded_bytes": size,
                "multitime_validation": multitime_validation,
                "time_descriptors": time_descriptors,
                "risk_engine_allowed": False,
            }
            save_json(descriptor_path, descriptor)
            record.update({
                "status": "SUCCESS",
                "completed_at": utc_now_iso(),
                "downloaded_bytes": size,
                "decoded_valid_time_count": len(time_descriptors),
                "descriptor_path": str(descriptor_path),
            })
        except Exception as exc:
            record.update({
                "status": "FAIL",
                "completed_at": utc_now_iso(),
                "error": f"{type(exc).__name__}: {exc}",
            })
        finally:
            if grib_path.exists():
                grib_path.unlink()
            checkpoint["requests"][rkey] = record
            save_json(summary_path, checkpoint)

    selected = [checkpoint["requests"].get(request_key(i, requests[i]), {}) for i in range(a.start_index, stop)]
    success_count = sum(x.get("status") == "SUCCESS" for x in selected)
    failure_count = sum(x.get("status") == "FAIL" for x in selected)
    decoded_time_count = sum(int(x.get("decoded_valid_time_count", 0)) for x in selected)
    checkpoint.update({
        "completed_at": utc_now_iso(),
        "selected_request_count": len(selected),
        "success_count": success_count,
        "failure_count": failure_count,
        "decoded_valid_time_count": decoded_time_count,
        "batch_gate": "PASS" if success_count == len(selected) else "FAIL",
    })
    save_json(summary_path, checkpoint)
    print(json.dumps({
        "selected_request_count": len(selected),
        "success_count": success_count,
        "failure_count": failure_count,
        "decoded_valid_time_count": decoded_time_count,
        "batch_gate": checkpoint["batch_gate"],
        "summary": str(summary_path),
    }, ensure_ascii=False, indent=2))
    return 0 if failure_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
