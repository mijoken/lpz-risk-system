#!/usr/bin/env python3
"""IMERG C-0 access probe.

Research-only connectivity/authentication/content probe. Downloads at most one
user-supplied IMERG file URL. It never stores credentials, never prints the
Bearer token, and does not touch O8.1/O9/Primary/Risk Engine.

Usage:
  python scripts/imerg_c0_access_probe.py --url "<one official file URL>" --output-dir reports/gap_recovery/c0_imerg

The script prompts securely for an Earthdata Bearer token. The token is kept
only in process memory.
"""
from __future__ import annotations
import argparse,getpass,hashlib,json,os,sys
from pathlib import Path
from urllib.parse import urlparse
import requests

ALLOWED_SUFFIXES=(".h5",".hdf5",".nc",".nc4")

def safe_name(url:str)->str:
    name=Path(urlparse(url).path).name or "imerg_probe.bin"
    return name.replace("..","_")

def inspect_hdf5(path:Path):
    try:
        import h5py
        out=[]
        with h5py.File(path,"r") as h:
            def visit(name,obj):
                if isinstance(obj,h5py.Dataset):
                    out.append({"path":name,"shape":list(obj.shape),"dtype":str(obj.dtype)})
            h.visititems(visit)
        return {"opened":True,"datasets":out[:200],"dataset_count":len(out)}
    except Exception as e:
        return {"opened":False,"error":f"{type(e).__name__}: {e}"}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--url",required=True,help="Exactly one official IMERG file download URL")
    ap.add_argument("--output-dir",type=Path,default=Path("reports/gap_recovery/c0_imerg"))
    ap.add_argument("--timeout",type=int,default=120)
    a=ap.parse_args()
    u=urlparse(a.url)
    if u.scheme!="https": raise SystemExit("REFUSE: URL must use https")
    token=getpass.getpass("Earthdata Bearer token (hidden; not stored): ").strip()
    if not token: raise SystemExit("REFUSE: empty token")
    a.output_dir.mkdir(parents=True,exist_ok=True)
    dst=a.output_dir/safe_name(a.url)
    tmp=dst.with_suffix(dst.suffix+".part")
    headers={"Authorization":f"Bearer {token}","User-Agent":"lpz-risk-system-imerg-c0/0.1"}
    meta={"schema_version":"0.1.0-imerg-c0","role":"RESEARCH_ONLY_ACCESS_PROBE","requested_host":u.hostname,"requested_path":u.path,"credentials_persisted":False,"risk_engine_allowed":False}
    try:
        with requests.get(a.url,headers=headers,stream=True,timeout=a.timeout,allow_redirects=True) as r:
            meta.update({"http_status":r.status_code,"final_host":urlparse(r.url).hostname,"content_type":r.headers.get("Content-Type"),"content_length_header":r.headers.get("Content-Length")})
            if r.status_code!=200:
                meta["result"]="HTTP_FAILURE"
                meta["redirect_history"]=[{"status":x.status_code,"host":urlparse(x.url).hostname} for x in r.history]
                print(json.dumps(meta,ensure_ascii=False,indent=2));return 2
            h=hashlib.sha256();n=0
            with tmp.open("wb") as f:
                for chunk in r.iter_content(1024*1024):
                    if chunk:
                        f.write(chunk);h.update(chunk);n+=len(chunk)
        os.replace(tmp,dst)
        meta.update({"result":"DOWNLOAD_OK","filename":dst.name,"bytes":n,"sha256":h.hexdigest()})
        if dst.suffix.lower() in ALLOWED_SUFFIXES:
            meta["hdf5_inspection"]=inspect_hdf5(dst)
        (a.output_dir/"probe_result.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(meta,ensure_ascii=False,indent=2));return 0
    finally:
        token=""
        if tmp.exists(): tmp.unlink(missing_ok=True)

if __name__=="__main__": sys.exit(main())
