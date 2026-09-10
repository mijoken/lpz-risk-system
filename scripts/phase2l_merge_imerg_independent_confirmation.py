#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,glob,json
from pathlib import Path
import numpy as np

PAIRS=[('mean','cmorph_rain_mean_mm_day','imerg_rain_mean_mm_day'),('max','cmorph_rain_max_mm_day','imerg_rain_max_mm_day'),('p90','cmorph_rain_p90_mm_day','imerg_rain_p90_mm_day'),('p95','cmorph_rain_p95_mm_day','imerg_rain_p95_mm_day')]

def rankdata(a):
    order=np.argsort(a,kind='mergesort'); ranks=np.empty(len(a),float); s=0
    while s<len(a):
        e=s+1
        while e<len(a) and a[order[e]]==a[order[s]]: e+=1
        ranks[order[s:e]]=(s+e-1)/2+1; s=e
    return ranks

def corr(x,y):
    x=np.asarray(x,float); y=np.asarray(y,float)
    if len(x)<2 or np.std(x)==0 or np.std(y)==0: return None
    return float(np.corrcoef(x,y)[0,1])

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--shards-dir',required=True); ap.add_argument('--output-dir',required=True); a=ap.parse_args()
    files=sorted(glob.glob(str(Path(a.shards_dir)/'**/phase2l_imerg_confirmation_*.csv'),recursive=True))
    if len(files)!=24: raise ValueError(f'expected 24 monthly CSV shards, got {len(files)}')
    rows=[]
    for fp in files:
        with open(fp,encoding='utf-8',newline='') as f: rows.extend(csv.DictReader(f))
    keys=[(r['date_utc'],r['primary_subdivision_code']) for r in rows]
    if len(rows)!=5943 or len(set(keys))!=5943: raise ValueError(f'expected 5943 unique region-days, got rows={len(rows)} unique={len(set(keys))}')
    if len({r['date_utc'] for r in rows})!=449: raise ValueError('expected 449 unique UTC days')
    metrics={}
    for name,c,i in PAIRS:
        x=np.array([float(r[c]) for r in rows]); y=np.array([float(r[i]) for r in rows]); d=y-x
        metrics[name]={'pearson':corr(x,y),'spearman':corr(rankdata(x),rankdata(y)),'mean_difference_imerg_minus_cmorph_mm_day':float(d.mean()),'median_abs_difference_mm_day':float(np.median(np.abs(d)))}
    out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)
    csvp=out/'phase2l_imerg_independent_confirmation_full.csv'
    with csvp.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    report={'schema_version':'1.0.0','phase':'2L-C-imerg-independent-confirmation-full','split':'DEVELOPMENT','candidate_region_day_count':5943,'confirmed_region_day_count':len(rows),'unique_utc_day_count':449,'source_selection':'CMORPH_ONLY_FROZEN_BEFORE_IMERG','imerg_role':'INDEPENDENT_SOURCE_NATIVE_CONFIRMATION_ONLY','source_agreement_descriptive':metrics,'candidate_membership_changed_by_imerg':False,'source_fusion_used':False,'hard_negative_label':None,'environment_variables_used':False,'gsmap_used_for_discovery':False,'validation_data_used':False,'retrospective_2026_used':False,'prospective_holdout_used':False,'risk_engine_allowed':False,'gate':'PASS_COMPLETE_IMERG_INDEPENDENT_CONFIRMATION_5943_REGION_DAYS'}
    (out/'phase2l_imerg_independent_confirmation_full.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False)); return 0

if __name__=='__main__': raise SystemExit(main())