#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, sys, urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from lpz_risk.historical_spatial import build_primary_subdivision_geojson

DEFAULT_CONFIG = ROOT/'config'/'jma_primary_subdivision_gis.json'
DEFAULT_OUTPUT = ROOT/'web'/'assets'/'japan_primary_subdivisions.geojson'
DEFAULT_REPORT = ROOT/'reports'/'web'/'phase2l_o2_public_geometry_report.json'
PASS_GATE = 'PASS_PHASE2L_O2_PUBLIC_JMA_PRIMARY_SUBDIVISION_GEOJSON'
MAX_DECIMALS = 10


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent':'lpz-risk-system/0.1 public-map-builder'})
    with urllib.request.urlopen(req, timeout=180) as r:
        b = r.read()
    if not b: raise ValueError(f'empty response: {url}')
    return b


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def dump_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, separators=(',',':'), allow_nan=False)+'\n').encode('utf-8')


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_bytes(data); tmp.replace(path)


def extract_class10s(b: bytes) -> dict[str,dict[str,Any]]:
    obj = json.loads(b.decode('utf-8'))
    src = obj.get('class10s')
    if not isinstance(src, dict) or not src: raise ValueError('JMA area.json missing class10s')
    out = {}
    for code, meta in src.items():
        code = str(code)
        if len(code)!=6 or not code.isdigit(): raise ValueError(f'bad class10s code: {code}')
        if not isinstance(meta,dict) or not str(meta.get('name','')).strip(): raise ValueError(f'bad class10s metadata: {code}')
        out[code]=meta
    return out


def point_seg_d2(p,a,b):
    ax,ay=a; bx,by=b; px,py=p; dx=bx-ax; dy=by-ay
    if dx==0 and dy==0: return (px-ax)**2+(py-ay)**2
    t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/(dx*dx+dy*dy)))
    qx=ax+t*dx; qy=ay+t*dy
    return (px-qx)**2+(py-qy)**2


def rdp(points, tol):
    if len(points)<=2: return points[:]
    a,b=points[0],points[-1]; best=-1; idx=-1
    for i in range(1,len(points)-1):
        d=point_seg_d2(points[i],a,b)
        if d>best: best=d; idx=i
    if best>tol*tol and idx>0:
        left=rdp(points[:idx+1],tol); right=rdp(points[idx:],tol)
        return left[:-1]+right
    return [a,b]


def open_ring(coords):
    pts=[]
    for p in coords:
        q=[float(p[0]),float(p[1])]
        if not pts or q!=pts[-1]: pts.append(q)
    if len(pts)>1 and pts[0]==pts[-1]: pts.pop()
    return pts


def close_round(pts, decimals):
    out=[]
    for p in pts:
        q=[round(float(p[0]),decimals),round(float(p[1]),decimals)]
        if not out or q!=out[-1]: out.append(q)
    if out and out[0]!=out[-1]: out.append(out[0][:])
    return out


def valid_ring(r):
    return len(r)>=4 and r[0]==r[-1] and len({tuple(p) for p in r[:-1]})>=3 and all(118<=p[0]<=156 and 18<=p[1]<=50 for p in r)


def simplify_open(pts,tol):
    if len(pts)<=3: return pts[:]
    i0=min(range(len(pts)),key=lambda i:(pts[i][0],pts[i][1]))
    p0=pts[i0]; i1=max(range(len(pts)),key=lambda i:(pts[i][0]-p0[0])**2+(pts[i][1]-p0[1])**2)
    rot=pts[i0:]+pts[:i0]; j=(i1-i0)%len(pts)
    if j<=0 or j>=len(rot): j=max(range(1,len(rot)),key=lambda i:(rot[i][0]-rot[0][0])**2+(rot[i][1]-rot[0][1])**2)
    merged=rdp(rot[:j+1],tol)+rdp(rot[j:]+[rot[0]],tol)[1:]
    ded=[]
    for p in merged:
        if not ded or p!=ded[-1]: ded.append(p)
    if ded and ded[0]==ded[-1]: ded.pop()
    return ded if len({tuple(p) for p in ded})>=3 else pts[:]


