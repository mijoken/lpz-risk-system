#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pandas as pd

FINAL_V07_LAST_DATE = "2025-09-30"
EXPECTED_TARGET_COUNT = 1218
EXPECTED_POSITIVE_COUNT = 23
EXPECTED_ROLLING_WINDOWS = 53
EXPECTED_J_GATE = "PASS_PHASE2L_J_2025_CMORPH_FROZEN_SCREEN_365D_18REGIONS"
EXPECTED_DAILY_GATE = "PASS_PHASE2L_K_2025_IMERG_ROLLING_3H_DAY"
GATE = "REVIEW_PHASE2L_K_IMERG_FINAL_V07_OFFICIAL_SOURCE_TRUNCATION_2025_09_30"

def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def atomic_write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    _ = tmp.read_text(encoding="utf-8")
    tmp.replace(path)

def atomic_write_json(path: Path, payload: dict[str, Any]):
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    json.loads(text)
    atomic_write_text(path, text)

def atomic_write_csv(path: Path, df: pd.DataFrame):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False)
    _ = pd.read_csv(tmp, dtype={"primary_subdivision_code":"string"})
    tmp.replace(path)

def parse_bool_series(s: pd.Series, name: str) -> pd.Series:
    if s.dtype == bool:
        return s
    mapped = s.astype(str).str.strip().str.lower().map(
        {"true":True,"false":False,"1":True,"0":False}
    )
    if mapped.isna().any():
        raise ValueError(f"cannot parse boolean column {name}")
    return mapped.astype(bool)

def circular_calendar_day_distance(a: pd.Timestamp, b: pd.Timestamp) -> int:
    aa = pd.Timestamp(year=2000, month=a.month, day=a.day)
    bb = pd.Timestamp(year=2000, month=b.month, day=b.day)
    d = abs((aa-bb).days)
    return int(min(d, 366-d))

def checkpoint_path(root: Path, date_s: str) -> Path:
    return root / "daily" / date_s[:7] / f"{date_s}.json"

