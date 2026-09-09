#!/usr/bin/env python3
"""Real-payload proof for canonical GSMaP and IMERG rainfall adapters.

Downloads one already-audited free payload from each provider, decodes it through
source-specific adapters, and emits only compact descriptors. Raw files remain
inside a temporary directory and are never persisted.
"""
from __future__ import annotations

import argparse
import ftplib
import json
import os
import tempfile
from pathlib import Path

import numpy as np

from lpz_risk.gsmap_v8 import decode_gsmap_gauge_v8_file
from lpz_risk.imerg_v07 import decode_imerg_final_v07_file

GSMAP_REMOTE = "/standard/v8/hourly_G/2023/01/01/gsmap_gauge.20230101.0000.v8.0000.0.dat.gz"


def _japan_summary(field) -> dict:
    lon = np.asarray(field.longitude_deg_e)
    lat = np.asarray(field.latitude_deg_n)
    a = np.asarray(field.rain_rate_mm_per_hr, dtype=float)
    lon_idx = np.where((lon >= 129.0) & (lon <= 146.0))[0]
    lat_idx = np.where((lat >= 30.0) & (lat <= 46.0))[0]
    if not lon_idx.size or not lat_idx.size:
        raise ValueError("Japan bbox does not intersect canonical grid")
    sub = a[np.ix_(lat_idx, lon_idx)]
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


def _gsmap(td: Path) -> dict:
    p = td / Path(GSMAP_REMOTE).name
    with ftplib.FTP("hokusai.eorc.jaxa.jp", timeout=60) as ftp:
        ftp.login(os.environ["GSMAP_FTP_USERNAME"], os.environ["GSMAP_FTP_PASSWORD"])
        with p.open("wb") as f:
            ftp.retrbinary(f"RETR {GSMAP_REMOTE}", f.write)
    field = decode_gsmap_gauge_v8_file(p)
    d = field.descriptor()
    d["real_payload_bytes"] = p.stat().st_size
    d["japan_bbox_summary"] = _japan_summary(field)
    d["accumulation_minmax_mm"] = [
        float(np.nanmin(field.accumulation_mm)),
        float(np.nanmax(field.accumulation_mm)),
    ]
    d["adapter_gate"] = "PASS_REAL_GSMAP_CANONICAL_DECODE"
    return d


def _imerg(td: Path) -> dict:
    import earthaccess
    earthaccess.login(strategy="environment")
    granules = earthaccess.search_data(
        short_name="GPM_3IMERGHH",
        version="07",
        bounding_box=(129.0, 30.0, 146.0, 46.0),
        temporal=("2025-07-01T00:00:00Z", "2025-07-01T00:31:00Z"),
        count=1,
    )
    if not granules:
        raise RuntimeError("IMERG granule search empty")
    paths = earthaccess.download(granules[:1], str(td), threads=1)
    if not paths:
        raise RuntimeError("IMERG download returned no path")
    p = Path(paths[0])
    field = decode_imerg_final_v07_file(p)
    d = field.descriptor()
    d["real_payload_bytes"] = p.stat().st_size
    d["japan_bbox_summary"] = _japan_summary(field)
    d["accumulation_minmax_mm"] = [
        float(np.nanmin(field.accumulation_mm)),
        float(np.nanmax(field.accumulation_mm)),
    ]
    d["adapter_gate"] = "PASS_REAL_IMERG_CANONICAL_DECODE"
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="reports/historical/canonical_rainfall_real_proof.json")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        providers = [_gsmap(td), _imerg(td)]

    report = {
        "schema_version": "0.1.0",
        "phase": "2G-canonical-rainfall-real-proof",
        "zero_cost_required": True,
        "providers": providers,
        "gates": {
            "gsmap": providers[0]["adapter_gate"],
            "imerg": providers[1]["adapter_gate"],
            "cross_source_averaging_performed": False,
            "raw_payloads_persisted": False,
        },
        "hard_negative_label": None,
        "lpz_classification": None,
        "risk_score": None,
        "risk_engine_allowed": False,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
