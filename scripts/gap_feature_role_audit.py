#!/usr/bin/env python3
"""Audit all extracted numeric features by scientific role for gap reconstruction.

Offline research utility only. It does not modify observations, O8.1/O9/Primary,
or Risk Engine. It consumes the extractor manifest and classifies every dynamic
candidate into a scientific role, with mandatory representation of event/count
features so ranking-by-continuity cannot silently omit them.
"""
from __future__ import annotations
import argparse, json
from collections import Counter, defaultdict
from pathlib import Path

ROLE_ORDER=(
 "RAIN_AREA_INTENSITY","LOCATION_MOTION","MORPHOLOGY_SHAPE",
 "WIND_ORIENTATION_SPEED","GENESIS_INFLOW_EVENT","AUXILIARY"
)

def role(path:str)->str:
    p=path.lower()
    if any(x in p for x in ("genesis","inflow","event_count","component_count","object_count","count")):
        return "GENESIS_INFLOW_EVENT"
    if any(x in p for x in ("centroid","motion","displacement","distance_km","speed_km","tracking")):
        return "LOCATION_MOTION"
    if any(x in p for x in ("wind_","600hpa","u_mps","v_mps","speed_mps","wind_axis","wind_from")):
        return "WIND_ORIENTATION_SPEED"
    if any(x in p for x in ("precipitation_pixels","rain","threshold","area_km2","mmph")):
        return "RAIN_AREA_INTENSITY"
    if any(x in p for x in ("aspect_ratio","elongat","orientation","axis_deg","geometry","morphology")):
        return "MORPHOLOGY_SHAPE"
    return "AUXILIARY"

def ftype(path:str)->str:
    p=path.lower()
    if any(x in p for x in ("_deg","angle","axis_deg","wind_from_deg","meteorological_from_deg")): return "ANGLE_CIRCULAR"
    if any(x in p for x in ("count","event_count")): return "COUNT_EVENT"
    if ".centroid.lat" in p or ".centroid.lon" in p: return "COORDINATE"
    return "CONTINUOUS"

def score(x):
    return (x.get("longest_continuous_slots",0),x.get("observation_count",0),x.get("unique_value_count",0))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--manifest',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); ap.add_argument('--per-role',type=int,default=8); a=ap.parse_args()
    m=json.loads(a.manifest.read_text(encoding='utf-8'))
    dynamic=[x for x in m.get('feature_classification_audit',[]) if x.get('classification')=='DYNAMIC_SCIENTIFIC_CANDIDATE']
    groups=defaultdict(list)
    for x in dynamic:
        y=dict(x); y['scientific_role']=role(y['feature_path']); y['feature_type']=ftype(y['feature_path']); groups[y['scientific_role']].append(y)
    selected=[]
    for r in ROLE_ORDER:
        g=sorted(groups[r],key=lambda x:(-score(x)[0],-score(x)[1],-score(x)[2],x['feature_path']))
        # Force count/event coverage first, then fill with strongest remaining features.
        mandatory=[x for x in g if x['feature_type']=='COUNT_EVENT']
        chosen=[]; seen=set()
        for x in mandatory+g:
            if x['feature_path'] in seen: continue
            chosen.append(x); seen.add(x['feature_path'])
            if len(chosen)>=a.per_role: break
        selected.extend(chosen)
    report={
      'schema_version':'0.1.0-gap-feature-role-audit','role':'OFFLINE_SCIENTIFIC_ROLE_SELECTION',
      'dynamic_feature_count':len(dynamic),'role_counts':{r:len(groups[r]) for r in ROLE_ORDER},
      'type_counts':dict(Counter(ftype(x['feature_path']) for x in dynamic)),
      'selection_contract':'up to per-role features; COUNT_EVENT forced before continuity ranking within each role',
      'selected_count':len(selected),'selected':selected,'risk_engine_allowed':False,
      'scientific_observation_values_modified':False
    }
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('dynamic_feature_count','role_counts','type_counts','selected_count')},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
