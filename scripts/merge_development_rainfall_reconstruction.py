#!/usr/bin/env python3
"""Merge Phase 2I DEVELOPMENT rainfall task reports and enforce completeness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lpz_risk.rainfall_reconstruction_merge import merge_development_rainfall_reconstruction


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", required=True)
    p.add_argument("--window-manifest", required=True)
    p.add_argument("--episode-registry", required=True)
    p.add_argument("--task-dir", required=True)
    p.add_argument("--output", default="reports/historical/development_rainfall_reconstruction.json")
    p.add_argument("--summary-output", default="reports/historical/development_rainfall_reconstruction_summary.json")
    a = p.parse_args()

    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    manifest = json.loads(Path(a.window_manifest).read_text(encoding="utf-8"))
    episodes = json.loads(Path(a.episode_registry).read_text(encoding="utf-8"))
    reports = []
    for path in sorted(Path(a.task_dir).rglob("*.json")):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if obj.get("phase") == "2I-development-real-rainfall-reconstruction-task":
            reports.append(obj)

    result = merge_development_rainfall_reconstruction(plan, manifest, episodes, reports)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    summary_keys = (
        "schema_version", "phase", "split", "expected_task_count", "received_task_report_count",
        "missing_task_ids", "unexpected_task_ids", "failed_tasks", "expected_window_count",
        "reconstructed_window_count", "missing_window_ids", "unexpected_window_ids",
        "expected_anchor_provider_mapping_count", "reconstructed_anchor_provider_mapping_count",
        "missing_anchor_provider_mapping_count", "development_local_episode_count", "provider_count",
        "expected_episode_representative_count", "episode_representative_count",
        "episode_representative_policy", "cross_subdivision_episode_grouping_complete",
        "source_distributions", "historical_rainfall_development_reconstruction_complete",
        "candidate_threshold_selected", "hard_negative_label", "validation_data_used",
        "retrospective_test_data_used", "prospective_holdout_data_used", "risk_score",
        "risk_engine_allowed", "gate",
    )
    summary = {k: result[k] for k in summary_keys}
    sout = Path(a.summary_output)
    sout.parent.mkdir(parents=True, exist_ok=True)
    sout.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result["historical_rainfall_development_reconstruction_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