def minimal_triangle(pts):
    i0=min(range(len(pts)),key=lambda i:(pts[i][0],pts[i][1]))
    p0=pts[i0]
    i1=max(range(len(pts)),key=lambda i:(pts[i][0]-p0[0])**2+(pts[i][1]-p0[1])**2)
    candidates=[i for i in range(len(pts)) if i not in {i0,i1}]
    i2=max(candidates,key=lambda i:point_seg_d2(pts[i],pts[i0],pts[i1]))
    if point_seg_d2(pts[i2],pts[i0],pts[i1])<=0: raise ValueError('degenerate official ring')
    chosen={i0,i1,i2}
    tri=[pts[i] for i in range(len(pts)) if i in chosen]
    if len(tri)!=3: raise ValueError('triangle fallback failed')
    return tri


def simplify_ring(coords,tol,decimals,stats):
    stats['rings_total']+=1
    pts=open_ring(coords)
    if len({tuple(p) for p in pts})<3: raise ValueError('official ring invalid')
    candidate=close_round(simplify_open(pts,tol),decimals)
    if valid_ring(candidate):
        if len(candidate)-1 < len(pts): stats['rings_simplified']+=1
        return candidate
    stats['rings_minimal_triangle']+=1
    tri=minimal_triangle(pts)
    for d in range(decimals,MAX_DECIMALS+1):
        r=close_round(tri,d)
        if valid_ring(r):
            if d>decimals: stats['rings_precision_escalated']+=1
            stats['max_decimals_used']=max(stats['max_decimals_used'],d)
            return r
    r=tri+[tri[0][:]]
    if valid_ring(r): return r
    raise ValueError('tiny ring fallback invalid')


def transform(g,tol,decimals,stats):
    t=g.get('type')
    if t=='Polygon': return {'type':'Polygon','coordinates':[simplify_ring(r,tol,decimals,stats) for r in g.get('coordinates',[])]}
    if t=='MultiPolygon': return {'type':'MultiPolygon','coordinates':[[simplify_ring(r,tol,decimals,stats) for r in poly] for poly in g.get('coordinates',[])]}
    if t=='GeometryCollection': return {'type':'GeometryCollection','geometries':[transform(x,tol,decimals,stats) for x in g.get('geometries',[])]}
    raise ValueError(f'unsupported geometry: {t}')


def count_vertices(g):
    t=g.get('type')
    if t=='Polygon': return sum(len(r) for r in g.get('coordinates',[]))
    if t=='MultiPolygon': return sum(len(r) for p in g.get('coordinates',[]) for r in p)
    if t=='GeometryCollection': return sum(count_vertices(x) for x in g.get('geometries',[]))
    raise ValueError(t)


def validate(g):
    t=g.get('type')
    if t=='Polygon': polys=[g.get('coordinates',[])]
    elif t=='MultiPolygon': polys=g.get('coordinates',[])
    elif t=='GeometryCollection':
        for x in g.get('geometries',[]): validate(x)
        return
    else: raise ValueError(t)
    for p in polys:
        if not p: raise ValueError('polygon without rings')
        for r in p:
            if not valid_ring(r): raise ValueError('invalid display ring')