def read_valid_checkpoint(path: Path, date_s: str):
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if obj.get("gate") != EXPECTED_DAILY_GATE or obj.get("date_utc") != date_s:
        return None
    rows = obj.get("rows")
    if not isinstance(rows,list):
        return None
    for row in rows:
        if int(row.get("rolling_window_count",-1)) != EXPECTED_ROLLING_WINDOWS:
            return None
    return obj

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--targets",required=True,type=Path)
    ap.add_argument("--phase2lj-report",required=True,type=Path)
    ap.add_argument("--phase2lk-output-dir",required=True,type=Path)
    ap.add_argument("--output-dir",required=True,type=Path)
    a=ap.parse_args()

    targets_path=a.targets.resolve()
    j_report_path=a.phase2lj_report.resolve()
    k_root=a.phase2lk_output_dir.resolve()
    outdir=a.output_dir.resolve()
    outdir.mkdir(parents=True,exist_ok=True)

    j_report=json.loads(j_report_path.read_text(encoding="utf-8"))
    if j_report.get("gate") != EXPECTED_J_GATE:
        raise ValueError(f"Phase 2L-J gate mismatch: {j_report.get('gate')}")

    targets=pd.read_csv(targets_path,dtype={"primary_subdivision_code":"string"})
    required={"date_utc","primary_subdivision_code","is_official_positive","selected_by_frozen_cmorph_screen","refinement_role"}
    miss=sorted(required-set(targets.columns))
    if miss:
        raise ValueError(f"target table missing columns: {miss}")
    targets["primary_subdivision_code"]=targets["primary_subdivision_code"].astype("string").str.zfill(6)
    targets["date_utc"]=pd.to_datetime(targets["date_utc"]).dt.strftime("%Y-%m-%d")
    targets["date_ts"]=pd.to_datetime(targets["date_utc"],utc=True)
    targets["is_official_positive"]=parse_bool_series(targets["is_official_positive"],"is_official_positive")
    targets["selected_by_frozen_cmorph_screen"]=parse_bool_series(targets["selected_by_frozen_cmorph_screen"],"selected_by_frozen_cmorph_screen")
    if len(targets)!=EXPECTED_TARGET_COUNT:
        raise ValueError(f"expected {EXPECTED_TARGET_COUNT} targets, got {len(targets)}")
    if int(targets["is_official_positive"].sum())!=EXPECTED_POSITIVE_COUNT:
        raise ValueError("unexpected Positive count")
    if targets.duplicated(["date_utc","primary_subdivision_code"]).any():
        raise ValueError("duplicate target keys")

    cutoff_ts=pd.Timestamp(FINAL_V07_LAST_DATE,tz="UTC")
    targets["final_v07_nominal_date_supported"]=targets["date_ts"]<=cutoff_ts

    cp_rows=[]
    for date_s, day_targets in targets.groupby("date_utc",sort=True):
        obj=read_valid_checkpoint(checkpoint_path(k_root,date_s),date_s)
        cp_rows.append({
            "date_utc":date_s,
            "expected_target_region_days":int(len(day_targets)),
            "valid_checkpoint":bool(obj is not None),
            "checkpoint_row_count":int(len(obj["rows"])) if obj is not None else 0,
            "source_supported_by_final_v07":bool(date_s<=FINAL_V07_LAST_DATE),
        })
    checkpoint_audit=pd.DataFrame(cp_rows)
    supported_missing=checkpoint_audit.loc[
        checkpoint_audit["source_supported_by_final_v07"] & ~checkpoint_audit["valid_checkpoint"]
    ].copy()
    unsupported_present=checkpoint_audit.loc[
        ~checkpoint_audit["source_supported_by_final_v07"] & checkpoint_audit["valid_checkpoint"]
    ].copy()

    positives=targets.loc[targets["is_official_positive"]].copy()
    positive_dates_by_region={
        str(region):list(group["date_ts"])
        for region,group in positives.groupby("primary_subdivision_code")
    }
    candidates=targets.loc[
        targets["selected_by_frozen_cmorph_screen"] & ~targets["is_official_positive"]
    ].copy()

    impact=[]
    for _,p in positives.sort_values(["date_utc","primary_subdivision_code"]).iterrows():
        region=str(p["primary_subdivision_code"])
        pool=candidates.loc[candidates["primary_subdivision_code"].astype(str)==region].copy()
        pool["season_day_difference"]=pool["date_ts"].map(
            lambda d:circular_calendar_day_distance(d,p["date_ts"])
        )
        pool=pool.loc[pool["season_day_difference"]<=60].copy()
        pos_dates=positive_dates_by_region.get(region,[])
        if pos_dates:
            near=pool["date_ts"].map(
                lambda d:any(abs((d.normalize()-q.normalize()).days)<=3 for q in pos_dates)
            )
            pool=pool.loc[~near].copy()
        unavailable=pool.loc[~pool["final_v07_nominal_date_supported"]]
        impact.append({
            "positive_date_utc":p["date_utc"],
            "primary_subdivision_code":region,
            "positive_final_v07_supported":bool(p["final_v07_nominal_date_supported"]),
            "eligible_comparison_candidates_total_cmorph_only":int(len(pool)),
            "eligible_comparison_candidates_v07_supported":int(pool["final_v07_nominal_date_supported"].sum()),
            "eligible_comparison_candidates_v07_unavailable":int(len(unavailable)),
            "frozen_matching_candidate_universe_fully_observable":bool(
                len(unavailable)==0 and p["final_v07_nominal_date_supported"]
            ),
            "unavailable_candidate_date_min":str(unavailable["date_utc"].min()) if len(unavailable) else None,
            "unavailable_candidate_date_max":str(unavailable["date_utc"].max()) if len(unavailable) else None,
        })
    positive_impact=pd.DataFrame(impact)

    target_partition_path=outdir/"phase2l_k_final_v07_target_partition.csv"
    checkpoint_path_out=outdir/"phase2l_k_final_v07_checkpoint_audit.csv"
    positive_impact_path=outdir/"phase2l_k_final_v07_positive_matching_impact.csv"
    report_path=outdir/"phase2l_k_final_v07_source_truncation_report.json"

    atomic_write_csv(target_partition_path,targets.drop(columns=["date_ts"]).sort_values(["date_utc","primary_subdivision_code"]))
    atomic_write_csv(checkpoint_path_out,checkpoint_audit)
    atomic_write_csv(positive_impact_path,positive_impact)

    supported_targets=int(targets["final_v07_nominal_date_supported"].sum())
    unsupported_targets=int((~targets["final_v07_nominal_date_supported"]).sum())
    supported_positive=int(positives["final_v07_nominal_date_supported"].sum())
    unsupported_positive=int((~positives["final_v07_nominal_date_supported"]).sum())
    fully_observable=int(positive_impact["frozen_matching_candidate_universe_fully_observable"].sum())

    report={
        "schema_version":"1.0.0",
        "phase":"2L-K-IMERG-Final-V07-source-truncation-audit",
        "gate":GATE,
        "generated_at_utc":utc_now(),
        "official_source":{
            "source_id":"NASA_IMERG_FINAL_V07_HALFHOUR",
            "short_name":"GPM_3IMERGHH",
            "version":"07",
            "final_available_nominal_utc_date":FINAL_V07_LAST_DATE,
            "final_available_half_hour_start_utc":"2025-09-30T23:30:00Z",
            "reason":"Official IMERG Final V07 record ends in September 2025 during the V08 transition."
        },
        "targets":{
            "total_region_days":int(len(targets)),
            "unique_target_days":int(targets["date_utc"].nunique()),
            "v07_supported_region_days":supported_targets,
            "v07_unavailable_region_days":unsupported_targets,
            "v07_supported_unique_days":int(checkpoint_audit["source_supported_by_final_v07"].sum()),
            "v07_unavailable_unique_days":int((~checkpoint_audit["source_supported_by_final_v07"]).sum())
        },
        "checkpoints":{
            "valid_total_unique_days":int(checkpoint_audit["valid_checkpoint"].sum()),
            "v07_supported_unique_days_missing_checkpoint":int(len(supported_missing)),
            "v07_unavailable_unique_days_with_checkpoint":int(len(unsupported_present)),
            "supported_segment_complete":bool(len(supported_missing)==0)
        },
        "official_positive_region_days":{
            "total":int(len(positives)),
            "v07_supported":supported_positive,
            "v07_unavailable":unsupported_positive,
            "v07_unavailable_rows":positives.loc[
                ~positives["final_v07_nominal_date_supported"],
                ["date_utc","primary_subdivision_code"]
            ].sort_values(["date_utc","primary_subdivision_code"]).to_dict("records")
        },
        "frozen_matching_impact":{
            "positive_region_days_with_entire_cmorph_eligible_pool_observable_under_v07":fully_observable,
            "positive_region_days_with_source_truncated_candidate_universe":int(len(positive_impact)-fully_observable),
            "interpretation":"Any unavailable eligible comparison means exact frozen IMERG distance ordering cannot be known."
        },
        "scientific_policy":{
            "fill_oct_dec_with_late_or_early_for_primary_validation":False,
            "fill_oct_dec_with_other_satellite_for_primary_validation":False,
            "refit_pca_on_partial_2025":False,
            "change_primary_hypothesis":False,
            "open_era5_before_rainfall_matching_resolved":False,
            "risk_engine_allowed":False,
            "recommended_status":"FULL_2025_CONFIRMATORY_VALIDATION_PENDING_CONSISTENT_RESEARCH_QUALITY_IMERG_SOURCE"
        },
        "outputs":{
            "target_partition_csv":str(target_partition_path),
            "checkpoint_audit_csv":str(checkpoint_path_out),
            "positive_matching_impact_csv":str(positive_impact_path)
        }
    }
    atomic_write_json(report_path,report)

    print("="*104)
    print("LPZ PHASE 2L-K — IMERG FINAL V07 OFFICIAL SOURCE TRUNCATION AUDIT")
    print("="*104)
    print(f"Final V07 last nominal UTC date          : {FINAL_V07_LAST_DATE}")
    print(f"Targets total                            : {len(targets)}")
    print(f"V07-supported targets                    : {supported_targets}")
    print(f"V07-unavailable targets                  : {unsupported_targets}")
    print(f"Unique target days total                 : {targets['date_utc'].nunique()}")
    print(f"V07-supported unique target days         : {int(checkpoint_audit['source_supported_by_final_v07'].sum())}")
    print(f"V07-unavailable unique target days       : {int((~checkpoint_audit['source_supported_by_final_v07']).sum())}")
    print(f"Valid day checkpoints                    : {int(checkpoint_audit['valid_checkpoint'].sum())}")
    print(f"Supported days missing checkpoint        : {len(supported_missing)}")
    print(f"Official Positive region-days            : {len(positives)}")
    print(f"Positive region-days V07-supported       : {supported_positive}")
    print(f"Positive region-days V07-unavailable     : {unsupported_positive}")
    print(f"Positive match universes fully observed  : {fully_observable} / {len(positive_impact)}")
    print("ERA5/environment read                    : NO")
    print("Rainfall matching performed              : NO")
    print("PCA refit                                : NO")
    print("Primary changed                          : NO")
    print("Risk engine                              : NOT ALLOWED")
    print("")
    print(f"Gate                                     : {GATE}")
    print(f"Report                                   : {report_path}")
    print("="*104)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
