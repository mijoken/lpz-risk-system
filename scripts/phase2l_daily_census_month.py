#!/usr/bin/env python3
"""Phase 2L-A monthly Development daily-rainfall census shard.

Descriptive only. No heavy-rain threshold, candidate label, source fusion, or risk score.
Raw daily payloads are deleted after extracting Japan-domain source-native summaries.
"""
from __future__ import annotations

import argparse, calendar, json, shutil, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from netCDF4 import Dataset

BBOX=(122.0,24.0,150.0,47.0) # west,south,east,north; retrieval/summary envelope, not JMA polygon
CMORPH_ROOT="https://noaa-cdr-precip-cmorph-pds.s3.amazonaws.com"
UA="lpz-risk-system/0.1 phase2l-research"


def _coord(ds, names):
    for n in names:
        if n in ds.variables:
            return np.asarray(ds.variables[n][:]).squeeze(), n
    raise KeyError(f"coordinate missing: {names}")


def _rain_var(ds, preferred):
    if preferred in ds.variables:
        return ds.variables[preferred], preferred
    for n,v in ds.variables.items():
        u=str(getattr(v,'units','')).lower()
        if len(v.dimensions)>=2 and ('mm' in u or 'precip' in n.lower() or 'cmorph' in n.lower()):
            return v,n
    raise KeyError(f"rain variable missing, preferred={preferred}")


def _summary(path: Path, preferred: str) -> dict:
    with Dataset(path) as ds:
        lat,latn=_coord(ds,['lat','latitude','Latitude'])
        lon,lonn=_coord(ds,['lon','longitude','Longitude'])
        v,vn=_rain_var(ds,preferred)
        a=np.ma.asarray(v[:]).squeeze()
        if a.ndim!=2:
            raise ValueError(f"unexpected rain shape {a.shape} for {vn}")
        if a.shape==(lon.size,lat.size):
            a=a.T
        elif a.shape!=(lat.size,lon.size):
            raise ValueError(f"shape/coord mismatch {a.shape} lat={lat.size} lon={lon.size}")
        lon2=np.mod(lon,360.0)
        w,e=BBOX[0]%360.0,BBOX[2]%360.0
        lm=(lat>=BBOX[1])&(lat<=BBOX[3])
        xm=(lon2>=w)&(lon2<=e)
        sub=np.ma.asarray(a[np.ix_(lm,xm)])
        vals=np.asarray(sub.compressed(),dtype=float)
        vals=vals[np.isfinite(vals)]
        vals=vals[vals>=0]
        if vals.size<100:
            raise ValueError(f"too few valid Japan-domain cells: {vals.size}")
        q=np.quantile(vals,[0.5,0.9,0.95,0.99])
        return {
            'variable':vn,'units':getattr(v,'units',None),'lat_name':latn,'lon_name':lonn,
            'valid_cell_count':int(vals.size),'zero_fraction':float(np.mean(vals==0)),
            'mean':float(np.mean(vals)),'median':float(q[0]),'p90':float(q[1]),
            'p95':float(q[2]),'p99':float(q[3]),'maximum':float(np.max(vals)),
        }


def _get(url: str, dst: Path, tries=3):
    last=None
    for i in range(tries):
        try:
            req=Request(url,headers={'User-Agent':UA})
            with urlopen(req,timeout=180) as r, dst.open('wb') as f:
                shutil.copyfileobj(r,f)
            if dst.stat().st_size<1024: raise ValueError('payload too small')
            return
        except Exception as exc:
            last=exc
            if dst.exists(): dst.unlink()
            if i+1<tries: time.sleep(5*(i+1))
    raise RuntimeError(f"download failed {url}: {type(last).__name__}: {last}")


