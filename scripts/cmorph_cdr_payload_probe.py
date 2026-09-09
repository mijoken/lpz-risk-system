#!/usr/bin/env python3
"""Acquire one official NOAA/NCEI CMORPH CDR NetCDF and prove canonical decode."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import urllib.request

import numpy as np

from lpz_risk.cmorph_v1 import decode_cmorph_cdr_v1_bytes

URL = (
    "https://www.ncei.noaa.gov/data/cmorph-high-resolution-global-precipitation-estimates/"
    "access/30min/8km/2023/01/01/CMORPH_V1.0_ADJ_8km-30min_2023010100.nc"
)
FILENAME = "CMORPH_V1.0_ADJ_8km-30min_2023010100.nc"


def _download() -> bytes:
    req = urllib.request.Request(URL, headers={"User-Agent": "lpz-risk-system/0.1 research"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        payload = resp.read()
    if len(payload) < 1024:
        raise ValueError(f"CMORPH payload unexpectedly small: {len(payload)} bytes")
    return payload


def _japan_bbox(field) -> dict:
    lon = np.asarray(field.longitude_deg_e, dtype=float)
    lat = np.asarray(field.latitude_deg_n, dtype=float)
    arr = np.asarray(field.rain_rate_mm_per_hr, dtype=float)
    lon_idx = np.where((lon >= 129.0) & (lon <= 146.0))[0]
    lat_idx = np.where((lat >= 30.0) & (lat <= 46.0))[0]
    if not lon_idx.size or not lat_idx.size:
        raise ValueError("CMORPH grid does not cover Japan bbox")
    sub = arr[np.ix_(lat_idx, lon_idx)]
    finite = sub[np.isfinite(sub)]
    return {
        "bbox": [129.0, 30.0, 146.0, 46.0],
        "bbox_shape": list(sub.shape),
        "finite_count": int(finite.size),
        "missing_count": int(sub.size - finite.size),
        "rain_rate_min_mm_per_hr": None if not finite.size else float(finite.min()),
        "rain_rate_max_mm_per_hr": None if not finite.size else float(finite.max()),
        "rain_rate_mean_mm_per_hr": None if not finite.size else float(finite.mean()),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", default="reports/historical/cmorph_cdr_payload_probe.json")
    a = p.parse_args()

    try:
        payload = _download()
        fields = decode_cmorph_cdr_v1_bytes(payload, filename=FILENAME)
        report = {
            "schema_version": "0.1.0",
            "phase": "2H-cmorph-cdr-real-payload-proof",
            "source_id": "NOAA_CMORPH_CDR",
            "official_url": URL,
            "payload_filename": FILENAME,
            "payload_bytes": len(payload),
            "native_field_count": len(fields),
            "fields": [f.descriptor() for f in fields],
            "japan_bbox_first_field": _japan_bbox(fields[0]),
            "gate": "PASS_REAL_CMORPH_CDR_CANONICAL_DECODE",
            "raw_payload_persisted": False,
            "hard_negative_label": None,
            "lpz_classification": None,
            "risk_score": None,
            "risk_engine_allowed": False,
        }
        ok = True
    except Exception as exc:
        report = {
            "schema_version": "0.1.0",
            "phase": "2H-cmorph-cdr-real-payload-proof",
            "source_id": "NOAA_CMORPH_CDR",
            "gate": "FAIL_REAL_CMORPH_CDR_CANONICAL_DECODE",
            "error": f"{type(exc).__name__}: {exc}",
            "raw_payload_persisted": False,
            "risk_engine_allowed": False,
        }
        ok = False

    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
