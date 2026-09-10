#!/usr/bin/env python3
"""Run one monthly shard of Phase 2L-C IMERG independent confirmation.

CMORPH already selected the candidate reservoir. IMERG is used only to re-measure
those frozen candidate region-days. No candidate inclusion/exclusion is changed.
"""
from __future__ import annotations

import argparse, csv, json, shutil, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from netCDF4 import Dataset

from lpz_risk.historical_spatial import build_primary_subdivision_geojson

PADDING_DEG = 0.5
JAPAN_BBOX = (122.0, 24.0, 150.0, 47.0)


def _login(tries=5):
    import earthaccess
    last=None
    for i in range(tries):
        try: return earthaccess.login(strategy='environment')
        except Exception as exc:
            last=exc
            if i+1<tries: time.sleep(10*(i+1))
    raise RuntimeError(f'Earthdata login failed: {type(last).__name__}: {last}')


def _download_day(date_s: str, dest: Path) -> Path:
    import earthaccess
    dt=datetime.strptime(date_s,'%Y-%m-%d').replace(tzinfo=timezone.utc)
    last=None
    for i in range(5):
        try:
            granules=earthaccess.search_data(short_name='GPM_3IMERGDF',version='07',bounding_box=JAPAN_BBOX,temporal=(dt.isoformat(),dt.replace(hour=23,minute=59,second=59).isoformat()),count=5)
            if len(granules)!=1: raise RuntimeError(f'expected one granule, got {len(granules)} for {date_s}')
            paths=earthaccess.download(granules,str(dest),threads=1)
            if len(paths)!=1: raise RuntimeError(f'download mismatch {date_s}: {paths}')
            p=Path(paths[0])
            if not p.exists() or p.stat().st_size<1024: raise RuntimeError(f'invalid payload {date_s}: {p}')
            return p
        except Exception as exc:
            last=exc
            if i+1<5: time.sleep(15*(i+1))
    raise RuntimeError(f'IMERG day failed {date_s}: {type(last).__name__}: {last}')


def _get(url: str, dst: Path, tries=5):
    last=None
    for i in range(tries):
        try:
            req=Request(url,headers={'User-Agent':'lpz-risk-system/0.1 phase2l-imerg-full-confirmation'})
            with urlopen(req,timeout=180) as r, dst.open('wb') as f: shutil.copyfileobj(r,f)
            if dst.stat().st_size<1024: raise ValueError('payload too small')
            return
        except Exception as exc:
            last=exc; dst.unlink(missing_ok=True)
            if i+1<tries: time.sleep(5*(i+1))
    raise RuntimeError(f'download failed {url}: {type(last).__name__}: {last}')


def _points(g):
    k=g.get('type')
    if k=='Polygon':
        for ring in g.get('coordinates') or []:
            for p in ring: yield float(p[0]),float(p[1])
    elif k=='MultiPolygon':
        for poly in g.get('coordinates') or []:
            for ring in poly:
                for p in ring: yield float(p[0]),float(p[1])
    elif k=='GeometryCollection':
        for part in g.get('geometries') or []: yield from _points(part)
    else: raise ValueError(f'unsupported geometry {k!r}')


def _window(g):
    pts=list(_points(g)); xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
    return (max(JAPAN_BBOX[0],min(xs)-PADDING_DEG),max(JAPAN_BBOX[1],min(ys)-PADDING_DEG),min(JAPAN_BBOX[2],max(xs)+PADDING_DEG),min(JAPAN_BBOX[3],max(ys)+PADDING_DEG))