def _earthdata_login(tries: int=5):
    """Retry only the external login handshake; never reinterpret auth failure as data."""
    import earthaccess
    last=None
    for i in range(tries):
        try:
            return earthaccess.login(strategy='environment')
        except Exception as exc:
            last=exc
            if i+1<tries:
                time.sleep(10*(i+1))
    raise RuntimeError(
        f"Earthdata login failed after {tries} attempts: {type(last).__name__}: {last}"
    ) from last


def _imerg(day: datetime, work: Path) -> tuple[Path,str]:
    import earthaccess
    gran=earthaccess.search_data(short_name='GPM_3IMERGDF',version='07',
        bounding_box=BBOX, temporal=(day.isoformat(),day.replace(hour=23,minute=59,second=59).isoformat()),count=5)
    if len(gran)!=1: raise RuntimeError(f"IMERG granule count {day.date()}={len(gran)}")
    paths=earthaccess.download(gran,str(work),threads=1)
    if len(paths)!=1: raise RuntimeError(f"IMERG download count {day.date()}={len(paths)}")
    return Path(paths[0]),'GPM_3IMERGDF'


def _cmorph(day: datetime, work: Path) -> tuple[Path,str]:
    key=f"data/daily/0.25deg/{day:%Y/%m}/CMORPH_V1.0_ADJ_0.25deg-DLY_00Z_{day:%Y%m%d}.nc"
    p=work/Path(key).name
    _get(f"{CMORPH_ROOT}/{key}",p)
    return p,key


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--month',required=True); ap.add_argument('--output',required=True); a=ap.parse_args()
    y,m=map(int,a.month.split('-'))
    if y not in (2023,2024): raise ValueError('Development only: 2023-2024')
    _earthdata_login()
    rows=[]; failures=[]
    with tempfile.TemporaryDirectory() as td:
        work=Path(td)
        for d in range(1,calendar.monthrange(y,m)[1]+1):
            day=datetime(y,m,d,tzinfo=timezone.utc)
            for src in ('IMERG','CMORPH'):
                p=None
                try:
                    if src=='IMERG': p,locator=_imerg(day,work); s=_summary(p,'precipitation'); sid='NASA_IMERG_FINAL_V07_DAILY'
                    else: p,locator=_cmorph(day,work); s=_summary(p,'cmorph'); sid='NOAA_CMORPH_CDR_DAILY'
                    rows.append({'date_utc':day.strftime('%Y-%m-%d'),'source_id':sid,'locator':locator,**s})
                except Exception as exc:
                    failures.append({'date_utc':day.strftime('%Y-%m-%d'),'source':src,'error_type':type(exc).__name__,'error':str(exc)[:500]})
                finally:
                    if p and p.exists(): p.unlink()
    expected=calendar.monthrange(y,m)[1]*2
    report={
      'schema_version':'1.1.0','phase':'2L-A-monthly-daily-rainfall-census','split':'DEVELOPMENT','month':a.month,
      'bbox_wsen':list(BBOX),'spatial_semantics':'JAPAN_DOMAIN_RETRIEVAL_ENVELOPE_NOT_JMA_SUBDIVISION_POLYGON',
      'earthdata_login_retry':{'max_attempts':5,'backoff_seconds':[10,20,30,40]},
      'expected_row_count':expected,'row_count':len(rows),'failure_count':len(failures),'rows':rows,'failures':failures,
      'source_fusion_used':False,'threshold_selected':False,'candidate_generated':False,'hard_negative_label':None,
      'validation_data_used':False,'retrospective_2026_used':False,'prospective_holdout_used':False,'risk_engine_allowed':False,
      'gate':'PASS_COMPLETE_MONTHLY_DUAL_SOURCE_CENSUS' if len(rows)==expected and not failures else 'FAIL_INCOMPLETE_MONTHLY_CENSUS'
    }
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'month':a.month,'gate':report['gate'],'rows':len(rows),'failures':len(failures)},ensure_ascii=False))
    return 0 if report['gate'].startswith('PASS') else 2

if __name__=='__main__': raise SystemExit(main())
