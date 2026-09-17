#!/usr/bin/env python3
"""Extract dynamic scientific numeric features for offline gap-estimation tests.

This Stage-A utility is isolated from O8.1, O9, Primary, ERA5 and Risk Engine.
Only COMPLETE canonical slots are eligible; gaps/incomplete slots are never
imputed here. Numeric leaves are classified before selection so configuration,
transport/HTTP, provenance and other operational metadata cannot dominate the
benchmark merely because they are well covered.
"""
from __future__ import annotations
import argparse,csv,gzip,json,math
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
from typing import Any,Iterable
UTC=timezone.utc
EXCLUDE_TOKENS=("transport","http_status","bytes","tile_count","origin_tile_",".zoom","threshold_mmph",
"forecast_hour","representative_valid_time_error_minutes","minimum_cycle_age_hours","recovery_age_minutes",
"generated_at","run_id","github_","latency","schema_version","as_of","raw_radar_archived","raw_grib_archived")
def parse_utc(v): return datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(UTC)
def iso_utc(v): return v.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00","Z")
def iter_numeric_leaves(value:Any,prefix:str="")->Iterable[tuple[str,float]]:
    if isinstance(value,bool) or value is None:return
    if isinstance(value,(int,float)):
        n=float(value)
        if math.isfinite(n):yield prefix or "value",n
        return
    if isinstance(value,dict):
        for key in sorted(value):yield from iter_numeric_leaves(value[key],f"{prefix}.{key}" if prefix else str(key))
def read_archive(path):
    rows=[]
    with gzip.open(path,"rt",encoding="utf-8") as fh:
        for i,line in enumerate(fh,1):
            if not line.strip():continue
            obj=json.loads(line)
            if not isinstance(obj,dict):raise ValueError(f"{path}:{i}: canonical row is not an object")
            rows.append(obj)
    return rows
def continuous_run_lengths(times,step_minutes=15):
    if not times:return []
    ordered=sorted(set(times));runs=[];current=1
    for left,right in zip(ordered,ordered[1:]):
        if int((right-left).total_seconds()//60)==step_minutes:current+=1
        else:runs.append(current);current=1
    runs.append(current);return runs
def classify_feature(feature,values):
    lower=feature.lower()
    for token in EXCLUDE_TOKENS:
        if token in lower:return "EXCLUDED_METADATA_OR_CONFIGURATION",f"matched:{token}"
    unique=len(set(values))
    if unique<=1:return "EXCLUDED_CONSTANT","single_unique_value"
    if unique<=2 and len(values)>=24:return "EXCLUDED_LOW_VARIATION",f"unique_values:{unique}"
    return "DYNAMIC_SCIENTIFIC_CANDIDATE","dynamic_numeric_feature"
def safe_name(feature):return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in feature).strip("_")[:180]
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--input",nargs="+",required=True,type=Path);ap.add_argument("--output-dir",required=True,type=Path)
    ap.add_argument("--min-observations",type=int,default=24);ap.add_argument("--min-continuous-slots",type=int,default=14);ap.add_argument("--top",type=int,default=30);args=ap.parse_args()
    feature_rows=defaultdict(list);slot_counts={"complete":0,"explicit_gap":0,"technical_incomplete":0,"other":0}
    for archive in sorted(args.input):
        for row in read_archive(archive):
            state=str(row.get("slot_state") or "")
            if state=="COMPLETE":slot_counts["complete"]+=1
            elif state=="EXPLICIT_GAP":slot_counts["explicit_gap"]+=1;continue
            elif state=="TECHNICAL_INCOMPLETE":slot_counts["technical_incomplete"]+=1;continue
            else:slot_counts["other"]+=1;continue
            slot_raw,bundle=row.get("collection_slot_utc"),row.get("bundle")
            if not isinstance(slot_raw,str) or not isinstance(bundle,dict):continue
            slot=parse_utc(slot_raw);role=str(row.get("selected_archive_role") or "")
            for feature,numeric in iter_numeric_leaves(bundle):feature_rows[feature].append((slot,numeric,role,archive.name))
    candidates=[];audit=[]
    for feature,values in feature_rows.items():
        by_time={}
        for t,v,role,source in sorted(values,key=lambda x:(x[0],x[3])):by_time.setdefault(t,(v,role,source))
        times=sorted(by_time);numeric_values=[by_time[t][0] for t in times];runs=continuous_run_lengths(times);category,reason=classify_feature(feature,numeric_values)
        audit.append({"feature_path":feature,"classification":category,"reason":reason,"observation_count":len(times),"unique_value_count":len(set(numeric_values)),"longest_continuous_slots":max(runs) if runs else 0})
        if category=="DYNAMIC_SCIENTIFIC_CANDIDATE":candidates.append({"feature":feature,"observation_count":len(times),"unique_value_count":len(set(numeric_values)),"longest_continuous_slots":max(runs) if runs else 0,"continuous_run_count":len(runs),"rows":by_time})
    eligible=[c for c in candidates if c["observation_count"]>=args.min_observations and c["longest_continuous_slots"]>=args.min_continuous_slots]
    eligible.sort(key=lambda c:(-c["longest_continuous_slots"],-c["observation_count"],-c["unique_value_count"],c["feature"]));selected=eligible[:max(0,args.top)]
    args.output_dir.mkdir(parents=True,exist_ok=True)
    for old in args.output_dir.glob("*.csv"):old.unlink()
    mf=[]
    for rank,item in enumerate(selected,1):
        filename=f"{rank:02d}_{safe_name(item['feature'])}.csv"
        with (args.output_dir/filename).open("w",encoding="utf-8",newline="") as fh:
            w=csv.writer(fh);w.writerow(["timestamp_utc","value","archive_role","source_archive","feature_path"])
            for t in sorted(item["rows"]):value,role,source=item["rows"][t];w.writerow([iso_utc(t),repr(value),role,source,item["feature"]])
        mf.append({"rank":rank,"feature_path":item["feature"],"csv":filename,"observation_count":item["observation_count"],"unique_value_count":item["unique_value_count"],"longest_continuous_slots":item["longest_continuous_slots"],"longest_continuous_minutes":(item["longest_continuous_slots"]-1)*15,"continuous_run_count":item["continuous_run_count"]})
    counts=defaultdict(int)
    for row in audit:counts[row["classification"]]+=1
    manifest={"schema_version":"0.2.1-gap-stage-a-extractor","role":"OFFLINE_GAP_ESTIMATION_STAGE_A_INPUT","input_archives":[str(p) for p in sorted(args.input)],"slot_counts":slot_counts,"numeric_feature_count_discovered":len(audit),"classification_counts":dict(sorted(counts.items())),"dynamic_candidate_count":len(candidates),"eligible_dynamic_feature_count":len(eligible),"selected_feature_count":len(selected),"selection":{"min_observations":args.min_observations,"min_continuous_slots":args.min_continuous_slots,"top":args.top},"features":mf,"feature_classification_audit":sorted(audit,key=lambda x:x["feature_path"]),"estimated_values_created":False,"risk_engine_allowed":False}
    (args.output_dir/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(json.dumps(manifest,ensure_ascii=False,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
