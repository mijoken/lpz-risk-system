#!/usr/bin/env python3
"""Build embedded-core genesis geometry descriptors from tracking + hierarchy reports."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.radar_genesis_geometry import build_genesis_geometry_descriptors  # noqa: E402


def summarize(rows: list[dict], threshold: int) -> dict:
    usable = [
        row for row in rows
        if int(row["threshold_mmph"]) == threshold
        and row.get("along_motion_km") is not None
        and not row.get("parent_boundary_truncated")
    ]
    along = [float(row["along_motion_km"]) for row in usable]
    distances = [float(row["child_relative_distance_km"]) for row in usable]
    return {
        "threshold_mmph": threshold,
        "usable_event_count": len(usable),
        "negative_along_motion_count": sum(value < 0.0 for value in along),
        "nonnegative_along_motion_count": sum(value >= 0.0 for value in along),
        "negative_fraction": None if not along else sum(value < 0.0 for value in along) / len(along),
        "median_along_motion_km": None if not along else statistics.median(along),
        "min_along_motion_km": None if not along else min(along),
        "max_along_motion_km": None if not along else max(along),
        "median_child_relative_distance_km": None if not distances else statistics.median(distances),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking", default="reports/scientific/radar_tracking.json")
    parser.add_argument("--hierarchy", default="reports/scientific/radar_hierarchy.json")
    parser.add_argument("--output", default="reports/scientific/radar_genesis_geometry.json")
    args = parser.parse_args()

    try:
        tracking = json.loads(Path(args.tracking).read_text(encoding="utf-8"))
        hierarchy = json.loads(Path(args.hierarchy).read_text(encoding="utf-8"))
        rows = build_genesis_geometry_descriptors(tracking, hierarchy, zoom=8)
        report = {
            "schema_version": "0.1.0",
            "phase": "1C-radar-genesis-relative-motion",
            "feature_id": "embedded_core_genesis_relative_parent_motion",
            "execution_ok": True,
            "event_count": len(rows),
            "events": rows,
            "summary": {str(threshold): summarize(rows, threshold) for threshold in (50, 80)},
            "backbuilding_classification": None,
            "historical_validation": False,
            "risk_engine_allowed": False,
            "interpretation": "Negative along_motion_km means geometrically behind the translating parent. It is not equivalent to back-building.",
            "gates": {
                "relative_motion_geometry": True,
                "upstream_environmental_inflow_comparison": False,
                "backbuilding_classification": False,
                "historical_validation": False,
                "risk_engine_allowed": False,
            },
        }
    except Exception as exc:
        report = {
            "schema_version": "0.1.0",
            "phase": "1C-radar-genesis-relative-motion",
            "execution_ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "risk_engine_allowed": False,
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "execution_ok": report.get("execution_ok"),
        "event_count": report.get("event_count"),
        "summary": report.get("summary"),
        "gates": report.get("gates"),
    }, indent=2))
    print(f"report={output}")
    return 0 if report.get("execution_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
