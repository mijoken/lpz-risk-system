#!/usr/bin/env python3
"""Merge Phase 2L-A monthly shards and locate frozen Positive episodes in the daily census."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np

METRICS=['mean','median','p90','p95','p99','maximum','zero_fraction']
RANK_METRICS=('mean','p90','p95','p99','maximum')


def dist(x):
    a=np.asarray([v for v in x if v is not None and math.isfinite(float(v))],dtype=float)
    if not a.size: return None
    q=np.quantile(a,[0,.1,.25,.5,.75,.9,.95,.99,1])
    return {'n':int(a.size),'mean':float(a.mean()),'q00':float(q[0]),'q10':float(q[1]),'q25':float(q[2]),'q50':float(q[3]),'q75':float(q[4]),'q90':float(q[5]),'q95':float(q[6]),'q99':float(q[7]),'q100':float(q[8])}


def pct_rank(value, population):
    a=np.asarray(population,dtype=float); v=float(value)
    return float(100.0*((a<v).sum()+0.5*(a==v).sum())/a.size)


def _rank_summary(events, source_ids):
    out={}
    for sid in source_ids:
        out[sid]={}
        for scope in ('development_percentile_rank','same_calendar_month_percentile_rank'):
            out[sid][scope]={m:dist([e['daily_source_native'][sid][scope][m] for e in events]) for m in RANK_METRICS}
    return out


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--shard-dir',required=True); ap.add_argument('--positive-baseline',required=True); ap.add_argument('--output',required=True); a=ap.parse_args()
    shards=[]
    for p in sorted(Path(a.shard_dir).rglob('phase2l_census_*.json')):
        d=json.loads(p.read_text(encoding='utf-8'))
        if d.get('gate')!='PASS_COMPLETE_MONTHLY_DUAL_SOURCE_CENSUS': raise RuntimeError(f'incomplete shard {p}: {d.get("gate")}')
        shards.append(d)
    months={s['month'] for s in shards}
    expected={f'{y}-{m:02d}' for y in (2023,2024) for m in range(1,13)}
    if months!=expected: raise RuntimeError(f'month coverage mismatch missing={sorted(expected-months)} extra={sorted(months-expected)}')
    rows=sorted([r for s in shards for r in s['rows']], key=lambda r:(r['date_utc'],r['source_id']))
    if len(rows)!=1462: raise RuntimeError(f'expected 1462 rows, got {len(rows)}')
    keys={(r['source_id'],r['date_utc']) for r in rows}
    if len(keys)!=1462: raise RuntimeError('duplicate source/date rows in census')
    bysrc={}
    for r in rows: bysrc.setdefault(r['source_id'],[]).append(r)
    counts={k:len(v) for k,v in bysrc.items()}
    if counts!={'NASA_IMERG_FINAL_V07_DAILY':731,'NOAA_CMORPH_CDR_DAILY':731}: raise RuntimeError(counts)
    source_distributions={s:{m:dist([r[m] for r in rr]) for m in METRICS} for s,rr in bysrc.items()}
    positive=json.loads(Path(a.positive_baseline).read_text(encoding='utf-8'))
    if positive.get('gate')!='PASS_COMPLETE_DEVELOPMENT_POSITIVE_ENVIRONMENT_BASELINE' or len(positive.get('episode_rows',[]))!=65:
        raise RuntimeError('positive baseline is not frozen complete 65-episode Phase2K')
    index={(r['source_id'],r['date_utc']):r for r in rows}
    pos=[]
    for e in positive['episode_rows']:
        date=e['analysis_time_utc'][:10]
        rr={'local_episode_id':e['local_episode_id'],'anchor_id':e['anchor_id'],'primary_subdivision_code':e['primary_subdivision_code'],'analysis_time_utc':e['analysis_time_utc'],'date_utc':date,'daily_source_native':{}}
        for sid,pop in bysrc.items():
            r=index[(sid,date)]; month=date[5:7]
            month_pop=[x for x in pop if x['date_utc'][5:7]==month]
            rr['daily_source_native'][sid]={
              'daily_summary':{m:r[m] for m in METRICS},
              'development_percentile_rank':{m:pct_rank(r[m],[x[m] for x in pop]) for m in RANK_METRICS},
              'same_calendar_month_percentile_rank':{m:pct_rank(r[m],[x[m] for x in month_pop]) for m in RANK_METRICS},
            }
        pos.append(rr)
    rank_summary=_rank_summary(pos,sorted(bysrc))
    # Multiple LPZ episodes can occur on the same UTC day. Keep episode-weighted and unique-date views separate.
    first_by_date={}
    for e in sorted(pos,key=lambda x:(x['date_utc'],x['analysis_time_utc'],x['local_episode_id'])):
        first_by_date.setdefault(e['date_utc'],e)
    unique_pos=list(first_by_date.values())
    unique_rank_summary=_rank_summary(unique_pos,sorted(bysrc))
    report={
      'schema_version':'1.1.0','phase':'2L-A-development-daily-rainfall-census','split':'DEVELOPMENT','development_period':'2023-01-01/2024-12-31',
      'day_count':731,'source_day_row_count':1462,'source_ids':sorted(bysrc),'bbox_wsen':[122.0,24.0,150.0,47.0],
      'spatial_semantics':'JAPAN_DOMAIN_RETRIEVAL_ENVELOPE_NOT_JMA_SUBDIVISION_POLYGON',
      'daily_metric_semantics':'SOURCE_NATIVE_DAILY_GRID_SUMMARIES; DAILY DATA USED FOR SCREENING/DISTRIBUTION ONLY, NOT FINAL 3H MATCHING',
      'source_day_rows':rows,
      'source_native_distributions':source_distributions,
      'positive_episode_count':65,'positive_unique_date_count':len(unique_pos),
      'positive_episode_daily_context':pos,'positive_daily_rank_summary_episode_weighted':rank_summary,
      'positive_unique_date_daily_rank_summary':unique_rank_summary,
      'duplicate_positive_date_guardrail':'Episode-weighted ranks retain all 65 frozen local episodes; unique-date ranks count each UTC date once to avoid interpreting same-day local episodes as independent national-day samples.',
      'interpretation_guardrail':'A positive episode occurring on a wet Japan-domain day does not imply its own subdivision had the domain maximum. Spatial candidate discovery is a later phase.',
      'source_fusion_used':False,'threshold_selected':False,'candidate_generated':False,'hard_negative_label':None,'gsmap_used_for_discovery':False,
      'validation_data_used':False,'retrospective_2026_used':False,'prospective_holdout_used':False,'risk_score':None,'risk_engine_allowed':False,
      'gate':'PASS_COMPLETE_DEVELOPMENT_DAILY_RAINFALL_CENSUS'
    }
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'gate':report['gate'],'days':731,'rows':1462,'positive_episodes':65,'positive_unique_dates':len(unique_pos)},ensure_ascii=False,indent=2)); return 0

if __name__=='__main__': raise SystemExit(main())
