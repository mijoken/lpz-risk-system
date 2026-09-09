#!/usr/bin/env python3
"""Download official JMA primary-subdivision GIS once and build required GeoJSON."""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

from lpz_risk.historical_spatial import build_primary_subdivision_geojson

JMA_GIS_URL = "https://www.data.jma.go.jp/developer/gis/20190125_AreaForecastLocalM_1saibun_GIS.zip"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", required=True)
    p.add_argument("--output", default="reports/historical/development_primary_subdivision_geometry.geojson")
    a = p.parse_args()
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    codes = {str(c) for t in plan["tasks"] for c in t["primary_subdivision_codes"]}
    req = urllib.request.Request(JMA_GIS_URL, headers={"User-Agent": "lpz-risk-system/0.1 research"})
    with urllib.request.urlopen(req, timeout=240) as resp:
        payload = resp.read()
    geo = build_primary_subdivision_geojson(payload, codes)
    if not geo["geometry_complete_for_required_codes"]:
        raise RuntimeError("official JMA polygon geometry incomplete")
    if len(geo["features"]) != len(codes):
        raise RuntimeError("unexpected official polygon feature count")
    geo["phase"] = "2I-development-rainfall-production-geometry"
    geo["split"] = "DEVELOPMENT"
    geo["source_zip_url"] = JMA_GIS_URL
    geo["raw_zip_persisted"] = False
    geo["risk_engine_allowed"] = False
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(geo, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({
        "required_code_count": len(codes),
        "resolved_feature_count": len(geo["features"]),
        "downloaded_zip_bytes": len(payload),
        "geometry_complete_for_required_codes": geo["geometry_complete_for_required_codes"],
        "raw_zip_persisted": False,
        "risk_engine_allowed": False,
        "output": str(out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
