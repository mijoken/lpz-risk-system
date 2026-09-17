#!/usr/bin/env python3
"""Stage-A v0.5: typed linear temporal interpolation baseline.
Offline research only; no observation mutation; Risk Engine locked.
"""
from __future__ import annotations
import argparse,csv,json,math
from datetime import datetime,timezone,timedelta
from pathlib import Path
from statistics import mean,median
GAPS=(15,30,60,120,180);MAX=180

def dt(s):return datetime.fromisoformat(s.replace('Z','+00:00')).astimezone(timezone.utc)
def load(p):
 d={}
 with p.open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   try:v=float(r['value'])
   except:continue
   if math.isfinite(v):d[dt(r['timestamp_utc'])]=v
 return d
def anchors(d):
 return [a for a in sorted(d) if all(t in d for t in [a-timedelta(minutes=15)]+[a+timedelta(minutes=15*k) for k in range(MAX//15+1)])]
def robust_scale(v):
 m=median(v);mad=median(abs(x-m) for x in v);return max(1.4826*mad,(max(v)-min(v))/10,1e-9)
def circdiff(a,b):return ((a-b+180)%360)-180
def interp(a,b,w,t):
 if t=='DIRECTION_CIRCULAR':return (a+w*circdiff(b,a))%360
 return a+w*(b-a)
def err(e,t,k):return abs(circdiff(e,t)) if k=='DIRECTION_CIRCULAR' else abs(e-t)
def csv_for(m,path):
 for x in m['features']:
  if x['feature_path']==path:return x['csv']

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input-dir',type=Path,required=True);ap.add_argument('--type-audit',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
 man=json.loads((a.input_dir/'manifest.json').read_text(encoding='utf-8'));ta=json.loads(a.type_audit.read_text(encoding='utf-8'));features=[];missing=[]
 for x in ta['selected']:
  fn=csv_for(man,x['feature_path'])
  if not fn:missing.append(x['feature_path']);continue
  d=load(a.input_dir/fn);an=anchors(d)
  if not an:missing.append(x['feature_path']);continue
  typ=x['feature_type_v02'];sc=robust_scale(list(d.values()));by={}
  for g in GAPS:
   nm=g//15;pairs=[]
   for q in an:
    l=d[q-timedelta(minutes=15)];r=d[q+timedelta(minutes=g)]
    for j in range(nm):
     truth=d[q+timedelta(minutes=15*j)];est=interp(l,r,(j+1)/(nm+1),typ);pairs.append((truth,est))
   ae=[err(e,t,typ) for t,e in pairs]
   met={'mae':round(mean(ae),4),'normalized_mae_pct':round(mean(ae)/sc*100,3)}
   if typ=='DIRECTION_CIRCULAR':met.update(circular_mae_deg=round(mean(ae),3),within_30deg_pct=round(100*sum(z<=30 for z in ae)/len(ae),2))
   elif typ=='BOUNDED_ANGLE':met.update(within_10deg_pct=round(100*sum(z<=10 for z in ae)/len(ae),2),within_30deg_pct=round(100*sum(z<=30 for z in ae)/len(ae),2))
   elif typ=='EVENT_COUNT':met.update(rounded_exact_pct=round(100*sum(round(e)==round(t) for t,e in pairs)/len(pairs),2),within_1_count_pct=round(100*sum(abs(round(e)-round(t))<=1 for t,e in pairs)/len(pairs),2))
   elif typ=='EXTENSIVE_COUNT':met.update(relative_mae_pct=round(100*mean(abs(e-t)/max(abs(t),1.0) for t,e in pairs),3))
   by[str(g)]={'paired_windows':len(an),'n':len(pairs),'metrics':met}
  features.append({'scientific_role':x['scientific_role'],'feature_type':typ,'feature_path':x['feature_path'],'paired_anchor_count':len(an),'results_by_gap':by})
 rep={'schema_version':'0.5.0-gap-stage-a','role':'OFFLINE_TYPED_LINEAR_TEMPORAL_BASELINE','baseline_method':'LINEAR_TEMPORAL_INTERPOLATION','gap_minutes':list(GAPS),'features':features,'missing_or_unbenchmarked':missing,'risk_engine_allowed':False,'scientific_observation_values_modified':False,'interpretation_guardrail':'This is a baseline estimator, not evidence that all feature classes are scientifically reconstructable by linear interpolation.'}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'benchmarked':len(features),'missing':len(missing),'type_counts':{t:sum(f['feature_type']==t for f in features) for t in sorted(set(f['feature_type'] for f in features))},'paired_anchor_min':min((f['paired_anchor_count'] for f in features),default=0)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
