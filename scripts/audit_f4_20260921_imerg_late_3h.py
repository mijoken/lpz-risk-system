#!/usr/bin/env python3
"""Independent 3-hour IMERG Late V07 audit for the 2026-09-21 Tohoku case.

Downloads exactly six 30-minute NASA IMERG Late V07 granules covering
2026-09-21 10:00–13:00 UTC (19:00–22:00 JST), computes source-native
3-hour accumulation on the published F4 fixed-mosaic geographic envelope,
and prints descriptive accumulation/morphology only.

This is NOT the official JMA 5-km analyzed-rainfall LPZ algorithm, NOT F4-9C
forecast verification, and NOT an LPZ classifier. Raw NASA payloads live only
inside a temporary directory and are deleted when the process exits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import h5py
import numpy as np

START = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
END = datetime(2026, 9, 21, 13, 0, tzinfo=timezone.utc)
EXPECTED = [START + timedelta(minutes=30*i) for i in range(6)]
BBOX = (140.625, 36.597889, 146.25, 40.979898)  # west,south,east,north
EARTH_RADIUS_KM = 6371.0088
FILENAME_RE = re.compile(
    r".*3IMERG\.(?P<date>\d{8})-S(?P<hh>\d{2})(?P<mm>\d{2})(?P<ss>\d{2})"
    r"-E(?P<eh>\d{2})(?P<em>\d{2})(?P<es>\d{2}).*V07[A-Z]?.*"
)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def start_from_name(name: str) -> datetime:
    m = FILENAME_RE.match(Path(name).name)
    if not m:
        raise ValueError(f"unrecognized IMERG Late V07 filename: {name}")
    d = datetime.strptime(m.group("date"), "%Y%m%d").replace(tzinfo=timezone.utc)
    return d.replace(hour=int(m.group("hh")), minute=int(m.group("mm")), second=int(m.group("ss")))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def decode(path: Path) -> tuple[datetime, np.ndarray, np.ndarray, np.ndarray, str]:
    start = start_from_name(path.name)
    with h5py.File(path, "r") as h:
        ds = h["/Grid/precipitation"]
        lon = np.asarray(h["/Grid/lon"][...], dtype=np.float64).reshape(-1)
        lat = np.asarray(h["/Grid/lat"][...], dtype=np.float64).reshape(-1)
        raw = np.asarray(ds[...], dtype=np.float64)
        if raw.ndim == 3 and raw.shape[0] == 1:
            raw = raw[0]
        if raw.shape == (lon.size, lat.size):
            rain = raw.T
        elif raw.shape == (lat.size, lon.size):
            rain = raw
        else:
            raise ValueError(f"unexpected IMERG grid shape {raw.shape}")
        fill = ds.attrs.get("_FillValue", None)
        if fill is not None:
            fv = float(np.asarray(fill).reshape(-1)[0])
            rain[np.isclose(rain, fv)] = np.nan
        rain[rain < 0.0] = np.nan
        units = ds.attrs.get("units", "")
        if isinstance(units, bytes):
            units = units.decode("utf-8", errors="replace")
        normalized = str(units).lower().replace(" ", "")
        if normalized not in {"mm/hr", "mmhr-1", "mmh-1"}:
            raise ValueError(f"unexpected precipitation units {units!r}")
        header = h.attrs.get("FileHeader", "")
        if isinstance(header, bytes):
            header = header.decode("utf-8", errors="replace")
    return start, rain, lon, lat, str(header)


def subset(rain: np.ndarray, lon: np.ndarray, lat: np.ndarray):
    west, south, east, north = BBOX
    xi = np.where((lon >= west) & (lon <= east))[0]
    yi = np.where((lat >= south) & (lat <= north))[0]
    if not len(xi) or not len(yi):
        raise ValueError("event bbox not represented in IMERG grid")
    return rain[np.ix_(yi, xi)], lon[xi], lat[yi]


def cell_area_km2(lat_center: float, dlat: float, dlon: float) -> float:
    lat1 = math.radians(lat_center - dlat/2)
    lat2 = math.radians(lat_center + dlat/2)
    return (EARTH_RADIUS_KM**2) * math.radians(dlon) * abs(math.sin(lat2)-math.sin(lat1))


def components(mask: np.ndarray) -> list[np.ndarray]:
    h,w = mask.shape
    seen = np.zeros(mask.shape, dtype=bool)
    out=[]
    neigh=((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1))
    for r,c in np.argwhere(mask):
        r=int(r);c=int(c)
        if seen[r,c]:
            continue
        q=deque([(r,c)]);seen[r,c]=True;pts=[]
        while q:
            rr,cc=q.popleft();pts.append((rr,cc))
            for dr,dc in neigh:
                nr,nc=rr+dr,cc+dc
                if 0<=nr<h and 0<=nc<w and mask[nr,nc] and not seen[nr,nc]:
                    seen[nr,nc]=True;q.append((nr,nc))
        out.append(np.asarray(pts,dtype=np.int32))
    return out


def component_descriptor(points: np.ndarray, lon: np.ndarray, lat: np.ndarray) -> dict[str, Any]:
    rr=points[:,0]; cc=points[:,1]
    lons=lon[cc]; lats=lat[rr]
    dlat=float(np.median(np.abs(np.diff(lat)))) if len(lat)>1 else 0.1
    dlon=float(np.median(np.abs(np.diff(lon)))) if len(lon)>1 else 0.1
    area=sum(cell_area_km2(float(x), dlat, dlon) for x in lats)
    clat=float(np.mean(lats)); clon=float(np.mean(lons))
    x=(lons-clon)*111.32*math.cos(math.radians(clat))
    y=(lats-clat)*111.32
    if len(points)>=2:
        cov=np.cov(np.column_stack([x,y]),rowvar=False,ddof=0)
        vals,vecs=np.linalg.eigh(cov)
        order=np.argsort(vals)[::-1]; vals=np.maximum(vals[order],0.0); vecs=vecs[:,order]
        ratio=None if len(vals)<2 or vals[1]<=0 else math.sqrt(float(vals[0]/vals[1]))
        vx,vy=map(float,vecs[:,0])
        orientation=math.degrees(math.atan2(vx,vy))%180.0
    else:
        ratio=None; orientation=None
    return {
        "cell_count": int(len(points)),
        "area_km2": round(float(area),2),
        "centroid_lon": round(clon,4),
        "centroid_lat": round(clat,4),
        "pca_aspect_ratio": round(ratio,3) if ratio is not None else None,
        "orientation_deg_clockwise_from_north": round(orientation,2) if orientation is not None else None,
    }


def summarize(accum: np.ndarray, lon: np.ndarray, lat: np.ndarray) -> dict[str, Any]:
    valid=np.isfinite(accum)
    vals=accum[valid]
    if vals.size==0:
        raise ValueError("no valid IMERG accumulation cells in event bbox")
    summary={
        "valid_cell_count": int(vals.size),
        "max_3h_mm": round(float(np.max(vals)),2),
        "p90_3h_mm": round(float(np.percentile(vals,90)),2),
        "p95_3h_mm": round(float(np.percentile(vals,95)),2),
        "p99_3h_mm": round(float(np.percentile(vals,99)),2),
    }
    rr,cc=np.unravel_index(np.nanargmax(accum),accum.shape)
    summary["max_cell_lon_lat"]=[round(float(lon[cc]),4),round(float(lat[rr]),4)]
    thresholds={}
    for threshold in (50.0,80.0,100.0,150.0):
        mask=valid & (accum>=threshold)
        comps=components(mask)
        desc=sorted((component_descriptor(p,lon,lat) for p in comps),key=lambda x:x["area_km2"],reverse=True)
        thresholds[str(int(threshold))]={
            "cell_count": int(np.count_nonzero(mask)),
            "connected_component_count": len(comps),
            "largest_component": desc[0] if desc else None,
        }
    summary["source_native_threshold_descriptors_mm"]=thresholds
    return summary


def run_download() -> dict[str, Any]:
    if not os.environ.get("EARTHDATA_USERNAME") or not os.environ.get("EARTHDATA_PASSWORD"):
        raise RuntimeError("EARTHDATA_USERNAME/EARTHDATA_PASSWORD are required in this process only")
    import earthaccess
    auth=earthaccess.login(strategy="environment")
    if not auth.authenticated:
        raise RuntimeError("Earthdata authentication failed")
    granules=earthaccess.search_data(
        short_name="GPM_3IMERGHHL",
        version="07",
        bounding_box=BBOX,
        temporal=(iso(START), iso(END-timedelta(seconds=1))),
        count=20,
    )
    if len(granules)<6:
        raise RuntimeError(f"expected at least six IMERG Late granules, found {len(granules)}")
    with tempfile.TemporaryDirectory(prefix="lpz-imerg-late-audit-") as td:
        paths=[Path(p) for p in earthaccess.download(granules,td,threads=1)]
        decoded={}
        provenance=[]
        for p in paths:
            try:
                start,rain,lon,lat,header=decode(p)
            except Exception:
                continue
            if start not in EXPECTED:
                continue
            if start in decoded:
                raise ValueError(f"duplicate IMERG Late granule for {iso(start)}")
            sub,slon,slat=subset(rain,lon,lat)
            decoded[start]=(sub,slon,slat)
            provenance.append({
                "start_utc":iso(start),
                "filename":p.name,
                "sha256":sha256(p),
                "bytes":p.stat().st_size,
                "file_header_hybrid_or_version_excerpt":header[:500],
            })
        missing=[x for x in EXPECTED if x not in decoded]
        if missing:
            raise RuntimeError("missing exact half-hour granules: "+",".join(iso(x) for x in missing))
        first=decoded[EXPECTED[0]]
        lon=first[1];lat=first[2]
        fields=[]
        for t in EXPECTED:
            a,lo,la=decoded[t]
            if not np.array_equal(lo,lon) or not np.array_equal(la,lat):
                raise ValueError("IMERG event subset grid changed inside 3-hour window")
            fields.append(a)
        stack=np.stack(fields)
        complete=np.all(np.isfinite(stack),axis=0)
        accum=np.full(stack.shape[1:],np.nan,dtype=np.float64)
        accum[complete]=np.sum(stack[:,complete]*0.5,axis=0)
        result={
            "audit_product":"F4_20260921_IMERG_LATE_V07_3H_INDEPENDENT_ACCUMULATION",
            "product_short_name":"GPM_3IMERGHHL",
            "product_version":"07",
            "known_2026_processing_context":"IMERG Late/Early V07 hybrid period pending V08 NRT switch",
            "window_start_utc":iso(START),
            "window_end_utc":iso(END),
            "half_hour_granule_count":6,
            "event_bbox_wsen":list(BBOX),
            "raw_payloads_persisted":False,
            "provenance":sorted(provenance,key=lambda x:x["start_utc"]),
            "summary":summarize(accum,lon,lat),
            "interpretation_limits":[
                "IMERG Late is a 0.1-degree multisatellite estimate, not JMA 5-km analyzed rainfall.",
                "100/150-mm descriptors are source-native 3-hour accumulation screens, not official LPZ issuance criteria.",
                "IMERG Late extremes are less research-final than IMERG Final; Final is not yet expected for this event.",
                "2026 Late/Early processing is in the documented hybrid V07 transition posture.",
                "No F4-9C future observations, verification rows, forecast skill, or F4-9D decision are read.",
            ],
            "read_f4_9c_verifications":False,
            "forecast_skill_scored":False,
            "risk_engine_allowed":False,
        }
        return result


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output",default="")
    args=ap.parse_args()
    result=run_download()
    text=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    print(text,end="")
    if args.output:
        out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(text,encoding="utf-8")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