def build_candidate(official, meta, cfg, tol, decimals, zip_sha, area_sha):
    stats={'rings_total':0,'rings_simplified':0,'rings_minimal_triangle':0,'rings_precision_escalated':0,'max_decimals_used':decimals}
    feats=[]; before=after=0; seen=set()
    for f in official['features']:
        code=str(f['id'])
        if code not in meta or code in seen: raise RuntimeError(f'bad/duplicate code {code}')
        seen.add(code); raw=f['geometry']; g=transform(raw,tol,decimals,stats); validate(g)
        before+=count_vertices(raw); after+=count_vertices(g)
        p=f.get('properties',{})
        feats.append({'type':'Feature','id':code,'properties':{'region_code':code,'geometry_key':code,'name_ja':meta[code].get('name'),'name_en':meta[code].get('enName'),'parent_code':meta[code].get('parent'),'office_name_ja':meta[code].get('officeName'),'source_part_count':p.get('source_part_count')},'geometry':g})
    if seen!=set(meta): raise RuntimeError('public feature code mismatch')
    feats.sort(key=lambda x:x['id'])
    obj={'type':'FeatureCollection','schema_version':'1.0.2','product':'LPZ_PUBLIC_JMA_PRIMARY_SUBDIVISION_GEOMETRY','geographic_unit':'JMA_PRIMARY_SUBDIVISION','geometry_key':'region_code','display_geometry_semantics':'AUTO_SIMPLIFIED_DERIVATIVE_FOR_WEB_DISPLAY_ONLY','scientific_masking_allowed':False,'risk_engine_allowed':False,'source':{'authority':cfg['source_authority'],'source_id':cfg['source_id'],'source_page':cfg['source_page'],'source_zip_url':cfg['zip_url'],'area_metadata_url':cfg['area_metadata_url'],'source_crs':'JGD2011 geographic lon/lat','source_zip_sha256':zip_sha,'area_metadata_sha256':area_sha},'display_transform':{'simplification_algorithm':'RDP_AUTO_TUNED_WITH_TINY_RING_TRIANGLE','tolerance_degrees':tol,'nominal_coordinate_decimals':decimals,'adaptive_precision_max_decimals':MAX_DECIMALS,'tiny_ring_fallback':'DISPLAY_ONLY_MINIMAL_TRIANGLE','research_geometry_modified':False},'region_count':len(feats),'features':feats}
    return obj, {'before':before,'after':after,'stats':stats}


