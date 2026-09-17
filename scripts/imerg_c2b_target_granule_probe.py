#!/usr/bin/env python3
"""C-2B targeted IMERG Early granule discovery/download for a C-2A JMA capture.

Research only. Reads a local C-2A manifest, derives the IMERG half-hour windows
that overlap the captured JMA frames, queries CMR for those exact windows, and
optionally downloads at most the selected granules. No production integration.
"""
from __future__ import annotations
import argparse, getpass, hashlib, json, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

CMR="https://cmr.earthdata.nasa.gov/search/granules.umm_json"
SHORT="GPM_3IMERGHHE"; VERSION="07"; CLIENT="lpz-risk-system-imerg-c2b"
DEFAULT_JMA=Path("reports/gap_recovery/c2a_jma_raw")
DEFAULT_OUT=Path("reports/gap_recovery/c2b_imerg_target")

def parse_iso(s): return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc)
def iso(d): return d.isoformat().replace("+00:00","Z")
def floor30(d): return d.replace(minute=(d.minute//30)*30,second=0,microsecond=0)

def newest_manifest(root):
    c=list(root.rglob("manifest.json"))
    if not c: raise SystemExit(f"NO_C2A_MANIFEST: {root}")
    return max(c,key=lambda p:p.stat().st_mtime)

def windows_from_manifest(m):
    # Pair by actual captured frame timestamps. A 30-min IMERG window is retained
    # when it contains >=2 JMA frames; exact weighting/alignment is deferred to C-2C.
    ts=[parse_iso(x["valid_time_utc"]) for x in m["frames"]]
    groups={}
    for t in ts: groups.setdefault(floor30(t),[]).append(t)
    out=[]
    for st,frames in sorted(groups.items()):
        en=st+timedelta(minutes=30)
        if len(frames)>=2: out.append({"start":st,"end":en,"jma_frames":[iso(x) for x in frames]})
    return out

def discover(st,en):
    # CMR temporal end is made one second before the next boundary to avoid pulling
    # the adjacent granule merely because intervals touch.
    qend=en-timedelta(microseconds=1)
    params={"short_name":SHORT,"version":VERSION,"downloadable":"true","page_size":20,
            "temporal":f"{iso(st)},{iso(qend)}"}
    r=requests.get(CMR,params=params,headers={"Accept":"application/json","Client-Id":CLIENT},timeout=30); r.raise_for_status()
    data=r.json(); hits=[]
    for item in data.get("items",[]):
        umm=item.get("umm") or {}; ur=str(umm.get("GranuleUR") or "")
        te=umm.get("TemporalExtent") or {}; urls=[]
        for u in umm.get("RelatedUrls") or []:
            if u.get("Type")=="GET DATA" and u.get("URL"): urls.append(u["URL"])
        # Prefer the exact half-hour start encoded in the IMERG filename.
        token=st.strftime("%Y%m%d-S%H%M%S")
        exact=token in ur
        hits.append({"concept_id":item.get("meta",{}).get("concept-id"),"granule_ur":ur,
                     "temporal_extent":te,"get_data_urls":urls,"exact_start_match":exact})
    exact=[x for x in hits if x["exact_start_match"] and x["get_data_urls"]]
    return hits, (exact[0] if len(exact)==1 else None)

def download(url,outdir,token):
    name=Path(urlparse(url).path).name; dest=outdir/name; part=dest.with_suffix(dest.suffix+".part")
    with requests.get(url,headers={"Authorization":f"Bearer {token}","User-Agent":CLIENT},stream=True,timeout=60) as r:
        r.raise_for_status(); h=hashlib.sha256(); n=0
        with part.open("wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk: f.write(chunk); h.update(chunk); n+=len(chunk)
        final_host=urlparse(r.url).hostname
    part.replace(dest)
    return {"filename":name,"path":str(dest),"bytes":n,"sha256":h.hexdigest(),"final_host":final_host}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--manifest",type=Path); ap.add_argument("--jma-root",type=Path,default=DEFAULT_JMA)
    ap.add_argument("--output-dir",type=Path,default=DEFAULT_OUT); ap.add_argument("--download",action="store_true"); a=ap.parse_args()
    mp=a.manifest or newest_manifest(a.jma_root); m=json.loads(mp.read_text(encoding="utf-8")); wins=windows_from_manifest(m)
    report={"schema_version":"0.1.0-imerg-c2b","role":"RESEARCH_ONLY_TARGET_GRANULE_PROBE","risk_engine_allowed":False,
            "production_integration_allowed":False,"jma_manifest":str(mp),"collection":{"short_name":SHORT,"version":VERSION},"windows":[]}
    selected=[]
    for w in wins:
        hits,sel=discover(w["start"],w["end"])
        row={"start_utc":iso(w["start"]),"end_utc":iso(w["end"]),"jma_frames":w["jma_frames"],"cmr_hit_count":len(hits),
             "exact_candidates":[{"granule_ur":x["granule_ur"],"temporal_extent":x["temporal_extent"],"get_data_url_count":len(x["get_data_urls"])} for x in hits if x["exact_start_match"]]}
        if sel:
            row["selected_granule_ur"]=sel["granule_ur"]; row["selected_url_host"]=urlparse(sel["get_data_urls"][0]).hostname
            selected.append((row,sel["get_data_urls"][0]))
        report["windows"].append(row)
    report["selected_granule_count"]=len(selected)
    if a.download and selected:
        token=getpass.getpass("Earthdata Bearer token (hidden; not stored): ").strip()
        if not token: raise SystemExit("EMPTY_TOKEN")
        a.output_dir.mkdir(parents=True,exist_ok=True); report["downloads"]=[]
        for row,url in selected:
            d=download(url,a.output_dir,token); d["granule_ur"]=row["selected_granule_ur"]; report["downloads"].append(d)
        report["credentials_persisted"]=False
    report["result"]=("TARGET_GRANULES_DOWNLOADED" if a.download and selected else "TARGET_GRANULES_DISCOVERED" if selected else "TARGET_GRANULES_NOT_YET_AVAILABLE")
    a.output_dir.mkdir(parents=True,exist_ok=True); (a.output_dir/"probe_result.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
