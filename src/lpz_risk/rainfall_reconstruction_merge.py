"""Merge Phase 2I task descriptors with strict completeness and leakage gates."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


def _q(values: list[float], pct: float) -> float | None:
    return None if not values else float(np.percentile(np.asarray(values, dtype=float), pct))


def merge_development_rainfall_reconstruction(
    plan: dict[str, Any],
    manifest: dict[str, Any],
    episode_registry: dict[str, Any],
    task_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    if plan.get("split") != "DEVELOPMENT" or manifest.get("split") != "DEVELOPMENT":
        raise ValueError("DEVELOPMENT-only merge")

    expected_task_ids = {str(t["task_id"]) for t in plan["tasks"]}
    reports_by_id: dict[str, dict[str, Any]] = {}
    failed_tasks: list[dict[str, Any]] = []
    for report in task_reports:
        tid = str(report.get("task_id", ""))
        if not tid:
            continue
        if tid in reports_by_id:
            raise ValueError(f"duplicate task report: {tid}")
        reports_by_id[tid] = report
        if report.get("gate") != "PASS_TASK_REAL_PAYLOAD_RECONSTRUCTION":
            failed_tasks.append({"task_id": tid, "gate": report.get("gate"), "error": report.get("error")})

    missing_task_ids = sorted(expected_task_ids - set(reports_by_id))
    unexpected_task_ids = sorted(set(reports_by_id) - expected_task_ids)

    descriptor_by_window: dict[str, dict[str, Any]] = {}
    for tid in sorted(expected_task_ids & set(reports_by_id)):
        report = reports_by_id[tid]
        if report.get("gate") != "PASS_TASK_REAL_PAYLOAD_RECONSTRUCTION":
            continue
        if report.get("split") != "DEVELOPMENT":
            raise ValueError("non-DEVELOPMENT task report entered merge")
        if report.get("risk_engine_allowed") is not False:
            raise ValueError("task report unexpectedly enabled risk engine")
        for row in report.get("window_descriptors") or []:
            wid = str(row["window_id"])
            if wid in descriptor_by_window:
                raise ValueError(f"duplicate reconstructed window: {wid}")
            descriptor_by_window[wid] = row

    expected_window_ids = {str(w["window_id"]) for w in manifest["windows"]}
    missing_window_ids = sorted(expected_window_ids - set(descriptor_by_window))
    unexpected_window_ids = sorted(set(descriptor_by_window) - expected_window_ids)

    anchor_rows: list[dict[str, Any]] = []
    for mapping in manifest["anchor_window_mappings"]:
        wid = str(mapping["window_id"])
        drow = descriptor_by_window.get(wid)
        if drow is None:
            continue
        desc = drow["descriptor"]
        anchor_rows.append({
            "anchor_id": mapping["anchor_id"],
            "local_episode_id": mapping["local_episode_id"],
            "primary_subdivision_code": mapping["primary_subdivision_code"],
            "analysis_time_utc": mapping["analysis_time_utc"],
            "source_id": mapping["source_id"],
            "window_id": wid,
            "source_lag_seconds": mapping["source_lag_seconds"],
            "max_accumulation_mm": desc["max_accumulation_mm"],
            "mean_accumulation_mm": desc["mean_accumulation_mm"],
            "p90_accumulation_mm": desc["p90_accumulation_mm"],
            "p95_accumulation_mm": desc["p95_accumulation_mm"],
            "p99_accumulation_mm": desc["p99_accumulation_mm"],
            "finite_polygon_area_km2": desc["finite_polygon_area_km2"],
            "finite_coverage_fraction": desc["finite_coverage_fraction"],
            "risk_score": None,
        })

    expected_anchor_mapping_count = int(manifest["anchor_provider_mapping_count"])
    missing_anchor_mapping_count = expected_anchor_mapping_count - len(anchor_rows)

    # One observation per local episode/provider: the earliest realized-positive
    # anchor in that local episode. This avoids treating repeated 10-minute rows
    # as independent calibration observations. Cross-subdivision independence is
    # still explicitly unresolved.
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in anchor_rows:
        grouped[(str(row["local_episode_id"]), str(row["source_id"]))].append(row)
    episode_representatives: list[dict[str, Any]] = []
    for (episode_id, source), rows in grouped.items():
        chosen = min(rows, key=lambda r: (r["analysis_time_utc"], r["anchor_id"]))
        episode_representatives.append({**chosen, "representative_policy": "EARLIEST_REALIZED_POSITIVE_ANCHOR_PER_LOCAL_EPISODE_PROVIDER"})
    episode_representatives.sort(key=lambda r: (r["source_id"], r["analysis_time_utc"], r["local_episode_id"]))

    dev_episode_count = int((episode_registry.get("split_local_episode_counts") or {}).get("DEVELOPMENT", 0))
    providers = sorted({str(s["source_id"]) for s in plan["source_summary"]})
    expected_episode_rep_count = dev_episode_count * len(providers)

    source_distributions = []
    for source in providers:
        rows = [r for r in episode_representatives if r["source_id"] == source]
        metrics = {}
        for metric in ("max_accumulation_mm", "mean_accumulation_mm", "p90_accumulation_mm", "p95_accumulation_mm", "p99_accumulation_mm"):
            values = [float(r[metric]) for r in rows]
            metrics[metric] = {
                "n": len(values),
                "min": None if not values else float(min(values)),
                "q25": _q(values, 25),
                "median": _q(values, 50),
                "q75": _q(values, 75),
                "q90": _q(values, 90),
                "q95": _q(values, 95),
                "q99": _q(values, 99),
                "max": None if not values else float(max(values)),
                "mean": None if not values else float(np.mean(values)),
            }
        source_distributions.append({
            "source_id": source,
            "local_episode_representative_count": len(rows),
            "metrics": metrics,
        })

    complete = (
        not missing_task_ids
        and not unexpected_task_ids
        and not failed_tasks
        and not missing_window_ids
        and not unexpected_window_ids
        and len(descriptor_by_window) == int(plan["input_unique_window_count"])
        and len(anchor_rows) == expected_anchor_mapping_count
        and len(episode_representatives) == expected_episode_rep_count
    )

    return {
        "schema_version": "0.1.0",
        "phase": "2I-development-real-rainfall-reconstruction-merge",
        "split": "DEVELOPMENT",
        "expected_task_count": len(expected_task_ids),
        "received_task_report_count": len(reports_by_id),
        "missing_task_ids": missing_task_ids,
        "unexpected_task_ids": unexpected_task_ids,
        "failed_tasks": failed_tasks,
        "expected_window_count": int(plan["input_unique_window_count"]),
        "reconstructed_window_count": len(descriptor_by_window),
        "missing_window_ids": missing_window_ids,
        "unexpected_window_ids": unexpected_window_ids,
        "expected_anchor_provider_mapping_count": expected_anchor_mapping_count,
        "reconstructed_anchor_provider_mapping_count": len(anchor_rows),
        "missing_anchor_provider_mapping_count": missing_anchor_mapping_count,
        "development_local_episode_count": dev_episode_count,
        "provider_count": len(providers),
        "expected_episode_representative_count": expected_episode_rep_count,
        "episode_representative_count": len(episode_representatives),
        "episode_representative_policy": "EARLIEST_REALIZED_POSITIVE_ANCHOR_PER_LOCAL_EPISODE_PROVIDER",
        "cross_subdivision_episode_grouping_complete": False,
        "window_descriptors": [descriptor_by_window[k] for k in sorted(descriptor_by_window)],
        "anchor_provider_features": anchor_rows,
        "episode_representative_features": episode_representatives,
        "source_distributions": source_distributions,
        "historical_rainfall_development_reconstruction_complete": complete,
        "candidate_threshold_selected": False,
        "hard_negative_label": None,
        "validation_data_used": False,
        "retrospective_test_data_used": False,
        "prospective_holdout_data_used": False,
        "risk_score": None,
        "risk_engine_allowed": False,
        "gate": "PASS_COMPLETE_DEVELOPMENT_RECONSTRUCTION" if complete else "BLOCKED_INCOMPLETE_DEVELOPMENT_RECONSTRUCTION",
    }