def schedule(base,maxv):
    vals=[]; v=base
    while v<=maxv+1e-12:
        vals.append(round(v,10)); v*=2
    if not vals or vals[-1]<maxv: vals.append(maxv)
    return vals


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--config',type=Path,default=DEFAULT_CONFIG); ap.add_argument('--output',type=Path,default=DEFAULT_OUTPUT); ap.add_argument('--report',type=Path,default=DEFAULT_REPORT)
    ap.add_argument('--tolerance-deg',type=float,default=0.0015); ap.add_argument('--max-tolerance-deg',type=float,default=0.096); ap.add_argument('--coordinate-decimals',type=int,default=5); ap.add_argument('--target-output-mib',type=float,default=8.0); ap.add_argument('--max-output-mib',type=float,default=10.0)
    a=ap.parse_args()
    if a.tolerance_deg<=0 or a.max_tolerance_deg<a.tolerance_deg: raise ValueError('invalid tolerance range')
    if not 4<=a.coordinate_decimals<=8: raise ValueError('coordinate decimals must be 4..8')
    if not 0<a.target_output_mib<=a.max_output_mib: raise ValueError('invalid size limits')
    cfg=json.loads(a.config.read_text(encoding='utf-8'))
    if cfg.get('source_id')!='JMA_PRIMARY_SUBDIVISION_GIS': raise ValueError('unexpected source_id')

    print('='*104); print('LPZ PHASE 2L-O2 — PUBLIC JMA PRIMARY-SUBDIVISION GEOJSON'); print('='*104)
    print('Downloading JMA area metadata ...'); area=download(str(cfg['area_metadata_url'])); meta=extract_class10s(area); codes=set(meta); print(f'JMA class10s regions             : {len(codes)}')
    print('Downloading official JMA primary-subdivision GIS archive ...'); z=download(str(cfg['zip_url'])); print(f'GIS archive downloaded           : {len(z)/(1024**2):.1f} MiB')
    official=build_primary_subdivision_geojson(z,codes); missing=list(official.get('missing_required_codes') or [])
    if missing or int(official.get('resolved_code_count',-1))!=len(codes): raise RuntimeError(f'official geometry incomplete: {missing[:20]}')
    print(f'Official geometry resolved       : {len(codes)} / {len(codes)}')
    print(f'Auto-size target / hard max      : {a.target_output_mib:.2f} / {a.max_output_mib:.2f} MiB'); print('-'*104)

    trials=[]; chosen=None; best=None; zsha=sha256(z); asha=sha256(area)
    for tol in schedule(a.tolerance_deg,a.max_tolerance_deg):
        obj,m=build_candidate(official,meta,cfg,tol,a.coordinate_decimals,zsha,asha); payload=dump_bytes(obj); size=len(payload)/(1024**2); ratio=m['after']/m['before'] if m['before'] else 0
        trials.append({'tolerance_degrees':tol,'output_size_mib':size,'after_vertices':m['after'],'vertex_retention_fraction':ratio,'ring_fallback_statistics':m['stats']})
        print(f'trial tolerance={tol:<8g} size={size:>7.2f} MiB vertices={m["after"]:,} retention={ratio:.2%}')
        if size<=a.max_output_mib: best=(tol,obj,m,payload)
        if size<=a.target_output_mib: chosen=(tol,obj,m,payload); break
    if chosen is None: chosen=best
    if chosen is None:
        report={'schema_version':'1.0.2','phase':'2L-O2-public-primary-subdivision-geometry','gate':'FAIL_PHASE2L_O2_PUBLIC_GEOJSON_TOO_LARGE','trials':trials,'scientific_masking_allowed':False,'research_geometry_modified':False,'risk_engine_allowed':False}
        atomic_write(a.report,(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        raise RuntimeError(f'no safe simplification fit under {a.max_output_mib:.2f} MiB; see report')

    tol,obj,m,payload=chosen; atomic_write(a.output,payload); size=len(payload)/(1024**2); ratio=m['after']/m['before'] if m['before'] else 0; st=m['stats']
    report={'schema_version':'1.0.2','phase':'2L-O2-public-primary-subdivision-geometry','gate':PASS_GATE,'jma_class10s_count':len(codes),'official_geometry_resolved_count':len(codes),'output':str(a.output),'output_size_mib':size,'official_vertex_count_before_display_transform':m['before'],'public_vertex_count_after_display_transform':m['after'],'vertex_retention_fraction':ratio,'initial_tolerance_degrees':a.tolerance_deg,'selected_tolerance_degrees':tol,'ring_fallback_statistics':st,'auto_tuning_trials':trials,'scientific_masking_allowed':False,'research_geometry_modified':False,'risk_engine_allowed':False,'source_zip_sha256':zsha,'area_metadata_sha256':asha}
    atomic_write(a.report,(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print('-'*104); print(f'Selected display tolerance       : {tol:g} deg'); print(f'Vertices before display simplify : {m["before"]:,}'); print(f'Vertices after display simplify  : {m["after"]:,}'); print(f'Vertex retention                 : {ratio:.2%}'); print(f'Tiny-ring triangles              : {st["rings_minimal_triangle"]:,}'); print(f'Precision-escalated triangles    : {st["rings_precision_escalated"]:,}'); print(f'Maximum decimals actually used   : {st["max_decimals_used"]}'); print(f'Public GeoJSON size              : {size:.2f} MiB'); print('Scientific masking allowed       : NO'); print('Research geometry modified       : NO'); print('Risk engine                      : NOT ALLOWED'); print(); print(f'Gate                             : {PASS_GATE}'); print(f'GeoJSON                          : {a.output}'); print(f'Report                           : {a.report}'); print('='*104)
    return 0

if __name__=='__main__': raise SystemExit(main())
