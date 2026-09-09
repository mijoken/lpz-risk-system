#!/usr/bin/env python3
"""Download exactly one ERA5 request from the frozen historical manifest.

This is an explicit manual proof only. It requires CDSAPI_KEY and never runs in
ordinary scheduled CI. No credential is written to disk or reports.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import cdsapi

CDS_URL = "https://cds.climate.copernicus.eu/api"


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


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", default="reports/historical/era5_request_manifest.json")
    p.add_argument("--request-index", type=int, default=0)
    p.add_argument("--output-grib", default="reports/historical/era5_probe.grib")
    p.add_argument("--output-report", default="reports/historical/era5_authenticated_probe.json")
    a = p.parse_args()

    key = os.environ.get("CDSAPI_KEY", "").strip()
    if not key:
        raise SystemExit("CDSAPI_KEY is required for this manual proof")

    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    requests = manifest.get("requests", [])
    if not requests:
        raise SystemExit("ERA5 manifest contains no requests")
    if not 0 <= a.request_index < len(requests):
        raise SystemExit(f"request index out of range: {a.request_index}")

    selected = requests[a.request_index]
    cds_request = build_cds_request(selected)
    output = Path(a.output_grib)
    output.parent.mkdir(parents=True, exist_ok=True)

    client = cdsapi.Client(url=CDS_URL, key=key, quiet=False)
    client.retrieve(manifest["dataset"], cds_request, str(output))
    size = output.stat().st_size if output.exists() else 0
    if size <= 0:
        raise RuntimeError("CDS request completed without a non-empty GRIB file")

    report = {
        "schema_version": "0.1.0",
        "phase": "2B-era5-authenticated-proof",
        "execution_ok": True,
        "dataset": manifest["dataset"],
        "request_index": a.request_index,
        "date": selected["date"],
        "primary_subdivision_code": selected["primary_subdivision_code"],
        "times_utc": selected["times_utc"],
        "pressure_levels_hpa": selected["pressure_levels_hpa"],
        "variables": selected["variables"],
        "cds_area_north_west_south_east": selected["cds_area_north_west_south_east"],
        "downloaded_bytes": size,
        "credential_present": True,
        "credential_value_recorded": False,
        "scientific_decode_complete": False,
        "risk_engine_allowed": False,
    }
    report_path = Path(a.output_report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
