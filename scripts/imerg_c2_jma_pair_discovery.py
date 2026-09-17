#!/usr/bin/env python3
"""C-2 preflight: discover whether the local canonical JMA archive can pair with IMERG.

Research-only. No network, no downloads, no production changes. This does NOT
pretend derived JMA feature JSON is a raw precipitation raster. It inventories
canonical records around the IMERG 30-minute support and reports whether a
true raster comparison is currently possible from local retained material.
"""
from __future__ import annotations
import argparse, gzip, json, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import h5py

DEFAULT_ARCHIVE_DIR=Path("reports/prospective/o8_1_canonical_daily")
ALT_ARCHIVE_DIRS=(Path("reports/prospective/o8_1_daily"),Path("reports/prospective/canonical_daily"),Path("reports/prospective"))
DEFAULT_IMERG_DIR=Path("reports/gap_recovery/c0_imerg")
DEFAULT_OUT=Path("reports/gap_recovery/c2_pair_discovery.json")
SLOT_KEYS=("collection_slot_utc","slot_utc","scientific_slot_utc","target_slot_utc")
RAW_HINTS=("raw","png","grib","grib2","raster","mosaic","tile_bytes","radar_bytes")

def newest_imerg(d:Path)->Path:
    c=[]
    for p in ("*.HDF5","*.hdf5","*.h5","*.H5"): c += list(d.glob(p))
    if not c: raise SystemExit(f"NO_IMERG_HDF5: {d}")
    return max(c,key=lambda x:x.stat().st_mtime)

def gpsish_to_iso(sec:int)->str:
    # Dataset documents seconds since 1980-01-06 and explicitly says leap seconds are not added.
    epoch=datetime(1980,1,6,tzinfo=timezone.utc)
    from datetime import timedelta
    return (epoch+timedelta(seconds=int(sec))).isoformat().replace("+00:00","Z")

def iter_json(path:Path)->Iterable[Any]:
    op=gzip.open if path.suffix==".gz" else open
    mode="rt"
    with op(path,mode,encoding="utf-8") as f:
        text=f.read()
    s=text.lstrip()
    if not s:return
    if s[0]=="[":
        for x in json.loads(text):yield x
    else:
        for line in text.splitlines():
            if line.strip():
                try: yield json.loads(line)
                except json.JSONDecodeError: continue

def walk(o:Any,prefix=""):
    if isinstance(o,dict):
        for k,v in o.items():
            p=f"{prefix}.{k}" if prefix else str(k)
            yield p,v
            yield from walk(v,p)
    elif isinstance(o,list):
        for i,v in enumerate(o): yield from walk(v,f"{prefix}[{i}]")

def slot_of(o:Any):
    if not isinstance(o,dict):return None
    for p,v in walk(o):
        if p.split(".")[-1] in SLOT_KEYS and isinstance(v,str): return v
    return None

def status_of(o:Any):
    if not isinstance(o,dict):return None
    for k in ("canonical_status","status","slot_status","quality"):
        if k in o:return o[k]
    return None

def raw_evidence(o:Any):
    hits=[]
    if isinstance(o,dict):
        for p,v in walk(o):
            q=p.lower()
            if any(h in q for h in RAW_HINTS):
                # Mere booleans saying raw archive is false are evidence of absence, not availability.
                hits.append({"path":p,"value":str(v)[:160]})
    return hits[:30]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--imerg",type=Path)
    ap.add_argument("--imerg-dir",type=Path,default=DEFAULT_IMERG_DIR)
    ap.add_argument("--archive-dir",type=Path)
    ap.add_argument("--output",type=Path,default=DEFAULT_OUT)
    a=ap.parse_args()
    im=a.imerg or newest_imerg(a.imerg_dir)
    with h5py.File(im,"r") as h:
        b=[int(x) for x in h["Grid/time_bnds"][0]]
    start_iso,end_iso=map(gpsish_to_iso,b)
    # Filename is authoritative cross-check for this product; retain both representations.
    m=re.search(r"(\d{8})-S(\d{6})-E(\d{6})",im.name)
    filename_window=None
    if m: filename_window={"date":m.group(1),"start_hhmmss":m.group(2),"end_hhmmss":m.group(3)}

    dirs=[a.archive_dir] if a.archive_dir else [DEFAULT_ARCHIVE_DIR,*ALT_ARCHIVE_DIRS]
    files=[]
    for d in dirs:
        if d and d.exists():
            files += list(d.rglob("*.jsonl.gz"))+list(d.rglob("*.jsonl"))+list(d.rglob("*.json"))
    files=sorted(set(files))
    # Restrict parsing to files plausibly containing the target UTC date when names allow it.
    target_date=im.name.split("3IMERG.")[-1][:8] if "3IMERG." in im.name else ""
    preferred=[p for p in files if target_date and target_date in p.name.replace("-","")]
    scan=preferred or files
    records=[]; raw_hits=[]
    for p in scan:
        try:
            for o in iter_json(p):
                s=slot_of(o)
                if s and target_date and target_date[:4]+"-"+target_date[4:6]+"-"+target_date[6:8] in s:
                    records.append({"file":str(p),"slot":s,"status":status_of(o)})
                    for h in raw_evidence(o): raw_hits.append({"file":str(p),"slot":s,**h})
        except Exception as e:
            records.append({"file":str(p),"parse_error":f"{type(e).__name__}: {e}"})
    slots=sorted({r["slot"] for r in records if "slot" in r})
    around=[s for s in slots if ("T23:15" in s or "T23:30" in s or "T23:45" in s or "T00:00" in s)]
    report={
      "schema_version":"0.1.0-imerg-c2-preflight","role":"RESEARCH_ONLY_PAIR_DISCOVERY",
      "risk_engine_allowed":False,"production_integration_allowed":False,
      "imerg_file":str(im),"imerg_time_bounds_dataset_interpretation":{"start":start_iso,"end":end_iso,"note":"Dataset epoch interpretation; filename retained as product-window cross-check"},
      "imerg_filename_window":filename_window,"archive_dirs_checked":[str(d) for d in dirs if d],
      "archive_files_found":len(files),"archive_files_scanned":len(scan),"target_date_records":len([r for r in records if "slot" in r]),
      "target_date_unique_slots":len(slots),"candidate_slots_near_imerg_window":around,
      "raw_raster_hint_count":len(raw_hits),"raw_raster_hints":raw_hits[:30],
    }
    # Current canonical archives are expected to be derived feature records. Do not claim a
    # raster comparison unless actual raw/raster material is evidenced.
    report["decision"]="PAIR_METADATA_FOUND_RAW_RASTER_NOT_PROVEN" if around else "NO_PAIR_METADATA_FOUND"
    report["next_required_input"]="raw JMA precipitation raster/tile material for the same 30-minute support, or a fresh temporary raw capture; derived feature JSON alone is insufficient for 0.1-degree raster comparison"
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
