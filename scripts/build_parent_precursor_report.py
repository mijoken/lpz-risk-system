#!/usr/bin/env python3
"""Build per-parent descriptive precursor features from temporal + inflow reports."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.parent_precursor import build_parent_precursor_descriptors  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temporal", default="reports/scientific/radar_temporal.json")
    parser.add_argument("--inflow", default="reports/scientific/radar_inflow_geometry.json")
    parser.add_argument("--output", default="reports/scientific/parent_precursor_features.json")
    parser.add_argument("--csv-output", default="reports/scientific/parent_precursor_features.csv")
    args = parser.parse_args()

    try:
        temporal = json.loads(Path(args.temporal).read_text(encoding="utf-8"))
        inflow = json.loads(Path(args.inflow).read_text(encoding="utf-8"))
        rows = build_parent_precursor_descriptors(temporal, inflow)
        report = {
            "schema_version": "0.1.0",
            "phase": "1C-parent-precursor-feature-table",
            "feature_id": "parent_precursor_descriptive_table",
            "execution_ok": True,
            "descriptor_count": len(rows),
            "descriptors": rows,
            "classification": None,
            "backbuilding_classification": None,
            "risk_score": None,
            "historical_validation": False,
            "risk_engine_allowed": False,
            "interpretation": "Joined raw descriptors for evidence-database reconstruction; no threshold or score is applied.",
            "gates": {
                "temporal_descriptors": True,
                "parent_motion_genesis_geometry": True,
                "inflow_relative_genesis_geometry": True,
                "parent_precursor_table": True,
                "historical_validation": False,
                "risk_engine_allowed": False,
            },
        }
    except Exception as exc:
        rows = []
        report = {
            "schema_version": "0.1.0",
            "phase": "1C-parent-precursor-feature-table",
            "execution_ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "risk_engine_allowed": False,
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    csv_output = Path(args.csv_output)
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        fieldnames = sorted({key for row in rows for key in row.keys() if not isinstance(row.get(key), (dict, list))})
        with csv_output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key) for key in fieldnames})
    else:
        csv_output.write_text("", encoding="utf-8")

    print(json.dumps({
        "execution_ok": report.get("execution_ok"),
        "descriptor_count": report.get("descriptor_count"),
        "gates": report.get("gates"),
    }, indent=2))
    print(f"report={output}")
    print(f"csv={csv_output}")
    return 0 if report.get("execution_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
