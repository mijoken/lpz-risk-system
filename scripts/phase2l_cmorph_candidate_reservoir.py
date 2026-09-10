#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd

METRICS = ["rain_max_mm_day", "rain_p90_mm_day", "rain_p95_mm_day"]
THRESHOLD_PERCENTILE = 80.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--census", required=True)
    ap.add_argument("--positive-positions", required=True)
    ap.add_argument("--output-dir", required=True)
    a = ap.parse_args()

    census = pd.read_csv(a.census, dtype={"primary_subdivision_code": str})
    positives = pd.read_csv(a.positive_positions, dtype={"primary_subdivision_code": str})
    census["date_utc"] = pd.to_datetime(census["date_utc"]).dt.strftime("%Y-%m-%d")

    if len(census) != 32895:
        raise ValueError(f"expected 32895 region-days, got {len(census)}")
    if census["date_utc"].nunique() != 731:
        raise ValueError("expected 731 Development days")
    if census["primary_subdivision_code"].nunique() != 45:
        raise ValueError("expected 45 Development matched-domain regions")
    if len(positives) != 65:
        raise ValueError("expected frozen 65 Development positive episodes")

    for metric in METRICS:
        census[f"{metric}_percentile_same_region_731d"] = (
            census.groupby("primary_subdivision_code")[metric]
            .rank(method="average", pct=True) * 100.0
        )

    mask = pd.Series(True, index=census.index)
    for metric in METRICS:
        mask &= census[f"{metric}_percentile_same_region_731d"] >= THRESHOLD_PERCENTILE
    reservoir = census.loc[mask].copy()
    reservoir["screening_rule_id"] = "CMORPH_REGION_ANNUAL_P80_INTERSECTION_MAX_P90_P95_V1"
    reservoir["screening_role"] = "HIGH_RECALL_RAINFALL_CANDIDATE_RESERVOIR_NOT_NEGATIVE_LABEL"

    # Development-positive recall audit using direct UTC-date mapping only.
    pos_keys = positives[["date_utc_direct", "primary_subdivision_code", "local_episode_id", "anchor_id"]].copy()
    pos_keys = pos_keys.rename(columns={"date_utc_direct": "date_utc"})
    pos_audit = pos_keys.merge(
        reservoir[["date_utc", "primary_subdivision_code"]].drop_duplicates(),
        on=["date_utc", "primary_subdivision_code"], how="left", indicator=True,
    )
    pos_audit["selected_by_reservoir_direct_utc_date"] = pos_audit["_merge"].eq("both")
    pos_audit = pos_audit.drop(columns=["_merge"])
    recall_count = int(pos_audit["selected_by_reservoir_direct_utc_date"].sum())

    out = Path(a.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    reservoir.to_csv(out / "phase2l_cmorph_candidate_reservoir.csv", index=False)
    pos_audit.to_csv(out / "phase2l_cmorph_candidate_positive_recall_audit.csv", index=False)

    report = {
        "schema_version": "1.0.0",
        "phase": "2L-C-cmorph-high-recall-candidate-reservoir",
        "split": "DEVELOPMENT",
        "source_id": "NOAA_CMORPH_CDR_DAILY_0P25DEG",
        "matched_window_semantics": "OFFICIAL_JMA_PRIMARY_SUBDIVISION_GEOMETRY_BBOX_PLUS_FROZEN_ERA5_0P5_DEG_PADDING",
        "screening_rule_id": "CMORPH_REGION_ANNUAL_P80_INTERSECTION_MAX_P90_P95_V1",
        "rule": {
            "reference_population": "SAME_PRIMARY_SUBDIVISION_ALL_731_DEVELOPMENT_DAYS",
            "percentile_threshold": THRESHOLD_PERCENTILE,
            "required_metrics": METRICS,
            "logic": "ALL_THREE_METRICS_AT_OR_ABOVE_P80",
            "reason": "Rounded high-recall Development-only rainfall severity screen; not optimized against negatives and not an LPZ classifier."
        },
        "input_region_day_count": int(len(census)),
        "selected_region_day_count": int(len(reservoir)),
        "selected_fraction": float(len(reservoir) / len(census)),
        "selected_unique_utc_day_count": int(reservoir["date_utc"].nunique()),
        "positive_episode_count": 65,
        "positive_direct_utc_date_recall_count": recall_count,
        "positive_direct_utc_date_recall_fraction": float(recall_count / 65.0),
        "utc_boundary_warning": "Direct UTC-date recall is only a descriptive gate. Final 3h refinement must evaluate boundary-crossing windows and must not treat UTC daily bins as event windows.",
        "threshold_selected": True,
        "threshold_selection_scope": "DEVELOPMENT_POSITIVE_RECALL_ONLY_NO_NEGATIVE_LABELS_USED",
        "candidate_generated": True,
        "hard_negative_label": None,
        "environment_variables_used_for_selection": False,
        "source_fusion_used": False,
        "imerg_used_for_selection": False,
        "gsmap_used_for_discovery": False,
        "validation_data_used": False,
        "retrospective_2026_used": False,
        "prospective_holdout_used": False,
        "risk_engine_allowed": False,
        "gate": "PASS_CMORPH_HIGH_RECALL_RESERVOIR" if recall_count == 65 else "FAIL_POSITIVE_RECALL"
    }
    (out / "phase2l_cmorph_candidate_reservoir_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["gate","selected_region_day_count","selected_unique_utc_day_count","positive_direct_utc_date_recall_count"]}, ensure_ascii=False))
    return 0 if report["gate"].startswith("PASS") else 2

if __name__ == "__main__":
    raise SystemExit(main())
