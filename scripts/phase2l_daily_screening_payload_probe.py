#!/usr/bin/env python3
"""Probe IMERG Final V07 daily and CMORPH daily payload structure for Phase 2L.

No threshold selection, candidate labeling, or risk scoring is performed.
CMORPH is read from the official NOAA public S3 daily 0.25-degree archive.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

CMORPH_S3_HTTPS = "https://noaa-cdr-precip-cmorph-pds.s3.amazonaws.com"
USER_AGENT = "lpz-risk-system/0.1 research"


def _jsonable(v):
    try:
        return v.item()
    except Exception:
        return str(v)


def _inspect_netcdf(path: Path) -> dict:
    from netCDF4 import Dataset
    out = {"path": path.name, "variables": {}, "dimensions": {}}
    with Dataset(path) as ds:
        out["dimensions"] = {k: len(v) for k, v in ds.dimensions.items()}
        for name, var in ds.variables.items():
            out["variables"][name] = {
                "dimensions": list(var.dimensions),
                "shape": list(var.shape),
                "dtype": str(var.dtype),
                "units": getattr(var, "units", None),
                "standard_name": getattr(var, "standard_name", None),
                "long_name": getattr(var, "long_name", None),
                "fill_value": _jsonable(getattr(var, "_FillValue", None)),
            }
    return out


def _read_url(url: str, timeout: int = 180) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as response:
        payload = response.read()
    if len(payload) < 1024:
        raise ValueError(f"payload unexpectedly small: {url} {len(payload)} bytes")
    return payload


def _probe_imerg(date: str, work: Path) -> dict:
    import earthaccess
    dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    earthaccess.login(strategy="environment")
    granules = earthaccess.search_data(
        short_name="GPM_3IMERGDF",
        version="07",
        bounding_box=(122.0, 24.0, 150.0, 47.0),
        temporal=(dt.isoformat(), dt.replace(hour=23, minute=59, second=59).isoformat()),
        count=5,
    )
    if len(granules) != 1:
        raise RuntimeError(f"expected exactly one IMERG daily granule, got {len(granules)}")
    dest = work / "imerg"
    dest.mkdir(parents=True, exist_ok=True)
    paths = earthaccess.download(granules, str(dest), threads=1)
    if len(paths) != 1:
        raise RuntimeError(f"IMERG daily download count mismatch: {paths}")
    p = Path(paths[0])
    return {
        "provider": "NASA_IMERG_FINAL_V07_DAILY",
        "short_name": "GPM_3IMERGDF",
        "inspection": _inspect_netcdf(p),
    }


def _cmorph_key(dt: datetime) -> str:
    return (
        f"data/daily/0.25deg/{dt:%Y/%m}/"
        f"CMORPH_V1.0_ADJ_0.25deg-DLY_00Z_{dt:%Y%m%d}.nc"
    )


def _probe_cmorph(date: str, work: Path) -> dict:
    dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    key = _cmorph_key(dt)
    url = f"{CMORPH_S3_HTTPS}/{key}"
    payload = _read_url(url, timeout=120)
    p = work / Path(key).name
    p.write_bytes(payload)
    return {
        "provider": "NOAA_CMORPH_CDR_DAILY",
        "distribution": "NOAA_PUBLIC_S3_DAILY_0P25DEG",
        "s3_bucket": "noaa-cdr-precip-cmorph-pds",
        "s3_key": key,
        "url": url,
        "bytes": len(payload),
        "inspection": _inspect_netcdf(p),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2023-07-10")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    work = Path("work/phase2l_probe")
    work.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "0.3.0",
        "phase": "2L-daily-screening-payload-proof",
        "probe_date": args.date,
        "imerg": _probe_imerg(args.date, work),
        "cmorph": _probe_cmorph(args.date, work),
        "threshold_selected": False,
        "candidate_generated": False,
        "hard_negative_label": None,
        "validation_data_used": False,
        "risk_engine_allowed": False,
        "gate": "PASS_DUAL_DAILY_SCREENING_PAYLOAD_PROOF",
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "gate": report["gate"],
        "imerg_file": report["imerg"]["inspection"]["path"],
        "cmorph_key": report["cmorph"]["s3_key"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
