#!/usr/bin/env python3
"""Publish an explicitly archived F4 retrospective research summary (never live risk).

Input must be a verified summary from scripts/summarize_f4_identity_retrospective.py.
The two run IDs are fixed evidence references, NOT the newest weather acquisition.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SOURCE_RUN_ID = "35564667965"
TARGET_RUN_ID = "35565907043"
PRODUCT = "LPZ_F4_ARCHIVED_RESEARCH_PUBLIC_SUMMARY"


def publish(summary: dict) -> dict:
    if (summary.get("source_run_id") != SOURCE_RUN_ID
            or summary.get("target_run_id") != TARGET_RUN_ID
            or summary.get("risk_engine_allowed") is not False
            or summary.get("lpz_forecast_generated") is not False):
        raise ValueError("F4 archived research source or release state mismatch")
    counts = summary["counts"]
    categories = summary["no_continuous_match_association_categories"]
    statuses = summary["identity_status_counts"]
    horizons = summary["horizons_from_as_of_minutes"]
    if (counts["comparable_projections"] != counts["identity_matched_projections"]
            + counts["identity_unresolved_projections"]
            or 2 * counts["projected_objects"] != (
                counts["comparable_projections"] + counts["no_exact_comparable_target"])
            or sum(categories.values()) != counts["identity_unresolved_projections"]
            or statuses["CONTINUOUS_PRIMARY_MATCH_OBSERVED"] != counts["identity_matched_projections"]
            or statuses["NO_CONTINUOUS_PRIMARY_MATCH"] != counts["identity_unresolved_projections"]
            or statuses["NOT_EVALUATED_NO_EXACT_TARGET"] != counts["no_exact_comparable_target"]
            or sum(horizons[str(i)]["identity_matched_count"] for i in (15, 30))
            != counts["identity_matched_projections"]):
        raise ValueError("F4 research accounting mismatch")
    return {
        "schema_version": "1.0.0",
        "product": PRODUCT,
        "archived_research_only": True,
        "source_run_id": SOURCE_RUN_ID,
        "target_run_id": TARGET_RUN_ID,
        "counts": counts,
        "identity_status_counts": statuses,
        "no_continuous_match_association_categories": categories,
        "no_overlap_geometry_diagnostics": summary["no_overlap_geometry_diagnostics"],
        "horizons_from_as_of_minutes": horizons,
        "risk_engine_allowed": False,
        "lpz_forecast_generated": False,
        "not_operational_warning": True,
        "interpretation": "Retrospective 30 mm/h observed radar-object centroid research, not nationwide LPZ prediction, live alert, independent tracking ground truth or skill certification.",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--summary", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    if a.output.exists():
        p.error("refusing overwrite")
    result = publish(json.loads(a.summary.read_text(encoding="utf-8")))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({"product": PRODUCT, "counts": result["counts"],
                      "risk_engine_allowed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
