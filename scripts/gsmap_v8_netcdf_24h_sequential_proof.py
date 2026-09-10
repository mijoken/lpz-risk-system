#!/usr/bin/env python3
"""Phase 2L: conservative 24-hour sequential GSMaP v8 NetCDF FTP proof.

One FTP control session, one transfer at a time, fixed pause between files, no broad
traversal, no parallelism, no automatic reconnect storm. Raw files remain ephemeral.
The proof records per-file integrity/variable metadata and fails closed on the first
transfer/decode error while still writing a diagnostic report.
"""
from __future__ import annotations

import argparse
import ftplib
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

HOST = "hokusai.eorc.jaxa.jp"
ROOT = "/standard/v8/netcdf"
REQUIRED = {"hourlyPrecipRate", "hourlyPrecipRateGC", "reliabilityFlag"}


def list_names(ftp: ftplib.FTP, path: str) -> list[str]:
    cur = ftp.pwd()
    try:
        ftp.cwd(path)
        return sorted(
            x.rstrip("/").split("/")[-1]
            for x in ftp.nlst()
            if x.rstrip("/").split("/")[-1] not in {".", ".."}
        )
    finally:
        ftp.cwd(cur)


def inspect_minimal(path: Path) -> dict:
    from netCDF4 import Dataset

    with Dataset(path) as ds:
        missing = sorted(REQUIRED - set(ds.variables))
        if missing:
            raise RuntimeError(f"required variables missing: {missing}")
        dims = {k: len(v) for k, v in ds.dimensions.items()}
        vars_ = {}
        for name in sorted(REQUIRED | {"Time", "Latitude", "Longitude"}):
            if name not in ds.variables:
                continue
            v = ds.variables[name]
            vars_[name] = {
                "shape": list(v.shape),
                "dtype": str(v.dtype),
                "units": getattr(v, "units", None),
                "long_name": getattr(v, "long_name", None),
            }
    return {"dimensions": dims, "variables": vars_}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2023-07-10")
    ap.add_argument("--pause-seconds", type=float, default=1.0)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    y, m, d = args.date.split("-")
    ymd = y + m + d
    day_dir = f"{ROOT}/{y}/{m}/{d}"
    report = {
        "schema_version": "1.0.0",
        "phase": "2L-GSMAP-V8-NETCDF-24H-SEQUENTIAL-PROOF",
        "host": HOST,
        "day_directory": day_dir,
        "probe_date": args.date,
        "single_control_session": True,
        "parallel_connections": 1,
        "pause_seconds_between_transfers": args.pause_seconds,
        "automatic_reconnect": False,
        "retry_count_per_file": 0,
        "broad_traversal_used": False,
        "raw_payload_persisted": False,
        "threshold_selected": False,
        "candidate_generated": False,
        "hard_negative_label": None,
        "source_fusion_used": False,
        "validation_data_used": False,
        "retrospective_2026_used": False,
        "prospective_holdout_used": False,
        "risk_engine_allowed": False,
        "files": [],
    }

    user = os.environ["GSMAP_FTP_USERNAME"]
    password = os.environ["GSMAP_FTP_PASSWORD"]
    failure = None
    started = time.monotonic()

    try:
        with ftplib.FTP(timeout=90) as ftp:
            ftp.connect(HOST, 21)
            ftp.login(user, password)
            names = list_names(ftp, day_dir)
            nc = [n for n in names if n.lower().endswith(".nc") and ymd in n]
            by_hour = {}
            for n in nc:
                mt = re.search(rf"gsmap_mvk\.{ymd}\.(\d{{2}})00\.v8\.[^.]+\.[^.]+\.nc$", n, re.I)
                if mt:
                    hour = int(mt.group(1))
                    by_hour.setdefault(hour, []).append(n)
            duplicates = {h: v for h, v in by_hour.items() if len(v) != 1}
            missing_hours = [h for h in range(24) if h not in by_hour]
            if duplicates or missing_hours:
                raise RuntimeError(f"24h file-set invalid; missing={missing_hours}, duplicates={duplicates}")

            report["day_entry_count"] = len(names)
            report["resolved_hour_count"] = len(by_hour)
            with tempfile.TemporaryDirectory() as td:
                temp = Path(td)
                for hour in range(24):
                    name = by_hour[hour][0]
                    remote = f"{day_dir}/{name}"
                    local = temp / name
                    row = {"hour_utc": hour, "remote_path": remote}
                    try:
                        t0 = time.monotonic()
                        with local.open("wb") as fh:
                            ftp.retrbinary(f"RETR {remote}", fh.write, blocksize=64 * 1024)
                        size = local.stat().st_size
                        if size < 1_000_000:
                            raise RuntimeError(f"unexpectedly small payload: {size}")
                        row["bytes"] = size
                        row["sha256"] = hashlib.sha256(local.read_bytes()).hexdigest()
                        row["netcdf"] = inspect_minimal(local)
                        row["transfer_elapsed_seconds"] = round(time.monotonic() - t0, 3)
                        row["status"] = "PASS"
                    except Exception as exc:
                        row["status"] = "FAIL"
                        row["error_type"] = type(exc).__name__
                        row["error"] = str(exc)[:1000]
                        report["files"].append(row)
                        failure = row
                        break
                    finally:
                        try:
                            local.unlink(missing_ok=True)
                        except Exception:
                            pass
                    report["files"].append(row)
                    if hour != 23:
                        time.sleep(max(0.0, args.pause_seconds))
    except Exception as exc:
        if failure is None:
            failure = {"error_type": type(exc).__name__, "error": str(exc)[:1500]}

    report["completed_file_count"] = sum(r.get("status") == "PASS" for r in report["files"])
    report["total_payload_bytes"] = sum(int(r.get("bytes", 0)) for r in report["files"])
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    if failure is None and report["completed_file_count"] == 24:
        report["gate"] = "PASS_GSMAP_V8_NETCDF_24H_SEQUENTIAL_FTP_PROOF"
        report["access_status_after_run"] = "AUTOMATED_24H_SEQUENTIAL_TRANSFER_CONFIRMED_CAUSE_UNKNOWN"
    else:
        report["gate"] = "FAIL_GSMAP_V8_NETCDF_24H_SEQUENTIAL_FTP_PROOF"
        report["failure"] = failure
        report["access_status_after_run"] = "DO_NOT_SCALE_24H_SEQUENCE_NOT_CONFIRMED"

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ["gate", "completed_file_count", "total_payload_bytes", "elapsed_seconds", "access_status_after_run", "failure"]}, ensure_ascii=False, indent=2))
    return 0 if report["gate"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
