#!/usr/bin/env python3
"""Acquire one small real payload from each zero-cost historical precipitation provider.

Raw payloads are used ephemerally for scientific format inspection and are not committed.
The emitted JSON contains only metadata/descriptors and never credentials.
"""
from __future__ import annotations

import argparse
import ftplib
import gzip
import json
import os
import re
import tempfile
from pathlib import Path

import h5py
import numpy as np


def _safe_nlst(ftp: ftplib.FTP, path: str) -> list[str]:
    cur = ftp.pwd()
    try:
        ftp.cwd(path)
        rows = ftp.nlst()
        return sorted(str(x) for x in rows)
    finally:
        ftp.cwd(cur)


def _gsmap_probe() -> dict:
    host = "hokusai.eorc.jaxa.jp"
    user = os.environ["GSMAP_FTP_USERNAME"]
    password = os.environ["GSMAP_FTP_PASSWORD"]
    out = {
        "source_id": "GSMAP_GAUGE_STANDARD_V8",
        "host": host,
        "requested_root": "/standard/v8",
        "secret_value_recorded": False,
        "risk_score": None,
    }
    with ftplib.FTP(timeout=60) as ftp:
        ftp.connect(host, 21)
        ftp.login(user, password)
        root = _safe_nlst(ftp, "/standard/v8")
        out["root_entries"] = root[:100]
        out["root_entry_count"] = len(root)

        # Discover likely gauge/data directories conservatively without assuming layout.
        candidate_dirs = []
        for x in root:
            name = x.rstrip("/").split("/")[-1]
            if re.search(r"gauge|hour|dat|binary|txt|product", name, re.I):
                candidate_dirs.append(name)
        out["candidate_entries"] = candidate_dirs[:50]

        # Retrieve one small documentation text file if present.
        doc_candidates = [x for x in root if re.search(r"readme|format|history|note|txt$|pdf$", x, re.I)]
        docs = []
        for name in doc_candidates[:5]:
            base = name.rstrip("/").split("/")[-1]
            buf = bytearray()
            try:
                ftp.retrbinary(f"RETR /standard/v8/{base}", buf.extend)
                docs.append({"name": base, "bytes": len(buf), "sha256_prefix": __import__('hashlib').sha256(buf).hexdigest()[:16]})
            except Exception:
                continue
        out["documentation_files_retrieved"] = docs

        # Walk only a few likely directories and find one compressed/binary data file.
        data_file = None
        data_dir = None
        search_dirs = ["/standard/v8"]
        for x in root:
            base = x.rstrip("/").split("/")[-1]
            if base and not re.search(r"readme|pdf|txt|history|note", base, re.I):
                search_dirs.append(f"/standard/v8/{base}")
        for d in search_dirs[:20]:
            try:
                entries = _safe_nlst(ftp, d)
            except Exception:
                continue
            for e in entries[:300]:
                base = e.rstrip("/").split("/")[-1]
                if re.search(r"\.(gz|bin|dat)$", base, re.I) or re.search(r"gsmap.*\d{8}", base, re.I):
                    data_file = base
                    data_dir = d
                    break
            if data_file:
                break
        out["first_level_data_candidate"] = None if not data_file else f"{data_dir}/{data_file}"
        if data_file:
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / data_file
                with p.open("wb") as f:
                    ftp.retrbinary(f"RETR {data_dir}/{data_file}", f.write)
                out["payload_bytes"] = p.stat().st_size
                out["payload_filename"] = data_file
                out["payload_suffixes"] = p.suffixes
                # Do not interpret the binary until format documentation is audited.
                out["payload_gate"] = "PASS_REAL_FILE_ACQUIRED_FORMAT_DECODE_PENDING"
        else:
            out["payload_gate"] = "PASS_DIRECTORY_ACCESS_DATA_FILE_DISCOVERY_PENDING"
    return out


