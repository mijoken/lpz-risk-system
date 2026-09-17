#!/usr/bin/env python3
"""Offline held-out gap reconstruction benchmark for LPZ Stage A.

Production scientific logic is untouched. The benchmark masks only truly
contiguous observed intervals with real observations immediately before and
after the artificial gap. This prevents archive discontinuities from being
mistaken for controlled held-out experiments.
"""
from __future__ import annotations
import argparse, csv, json, math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Protocol

GAP_MINUTES=(15,30,60,120,180)
SCHEMA_VERSION="0.2.0-gap-estimation"

def parse_utc(v:str)->datetime: return datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(timezone.utc)
def iso_utc(v:datetime)->str: return v.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")

@dataclass(frozen=True)
class Observation: time:datetime; value:float
@dataclass
class Reconstruction:
    time:datetime; truth:float; estimate:float; method:str; provenance:str="MODEL_ESTIMATED"

class Estimator(Protocol):
    name:str
    def estimate(self, observations:list[Observation], masked_times:set[datetime])->list[Reconstruction]: ...

class LinearTimeInterpolator:
    name="linear_time_interpolation"
    def estimate(self, observations, masked_times):
        truth={o.time:o.value for o in observations}; available=[o for o in observations if o.time not in masked_times]
        out=[]
        for target in sorted(masked_times):
            before=[o for o in available if o.time<target]; after=[o for o in available if o.time>target]
            if not before or not after: continue
            left,right=before[-1],after[0]; span=(right.time-left.time).total_seconds()
            w=(target-left.time).total_seconds()/span
            out.append(Reconstruction(target,truth[target],left.value+w*(right.value-left.value),self.name))
        return out

def load_csv(path:Path,value_column:str)->list[Observation]:
    rows=[]
    with path.open("r",encoding="utf-8-sig",newline="") as fh:
        reader=csv.DictReader(fh); missing={"timestamp_utc",value_column}-set(reader.fieldnames or [])
        if missing: raise ValueError(f"missing CSV columns: {sorted(missing)}")
        for row in reader:
            try: value=float(row[value_column])
            except (TypeError,ValueError): continue
            if math.isfinite(value): rows.append(Observation(parse_utc(row["timestamp_utc"]),value))
    rows.sort(key=lambda x:x.time)
    if len(rows)<3: raise ValueError("at least three valid observations are required")
    return rows

def infer_step_minutes(rows):
    ds=[int((b.time-a.time).total_seconds()//60) for a,b in zip(rows,rows[1:]) if b.time>a.time]
    if not ds: raise ValueError("could not infer positive observation interval")
    return max(set(ds),key=ds.count)

def mask_windows(rows,gap_minutes,step_minutes):
    n=max(1,math.ceil(gap_minutes/step_minutes)); expected=step_minutes*60
    # Window = left boundary + n masked observations + right boundary.
    # Every adjacent timestamp must be exactly one scientific step apart.
    # Non-overlapping masked intervals are preferred to limit dependence.
    last_mask_end=-1
    for start in range(1,len(rows)-n):
        end=start+n-1
        if start<=last_mask_end: continue
        segment=rows[start-1:start+n+1]
        if len(segment)!=n+2: continue
        if not all((b.time-a.time).total_seconds()==expected for a,b in zip(segment,segment[1:])): continue
        last_mask_end=end
        yield {x.time for x in rows[start:start+n]}

def summarize(rs):
    if not rs: return {"n":0,"mae":None,"rmse":None,"mean_absolute_percent_error":None,"bias":None}
    e=[r.estimate-r.truth for r in rs]; ae=[abs(x) for x in e]
    pct=[abs(r.estimate-r.truth)/abs(r.truth)*100 for r in rs if abs(r.truth)>1e-9]
    return {"n":len(rs),"mae":round(mean(ae),4),"rmse":round(math.sqrt(mean([x*x for x in e])),4),
            "mean_absolute_percent_error":round(mean(pct),3) if pct else None,"bias":round(mean(e),4)}

def run(rows,estimator,gaps):
    step=infer_step_minutes(rows); results={}
    for gap in gaps:
        all_r=[]; windows=0
        for masked in mask_windows(rows,gap,step): windows+=1; all_r.extend(estimator.estimate(rows,masked))
        results[str(gap)]={"gap_minutes":gap,"windows_tested":windows,"metrics":summarize(all_r)}
    return {"schema_version":SCHEMA_VERSION,"benchmark_role":"OFFLINE_HELD_OUT_GAP_RECONSTRUCTION",
            "controlled_gap_windows_require_contiguous_observations":True,
            "scientific_observation_values_modified":False,"risk_engine_allowed":False,"estimator":estimator.name,
            "input":{"observation_count":len(rows),"first_time_utc":iso_utc(rows[0].time),"last_time_utc":iso_utc(rows[-1].time),"inferred_step_minutes":step},
            "results_by_gap":results,"provenance_contract":{"estimated":"MODEL_ESTIMATED","estimated_never_promoted_to_observed":True}}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",required=True,type=Path); p.add_argument("--value-column",default="value")
    p.add_argument("--output",required=True,type=Path); p.add_argument("--gap-minutes",nargs="*",type=int,default=list(GAP_MINUTES)); a=p.parse_args()
    gaps=tuple(sorted(set(a.gap_minutes)))
    if not gaps or any(x<=0 for x in gaps): raise ValueError("gap minutes must be positive")
    report=run(load_csv(a.input,a.value_column),LinearTimeInterpolator(),gaps); a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps(report,ensure_ascii=False,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
