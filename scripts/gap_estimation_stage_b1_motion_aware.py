#!/usr/bin/env python3
"""Stage B-1: motion-aware feature reconstruction benchmark.

Offline research only. Compares frozen Stage-A v0.5 linear interpolation with
one-sided constant-velocity extrapolation derived strictly from observations
available before each artificial gap. No future endpoint is used by the
motion-aware estimator. O8.1/O9/Primary/Risk Engine are untouched.
"""
from __future__ import annotations
import argparse,csv,json,math
from datetime import datetime,timezone,timedelta
from pathlib import Path
from statistics import mean,median
GAPS=(15,30,60,120,180);MAX=180
ELIGIBLE=('COORDINATE','NONNEGATIVE_CONTINUOUS','GENERIC_CONTINUOUS')

def dt(s): return datetime.fromisoformat(s.replace('Z','+00:00')).astimezone(timezone.utc)
def load(p):
 d={}
 with p.open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   try:v=float(r['value'])
   except:continue
   if math.isfinite(v): d[dt(r['timestamp_utc'])]=v
 return d
def robust_scale(v):
 m=median(v);mad=median(abs(x-m) for x in v);return max(1.4826*mad,(max(v)-min(v))/10,1e-9)
def anchors(d):
 # Need two pre-gap observations (-30,-15), all truths through 165m, and the
 # future boundary at gap length for the frozen two-sided linear baseline.
 out=[]
 for a in sorted(d):
  need=[a-timedelta(minutes=30),a-timedelta(minutes=15)]
  need += [a+timedelta(minutes=15*k) for k in range(MAX//15+1)]
  if all(t in d for t in need): out.append(a)
 return out
def csv_for(m,path):
 for x in m['features']:
  if x['feature_path']==path:return x['csv']
def linear(left,right,j,n): return left+(j+1)/(n+1)*(right-left)
def motion(prev,left,j):
 # Constant velocity from the two latest pre-gap 15-minute observations.
 velocity=left-prev
 return left+(j+1)*velocity
def metrics(pairs,scale):
 ae=[abs(e-t) for t,e in pairs]
 return {'mae':round(mean(ae),4),'normalized_mae_pct':round(mean(ae)/scale*100,3)}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input-dir',type=Path,required=True);ap.add_argument('--type-audit',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
 man=json.loads((a.input_dir/'manifest.json').read_text(encoding='utf-8'));ta=json.loads(a.type_audit.read_text(encoding='utf-8'))
 feats=[];skipped=[]
 for x in ta['selected']:
  typ=x['feature_type_v02'];path=x['feature_path']
  if typ not in ELIGIBLE:
   skipped.append({'feature_path':path,'feature_type':typ,'reason':'not_scalar_motion_candidate'});continue
  fn=csv_for(man,path)
  if not fn:
   skipped.append({'feature_path':path,'feature_type':typ,'reason':'csv_missing'});continue
  d=load(a.input_dir/fn);an=anchors(d)
  if not an:
   skipped.append({'feature_path':path,'feature_type':typ,'reason':'no_paired_anchor'});continue
  sc=robust_scale(list(d.values()));by={}
  for g in GAPS:
   n=g//15;base=[];mot=[]
   for q in an:
    prev=d[q-timedelta(minutes=30)];left=d[q-timedelta(minutes=15)];right=d[q+timedelta(minutes=g)]
    for j in range(n):
     truth=d[q+timedelta(minutes=15*j)]
     base.append((truth,linear(left,right,j,n)))
     mot.append((truth,motion(prev,left,j)))
   bm=metrics(base,sc);mm=metrics(mot,sc);b=bm['normalized_mae_pct'];m=mm['normalized_mae_pct']
   improvement=(b-m)/b*100 if b>1e-12 else (0.0 if m<=1e-12 else -math.inf)
   by[str(g)]={'paired_windows':len(an),'n':len(base),'baseline_linear':bm,'motion_aware':mm,'normalized_mae_improvement_pct':None if not math.isfinite(improvement) else round(improvement,3),'winner':'MOTION_AWARE' if m<b else ('TIE' if abs(m-b)<1e-12 else 'LINEAR_BASELINE')}
  feats.append({'scientific_role':x['scientific_role'],'feature_type':typ,'feature_path':path,'paired_anchor_count':len(an),'results_by_gap':by})
 rep={'schema_version':'0.1.0-gap-stage-b1','role':'OFFLINE_MOTION_AWARE_RECONSTRUCTION_BENCHMARK','comparison':'FROZEN_LINEAR_BASELINE_VS_CAUSAL_CONSTANT_VELOCITY','important_method_note':'Motion-aware uses only t-30 and t-15 observations. Linear baseline uses t-15 and the post-gap right boundary, matching Stage-A v0.5 interpolation semantics. Therefore this benchmark tests whether simple causal persistence-of-velocity is competitive; it is not yet a like-for-like causal baseline comparison.','gap_minutes':list(GAPS),'eligible_types':list(ELIGIBLE),'features':feats,'skipped':skipped,'risk_engine_allowed':False,'scientific_observation_values_modified':False}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 wins=sum(z['winner']=='MOTION_AWARE' for f in feats for z in f['results_by_gap'].values());tests=len(feats)*len(GAPS)
 print(json.dumps({'benchmarked_features':len(feats),'comparison_cells':tests,'motion_aware_wins':wins,'linear_baseline_wins_or_ties':tests-wins,'paired_anchor_min':min((f['paired_anchor_count'] for f in feats),default=0),'skipped_count':len(skipped)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