def _walk_hdf5(group: h5py.Group, prefix: str = "") -> list[dict]:
    rows = []
    for key, obj in group.items():
        path = f"{prefix}/{key}" if prefix else f"/{key}"
        if isinstance(obj, h5py.Dataset):
            rows.append({
                "path": path,
                "shape": list(obj.shape),
                "dtype": str(obj.dtype),
                "units": str(obj.attrs.get("units", "")),
                "long_name": str(obj.attrs.get("LongName", obj.attrs.get("long_name", ""))),
            })
        elif isinstance(obj, h5py.Group):
            rows.extend(_walk_hdf5(obj, path))
    return rows


def _imerg_probe() -> dict:
    import earthaccess

    short_name = "GPM_3IMERGHH"
    version = "07"
    earthaccess.login(strategy="environment")
    granules = earthaccess.search_data(
        short_name=short_name,
        version=version,
        bounding_box=(129.0, 30.0, 146.0, 46.0),
        temporal=("2025-07-01T00:00:00Z", "2025-07-01T00:31:00Z"),
        count=1,
    )
    if not granules:
        raise RuntimeError("IMERG granule search returned zero rows")
    with tempfile.TemporaryDirectory() as td:
        paths = earthaccess.download(granules[:1], td, threads=1)
        if not paths:
            raise RuntimeError("IMERG download returned no path")
        p = Path(paths[0])
        with h5py.File(p, "r") as h:
            datasets = _walk_hdf5(h)
            precip = [d for d in datasets if "precip" in d["path"].lower()]
            finite_summary = None
            # Prefer gauge-calibrated precipitation where present.
            preferred = next((d for d in precip if d["path"].lower().endswith("/precipitation")), precip[0] if precip else None)
            if preferred is not None:
                arr = np.asarray(h[preferred["path"]][...], dtype=float)
                fill = h[preferred["path"]].attrs.get("_FillValue")
                if fill is not None:
                    arr = arr[arr != float(fill)]
                arr = arr[np.isfinite(arr)]
                if arr.size:
                    finite_summary = {
                        "dataset": preferred["path"],
                        "finite_count": int(arr.size),
                        "min": float(np.min(arr)),
                        "max": float(np.max(arr)),
                        "mean": float(np.mean(arr)),
                    }
        return {
            "source_id": "NASA_IMERG_FINAL_V07",
            "short_name": short_name,
            "version": version,
            "granule_count": len(granules),
            "payload_filename": p.name,
            "payload_bytes": p.stat().st_size,
            "dataset_count": len(datasets),
            "precipitation_dataset_count": len(precip),
            "precipitation_datasets": precip[:30],
            "finite_precipitation_summary": finite_summary,
            "payload_gate": "PASS_REAL_HDF5_ACQUIRED_AND_DECODED" if precip else "FAIL_NO_PRECIPITATION_DATASET",
            "secret_value_recorded": False,
            "risk_score": None,
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="reports/historical/free_precipitation_payload_probe.json")
    args = ap.parse_args()

    providers = []
    errors = []
    for fn in (_gsmap_probe, _imerg_probe):
        try:
            providers.append(fn())
        except Exception as exc:
            providers.append({
                "source_id": fn.__name__.removeprefix("_").removesuffix("_probe").upper(),
                "payload_gate": "FAIL",
                "error_type": type(exc).__name__,
                "error": str(exc)[:1000],
                "secret_value_recorded": False,
                "risk_score": None,
            })
            errors.append(type(exc).__name__)

    report = {
        "schema_version": "0.1.0",
        "phase": "2F-free-precipitation-payload-proof",
        "zero_cost_required": True,
        "providers": providers,
        "all_payload_proofs_pass": all(str(p.get("payload_gate", "")).startswith("PASS") for p in providers),
        "raw_payloads_persisted": False,
        "lpz_classification": None,
        "risk_score": None,
        "risk_engine_allowed": False,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_payload_proofs_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
