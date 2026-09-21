#!/usr/bin/env python3
"""F4-9D terminal Go/No-Go decision.

This script is frozen before F4-9C prospective results are available.
It only reads completed F4-9C immutable case/verification artifacts and applies
the pre-specified decision rule. Regardless of GO or NO-GO, F4 closes.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


READY_STATES = {
    "READY_FOR_F4_9D_TARGET_MET",
    "READY_FOR_F4_9D_DEADLINE",
}
LEADS = (15, 30)


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _load_rows(cohort_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    status = _read_json(cohort_root / "cohort_status.json")
    if status.get("state") not in READY_STATES:
        raise ValueError(
            f"F4-9C cohort is not ready for F4-9D: {status.get('state')}"
        )
    rows: list[dict[str, Any]] = []
    for path in sorted((cohort_root / "verifications").glob("*.json")):
        payload = _read_json(path)
        if payload.get("verification_status") != "VERIFIED_EXACT_FUTURE":
            continue
        if payload.get("risk_engine_allowed") is not False:
            raise ValueError("verification Risk Engine lock violated")
        if payload.get("parameter_tuning_performed") is not False:
            raise ValueError("verification parameter-tuning lock violated")
        if payload.get("validated_forecast") is not False:
            raise ValueError("verification validation lock violated")
        comparisons = payload.get("comparisons")
        if not isinstance(comparisons, list):
            raise ValueError("verification comparisons missing")
        rows.extend(comparisons)
    return rows, status


def _lead_summary(rows: list[dict[str, Any]], lead: int) -> dict[str, Any]:
    selected = [
        row for row in rows
        if int(row["lead_minutes_from_as_of"]) == lead
    ]
    optical_iou = [
        float(row["optical_flow"]["best_iou"]) for row in selected
    ]
    persistence_iou = [
        float(row["persistence"]["best_iou"]) for row in selected
    ]
    delta_iou = [
        float(row["paired_best_iou_delta"]) for row in selected
    ]
    optical_distance = [
        float(row["optical_flow"]["nearest_target_centroid_distance_km"])
        for row in selected
    ]
    persistence_distance = [
        float(row["persistence"]["nearest_target_centroid_distance_km"])
        for row in selected
    ]
    optical_overlap = [
        bool(row["optical_flow"]["any_overlap"]) for row in selected
    ]
    persistence_overlap = [
        bool(row["persistence"]["any_overlap"]) for row in selected
    ]

    return {
        "comparison_count": len(selected),
        "optical_flow_best_iou_mean": _mean(optical_iou),
        "persistence_best_iou_mean": _mean(persistence_iou),
        "paired_best_iou_delta_mean": _mean(delta_iou),
        "paired_best_iou_delta_median": _median(delta_iou),
        "optical_flow_any_overlap_rate": (
            sum(optical_overlap) / len(optical_overlap)
            if optical_overlap else None
        ),
        "persistence_any_overlap_rate": (
            sum(persistence_overlap) / len(persistence_overlap)
            if persistence_overlap else None
        ),
        "optical_flow_nearest_centroid_distance_km_median": _median(
            optical_distance
        ),
        "persistence_nearest_centroid_distance_km_median": _median(
            persistence_distance
        ),
    }


def evaluate(cohort_root: Path) -> dict[str, Any]:
    rows, status = _load_rows(cohort_root)

    summaries = {str(lead): _lead_summary(rows, lead) for lead in LEADS}

    checks: dict[str, bool] = {}
    for lead in LEADS:
        summary = summaries[str(lead)]
        enough_rows = int(summary["comparison_count"]) > 0
        checks[f"comparison_rows_available_{lead}m"] = enough_rows
        checks[f"mean_iou_delta_positive_{lead}m"] = (
            enough_rows
            and summary["paired_best_iou_delta_mean"] is not None
            and float(summary["paired_best_iou_delta_mean"]) > 0.0
        )
        checks[f"any_overlap_not_worse_{lead}m"] = (
            enough_rows
            and summary["optical_flow_any_overlap_rate"] is not None
            and summary["persistence_any_overlap_rate"] is not None
            and float(summary["optical_flow_any_overlap_rate"])
            >= float(summary["persistence_any_overlap_rate"])
        )
        checks[f"median_centroid_distance_not_worse_{lead}m"] = (
            enough_rows
            and summary["optical_flow_nearest_centroid_distance_km_median"] is not None
            and summary["persistence_nearest_centroid_distance_km_median"] is not None
            and float(
                summary[
                    "optical_flow_nearest_centroid_distance_km_median"
                ]
            )
            <= float(
                summary[
                    "persistence_nearest_centroid_distance_km_median"
                ]
            )
        )

    case_files = sorted((cohort_root / "cases").glob("*.json"))
    verification_files = sorted(
        (cohort_root / "verifications").glob("*.json")
    )
    permanent_failures = 0
    invariant_ok = True

    for path in case_files:
        case = _read_json(path)
        invariant_ok = invariant_ok and all(
            (
                case.get("captured_before_first_target") is True,
                case.get("future_observations_read_at_capture") is False,
                case.get("forecast_skill_scored_at_capture") is False,
                case.get("parameter_tuning_performed") is False,
                case.get("risk_engine_allowed") is False,
            )
        )

    for path in verification_files:
        verification = _read_json(path)
        if verification.get("verification_status") == "PERMANENT_TECHNICAL_FAILURE":
            permanent_failures += 1

    checks["scientific_invariants_ok"] = bool(invariant_ok)
    decision = "GO" if all(checks.values()) else "NO_GO"

    total_cases = len(case_files)
    result = {
        "schema_version": "1.0.0",
        "product": "F4_9D_TERMINAL_DECISION",
        "research_stage": "F4-9D",
        "cohort_terminal_state": status["state"],
        "verified_comparison_count": int(
            status["verified_comparison_count"]
        ),
        "verified_distinct_slot_count": int(
            status["verified_distinct_slot_count"]
        ),
        "case_count": total_cases,
        "permanent_technical_failure_case_count": permanent_failures,
        "technical_failure_rate": (
            permanent_failures / total_cases if total_cases else None
        ),
        "lead_summaries": summaries,
        "go_checks": checks,
        "decision": decision,
        "f4_closed": True,
        "production_integration_enabled": False,
        "risk_engine_allowed": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
        "validated_forecast": False,
        "posthoc_retuning_allowed": False,
        "next_step": (
            "NEW_SEPARATELY_SCOPED_INTEGRATION_PHASE"
            if decision == "GO"
            else "KEEP_PERSISTENCE_BASELINE_AND_END_F4"
        ),
        "interpretation": (
            "Terminal pre-specified F4 decision. GO authorizes only a new, "
            "separately scoped integration phase; it does not enable production. "
            "NO-GO keeps persistence as the short-time spatial baseline. "
            "F4 closes regardless of outcome."
        ),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if args.output.exists():
        parser.error(f"refusing overwrite: {args.output}")

    result = evaluate(args.cohort_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2, allow_nan=False)
        fp.write("\n")

    print(
        json.dumps(
            {
                "decision": result["decision"],
                "f4_closed": result["f4_closed"],
                "verified_comparison_count": result[
                    "verified_comparison_count"
                ],
                "verified_distinct_slot_count": result[
                    "verified_distinct_slot_count"
                ],
                "go_checks": result["go_checks"],
                "next_step": result["next_step"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
