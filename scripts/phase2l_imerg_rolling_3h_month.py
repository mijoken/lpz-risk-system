#!/usr/bin/env python3
"""Phase 2L-C monthly IMERG Final V07 half-hourly rolling 3h refinement.

CMORPH has already selected the Development candidate reservoir. This stage only
reconstructs exact six-slot IMERG 3h maxima for those frozen candidate region-days.
"""
from __future__ import annotations

import argparse, csv, json, shutil, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from phase2l_imerg_rolling_3h_pilot import (
    PADDING_DEG, _download_slots, _extract_start_from_filename, _get,
    _login, _matched_window, _read_imerg_halfhour,
)
from lpz_risk.historical_spatial import build_primary_subdivision_geojson


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--reservoir',required=True)
    ap.add_argument('--month',required=True)
    ap.add_argument('--output-dir',required=True)
    ap.add_argument('--gis-config',default='config/jma_primary_subdivision_gis.json')
    ap.add_argument('--era5-config',default='config/historical_environment_era5.json')
    a=ap.parse_args()
    if len(a.month)!=7 or not (a.month.startswith('2023-') or a.month.startswith('2024-')):
        raise ValueError('Development YYYY-MM required')

    rows=[]
    with Path(a.reservoir).open(encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):
            if r['date_utc'].startswith(a.month+'-'):
                rows.append(r)
    if not rows:
        raise ValueError(f'no frozen CMORPH candidates in {a.month}')
    by_date={}
    for r in rows:
        by_date.setdefault(r['date_utc'],[]).append(r)
    codes={r['primary_subdivision_code'] for r in rows}

    era5=json.loads(Path(a.era5_config).read_text(encoding='utf-8'))
    if float(era5['spatial_sampling']['bbox_padding_degrees'])!=PADDING_DEG:
        raise ValueError('frozen ERA5 bbox padding mismatch')
    gis=json.loads(Path(a.gis_config).read_text(encoding='utf-8'))
    out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)
    result_rows=[]; slot_audit=[]
    _login()

    with tempfile.TemporaryDirectory() as td_raw:
        td=Path(td_raw)
        jzip=td/'jma.zip'; _get(gis['zip_url'],jzip)
        geo=build_primary_subdivision_geojson(jzip.read_bytes(),codes)
        if not geo.get('geometry_complete_for_required_codes'):
            raise RuntimeError(f"missing JMA geometries: {geo.get('missing_required_codes')}")
        feats={str(f['properties']['primary_subdivision_code']):f['geometry'] for f in geo['features']}
        windows={c:_matched_window(feats[c]) for c in codes}

        for date_s in sorted(by_date):
            day=datetime.strptime(date_s,'%Y-%m-%d').replace(tzinfo=timezone.utc)
            first_start=day-timedelta(hours=2,minutes=30)
            last_start=day+timedelta(hours=23,minutes=30)
            final_slot_start=last_start+timedelta(hours=2,minutes=30)
            search_end=final_slot_start+timedelta(minutes=29,seconds=59)
            ddir=td/date_s; ddir.mkdir()
            files=_download_slots(first_start,search_end,ddir)
            slot_files={}
            for fp in files:
                ts=_extract_start_from_filename(fp)
                if first_start<=ts<=final_slot_start:
                    slot_files[ts]=fp
            expected=[first_start+timedelta(minutes=30*i) for i in range(int((final_slot_start-first_start).total_seconds()/1800)+1)]
            missing=[x.isoformat() for x in expected if x not in slot_files]
            slot_audit.append({'date_utc':date_s,'expected_slot_count':len(expected),'available_slot_count':len(expected)-len(missing),'missing_slots':missing})
            if missing:
                raise RuntimeError(f'missing IMERG slots for {date_s}: {missing[:10]} count={len(missing)}')
            cache={ts:_read_imerg_halfhour(slot_files[ts]) for ts in expected}

            for cr in by_date[date_s]:
                code=cr['primary_subdivision_code']; x0,y0,x1,y1=windows[code]
                best={k:(-np.inf,None,None) for k in ('mean','max','p90','p95')}
                valid_windows=0
                start=first_start
                while start<=last_start:
                    six=[start+timedelta(minutes=30*i) for i in range(6)]
                    lat,lon,_=cache[six[0]]
                    iy=np.where((lat>=y0)&(lat<=y1))[0]; ix=np.where((lon>=x0)&(lon<=x1))[0]
                    if iy.size==0 or ix.size==0:
                        raise RuntimeError(f'empty IMERG matched window {date_s} {code}')
                    accum=None
                    for ts in six:
                        lat2,lon2,rr=cache[ts]
                        if lat2.shape!=lat.shape or lon2.shape!=lon.shape or not np.allclose(lat2,lat) or not np.allclose(lon2,lon):
                            raise RuntimeError('IMERG grid changed within rolling window')
                        amount=np.ma.asarray(rr[np.ix_(iy,ix)],dtype=float)*0.5
                        accum=amount if accum is None else accum+amount
                    vals=np.asarray(np.ma.asarray(accum).compressed(),dtype=float)
                    vals=vals[np.isfinite(vals)&(vals>=0)]
                    if vals.size:
                        valid_windows+=1
                        stats={'mean':float(vals.mean()),'max':float(vals.max()),'p90':float(np.percentile(vals,90)),'p95':float(np.percentile(vals,95))}
                        for k,v in stats.items():
                            if v>best[k][0]:
                                best[k]=(v,start,start+timedelta(hours=3))
                    start+=timedelta(minutes=30)
                if valid_windows!=53:
                    raise RuntimeError(f'expected 53 rolling windows, got {valid_windows} for {date_s} {code}')
                row={'date_utc':date_s,'primary_subdivision_code':code,'rolling_window_count':valid_windows}
                for k,(v,s,e) in best.items():
                    row[f'imerg_3h_{k}_max_mm']=v
                    row[f'imerg_3h_{k}_window_start_utc']=s.isoformat()
                    row[f'imerg_3h_{k}_window_end_utc']=e.isoformat()
                result_rows.append(row)
            shutil.rmtree(ddir,ignore_errors=True)

    csvp=out/f'phase2l_imerg_rolling_3h_{a.month}.csv'
    with csvp.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(result_rows[0])); w.writeheader(); w.writerows(result_rows)
    (out/f'phase2l_imerg_rolling_3h_slot_audit_{a.month}.json').write_text(json.dumps(slot_audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report={
        'schema_version':'1.0.0','phase':'2L-C-imerg-rolling-3h-month','split':'DEVELOPMENT','month':a.month,
        'candidate_region_day_count':len(rows),'refined_region_day_count':len(result_rows),'unique_utc_day_count':len(by_date),
        'source_id':'NASA_IMERG_FINAL_V07_HALFHOUR','native_slot_minutes':30,'slots_per_3h_window':6,
        'rolling_window_count_per_region_day':53,'boundary_crossing_windows_included':True,'missing_slot_interpolation':False,
        'candidate_membership_changed':False,'source_fusion_used':False,'environment_variables_used':False,'hard_negative_label':None,
        'validation_data_used':False,'retrospective_2026_used':False,'prospective_holdout_used':False,'risk_engine_allowed':False,
        'gate':'PASS_IMERG_ROLLING_3H_MONTH' if len(result_rows)==len(rows) else 'FAIL_INCOMPLETE_IMERG_ROLLING_3H_MONTH'
    }
    (out/f'phase2l_imerg_rolling_3h_{a.month}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['gate'].startswith('PASS') else 2

if __name__=='__main__':
    raise SystemExit(main())
