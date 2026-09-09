#!/usr/bin/env python3
"""Checkpointed authenticated ERA5 batch reconstruction pilot.

Downloads a small frozen slice of the ERA5 request manifest, scientifically
validates each payload immediately, writes compact JSON descriptors, and then
removes the temporary GRIB. Designed to prove restart-safe batch semantics
before expanding to all historical requests.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import cdsapi

from lpz_risk.era5_science import decode_era5_pressure_fields, validate_era5_required_fields, era5_environment_descriptors
from scripts.era5_authenticated_probe import CDS_URL, build_cds_request


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def request_key(index: int, row: dict) -> str:
    return f"{index:04d}_{row['date']}_{row['primary_subdivision_code']}"


def load_checkpoint(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "schema_version": "0.1.0",
        "phase": "2B-era5-batch-pilot",
        "created_at": utc_now_iso(),
        "requests": {},
        "risk_engine_allowed": False,
    }


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    checkpoint = load_checkpoint(summary_path)
    checkpoint["manifest_request_count"] = len(requests)
    checkpoint["selected_index_range"] = [a.start_index, stop - 1]
    checkpoint["source"] = "ERA5"
    checkpoint["exactness"] = "PROXY_REANALYSIS"

    client = cdsapi.Client(url=CDS_URL, key=key, quiet=False)

    for index in range(a.start_index, stop):
        row = requests[index]
        rkey = request_key(index, row)
        existing = checkpoint["requests"].get(rkey)
        if existing and existing.get("status") == "SUCCESS":
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
            cds_request = build_cds_request(row)
            grib_path.parent.mkdir(parents=True, exist_ok=True)
            client.retrieve(manifest["dataset"], cds_request, str(grib_path))
            size = grib_path.stat().st_size if grib_path.exists() else 0
            if size <= 0:
                raise RuntimeError("empty ERA5 GRIB payload")

            fields = decode_era5_pressure_fields(grib_path)
            validation = validate_era5_required_fields(fields)
            if not validation["required_fields_pass"]:
                raise ValueError(f"required ERA5 fields failed validation: {validation}")
            descriptor = {
                "schema_version": "0.1.0",
                "phase": "2B-era5-batch-pilot-request",
                "source": "ERA5",
                "exactness": "PROXY_REANALYSIS",
                "request_index": index,
                "request_key": rkey,
                "date": row["date"],
                "primary_subdivision_code": row["primary_subdivision_code"],
                "times_utc": row["times_utc"],
                "cds_area_north_west_south_east": row["cds_area_north_west_south_east"],
                "downloaded_bytes": size,
                "validation": validation,
                "environment_descriptors": era5_environment_descriptors(fields),
                "risk_engine_allowed": False,
            }
            save_json(descriptor_path, descriptor)
            record.update({
                "status": "SUCCESS",
                "completed_at": utc_now_iso(),
                "downloaded_bytes": size,
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
    checkpoint["completed_at"] = utc_now_iso()
    checkpoint["selected_request_count"] = len(selected)
    checkpoint["success_count"] = success_count
    checkpoint["failure_count"] = failure_count
    checkpoint["batch_gate"] = "PASS" if success_count == len(selected) else "FAIL"
    save_json(summary_path, checkpoint)
    print(json.dumps({
        "selected_request_count": len(selected),
        "success_count": success_count,
        "failure_count": failure_count,
        "batch_gate": checkpoint["batch_gate"],
        "summary": str(summary_path),
    }, ensure_ascii=False, indent=2))
    return 0 if failure_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
