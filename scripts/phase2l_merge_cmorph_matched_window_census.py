#!/usr/bin/env python3
"""Merge 24 CMORPH monthly matched-window census shards and describe positives.

No screening threshold or candidate rule is selected here. Positive mappings are
used only to locate frozen Development LPZ episodes within the source-native
region/day rainfall distributions.
"""
from __future__ import annotations

import argparse, csv, json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

METRICS=("rain_mean_mm_day","rain_max_mm_day","rain_p90_mm_day","rain_p95_mm_day")


def _f(v):
    try: return float(v)
    except (TypeError,ValueError): return float('nan')


def _pct_rank(values, x):
    a=np.asarray([v for v in values if np.isfinite(v)],dtype=float)
    if not a.size or not np.isfinite(x): return None
    return float(100.0*np.mean(a<=x))


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--shards-dir',required=True); ap.add_argument('--phase2k',required=True); ap.add_argument('--output-dir',required=True); a=ap.parse_args()
    root=Path(a.shards_dir); out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)
    csvs=sorted(root.rglob('cmorph_matched_window_census_*.csv')); metas=sorted(root.rglob('cmorph_matched_window_census_*.json'))
    if len(csvs)!=24 or len(metas)!=24: raise ValueError(f'expected 24 csv + 24 json shards, got {len(csvs)} + {len(metas)}')
    months=[]; total_downloaded=0
    for p in metas:
        d=json.loads(p.read_text(encoding='utf-8'))
        if d.get('gate')!='PASS_COMPLETE_MONTHLY_MATCHED_WINDOW_CENSUS': raise ValueError(f'non-pass shard {p}: {d.get("gate")}')
        months.append(d['month']); total_downloaded+=int(d.get('downloaded_bytes') or 0)
    expected=[f'{y}-{m:02d}' for y in (2023,2024) for m in range(1,13)]
    if sorted(months)!=expected: raise ValueError(f'month coverage mismatch: {sorted(months)}')

    rows=[]
    for p in csvs:
        with p.open(encoding='utf-8',newline='') as f: rows.extend(csv.DictReader(f))
    if len(rows)!=731*45: raise ValueError(f'expected 32895 rows, got {len(rows)}')
    keys={(r['date_utc'],r['primary_subdivision_code']) for r in rows}
    if len(keys)!=len(rows): raise ValueError('duplicate region-day keys')

    by_region=defaultdict(list); by_region_month=defaultdict(list)
    for r in rows:
        c=r['primary_subdivision_code']; month=int(r['date_utc'][5:7]); by_region[c].append(r); by_region_month[(c,month)].append(r)
    if len(by_region)!=45 or any(len(v)!=731 for v in by_region.values()): raise ValueError('region coverage is not 45 x 731 complete')

    region_summary=[]
    for c in sorted(by_region):
        rr=by_region[c]; item={'primary_subdivision_code':c,'day_count':len(rr),'grid_cell_count':int(float(rr[0]['grid_cell_count']))}
        for metric in METRICS:
            vals=np.asarray([_f(x[metric]) for x in rr],dtype=float); vals=vals[np.isfinite(vals)]
            item[metric+'_median']=float(np.median(vals)); item[metric+'_p90']=float(np.percentile(vals,90)); item[metric+'_p95']=float(np.percentile(vals,95)); item[metric+'_p99']=float(np.percentile(vals,99))
        region_summary.append(item)

    phase2k=json.loads(Path(a.phase2k).read_text(encoding='utf-8')); eps=phase2k.get('episode_rows') or []
    if phase2k.get('gate')!='PASS_COMPLETE_DEVELOPMENT_POSITIVE_ENVIRONMENT_BASELINE' or len(eps)!=65: raise ValueError('invalid Phase 2K baseline')
    lookup={(r['date_utc'],r['primary_subdivision_code']):r for r in rows}
    positive=[]
    for e in eps:
        dt=datetime.fromisoformat(e['analysis_time_utc'].replace('Z','+00:00')).astimezone(timezone.utc); ds=dt.date().isoformat(); c=str(e['primary_subdivision_code']); rr=lookup.get((ds,c))
        if rr is None: raise ValueError(f'missing positive mapped region-day {ds} {c}')
        item={'local_episode_id':e['local_episode_id'],'anchor_id':e['anchor_id'],'analysis_time_utc':e['analysis_time_utc'],'date_utc_direct':ds,'primary_subdivision_code':c,'utc_boundary_note':'DIRECT_ANALYSIS_UTC_DATE_ONLY_NOT_YET_A_SCREENING_RULE'}
        for metric in METRICS:
            x=_f(rr[metric]); item[metric]=x; item[metric+'_percentile_same_region_731d']=_pct_rank([_f(z[metric]) for z in by_region[c]],x); item[metric+'_percentile_same_region_calendar_month']=_pct_rank([_f(z[metric]) for z in by_region_month[(c,dt.month)]],x)
        positive.append(item)

    merged_csv=out/'phase2l_cmorph_matched_window_region_day_census.csv'
    with merged_csv.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    pos_csv=out/'phase2l_cmorph_positive_region_day_positions.csv'
    with pos_csv.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(positive[0].keys())); w.writeheader(); w.writerows(positive)
    (out/'phase2l_cmorph_region_distribution_summary.json').write_text(json.dumps(region_summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    pos_summary={}
    for metric in METRICS:
        for suffix in ('percentile_same_region_731d','percentile_same_region_calendar_month'):
            vals=np.asarray([p[metric+'_'+suffix] for p in positive if p[metric+'_'+suffix] is not None],dtype=float)
            pos_summary[metric+'_'+suffix]={'n':int(vals.size),'median':float(np.median(vals)),'p10':float(np.percentile(vals,10)),'p25':float(np.percentile(vals,25)),'p75':float(np.percentile(vals,75)),'p90':float(np.percentile(vals,90))}

    report={'schema_version':'1.0.0','phase':'2L-C-cmorph-matched-window-spatial-census','split':'DEVELOPMENT','development_years':[2023,2024],'day_count':731,'region_count':45,'region_day_count':len(rows),'positive_episode_count':65,'matched_window_semantics':'OFFICIAL_JMA_PRIMARY_SUBDIVISION_GEOMETRY_BBOX_PLUS_FROZEN_ERA5_0P5_DEG_PADDING','source_id':'NOAA_CMORPH_CDR_DAILY_0P25DEG','total_downloaded_bytes_across_shards':total_downloaded,'positive_position_summary':pos_summary,'positive_date_mapping_warning':'Daily CMORPH uses UTC days. Direct analysis-date mapping is descriptive only; boundary-aware screening semantics must be frozen before candidate generation.','threshold_selected':False,'candidate_generated':False,'hard_negative_label':None,'source_fusion_used':False,'gsmap_used_for_discovery':False,'validation_data_used':False,'retrospective_2026_used':False,'prospective_holdout_used':False,'risk_engine_allowed':False,'gate':'PASS_COMPLETE_731D_X_45_REGION_CMORPH_MATCHED_WINDOW_CENSUS'}
    (out/'phase2l_cmorph_matched_window_census_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0
if __name__=='__main__': raise SystemExit(main())
