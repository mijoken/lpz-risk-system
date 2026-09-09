#!/usr/bin/env python3
"""Build provider-native DEVELOPMENT rainfall production plan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lpz_risk.rainfall_production_plan import build_development_rainfall_production_plan


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--window-manifest", required=True)
    p.add_argument("--output", default="reports/historical/development_rainfall_production_plan.json")
    a = p.parse_args()
    manifest = json.loads(Path(a.window_manifest).read_text(encoding="utf-8"))
    result = build_development_rainfall_production_plan(manifest)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "input_unique_window_count": result["input_unique_window_count"],
        "unique_native_field_count": result["unique_native_field_count"],
        "unique_payload_count": result["unique_payload_count"],
        "production_task_count": result["production_task_count"],
        "payload_task_use_count": result["payload_task_use_count"],
        "source_summary": result["source_summary"],
        "candidate_threshold_selected": result["candidate_threshold_selected"],
        "risk_engine_allowed": result["risk_engine_allowed"],
        "output": str(out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
