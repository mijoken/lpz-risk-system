#!/usr/bin/env python3
"""Summarize an existing F4 archived evaluation; no data acquisition or scoring."""
from __future__ import annotations
import argparse
import json
import statistics
from collections import Counter
from pathlib import Path


def summarize(report: dict) -> dict:
    if (report.get("product") != "F4_RETROSPECTIVE_ARCHIVED_POINT_PROXIMITY"
            or report.get("risk_engine_allowed") is not False
            or report.get("lpz_forecast_generated") is not False
            or report.get("research_mode") != "RETROSPECTIVE_DERIVATIVE_NOT_PROSPECTIVE_VALIDATION"):
        raise ValueError("not a locked F4 retrospective research report")
    rows = report["results"]
    statuses = Counter(r["identity_status"] for r in rows)
    horizons = {}
    for lead in (15, 30):
        eligible = [r for r in rows if r["lead_from_as_of_minutes"] == lead
                    and r["identity_verified"] is True]
        if any(r["identity_matched_distance_km"] is None
               or r["identity_persistence_distance_km"] is None for r in eligible):
            raise ValueError("verified row lacks distance")
        horizons[str(lead)] = {
            "identity_matched_count": len(eligible),
            "motion_median_km": (statistics.median(
                r["identity_matched_distance_km"] for r in eligible)
                if eligible else None),
            "persistence_median_km": (statistics.median(
                r["identity_persistence_distance_km"] for r in eligible)
                if eligible else None),
        }
    verified = sum(r["identity_verified"] is True for r in rows)
    if (verified != report["counts"]["identity_matched_projections"]
            or sum(r["identity_status"] != "NOT_EVALUATED_NO_EXACT_TARGET"
                   and r["identity_verified"] is False for r in rows)
            != report["counts"]["identity_unresolved_projections"]):
        raise ValueError("identity counts disagree")
    return {
        "source_run_id": report["source_run_id"],
        "target_run_id": report["target_run_id"],
        "counts": report["counts"],
        "identity_status_counts": dict(sorted(statuses.items())),
        "horizons_from_as_of_minutes": horizons,
        "risk_engine_allowed": False,
        "lpz_forecast_generated": False,
        "interpretation": "Retrospective algorithmic radar identity, not independent ground truth or LPZ forecast skill.",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    if args.output.exists():
        p.error("refusing overwrite")
    result = summarize(json.loads(args.report.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
