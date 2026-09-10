#!/usr/bin/env python3
"""Build one monthly shard of the Phase 2L-C CMORPH matched-window census.

Development 2023-2024 only. Uses frozen JMA primary-subdivision bbox + 0.5deg
padding. Produces descriptive region-day rainfall summaries only.
"""
from __future__ import annotations

import argparse, csv, json, shutil, tempfile, time
from calendar import monthrange
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from netCDF4 import Dataset

from lpz_risk.historical_spatial import build_primary_subdivision_geojson

CMORPH_ROOT = "https://noaa-cdr-precip-cmorph-pds.s3.amazonaws.com"
UA = "lpz-risk-system/0.1 phase2l-cmorph-monthly-census"
JAPAN_BBOX = (122.0, 24.0, 150.0, 47.0)
PADDING_DEG = 0.5


def _get(url: str, dst: Path, tries: int = 5) -> None:
    last = None
    for i in range(tries):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=180) as r, dst.open("wb") as f:
                shutil.copyfileobj(r, f)
            if dst.stat().st_size < 1024:
                raise ValueError("payload too small")
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            if dst.exists(): dst.unlink()
            if i + 1 < tries: time.sleep(5 * (i + 1))
    raise RuntimeError(f"download failed {url}: {type(last).__name__}: {last}")


def _required_codes(phase2k: dict) -> set[str]:
    rows = phase2k.get("episode_rows") or []
    if phase2k.get("gate") != "PASS_COMPLETE_DEVELOPMENT_POSITIVE_ENVIRONMENT_BASELINE" or len(rows) != 65:
        raise ValueError("Phase 2K baseline is not frozen complete 65-episode Development data")
    codes = {str(r["primary_subdivision_code"]) for r in rows}
    if not codes: raise ValueError("no Development primary-subdivision codes found")
    return codes


def _geometry_points(g):
    k = g.get("type")
    if k == "Polygon":
        for ring in g.get("coordinates") or []:
            for p in ring: yield float(p[0]), float(p[1])
    elif k == "MultiPolygon":
        for poly in g.get("coordinates") or []:
            for ring in poly:
                for p in ring: yield float(p[0]), float(p[1])
    elif k == "GeometryCollection":
        for part in g.get("geometries") or []: yield from _geometry_points(part)
    else: raise ValueError(f"unsupported geometry type {k!r}")


def _bbox(g):
    pts = list(_geometry_points(g)); xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
    return min(xs),min(ys),max(xs),max(ys)


