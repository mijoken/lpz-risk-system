#!/usr/bin/env python3
"""Probe IMERG Final V07 daily and CMORPH daily payload structure for Phase 2L.

No threshold selection, candidate labeling, or risk scoring is performed.
CMORPH daily CDR is resolved from the provider's live CPC monthly-tar index;
no creation/revision suffix is fabricated.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import tarfile
from calendar import monthrange
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

CPC_CMORPH_CDR_INDEX = "https://ftp.cpc.ncep.noaa.gov/precip/CDR_CMORPH/"
USER_AGENT = "lpz-risk-system/0.1 research"


def _jsonable(v):
    try:
        return v.item()
    except Exception:
        return str(v)


def _inspect_netcdf(path: Path) -> dict:
    from netCDF4 import Dataset

    out = {"path": path.name, "variables": {}, "dimensions": {}}
    with Dataset(path) as ds:
        out["dimensions"] = {k: len(v) for k, v in ds.dimensions.items()}
        for name, var in ds.variables.items():
            out["variables"][name] = {
                "dimensions": list(var.dimensions),
                "shape": list(var.shape),
                "dtype": str(var.dtype),
                "units": getattr(var, "units", None),
                "standard_name": getattr(var, "standard_name", None),
                "long_name": getattr(var, "long_name", None),
                "fill_value": _jsonable(getattr(var, "_FillValue", None)),
            }
    return out


def _read_url(url: str, timeout: int = 180) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as response:
        payload = response.read()
    if len(payload) < 1024:
        raise ValueError(f"payload unexpectedly small: {url} {len(payload)} bytes")
    return payload


def _probe_imerg(date: str, work: Path) -> dict:
    import earthaccess

    dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    earthaccess.login(strategy="environment")
    granules = earthaccess.search_data(
        short_name="GPM_3IMERGDF",
        version="07",
        bounding_box=(122.0, 24.0, 150.0, 47.0),
        temporal=(
            dt.isoformat(),
            dt.replace(hour=23, minute=59, second=59).isoformat(),
        ),
        count=5,
    )
    if len(granules) != 1:
        raise RuntimeError(
            f"expected exactly one IMERG daily granule, got {len(granules)}"
        )
    dest = work / "imerg"
    dest.mkdir(parents=True, exist_ok=True)
    paths = earthaccess.download(granules, str(dest), threads=1)
    if len(paths) != 1:
        raise RuntimeError(f"IMERG daily download count mismatch: {paths}")
    p = Path(paths[0])
    return {
        "provider": "NASA_IMERG_FINAL_V07_DAILY",
        "short_name": "GPM_3IMERGDF",
        "inspection": _inspect_netcdf(p),
    }


def _resolve_cmorph_monthly_tar(dt: datetime) -> tuple[str, str]:
    html = _read_url(CPC_CMORPH_CDR_INDEX, timeout=60).decode(
        "utf-8", errors="replace"
    )
    last_day = monthrange(dt.year, dt.month)[1]
    prefix = (
        f"cmorph_v1.0_0.25deg_daily_s{dt:%Y%m}01_"
        f"e{dt:%Y%m}{last_day:02d}_c"
    )
    pattern = re.compile(
        rf'href=["\']([^"\']*{re.escape(prefix)}\d{{8}}\.tar)["\']',
        re.IGNORECASE,
    )
    names = sorted({Path(m).name for m in pattern.findall(html)})
    if not names:
        # Fall back to visible-text matching because Apache index formatting can vary.
        text_pattern = re.compile(
            rf'({re.escape(prefix)}\d{{8}}\.tar)', re.IGNORECASE
        )
        names = sorted({Path(m).name for m in text_pattern.findall(html)})
    if len(names) != 1:
        raise RuntimeError(
            f"CMORPH monthly daily tar resolution failed for {dt:%Y-%m}: {names}"
        )
    name = names[0]
    return name, CPC_CMORPH_CDR_INDEX + name


def _extract_cmorph_daily_member(
    tar_payload: bytes, dt: datetime, work: Path
) -> tuple[Path, str, list[str]]:
    target_token = dt.strftime("%Y%m%d")
    with tarfile.open(fileobj=io.BytesIO(tar_payload), mode="r:*") as tf:
        members = [
            m
            for m in tf.getmembers()
            if m.isfile()
            and target_token in Path(m.name).name
            and Path(m.name).suffix.lower() == ".nc"
        ]
        all_nc = [Path(m.name).name for m in tf.getmembers() if m.isfile() and Path(m.name).suffix.lower() == ".nc"]
        if len(members) != 1:
            raise RuntimeError(
                f"expected one CMORPH daily NetCDF member for {target_token}, "
                f"got {[m.name for m in members]}"
            )
        member = members[0]
        source = tf.extractfile(member)
        if source is None:
            raise RuntimeError(f"failed to extract CMORPH member: {member.name}")
        payload = source.read()
    if len(payload) < 1024:
        raise ValueError(
            f"CMORPH daily member unexpectedly small: {member.name} {len(payload)}"
        )
    out = work / Path(member.name).name
    out.write_bytes(payload)
    return out, member.name, all_nc


def _probe_cmorph(date: str, work: Path) -> dict:
    dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    tar_name, tar_url = _resolve_cmorph_monthly_tar(dt)
    tar_payload = _read_url(tar_url, timeout=180)
    p, member_name, all_nc = _extract_cmorph_daily_member(tar_payload, dt, work)
    return {
        "provider": "NOAA_CMORPH_CDR_DAILY",
        "distribution": "CPC_CDR_CMORPH_MONTHLY_TAR",
        "monthly_tar_name": tar_name,
        "monthly_tar_url": tar_url,
        "monthly_tar_bytes": len(tar_payload),
        "daily_member_name": member_name,
        "monthly_netcdf_member_count": len(all_nc),
        "inspection": _inspect_netcdf(p),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2023-07-10")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    work = Path("work/phase2l_probe")
    work.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "0.2.0",
        "phase": "2L-daily-screening-payload-proof",
        "probe_date": args.date,
        "imerg": _probe_imerg(args.date, work),
        "cmorph": _probe_cmorph(args.date, work),
        "threshold_selected": False,
        "candidate_generated": False,
        "hard_negative_label": None,
        "validation_data_used": False,
        "risk_engine_allowed": False,
        "gate": "PASS_DUAL_DAILY_SCREENING_PAYLOAD_PROOF",
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "gate": report["gate"],
                "imerg_file": report["imerg"]["inspection"]["path"],
                "cmorph_tar": report["cmorph"]["monthly_tar_name"],
                "cmorph_member": report["cmorph"]["daily_member_name"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
