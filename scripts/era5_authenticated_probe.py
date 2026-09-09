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
import requests

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


def _write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _classify_http_error(exc: requests.HTTPError) -> tuple[str, str]:
    text = str(exc)
    response_text = ""
    if getattr(exc, "response", None) is not None:
        try:
            response_text = exc.response.text or ""
        except Exception:
            response_text = ""
    combined = f"{text}\n{response_text}".lower()
    if "required licences not accepted" in combined or "licence" in combined and "not accepted" in combined:
        return "BLOCKED_PENDING_DATASET_LICENCE_ACCEPTANCE", "CDS credentials were presented, but required ERA5 dataset licence(s) are not yet accepted."
    if "401" in combined or "unauthorized" in combined or "invalid token" in combined or "invalid key" in combined:
        return "BLOCKED_INVALID_CDS_CREDENTIAL", "CDS rejected the supplied API credential."
    if "403" in combined or "forbidden" in combined:
        return "BLOCKED_CDS_FORBIDDEN_OTHER", "CDS returned HTTP 403 for a reason other than the recognized licence gate."
    return "BLOCKED_CDS_HTTP_ERROR", "CDS request failed with an HTTP error."


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", default="reports/historical/era5_request_manifest.json")
    p.add_argument("--request-index", type=int, default=0)
    p.add_argument("--output-grib", default="reports/historical/era5_probe.grib")
    p.add_argument("--output-report", default="reports/historical/era5_authenticated_probe.json")
    a = p.parse_args()

    key = os.environ.get("CDSAPI_KEY", "").strip()
    report_path = Path(a.output_report)
    if not key:
        _write_report(report_path, {
            "schema_version": "0.1.0",
            "phase": "2B-era5-authenticated-proof",
            "execution_ok": False,
            "gate": "BLOCKED_MISSING_CDS_CREDENTIAL",
            "credential_present": False,
            "credential_value_recorded": False,
            "risk_engine_allowed": False,
        })
        return 2

    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    requests_list = manifest.get("requests", [])
    if not requests_list:
        raise SystemExit("ERA5 manifest contains no requests")
    if not 0 <= a.request_index < len(requests_list):
        raise SystemExit(f"request index out of range: {a.request_index}")

    selected = requests_list[a.request_index]
    cds_request = build_cds_request(selected)
    output = Path(a.output_grib)
    output.parent.mkdir(parents=True, exist_ok=True)

    base_report = {
        "schema_version": "0.1.0",
        "phase": "2B-era5-authenticated-proof",
        "dataset": manifest["dataset"],
        "request_index": a.request_index,
        "date": selected["date"],
        "primary_subdivision_code": selected["primary_subdivision_code"],
        "times_utc": selected["times_utc"],
        "pressure_levels_hpa": selected["pressure_levels_hpa"],
        "variables": selected["variables"],
        "cds_area_north_west_south_east": selected["cds_area_north_west_south_east"],
        "credential_present": True,
        "credential_value_recorded": False,
        "scientific_decode_complete": False,
        "risk_engine_allowed": False,
    }

    client = cdsapi.Client(url=CDS_URL, key=key, quiet=False)
    try:
        client.retrieve(manifest["dataset"], cds_request, str(output))
    except requests.HTTPError as exc:
        gate, reason = _classify_http_error(exc)
        report = {
            **base_report,
            "execution_ok": False,
            "gate": gate,
            "reason": reason,
            "http_status": getattr(getattr(exc, "response", None), "status_code", None),
            "downloaded_bytes": 0,
        }
        _write_report(report_path, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 3
    except Exception as exc:
        report = {
            **base_report,
            "execution_ok": False,
            "gate": "BLOCKED_CDS_UNCLASSIFIED_ERROR",
            "reason": f"{type(exc).__name__}: {exc}",
            "downloaded_bytes": 0,
        }
        _write_report(report_path, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 4

    size = output.stat().st_size if output.exists() else 0
    if size <= 0:
        report = {
            **base_report,
            "execution_ok": False,
            "gate": "BLOCKED_EMPTY_ERA5_PAYLOAD",
            "downloaded_bytes": size,
        }
        _write_report(report_path, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 5

    report = {
        **base_report,
        "execution_ok": True,
        "gate": "ERA5_PAYLOAD_DOWNLOADED",
        "downloaded_bytes": size,
    }
    _write_report(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
