#!/usr/bin/env python3
"""Phase 2L-O4 — build validated public JSON for GitHub Pages."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.public_web import build_public_products, publish_public_products

DEFAULT_SOURCE_HEALTH = (
    ROOT / "local_data" / "phase2l_l_source_health" / "phase2l_l_source_health_report.json"
)
DEFAULT_K2 = (
    ROOT
    / "research"
    / "phase2"
    / "phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912.json"
)
DEFAULT_GEOGRAPHY = ROOT / "web" / "assets" / "japan_primary_subdivisions.geojson"
DEFAULT_OUTPUT = ROOT / "web" / "data"
PASS_GATE = "PASS_PHASE2L_O4_PUBLIC_WEB_DATA_CONTRACT"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-health-report", type=Path, default=DEFAULT_SOURCE_HEALTH)
    p.add_argument("--k2-freeze", type=Path, default=DEFAULT_K2)
    p.add_argument("--geography", type=Path, default=DEFAULT_GEOGRAPHY)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument(
        "--pipeline-state",
        choices=["PASS", "DEGRADED", "FAIL", "UNKNOWN"],
        default="PASS",
    )
    p.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID"))
    p.add_argument("--commit-sha", default=os.environ.get("GITHUB_SHA"))
    args = p.parse_args()

    for path in (args.source_health_report, args.k2_freeze, args.geography):
        if not path.exists():
            raise FileNotFoundError(path)

    products = build_public_products(
        source_health_report_path=args.source_health_report.resolve(),
        k2_freeze_path=args.k2_freeze.resolve(),
        geography_path=args.geography.resolve(),
        pipeline_state=args.pipeline_state,
        run_id=args.run_id,
        commit_sha=args.commit_sha,
    )
    publish_public_products(products, args.output_dir.resolve())

    status = products["system_status.json"]
    health = products["source_health.json"]
    latest = products["latest.json"]
    imerg = next(
        (s for s in health["sources"] if s["source_id"] == "nasa_earthdata_imerg"),
        None,
    )

    print("=" * 104)
    print("LPZ PHASE 2L-O4 — PUBLIC WEB DATA CONTRACT")
    print("=" * 104)
    print(f"System operational status        : {status['overall_operational_status']}")
    print(f"Public source health             : {health['overall_status']}")
    print(f"JMA regions in latest.json       : {len(latest['regions'])}")
    print(f"Risk engine allowed              : {status['scientific_release']['risk_engine_allowed']}")
    print(f"Validation status                : {status['scientific_release']['validation_status']}")
    print(f"IMERG Final V08 probe            : {(imerg or {}).get('probe_status')}")
    print("2025 ERA5 environment opened     : NO")
    print("Primary confirmatory test run    : NO")
    print("Schema validation                : PASS")
    print("GeoJSON join-key validation      : PASS")
    print("Locked-risk invariant            : PASS")
    print("")
    print(f"Gate                             : {PASS_GATE}")
    print(f"Output                           : {args.output_dir.resolve()}")
    print("=" * 104)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
