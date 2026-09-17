#!/usr/bin/env python3
"""Stage-A v0.3: type-aware, paired-window gap reconstruction benchmark.

Offline research only. Does not modify observations and is not connected to Risk Engine.
Consumes extractor manifest + selected CSVs. Evaluates the same anchor windows across
15/30/60/120/180-minute gaps where the full 180-minute context is continuous.
Feature-aware metrics: circular angle error, count/event rounded agreement, and robust
scale-normalized absolute error for continuous/coordinate features.
"""
from __future__ import annotations
import argparse, csv, json, math
from datetime import datetime, timezone
from pathlib import Path
from statistics import median, mean

GAPS=(15,30,60,120,180)
MAX_GAP=max(GAPS)

def dt(s): return datetime.fromisoformat(s.replace('Z','+00:00')).astimezone(timezone.utc)

def load_csv(path):
    out=[]
    with path.open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            try: v=float(r['value'])
            except (ValueError,TypeError): continue
            if math.isfinite(v): out.append((dt(r['timestamp_utc']),v))
    return sorted(dict(out).items())

def ftype(name):
    n=name.lower()
    if any(x in n for x in ('_deg','angle','axis_deg','wind_from_deg','meteorological_from_deg')): return 'ANGLE_CIRCULAR'
    if any(x in n for x in ('count','event_count','genesis_by_threshold')): return 'COUNT_EVENT'
    if '.centroid.lat' in n or '.centroid.lon' in n: return 'COORDINATE'
    return 'CONTINUOUS'

def interp(a,b,w,kind):
    if kind=='ANGLE_CIRCULAR':
        # shortest signed arc in degrees
        d=((b-a+180.0)%360.0)-180.0
        return (a+w*d)%360.0
    return a+w*(b-a)

def circerr(a,b): return abs(((a-b+180.0)%360.0)-180.0)

def robust_scale(vals):
    if not vals: return None
    q=sorted(vals); m=median(q); mad=median([abs(x-m) for x in q])
    span=max(q)-min(q)
    return max(1.4826*mad, span/10.0, 1e-9)

def paired_windows(rows):
    by=dict(rows); times=[t for t,_ in rows]; step=15
    # anchor is first masked point. Require observation immediately before anchor,
    # every 15m through max gap, and one observation after max gap.
    for anchor in times:
        left=anchor.timestamp()-step*60
        left=datetime.fromtimestamp(left,timezone.utc)
        required=[left]
        for k in range(0,MAX_GAP//step+1):
            required.append(datetime.fromtimestamp(anchor.timestamp()+k*step*60,timezone.utc))
        if all(t in by for t in required): yield anchor

def evaluate(rows,name):
    kind=ftype(name); by=dict(rows); anchors=list(paired_windows(rows)); scale=robust_scale([v for _,v in rows])
    result={}
    for gap in GAPS:
        nmask=gap//15; rec=[]
        for anchor in anchors:
            left=datetime.fromtimestamp(anchor.timestamp()-15*60,timezone.utc)
            right=datetime.fromtimestamp(anchor.timestamp()+nmask*15*60,timezone.utc)
            lv,rv=by[left],by[right]
            for j in range(nmask):
                t=datetime.fromtimestamp(anchor.timestamp()+j*15*60,timezone.utc)
                truth=by[t]; w=(j+1)/(nmask+1); est=interp(lv,rv,w,kind)
                rec.append((truth,est))
        if not rec:
            result[str(gap)]={'paired_windows':0,'n':0}; continue
        if kind=='ANGLE_CIRCULAR':
            ae=[circerr(e,t) for t,e in rec]
        else: ae=[abs(e-t) for t,e in rec]
        signed=[e-t for t,e in rec]
        metrics={'mae':round(mean(ae),4),'rmse':round(math.sqrt(mean([(e-t)**2 for t,e in rec])),4),
                 'bias':round(mean(signed),4),'normalized_mae_pct':round(mean(ae)/scale*100,3) if scale else None}
        if kind=='ANGLE_CIRCULAR':
            metrics.update({'circular_mae_deg':round(mean(ae),3),'within_15deg_pct':round(sum(x<=15 for x in ae)/len(ae)*100,2),
                            'within_30deg_pct':round(sum(x<=30 for x in ae)/len(ae)*100,2)})
        if kind=='COUNT_EVENT':
            metrics.update({'rounded_exact_pct':round(sum(round(e)==round(t) for t,e in rec)/len(rec)*100,2),
                            'within_1_count_pct':round(sum(abs(round(e)-round(t))<=1 for t,e in rec)/len(rec)*100,2)})
        result[str(gap)]={'paired_windows':len(anchors),'n':len(rec),'metrics':metrics}
    return {'feature_path':name,'feature_type':kind,'observation_count':len(rows),'paired_anchor_count':len(anchors),
            'robust_scale':scale,'results_by_gap':result}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input-dir',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args()
    manifest=json.loads((a.input_dir/'manifest.json').read_text(encoding='utf-8'))
    feats=[]
    for f in manifest['features']:
        rows=load_csv(a.input_dir/f['csv']); x=evaluate(rows,f['feature_path']); x['rank']=f['rank']; x['csv']=f['csv']; feats.append(x)
    report={'schema_version':'0.3.0-gap-stage-a','role':'OFFLINE_TYPE_AWARE_PAIRED_GAP_BENCHMARK',
            'gap_minutes':list(GAPS),'pairing_contract':'same anchors for all gap lengths; full 180-minute context must be continuous',
            'scientific_observation_values_modified':False,'risk_engine_allowed':False,'features':feats}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'schema_version':report['schema_version'],'feature_count':len(feats),'paired_anchor_min':min((x['paired_anchor_count'] for x in feats),default=0),'paired_anchor_max':max((x['paired_anchor_count'] for x in feats),default=0)},indent=2))
if __name__=='__main__': main()