def _matched(g):
    x0,y0,x1,y1=_bbox(g)
    return (max(JAPAN_BBOX[0],x0-PADDING_DEG), max(JAPAN_BBOX[1],y0-PADDING_DEG), min(JAPAN_BBOX[2],x1+PADDING_DEG), min(JAPAN_BBOX[3],y1+PADDING_DEG))


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--phase2k',required=True); ap.add_argument('--month',required=True); ap.add_argument('--output-dir',required=True); ap.add_argument('--gis-config',default='config/jma_primary_subdivision_gis.json'); ap.add_argument('--era5-config',default='config/historical_environment_era5.json'); a=ap.parse_args()
    y,m=map(int,a.month.split('-'))
    if y not in (2023,2024) or not 1<=m<=12: raise ValueError('Development YYYY-MM required')
    phase2k=json.loads(Path(a.phase2k).read_text(encoding='utf-8')); codes=_required_codes(phase2k)
    gis_cfg=json.loads(Path(a.gis_config).read_text(encoding='utf-8')); era5=json.loads(Path(a.era5_config).read_text(encoding='utf-8'))
    if float(era5['spatial_sampling']['bbox_padding_degrees']) != PADDING_DEG: raise ValueError('frozen padding mismatch')
    out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)
    csv_path=out/f'cmorph_matched_window_census_{y:04d}_{m:02d}.csv'; meta_path=out/f'cmorph_matched_window_census_{y:04d}_{m:02d}.json'

    with tempfile.TemporaryDirectory() as td_raw:
        td=Path(td_raw); gz=td/'jma.zip'; _get(gis_cfg['zip_url'],gz)
        geo=build_primary_subdivision_geojson(gz.read_bytes(),codes)
        if not geo.get('geometry_complete_for_required_codes'): raise RuntimeError(f"missing geometries {geo.get('missing_required_codes')}")
        features={str(f['properties']['primary_subdivision_code']):f['geometry'] for f in geo['features']}
        windows={c:_matched(features[c]) for c in sorted(codes)}
        rows=[]; downloaded=0
        for d in range(1,monthrange(y,m)[1]+1):
            key=f'data/daily/0.25deg/{y:04d}/{m:02d}/CMORPH_V1.0_ADJ_0.25deg-DLY_00Z_{y:04d}{m:02d}{d:02d}.nc'
            fp=td/'cmorph.nc'; _get(f'{CMORPH_ROOT}/{key}',fp); downloaded += fp.stat().st_size
            with Dataset(fp) as ds:
                lat=np.asarray(ds.variables['lat'][:],dtype=float).squeeze(); lon=np.asarray(ds.variables['lon'][:],dtype=float).squeeze(); rain=np.ma.asarray(ds.variables['cmorph'][:]).squeeze()
                if rain.shape==(lon.size,lat.size): rain=rain.T
                if rain.shape!=(lat.size,lon.size): raise ValueError(f'shape mismatch {rain.shape}')
                lon=((lon+180.0)%360.0)-180.0
                for code,(x0,y0,x1,y1) in windows.items():
                    iy=np.where((lat>=y0)&(lat<=y1))[0]; ix=np.where((lon>=x0)&(lon<=x1))[0]; total=int(iy.size*ix.size)
                    sub=np.ma.asarray(rain[np.ix_(iy,ix)]); vals=np.asarray(sub.compressed(),dtype=float); vals=vals[np.isfinite(vals)&(vals>=0)]
                    rows.append({'date_utc':f'{y:04d}-{m:02d}-{d:02d}','primary_subdivision_code':code,'grid_cell_count':total,'valid_rain_cell_count':int(vals.size),'valid_fraction':float(vals.size/total) if total else 0.0,'rain_mean_mm_day':float(vals.mean()) if vals.size else '', 'rain_max_mm_day':float(vals.max()) if vals.size else '', 'rain_p90_mm_day':float(np.percentile(vals,90)) if vals.size else '', 'rain_p95_mm_day':float(np.percentile(vals,95)) if vals.size else ''})
            fp.unlink(missing_ok=True)

    fields=list(rows[0].keys())
    with csv_path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    meta={'schema_version':'1.0.0','phase':'2L-C-cmorph-matched-window-monthly-census','split':'DEVELOPMENT','month':a.month,'region_count':len(codes),'day_count':monthrange(y,m)[1],'row_count':len(rows),'expected_row_count':len(codes)*monthrange(y,m)[1],'padding_degrees':PADDING_DEG,'source_id':'NOAA_CMORPH_CDR_DAILY_0P25DEG','window_role':'COARSE_RECALL_ORIENTED_DAILY_SCREENING_ONLY','downloaded_bytes':downloaded,'threshold_selected':False,'candidate_generated':False,'hard_negative_label':None,'source_fusion_used':False,'gsmap_used_for_discovery':False,'validation_data_used':False,'retrospective_2026_used':False,'prospective_holdout_used':False,'risk_engine_allowed':False,'gate':'PASS_COMPLETE_MONTHLY_MATCHED_WINDOW_CENSUS' if len(rows)==len(codes)*monthrange(y,m)[1] else 'FAIL_INCOMPLETE_MONTHLY_CENSUS'}
    meta_path.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(meta,ensure_ascii=False))
    return 0 if meta['gate'].startswith('PASS') else 2
if __name__=='__main__': raise SystemExit(main())
