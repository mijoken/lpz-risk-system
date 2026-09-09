#!/usr/bin/env python3
"""Focused real-payload proof for JAXA GSMaP Gauge Standard v8.

The script authenticates with repository secrets, walks the official FTP hierarchy,
retrieves public format documentation, and downloads exactly one 2023-era hourly_G
payload when discoverable. Raw data are ephemeral; only metadata are written.
"""
from __future__ import annotations

import argparse
import ftplib
import hashlib
import json
import os
import re
import tempfile
from collections import deque
from pathlib import Path

HOST = "hokusai.eorc.jaxa.jp"
ROOT = "/standard/v8"
TARGET_ROOT = "/standard/v8/hourly_G"


def _list(ftp: ftplib.FTP, path: str) -> list[str]:
    cur = ftp.pwd()
    try:
        ftp.cwd(path)
        return sorted(str(x) for x in ftp.nlst())
    finally:
        ftp.cwd(cur)


def _is_dir(ftp: ftplib.FTP, path: str) -> bool:
    cur = ftp.pwd()
    try:
        ftp.cwd(path)
        return True
    except Exception:
        return False
    finally:
        try:
            ftp.cwd(cur)
        except Exception:
            pass


def _join(parent: str, entry: str) -> str:
    if entry.startswith("/"):
        return entry.rstrip("/")
    return parent.rstrip("/") + "/" + entry.rstrip("/").split("/")[-1]


def _retrieve_bytes(ftp: ftplib.FTP, path: str) -> bytes:
    buf = bytearray()
    ftp.retrbinary(f"RETR {path}", buf.extend)
    return bytes(buf)


def _find_2023_payload(ftp: ftplib.FTP) -> tuple[str | None, list[dict]]:
    audit = []
    queue = deque([(TARGET_ROOT, 0)])
    seen = set()
    fallback_file = None
    while queue:
        path, depth = queue.popleft()
        if path in seen or depth > 5:
            continue
        seen.add(path)
        try:
            entries = _list(ftp, path)
        except Exception as exc:
            audit.append({"path": path, "depth": depth, "error_type": type(exc).__name__})
            continue
        audit.append({"path": path, "depth": depth, "entry_count": len(entries), "entries_sample": entries[:20]})
        child_dirs = []
        files = []
        for e in entries[:500]:
            child = _join(path, e)
            if _is_dir(ftp, child):
                child_dirs.append(child)
            else:
                files.append(child)
        data_files = [f for f in files if re.search(r"(gsmap|gauge|precip|hour).*(\.gz|\.bin|\.dat|\.txt)$", f, re.I)]
        if data_files:
            preferred = [f for f in data_files if "2023" in f]
            if preferred:
                return preferred[0], audit
            if fallback_file is None:
                fallback_file = data_files[0]
        # Prefer branches that visibly contain 2023, then numeric/year-like dirs, then others.
        child_dirs.sort(key=lambda p: (0 if "2023" in p else 1, 0 if re.search(r"/20\d{2}(/|$)", p) else 1, p))
        for child in child_dirs[:80]:
            # Once a year-level set is visible, do not traverse every other year before 2023.
            if re.search(r"/20\d{2}(/|$)", child) and "2023" not in child:
                continue
            queue.append((child, depth + 1))
    return fallback_file, audit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="reports/historical/gsmap_standard_v8_payload_probe.json")
    args = ap.parse_args()

    user = os.environ["GSMAP_FTP_USERNAME"]
    password = os.environ["GSMAP_FTP_PASSWORD"]
    report = {
        "schema_version": "0.1.0",
        "phase": "2F-gsmap-standard-v8-real-payload-proof",
        "source_id": "GSMAP_GAUGE_STANDARD_V8",
        "host": HOST,
        "zero_cost_required": True,
        "secret_value_recorded": False,
        "raw_payload_persisted": False,
        "lpz_classification": None,
        "risk_score": None,
        "risk_engine_allowed": False,
    }

    try:
        with ftplib.FTP(timeout=60) as ftp:
            ftp.connect(HOST, 21)
            ftp.login(user, password)
            report["root_entries"] = _list(ftp, ROOT)
            report["hourly_g_entries"] = _list(ftp, TARGET_ROOT)[:100]

            docs = []
            for p in [f"{ROOT}/README.first.txt", f"{ROOT}/GSMaP_MVK_RNL_HISTORY.txt"]:
                try:
                    raw = _retrieve_bytes(ftp, p)
                    text = raw.decode("utf-8", errors="replace")
                    docs.append({
                        "path": p,
                        "bytes": len(raw),
                        "sha256_prefix": hashlib.sha256(raw).hexdigest()[:16],
                        "text_excerpt": text[:5000],
                    })
                except Exception as exc:
                    docs.append({"path": p, "error_type": type(exc).__name__})
            report["documentation"] = docs

            payload_path, traversal = _find_2023_payload(ftp)
            report["traversal_audit"] = traversal[:80]
            report["payload_path"] = payload_path
            if payload_path is None:
                report["payload_gate"] = "BLOCKED_PAYLOAD_PATH_NOT_DISCOVERED"
            else:
                with tempfile.TemporaryDirectory() as td:
                    p = Path(td) / Path(payload_path).name
                    with p.open("wb") as f:
                        ftp.retrbinary(f"RETR {payload_path}", f.write)
                    report["payload_filename"] = p.name
                    report["payload_bytes"] = p.stat().st_size
                    report["payload_sha256_prefix"] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
                    report["payload_gate"] = "PASS_REAL_GSMAP_FILE_ACQUIRED"
    except Exception as exc:
        report["payload_gate"] = "FAIL"
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)[:1000]

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if str(report.get("payload_gate", "")).startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
