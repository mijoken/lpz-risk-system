#!/usr/bin/env python3
"""Phase 2L GSMaP v8 NetCDF single-file FTP proof.

Purpose: verify the recovered JAXA FTP account can acquire one historical Standard v8
NetCDF file from a Development-era day without broad traversal or parallel access.
The raw NetCDF is kept only in a temporary directory. Only metadata/descriptors are
written to the report. No thresholds, labels, source fusion, or risk scoring.
"""
from __future__ import annotations

import argparse
import ftplib
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

HOST = "hokusai.eorc.jaxa.jp"
ROOT = "/standard/v8/netcdf"
DEFAULT_DATE = "2023-07-10"


def list_names(ftp: ftplib.FTP, path: str) -> list[str]:
    cur = ftp.pwd()
    try:
        ftp.cwd(path)
        return sorted(
            name.rstrip("/").split("/")[-1]
            for name in ftp.nlst()
            if name.rstrip("/").split("/")[-1] not in {".", ".."}
        )
    finally:
        ftp.cwd(cur)


def inspect_netcdf(path: Path) -> dict:
    from netCDF4 import Dataset

    with Dataset(path) as ds:
        dims = {name: len(dim) for name, dim in ds.dimensions.items()}
        variables = {}
        for name, var in ds.variables.items():
            variables[name] = {
                "dimensions": list(var.dimensions),
                "shape": list(var.shape),
                "dtype": str(var.dtype),
                "units": getattr(var, "units", None),
                "long_name": getattr(var, "long_name", None),
                "standard_name": getattr(var, "standard_name", None),
            }
        attrs = {name: str(ds.getncattr(name))[:500] for name in ds.ncattrs()}
    return {"dimensions": dims, "variables": variables, "global_attributes": attrs}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=DEFAULT_DATE)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    y, m, d = args.date.split("-")
    day_dir = f"{ROOT}/{y}/{m}/{d}"
    user = os.environ["GSMAP_FTP_USERNAME"]
    password = os.environ["GSMAP_FTP_PASSWORD"]

    report = {
        "schema_version": "1.0.0",
        "phase": "2L-GSMAP-V8-NETCDF-SINGLE-FILE-PROOF",
        "host": HOST,
        "day_directory": day_dir,
        "probe_date": args.date,
        "access_status_before_run": "ACCESS_RECOVERED_FULL_FILE_TRANSFER_CONFIRMED_V8_HISTORICAL_STRUCTURE_VERIFIED_CAUSE_UNKNOWN",
        "parallel_connections": 1,
        "broad_traversal_used": False,
        "raw_payload_persisted": False,
        "secret_value_recorded": False,
        "threshold_selected": False,
        "candidate_generated": False,
        "hard_negative_label": None,
        "source_fusion_used": False,
        "validation_data_used": False,
        "retrospective_2026_used": False,
        "prospective_holdout_used": False,
        "risk_score": None,
        "risk_engine_allowed": False,
    }

    try:
        with ftplib.FTP(timeout=60) as ftp:
            ftp.connect(HOST, 21)
            welcome = ftp.getwelcome() or ""
            ftp.login(user, password)
            names = list_names(ftp, day_dir)
            nc_names = [n for n in names if re.fullmatch(r"gsmap_mvk\.\d{8}\.\d{4}\.v8\.[^.]+\.[^.]+\.nc", n, re.I)]
            if not nc_names:
                nc_names = [n for n in names if n.lower().endswith(".nc")]
            if not nc_names:
                raise RuntimeError(f"no NetCDF files found under {day_dir}")

            # Deterministic and minimal: retrieve exactly one lexicographically first file.
            target = nc_names[0]
            remote = f"{day_dir}/{target}"
            report["server_welcome_prefix"] = welcome[:200]
            report["day_entry_count"] = len(names)
            report["netcdf_file_count"] = len(nc_names)
            report["selected_remote_path"] = remote

            with tempfile.TemporaryDirectory() as td:
                local = Path(td) / target
                with local.open("wb") as fh:
                    ftp.retrbinary(f"RETR {remote}", fh.write, blocksize=64 * 1024)
                size = local.stat().st_size
                if size < 1_000_000:
                    raise RuntimeError(f"unexpectedly small GSMaP NetCDF: {size} bytes")
                report["payload_filename"] = target
                report["payload_bytes"] = size
                report["payload_sha256"] = hashlib.sha256(local.read_bytes()).hexdigest()
                report["netcdf"] = inspect_netcdf(local)

        vars_ = report["netcdf"]["variables"]
        required = {"hourlyPrecipRate", "hourlyPrecipRateGC", "reliabilityFlag"}
        missing = sorted(required - set(vars_))
        if missing:
            raise RuntimeError(f"required GSMaP variables missing: {missing}")
        report["required_variables_verified"] = sorted(required)
        report["gate"] = "PASS_GSMAP_V8_NETCDF_SINGLE_FILE_FTP_PROOF"
        report["access_status_after_run"] = "AUTOMATED_SINGLE_FILE_TRANSFER_CONFIRMED_CAUSE_UNKNOWN"
    except Exception as exc:
        report["gate"] = "FAIL_GSMAP_V8_NETCDF_SINGLE_FILE_FTP_PROOF"
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)[:1500]
        report["access_status_after_run"] = "AUTOMATED_ACCESS_NOT_CONFIRMED_DO_NOT_SCALE"

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ["gate", "selected_remote_path", "payload_bytes", "access_status_after_run", "error_type", "error"]}, ensure_ascii=False, indent=2))
    return 0 if report["gate"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
