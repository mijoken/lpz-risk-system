#!/usr/bin/env python3
"""Build the Development positive-episode ERA5 × dual-source rainfall baseline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lpz_risk.positive_environment_baseline import (
    CMORPH,
    IMERG,
    build_development_positive_environment_baseline,
)
from lpz_risk.rainfall_reconstruction_merge import (
    merge_development_rainfall_reconstruction,
)

ALLOWED = {IMERG, CMORPH}


def _load_complete_dual_source_representatives(
    plan: dict,
    manifest: dict,
    episodes: dict,
    task_dir: Path,
) -> list[dict]:
    plan2 = dict(plan)
    plan2["tasks"] = [
        t for t in plan["tasks"] if t["source_id"] in ALLOWED
    ]
    plan2["source_summary"] = [
        s for s in plan["source_summary"] if s["source_id"] in ALLOWED
    ]
    task_ids = {t["task_id"] for t in plan2["tasks"]}
    window_ids = {w for t in plan2["tasks"] for w in t["window_ids"]}
    plan2["input_unique_window_count"] = len(window_ids)

    manifest2 = dict(manifest)
    manifest2["windows"] = [
        w for w in manifest["windows"] if w["source_id"] in ALLOWED
    ]
    manifest2["anchor_window_mappings"] = [
        m
        for m in manifest["anchor_window_mappings"]
        if m["source_id"] in ALLOWED
    ]
    manifest2["anchor_provider_mapping_count"] = len(
        manifest2["anchor_window_mappings"]
    )

    reports_by_id: dict[str, dict] = {}
    for path in sorted(task_dir.rglob("RAINPROD-*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        tid = report.get("task_id")
        if tid not in task_ids or report.get("source_id") not in ALLOWED:
            continue
        old = reports_by_id.get(tid)
        if old is None or (
            old.get("gate") != "PASS_TASK_REAL_PAYLOAD_RECONSTRUCTION"
            and report.get("gate") == "PASS_TASK_REAL_PAYLOAD_RECONSTRUCTION"
        ):
            reports_by_id[tid] = report

    expected_by_source = {
        src: {
            t["task_id"]
            for t in plan2["tasks"]
            if t["source_id"] == src
        }
        for src in ALLOWED
    }
    for src, expected in expected_by_source.items():
        passed = {
            tid
            for tid, report in reports_by_id.items()
            if report.get("source_id") == src
            and report.get("gate") == "PASS_TASK_REAL_PAYLOAD_RECONSTRUCTION"
        }
        if passed != expected:
            raise RuntimeError(
                f"incomplete {src}: pass={len(passed)} expected={len(expected)} "
                f"missing={sorted(expected - passed)}"
            )

    merged = merge_development_rainfall_reconstruction(
        plan2,
        manifest2,
        episodes,
        list(reports_by_id.values()),
    )
    if merged["gate"] != "PASS_COMPLETE_DEVELOPMENT_RECONSTRUCTION":
        raise RuntimeError(f"dual-source merge incomplete: {merged['gate']}")
    if merged["episode_representative_count"] != 130:
        raise RuntimeError(
            "expected 130 provider representatives, got "
            f"{merged['episode_representative_count']}"
        )
    return merged["episode_representative_features"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", required=True)
    p.add_argument("--window-manifest", required=True)
    p.add_argument("--episode-registry", required=True)
    p.add_argument("--task-dir", required=True)
    p.add_argument("--era5-table", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()

    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    manifest = json.loads(Path(a.window_manifest).read_text(encoding="utf-8"))
    episodes = json.loads(Path(a.episode_registry).read_text(encoding="utf-8"))
    era5 = json.loads(Path(a.era5_table).read_text(encoding="utf-8"))

    representatives = _load_complete_dual_source_representatives(
        plan,
        manifest,
        episodes,
        Path(a.task_dir),
    )
    report = build_development_positive_environment_baseline(
        representatives,
        era5,
        expected_episode_count=65,
    )

    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "gate": report["gate"],
                "episode_count": report["episode_count"],
                "era5_snapshot_count": report["era5_snapshot_count"],
                "source_fusion_used": report["source_fusion_used"],
                "candidate_threshold_selected": report[
                    "candidate_threshold_selected"
                ],
                "risk_engine_allowed": report["risk_engine_allowed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
