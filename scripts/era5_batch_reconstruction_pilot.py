#!/usr/bin/env python3
"""Checkpointed authenticated ERA5 batch reconstruction pilot."""

from __future__ import annotations

import argparse, json, os
from datetime import datetime, timezone
from pathlib import Path

import cdsapi

from lpz_risk.era5_science import decode_era5_pressure_fields, validate_era5_required_fields, era5_environment_descriptors

CDS_URL = "https://cds.climate.copernicus.eu/api"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def request_key(index, row):
    return f"{index:04d}_{row['date']}_{row['primary_subdivision_code']}"


def build_cds_request(row):
    year, month, day = row["date"].split("-")
    return {
        "product_type": ["reanalysis"],
        "variable": list(row["variables"]),
        "pressure_level": [str(x) for x in row["pressure_levels_hpa"]],
        "year": [year], "month": [month], "day": [day],
        "time": list(row["times_utc"]),
        "area": list(row["cds_area_north_west_south_east"]),
        "data_format": "grib",
    }


def save_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
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
        raise SystemExit("invalid start/count")
    stop = min(len(requests), a.start_index + a.count)

    outdir, summary_path = Path(a.output_dir), Path(a.summary)
    checkpoint = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {
        "schema_version": "0.1.0", "phase": "2B-era5-batch-pilot", "created_at": utc_now_iso(), "requests": {}, "risk_engine_allowed": False,
    }
    checkpoint.update({"manifest_request_count": len(requests), "selected_index_range": [a.start_index, stop - 1], "source": "ERA5", "exactness": "PROXY_REANALYSIS"})
    client = cdsapi.Client(url=CDS_URL, key=key, quiet=False)

    for index in range(a.start_index, stop):
        row = requests[index]; rkey = request_key(index, row)
        if checkpoint["requests"].get(rkey, {}).get("status") == "SUCCESS":
            continue
        grib = outdir / f"{rkey}.grib"; desc_path = outdir / f"{rkey}.json"
        rec = {"request_index": index, "request_key": rkey, "date": row["date"], "primary_subdivision_code": row["primary_subdivision_code"], "times_utc": row["times_utc"], "status": "RUNNING", "started_at": utc_now_iso(), "risk_engine_allowed": False}
        checkpoint["requests"][rkey] = rec; save_json(summary_path, checkpoint)
        try:
            grib.parent.mkdir(parents=True, exist_ok=True)
            client.retrieve(manifest["dataset"], build_cds_request(row), str(grib))
            size = grib.stat().st_size if grib.exists() else 0
            if size <= 0: raise RuntimeError("empty ERA5 GRIB payload")
            fields = decode_era5_pressure_fields(grib)
            validation = validate_era5_required_fields(fields)
            if not validation["required_fields_pass"]: raise ValueError(f"ERA5 validation failed: {validation}")
            descriptor = {"schema_version": "0.1.0", "phase": "2B-era5-batch-pilot-request", "source": "ERA5", "exactness": "PROXY_REANALYSIS", "request_index": index, "request_key": rkey, "date": row["date"], "primary_subdivision_code": row["primary_subdivision_code"], "times_utc": row["times_utc"], "cds_area_north_west_south_east": row["cds_area_north_west_south_east"], "downloaded_bytes": size, "validation": validation, "environment_descriptors": era5_environment_descriptors(fields), "risk_engine_allowed": False}
            save_json(desc_path, descriptor)
            rec.update({"status": "SUCCESS", "completed_at": utc_now_iso(), "downloaded_bytes": size, "descriptor_path": str(desc_path)})
        except Exception as exc:
            rec.update({"status": "FAIL", "completed_at": utc_now_iso(), "error": f"{type(exc).__name__}: {exc}"})
        finally:
            if grib.exists(): grib.unlink()
            checkpoint["requests"][rkey] = rec; save_json(summary_path, checkpoint)

    selected = [checkpoint["requests"].get(request_key(i, requests[i]), {}) for i in range(a.start_index, stop)]
    success = sum(x.get("status") == "SUCCESS" for x in selected); failure = sum(x.get("status") == "FAIL" for x in selected)
    checkpoint.update({"completed_at": utc_now_iso(), "selected_request_count": len(selected), "success_count": success, "failure_count": failure, "batch_gate": "PASS" if success == len(selected) else "FAIL"})
    save_json(summary_path, checkpoint)
    print(json.dumps({"selected_request_count": len(selected), "success_count": success, "failure_count": failure, "batch_gate": checkpoint["batch_gate"], "summary": str(summary_path)}, ensure_ascii=False, indent=2))
    return 0 if failure == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
