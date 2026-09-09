#!/usr/bin/env python3
"""Merge chunked ERA5 request descriptors and join them to positive snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lpz_risk.historical_environment_join import build_era5_snapshot_feature_table


def load_request_descriptors(root: Path) -> list[dict]:
    descriptors: list[dict] = []
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("phase") == "2B-era5-batch-request":
            descriptors.append(payload)
    return descriptors


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--descriptor-root", required=True)
    p.add_argument("--output", default="reports/historical/era5_positive_snapshot_feature_table.json")
    p.add_argument("--summary-output", default="reports/historical/era5_positive_snapshot_feature_summary.json")
    a = p.parse_args()

    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    descriptors = load_request_descriptors(Path(a.descriptor_root))
    result = build_era5_snapshot_feature_table(manifest, descriptors)

    output = Path(a.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {k: v for k, v in result.items() if k != "snapshot_features"}
    summary["output"] = str(output)
    summary_output = Path(a.summary_output)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "request_descriptor_count": result["request_descriptor_count"],
        "expected_request_count": result["expected_request_count"],
        "snapshot_feature_row_count": result["snapshot_feature_row_count"],
        "expected_snapshot_count": result["expected_snapshot_count"],
        "missing_snapshot_key_count": result["missing_snapshot_key_count"],
        "future_source_time_count": result["future_source_time_count"],
        "historical_environment_reconstruction_complete": result["historical_environment_reconstruction_complete"],
        "risk_engine_allowed": result["risk_engine_allowed"],
        "output": str(output),
        "summary_output": str(summary_output),
    }, ensure_ascii=False, indent=2))
    return 0 if result["historical_environment_reconstruction_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
