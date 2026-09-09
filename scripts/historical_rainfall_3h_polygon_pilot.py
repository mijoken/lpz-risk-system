#!/usr/bin/env python3
"""Real-payload proof of exact 3-hour accumulation plus official JMA polygon masking.

The proof uses one DEVELOPMENT-era UTC window (2023-01-01 00:00-03:00) and one
already-required primary subdivision code. It proves mechanics only; it does not
select a heavy-rain threshold or label any hard negative.
"""
from __future__ import annotations

import argparse
import ftplib
import json
import os
import tempfile
import urllib.request
from pathlib import Path

import numpy as np

from lpz_risk.gsmap_v8 import decode_gsmap_gauge_v8_file
from lpz_risk.historical_rainfall_window import build_exact_accumulation_window, build_subdivision_window_descriptor
from lpz_risk.historical_spatial import build_primary_subdivision_geojson
from lpz_risk.imerg_v07 import decode_imerg_final_v07_file

SUBDIVISION_CODE = "390030"
JMA_GIS_URL = "https://www.data.jma.go.jp/developer/gis/20190125_AreaForecastLocalM_1saibun_GIS.zip"
GSMAP_REMOTES = [
    f"/standard/v8/hourly_G/2023/01/01/gsmap_gauge.20230101.{hour:02d}00.v8.0000.0.dat.gz"
    for hour in range(3)
]


def _download_jma_geojson_feature() -> dict:
    req = urllib.request.Request(JMA_GIS_URL, headers={"User-Agent": "lpz-risk-system/0.1 research"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        payload = resp.read()
    geo = build_primary_subdivision_geojson(payload, {SUBDIVISION_CODE})
    if not geo["geometry_complete_for_required_codes"] or len(geo["features"]) != 1:
        raise RuntimeError("official JMA polygon resolution failed")
    return geo["features"][0]


def _download_gsmap(td: Path):
    fields = []
    with ftplib.FTP("hokusai.eorc.jaxa.jp", timeout=90) as ftp:
        ftp.login(os.environ["GSMAP_FTP_USERNAME"], os.environ["GSMAP_FTP_PASSWORD"])
        for remote in GSMAP_REMOTES:
            p = td / Path(remote).name
            with p.open("wb") as f:
                ftp.retrbinary(f"RETR {remote}", f.write)
            fields.append(decode_gsmap_gauge_v8_file(p))
    return fields


def _download_imerg(td: Path):
    import earthaccess

    earthaccess.login(strategy="environment")
    granules = earthaccess.search_data(
        short_name="GPM_3IMERGHH",
        version="07",
        bounding_box=(129.0, 30.0, 146.0, 46.0),
        temporal=("2023-01-01T00:00:00Z", "2023-01-01T02:59:59Z"),
        count=12,
    )
    if len(granules) < 6:
        raise RuntimeError(f"expected at least six IMERG granules, found {len(granules)}")
    paths = earthaccess.download(granules, str(td / "imerg"), threads=1)
    fields = [decode_imerg_final_v07_file(Path(p)) for p in paths]
    fields = [f for f in fields if f.valid_start_utc.isoformat() >= "2023-01-01T00:00:00+00:00" and f.valid_start_utc.isoformat() < "2023-01-01T03:00:00+00:00"]
    fields.sort(key=lambda f: f.valid_start_utc)
    # Search APIs may return adjacent granules; exact window constructor below is the final guard.
    return fields[:6]


def _provider_result(fields, feature):
    window = build_exact_accumulation_window(fields, target_seconds=10_800)
    desc = build_subdivision_window_descriptor(
        window,
        primary_subdivision_code=SUBDIVISION_CODE,
        polygon_feature=feature,
    )
    return {
        "window": window.descriptor(),
        "subdivision": desc,
        "three_hour_gate": "PASS_REAL_SOURCE_NATIVE_3H_POLYGON_DESCRIPTOR",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="reports/historical/historical_rainfall_3h_polygon_pilot.json")
    args = ap.parse_args()
    try:
        feature = _download_jma_geojson_feature()
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            gsmap = _provider_result(_download_gsmap(td), feature)
            imerg = _provider_result(_download_imerg(td), feature)
        report = {
            "schema_version": "0.1.0",
            "phase": "2H-real-three-hour-polygon-pilot",
            "split": "DEVELOPMENT",
            "primary_subdivision_code": SUBDIVISION_CODE,
            "window_utc": ["2023-01-01T00:00:00+00:00", "2023-01-01T03:00:00+00:00"],
            "providers": [gsmap, imerg],
            "provider_comparison_semantics": "SIDE_BY_SIDE_ONLY_NO_AVERAGING",
            "candidate_threshold_selected": False,
            "hard_negative_label": None,
            "lpz_classification": None,
            "risk_score": None,
            "raw_payloads_persisted": False,
            "risk_engine_allowed": False,
            "gate": "PASS_REAL_3H_ACCUMULATION_AND_OFFICIAL_POLYGON_MASKING",
        }
        ok = True
    except Exception as exc:
        report = {
            "schema_version": "0.1.0",
            "phase": "2H-real-three-hour-polygon-pilot",
            "gate": "FAIL_REAL_3H_ACCUMULATION_AND_OFFICIAL_POLYGON_MASKING",
            "error": f"{type(exc).__name__}: {exc}",
            "risk_engine_allowed": False,
        }
        ok = False

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
