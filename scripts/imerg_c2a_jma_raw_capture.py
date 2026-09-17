#!/usr/bin/env python3
"""C-2A temporary JMA HRPN raw capture for later IMERG pairing.

RESEARCH ONLY. Downloads a bounded Japan-domain z6 public-PNG set for seven
consecutive 5-minute analysis frames (30-minute span), selected from settled JMA
HRPN analysis metadata. Files are kept only under reports/gap_recovery and are
not production archives. No O8.1/O9/Primary/Risk Engine integration.
"""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(ROOT/"src"))
from lpz_risk.radar_science import lonlat_to_xyz

USER_AGENT="lpz-risk-system-c2a/0.1.0"
TIMES_URL="https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"
JAPAN_BBOX={"west":122.0,"east":154.0,"south":20.0,"north":46.0}
ZOOM=6; FRAME_COUNT=7; STEP_MIN=5; SETTLEMENT_MIN=15
TIMEOUT=20; MAX_BYTES=2*1024*1024; WORKERS=6
DEFAULT_OUT=Path("reports/gap_recovery/c2a_jma_raw")

def get(url,max_bytes=MAX_BYTES):
    req=Request(url,headers={"User-Agent":USER_AGENT,"Accept":"*/*","Cache-Control":"no-cache"})
    with urlopen(req,timeout=TIMEOUT) as r:
        body=r.read(max_bytes+1); status=getattr(r,"status",200); ctype=r.headers.get("Content-Type")
    if len(body)>max_bytes: raise ValueError("response too large")
    return body,status,ctype

def dt(v): return datetime.strptime(v,"%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
def iso(x): return x.isoformat().replace("+00:00","Z")

def tiles():
    _,x0,y0=lonlat_to_xyz(JAPAN_BBOX["west"],JAPAN_BBOX["north"],ZOOM)
    _,x1,y1=lonlat_to_xyz(JAPAN_BBOX["east"],JAPAN_BBOX["south"],ZOOM)
    xa,xb=sorted((x0,x1)); ya,yb=sorted((y0,y1))
    return [(x,y) for y in range(ya,yb+1) for x in range(xa,xb+1)]

def analysis_rows(rows):
    out={}
    for r in rows:
        if "hrpns" not in (r.get("elements") or []): continue
        if not r.get("basetime") or r.get("basetime")!=r.get("validtime"): continue
        try: out[dt(str(r["validtime"]))]=r
        except ValueError: pass
    return out

def choose_sequence(rowmap,now):
    cutoff=now-timedelta(minutes=SETTLEMENT_MIN)
    ends=sorted((t for t in rowmap if t<=cutoff),reverse=True)
    for end in ends:
        seq=[end-timedelta(minutes=STEP_MIN*i) for i in range(FRAME_COUNT-1,-1,-1)]
        if all(t in rowmap for t in seq): return [rowmap[t] for t in seq]
    raise RuntimeError("no settled contiguous 30-minute / 7-frame HRPN analysis sequence available")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output-root",type=Path,default=DEFAULT_OUT); a=ap.parse_args()
    now=datetime.now(timezone.utc)
    raw,status,ctype=get(TIMES_URL)
    rows=json.loads(raw.decode("utf-8")); seq=choose_sequence(analysis_rows(rows),now)
    start,end=dt(seq[0]["validtime"]),dt(seq[-1]["validtime"])
    capture=a.output_root/f"{start:%Y%m%dT%H%M%SZ}_{end:%Y%m%dT%H%M%SZ}_z{ZOOM}"
    capture.mkdir(parents=True,exist_ok=False)
    xy=tiles(); results=[]
    def one(item):
        row,x,y=item; vt=str(row["validtime"]); bt=str(row["basetime"])
        url=f"https://www.jma.go.jp/bosai/jmatile/data/nowc/{bt}/none/{vt}/surf/hrpns/{ZOOM}/{x}/{y}.png"
        rel=Path(vt)/f"z{ZOOM}_{x}_{y}.png"; path=capture/rel
        try:
            body,hs,ct=get(url); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(body)
            return {"validtime":vt,"z":ZOOM,"x":x,"y":y,"ok":True,"http_status":hs,"content_type":ct,"bytes":len(body),"sha256":hashlib.sha256(body).hexdigest(),"relative_path":str(rel)}
        except (HTTPError,URLError,TimeoutError,OSError,ValueError) as e:
            return {"validtime":vt,"z":ZOOM,"x":x,"y":y,"ok":False,"error":f"{type(e).__name__}: {e}"}
    jobs=[(r,x,y) for r in seq for x,y in xy]
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool: results=list(pool.map(one,jobs))
    failures=[r for r in results if not r["ok"]]
    per=[]
    for r in seq:
        vt=str(r["validtime"]); rr=[x for x in results if x["validtime"]==vt]
        per.append({"validtime":vt,"valid_time_utc":iso(dt(vt)),"tile_count":len(rr),"tiles_ok":sum(x["ok"] for x in rr),"tiles_failed":sum(not x["ok"] for x in rr)})
    manifest={"schema_version":"0.1.0-imerg-c2a","role":"RESEARCH_ONLY_TEMPORARY_JMA_RAW_CAPTURE","risk_engine_allowed":False,"production_integration_allowed":False,"raw_retention_policy":"TEMPORARY_RESEARCH_ONLY","captured_at_utc":iso(now),"source":"JMA_HRPN_ANALYSIS_PUBLIC_PNG","bbox":JAPAN_BBOX,"zoom":ZOOM,"frame_step_minutes":STEP_MIN,"frame_count":FRAME_COUNT,"support":{"start_utc":iso(start),"end_utc":iso(end),"span_minutes":int((end-start).total_seconds()/60)},"tile_count_per_frame":len(xy),"expected_downloads":len(jobs),"successful_downloads":sum(x["ok"] for x in results),"failed_downloads":len(failures),"frames":per,"tiles":results,"pairing_instruction":{"imerg_product":"GPM_3IMERGHHE V07","target_support":"later select IMERG half-hour granule overlapping this captured JMA support; do not upsample IMERG and call it JMA"},"result":"PASS_C2A_RAW_CAPTURE" if not failures else "FAIL_C2A_TILE_TRANSPORT"}
    (capture/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    summary={k:v for k,v in manifest.items() if k!="tiles"}; summary["capture_dir"]=str(capture); summary["manifest_path"]=str(capture/"manifest.json")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    raise SystemExit(0 if not failures else 2)
if __name__=="__main__": main()
