#!/usr/bin/env python3
"""Build threshold-free parent temporal descriptors from tracking + hierarchy reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.radar_temporal import build_parent_temporal_descriptors  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking", default="reports/scientific/radar_tracking.json")
    parser.add_argument("--hierarchy", default="reports/scientific/radar_hierarchy.json")
    parser.add_argument("--output", default="reports/scientific/radar_temporal_descriptors.json")
    args = parser.parse_args()

    try:
        tracking = json.loads(Path(args.tracking).read_text(encoding="utf-8"))
        hierarchy = json.loads(Path(args.hierarchy).read_text(encoding="utf-8"))
        descriptors = build_parent_temporal_descriptors(tracking, hierarchy)
        report = {
            "schema_version": "0.1.0",
            "phase": "1C-radar-temporal-descriptors",
            "feature_id": "parent_precipitation_temporal_descriptors_public_png",
            "execution_ok": True,
            "descriptor_count": len(descriptors),
            "descriptors": descriptors,
            "most_persistent": descriptors[:10],
            "most_core_generative": sorted(
                descriptors,
                key=lambda row: (row["embedded_core_genesis_count"], row["duration_minutes"], row["max_area_km2"]),
                reverse=True,
            )[:10],
            "classification": None,
            "stationarity_threshold": None,
            "backbuilding_threshold": None,
            "historical_validation": False,
            "risk_engine_allowed": False,
            "interpretation": "Long-form descriptive variables only. No stationarity or back-building decision threshold is defined.",
            "gates": {
                "tracking_input": True,
                "hierarchy_input": True,
                "temporal_descriptor_build": True,
                "stationarity_classification": False,
                "backbuilding_classification": False,
                "historical_validation": False,
                "risk_engine_allowed": False,
            },
        }
    except Exception as exc:
        report = {
            "schema_version": "0.1.0",
            "phase": "1C-radar-temporal-descriptors",
            "execution_ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "risk_engine_allowed": False,
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "execution_ok": report.get("execution_ok"),
        "descriptor_count": report.get("descriptor_count"),
        "gates": report.get("gates"),
    }, indent=2))
    print(f"report={output}")
    return 0 if report.get("execution_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
