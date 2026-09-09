#!/usr/bin/env python3
"""Build a conservative, spatially resolved ERA5 request manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.historical_environment import build_era5_request_manifest  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--positive-registry", default="reports/historical/positive_case_registry.json")
    p.add_argument("--config", default="config/historical_environment_era5.json")
    p.add_argument("--geometry", default="research/phase2/primary_subdivision_geometry_registry_20260909.json")
    p.add_argument("--output", default="reports/historical/era5_request_manifest.json")
    a = p.parse_args()

    try:
        registry = json.loads(Path(a.positive_registry).read_text(encoding="utf-8"))
        config = json.loads(Path(a.config).read_text(encoding="utf-8"))
        geometry = json.loads(Path(a.geometry).read_text(encoding="utf-8"))
        report = build_era5_request_manifest(registry, config, geometry)
        report["execution_ok"] = True
        ok = True
    except Exception as exc:
        report = {
            "schema_version": "0.2.0",
            "phase": "2B-era5-request-manifest",
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
        "snapshot_mapping_count": report.get("snapshot_mapping_count"),
        "unique_era5_source_time_count": report.get("unique_era5_source_time_count"),
        "request_day_count": report.get("request_day_count"),
        "date_subdivision_request_count": report.get("date_subdivision_request_count"),
        "unique_primary_subdivision_count": report.get("unique_primary_subdivision_count"),
        "maximum_times_per_request": report.get("maximum_times_per_request"),
        "maximum_source_lag_minutes": report.get("maximum_source_lag_minutes"),
        "future_source_time_count": report.get("future_source_time_count"),
        "spatial_sampling_gate": report.get("spatial_sampling_gate"),
        "authenticated_download_gate": report.get("authenticated_download_gate"),
        "error": report.get("error"),
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
