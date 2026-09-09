#!/usr/bin/env python3
"""Build normalized official JMA positive detection/anchor registry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.historical_positive_registry import build_positive_registry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-audit", default="reports/historical/historical_case_source_registry.json")
    parser.add_argument("--config", default="config/historical_case_sources.json")
    parser.add_argument("--output", default="reports/historical/positive_case_registry.json")
    args = parser.parse_args()

    try:
        source_audit = json.loads(Path(args.source_audit).read_text(encoding="utf-8"))
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        report = build_positive_registry(source_audit, list(config["snapshot_offsets_minutes"]))
        execution_ok = True
    except Exception as exc:
        report = {
            "schema_version": "0.1.0",
            "phase": "2A-positive-registry",
            "execution_ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "risk_engine_allowed": False,
        }
        execution_ok = False
    else:
        report["execution_ok"] = True

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "execution_ok": report.get("execution_ok"),
        "detection_row_count": report.get("detection_row_count"),
        "realized_positive_anchor_count": report.get("realized_positive_anchor_count"),
        "forecast_only_detection_row_count": report.get("forecast_only_detection_row_count"),
        "gates": report.get("gates"),
        "error": report.get("error"),
    }, ensure_ascii=False, indent=2))
    print(f"report={output}")
    return 0 if execution_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
