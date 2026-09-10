#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,glob,json
from pathlib import Path
import numpy as np

METRICS=['mean','max','p90','p95']

def q(a,p): return float(np.percentile(np.asarray(a,float),p)) if a else None

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--shards-dir',required=True); ap.add_argument('--output-dir',required=True); a=ap.parse_args()
    files=sorted(glob.glob(str(Path(a.shards_dir)/'**/phase2l_imerg_rolling_3h_20??-??.csv'),recursive=True))
    if len(files)!=24: raise ValueError(f'expected 24 monthly CSV shards, got {len(files)}')
    rows=[]
    for fp in files:
        with open(fp,encoding='utf-8',newline='') as f: rows.extend(csv.DictReader(f))
    keys=[(r['date_utc'],r['primary_subdivision_code']) for r in rows]
    if len(rows)!=5943 or len(set(keys))!=5943: raise ValueError(f'expected 5943 unique region-days, got rows={len(rows)} unique={len(set(keys))}')
    days={r['date_utc'] for r in rows}
    if len(days)!=449: raise ValueError(f'expected 449 unique UTC days, got {len(days)}')
    if any(int(r['rolling_window_count'])!=53 for r in rows): raise ValueError('non-53 rolling window count detected')
    summaries={}
    boundary_counts={}
    for m in METRICS:
        vals=[float(r[f'imerg_3h_{m}_max_mm']) for r in rows]
        summaries[m]={'n':len(vals),'mean_mm':float(np.mean(vals)),'median_mm':float(np.median(vals)),'p90_mm':q(vals,90),'p95_mm':q(vals,95),'p99_mm':q(vals,99),'max_mm':float(np.max(vals))}
        b=0
        for r in rows:
            s=r[f'imerg_3h_{m}_window_start_utc']
            if s[:10]!=r['date_utc']: b+=1
        boundary_counts[m]=b
    out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)
    csvp=out/'phase2l_imerg_rolling_3h_full.csv'
    with csvp.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    report={
        'schema_version':'1.0.0','phase':'2L-C-imerg-rolling-3h-full','split':'DEVELOPMENT',
        'candidate_region_day_count':5943,'refined_region_day_count':len(rows),'unique_utc_day_count':len(days),
        'source_id':'NASA_IMERG_FINAL_V07_HALFHOUR','native_slot_minutes':30,'slots_per_3h_window':6,
        'rolling_window_count_per_region_day':53,'boundary_crossing_windows_included':True,'missing_slot_interpolation':False,
        'source_native_3h_summary':summaries,'winning_window_start_outside_candidate_utc_day_count':boundary_counts,
        'candidate_membership_changed':False,'source_fusion_used':False,'environment_variables_used':False,'hard_negative_label':None,
        'validation_data_used':False,'retrospective_2026_used':False,'prospective_holdout_used':False,'risk_engine_allowed':False,
        'gate':'PASS_COMPLETE_IMERG_ROLLING_3H_REFINEMENT_5943_REGION_DAYS'
    }
    (out/'phase2l_imerg_rolling_3h_full.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False)); return 0

if __name__=='__main__': raise SystemExit(main())