def _grid(path: Path):
    with Dataset(path) as ds:
        lon=np.asarray(ds.variables['lon'][:],dtype=float).squeeze(); lat=np.asarray(ds.variables['lat'][:],dtype=float).squeeze(); rain=np.ma.asarray(ds.variables['precipitation'][:]).squeeze()
    if rain.shape==(lon.size,lat.size): rain=rain.T
    elif rain.shape!=(lat.size,lon.size): raise ValueError(f'shape mismatch {rain.shape}')
    lon=((lon+180.0)%360.0)-180.0
    return lat,lon,rain


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--reservoir',required=True); ap.add_argument('--month',required=True); ap.add_argument('--output-dir',required=True); ap.add_argument('--gis-config',default='config/jma_primary_subdivision_gis.json'); ap.add_argument('--era5-config',default='config/historical_environment_era5.json'); a=ap.parse_args()
    if len(a.month)!=7 or not (a.month.startswith('2023-') or a.month.startswith('2024-')): raise ValueError('Development YYYY-MM required')
    rows=[]
    with Path(a.reservoir).open(encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):
            if r['date_utc'].startswith(a.month+'-'): rows.append(r)
    if not rows: raise ValueError(f'no frozen CMORPH candidates in {a.month}')
    by_date={}
    for r in rows: by_date.setdefault(r['date_utc'],[]).append(r)
    codes={r['primary_subdivision_code'] for r in rows}
    era5=json.loads(Path(a.era5_config).read_text(encoding='utf-8'))
    if float(era5['spatial_sampling']['bbox_padding_degrees'])!=PADDING_DEG: raise ValueError('frozen padding mismatch')
    gis=json.loads(Path(a.gis_config).read_text(encoding='utf-8'))
    out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)
    out_rows=[]; total_bytes=0
    _login()
    with tempfile.TemporaryDirectory() as td_raw:
        td=Path(td_raw); jzip=td/'jma.zip'; _get(gis['zip_url'],jzip)
        geo=build_primary_subdivision_geojson(jzip.read_bytes(),codes)
        if not geo.get('geometry_complete_for_required_codes'): raise RuntimeError(f"missing geometries {geo.get('missing_required_codes')}")
        feats={str(f['properties']['primary_subdivision_code']):f['geometry'] for f in geo['features']}; windows={c:_window(feats[c]) for c in codes}
        for date_s in sorted(by_date):
            daydir=td/date_s; daydir.mkdir(); fp=_download_day(date_s,daydir); total_bytes+=fp.stat().st_size
            lat,lon,rain=_grid(fp)
            for cr in by_date[date_s]:
                code=cr['primary_subdivision_code']; x0,y0,x1,y1=windows[code]
                iy=np.where((lat>=y0)&(lat<=y1))[0]; ix=np.where((lon>=x0)&(lon<=x1))[0]
                vals=np.asarray(np.ma.asarray(rain[np.ix_(iy,ix)]).compressed(),dtype=float); vals=vals[np.isfinite(vals)&(vals>=0)]
                if vals.size==0: raise RuntimeError(f'no valid IMERG cells {date_s} {code}')
                out_rows.append({'date_utc':date_s,'primary_subdivision_code':code,'cmorph_rain_mean_mm_day':cr['rain_mean_mm_day'],'cmorph_rain_max_mm_day':cr['rain_max_mm_day'],'cmorph_rain_p90_mm_day':cr['rain_p90_mm_day'],'cmorph_rain_p95_mm_day':cr['rain_p95_mm_day'],'imerg_grid_cell_count':int(iy.size*ix.size),'imerg_valid_rain_cell_count':int(vals.size),'imerg_rain_mean_mm_day':float(vals.mean()),'imerg_rain_max_mm_day':float(vals.max()),'imerg_rain_p90_mm_day':float(np.percentile(vals,90)),'imerg_rain_p95_mm_day':float(np.percentile(vals,95))})
            shutil.rmtree(daydir,ignore_errors=True)
    csvp=out/f'phase2l_imerg_confirmation_{a.month}.csv'
    with csvp.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(out_rows[0])); w.writeheader(); w.writerows(out_rows)
    report={'schema_version':'1.0.0','phase':'2L-C-imerg-independent-confirmation-month','split':'DEVELOPMENT','month':a.month,'candidate_region_day_count':len(rows),'confirmed_region_day_count':len(out_rows),'unique_utc_day_count':len(by_date),'downloaded_bytes':total_bytes,'source_id':'NASA_IMERG_FINAL_V07_DAILY','cmorph_selected_candidates':True,'imerg_used_for_candidate_selection':False,'imerg_role':'INDEPENDENT_SOURCE_NATIVE_CONFIRMATION_ONLY','source_fusion_used':False,'hard_negative_label':None,'environment_variables_used':False,'gsmap_used_for_discovery':False,'validation_data_used':False,'retrospective_2026_used':False,'prospective_holdout_used':False,'risk_engine_allowed':False,'gate':'PASS_IMERG_MONTH_CONFIRMATION' if len(out_rows)==len(rows) else 'FAIL_INCOMPLETE_IMERG_MONTH_CONFIRMATION'}
    (out/f'phase2l_imerg_confirmation_{a.month}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False)); return 0 if report['gate'].startswith('PASS') else 2

if __name__=='__main__': raise SystemExit(main())