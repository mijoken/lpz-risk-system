#!/usr/bin/env python3
"""Download official JMA primary-subdivision GIS and build compact derived geometry."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.historical_spatial import (  # noqa: E402
    build_primary_subdivision_geojson,
    build_primary_subdivision_registry,
)


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "lpz-risk-system/0.1 research"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = resp.read()
    if len(payload) < 1024:
        raise ValueError(f"JMA GIS response unexpectedly small: {len(payload)} bytes")
    return payload


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--positive-registry", default="reports/historical/positive_case_registry.json")
    p.add_argument("--config", default="config/jma_primary_subdivision_gis.json")
    p.add_argument("--output", default="reports/historical/primary_subdivision_geometry.json")
    p.add_argument("--geojson-output", default=None, help="Optional compact official polygon FeatureCollection output")
    a = p.parse_args()

    try:
        positive = json.loads(Path(a.positive_registry).read_text(encoding="utf-8"))
        cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
        required = {str(x["primary_subdivision_code"]) for x in positive["realized_positive_anchors"]}
        payload = _download(cfg["zip_url"])
        report = build_primary_subdivision_registry(payload, required)
        report["execution_ok"] = True
        report["source_id"] = cfg["source_id"]
        report["source_page"] = cfg["source_page"]
        report["source_zip_url"] = cfg["zip_url"]
        report["downloaded_bytes"] = len(payload)
        ok = bool(report["geometry_complete_for_required_codes"])
        if not ok:
            report["execution_ok"] = False
            report["error"] = "Not all positive-anchor primary subdivision codes were resolved from official JMA GIS."

        if a.geojson_output and ok:
            geojson = build_primary_subdivision_geojson(payload, required)
            geojson["source_id"] = cfg["source_id"]
            geojson["source_page"] = cfg["source_page"]
            geojson["source_zip_url"] = cfg["zip_url"]
            geojson["source_archive_committed"] = False
            geo_path = Path(a.geojson_output)
            geo_path.parent.mkdir(parents=True, exist_ok=True)
            geo_path.write_text(json.dumps(geojson, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
            report["polygon_geojson_output"] = str(geo_path)
            report["polygon_geojson_feature_count"] = len(geojson["features"])
            report["polygon_geojson_complete"] = bool(geojson["geometry_complete_for_required_codes"])
    except Exception as exc:
        report = {
            "schema_version": "0.2.0",
            "phase": "2B-primary-subdivision-geometry",
            "execution_ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "risk_engine_allowed": False,
        }
        ok = False

    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "execution_ok": report.get("execution_ok"),
        "required_code_count": report.get("required_code_count"),
        "resolved_code_count": report.get("resolved_code_count"),
        "missing_required_codes": report.get("missing_required_codes"),
        "polygon_geojson_feature_count": report.get("polygon_geojson_feature_count"),
        "polygon_geojson_complete": report.get("polygon_geojson_complete"),
        "downloaded_bytes": report.get("downloaded_bytes"),
        "error": report.get("error"),
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
