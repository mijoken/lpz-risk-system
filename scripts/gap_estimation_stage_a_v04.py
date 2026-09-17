#!/usr/bin/env python3
"""Stage-A v0.4 role-balanced paired gap benchmark.

Offline research only. Uses the role-audit selection (including forced COUNT_EVENT)
and extractor CSVs. It never modifies observations and is not connected to Risk Engine.
"""
from __future__ import annotations
import argparse,csv,json,math
from datetime import datetime,timezone,timedelta
from pathlib import Path
from statistics import mean,median
GAPS=(15,30,60,120,180); MAX_GAP=180

def dt(s): return datetime.fromisoformat(s.replace('Z','+00:00')).astimezone(timezone.utc)
def load(path):
 d={}
 with path.open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   try:v=float(r['value'])
   except:continue
   if math.isfinite(v):d[dt(r['timestamp_utc'])]=v
 return d

def interp(a,b,w,k):
 if k=='ANGLE_CIRCULAR': return (a+w*(((b-a+180)%360)-180))%360
 return a+w*(b-a)
def ae(a,b,k): return abs(((a-b+180)%360)-180) if k=='ANGLE_CIRCULAR' else abs(a-b)
def scale(vals):
 q=sorted(vals); m=median(q); mad=median(abs(x-m) for x in q); span=max(q)-min(q)
 return max(1.4826*mad,span/10,1e-9)
def anchors(d):
 out=[]
 for a in sorted(d):
  req=[a-timedelta(minutes=15)]+[a+timedelta(minutes=15*k) for k in range(MAX_GAP//15+1)]
  if all(t in d for t in req):out.append(a)
 return out

def find_csv(manifest,path):
 for f in manifest['features']:
  if f['feature_path']==path:return f['csv']
 return None

def eval_feature(d,kind,ans):
 sc=scale(list(d.values())); out={}
 for gap in GAPS:
  nmask=gap//15; pairs=[]
  for a in ans:
   lv=d[a-timedelta(minutes=15)]; rv=d[a+timedelta(minutes=gap)]
   for j in range(nmask):
    t=a+timedelta(minutes=15*j); truth=d[t]; est=interp(lv,rv,(j+1)/(nmask+1),kind); pairs.append((truth,est))
  errs=[ae(e,t,kind) for t,e in pairs]; signed=[e-t for t,e in pairs]
  m={'mae':round(mean(errs),4),'rmse':round(math.sqrt(mean((e-t)**2 for t,e in pairs)),4),'bias':round(mean(signed),4),
     'normalized_mae_pct':round(mean(errs)/sc*100,3)}
  if kind=='ANGLE_CIRCULAR':m.update(circular_mae_deg=round(mean(errs),3),within_30deg_pct=round(100*sum(x<=30 for x in errs)/len(errs),2))
  if kind=='COUNT_EVENT':m.update(rounded_exact_pct=round(100*sum(round(e)==round(t) for t,e in pairs)/len(pairs),2),within_1_count_pct=round(100*sum(abs(round(e)-round(t))<=1 for t,e in pairs)/len(pairs),2))
  out[str(gap)]={'paired_windows':len(ans),'n':len(pairs),'metrics':m}
 return out

def main():
 p=argparse.ArgumentParser();p.add_argument('--input-dir',type=Path,required=True);p.add_argument('--role-audit',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 man=json.loads((a.input_dir/'manifest.json').read_text(encoding='utf-8')); audit=json.loads(a.role_audit.read_text(encoding='utf-8'))
 feats=[]; missing=[]
 for s in audit['selected']:
  fn=find_csv(man,s['feature_path'])
  if not fn: missing.append(s['feature_path']); continue
  d=load(a.input_dir/fn); an=anchors(d)
  if not an: missing.append(s['feature_path']); continue
  feats.append({'scientific_role':s['scientific_role'],'feature_type':s['feature_type'],'feature_path':s['feature_path'],'csv':fn,'observation_count':len(d),'paired_anchor_count':len(an),'results_by_gap':eval_feature(d,s['feature_type'],an)})
 report={'schema_version':'0.4.0-gap-stage-a','role':'OFFLINE_ROLE_BALANCED_PAIRED_GAP_BENCHMARK','gap_minutes':list(GAPS),'features':feats,'missing_or_unbenchmarked':missing,'risk_engine_allowed':False,'scientific_observation_values_modified':False}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'selected_from_audit':len(audit['selected']),'benchmarked':len(feats),'missing':len(missing),'count_event_benchmarked':sum(f['feature_type']=='COUNT_EVENT' for f in feats),'paired_anchor_min':min((f['paired_anchor_count'] for f in feats),default=0)},indent=2))
if __name__=='__main__':main()
