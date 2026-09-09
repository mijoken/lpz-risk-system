#!/usr/bin/env python3
"""Focused real-payload proof for JAXA GSMaP Gauge Standard v8.

Uses MLSD when available so directory/file type metadata are discovered in one FTP
operation per level. It retrieves public documentation and downloads exactly one
2023-era hourly_G payload. Raw data are ephemeral; only descriptors are written.
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
YEAR = "2023"


def _basename(x: str) -> str:
    return x.rstrip("/").split("/")[-1]


def _join(parent: str, name: str) -> str:
    return parent.rstrip("/") + "/" + _basename(name)


def _mlsd(ftp: ftplib.FTP, path: str) -> list[dict]:
    """Return name/type rows with a conservative NLST fallback."""
    cur = ftp.pwd()
    try:
        ftp.cwd(path)
        try:
            rows = []
            for name, facts in ftp.mlsd(facts=["type", "size", "modify"]):
                if name in {".", ".."}:
                    continue
                rows.append({
                    "name": name,
                    "type": str(facts.get("type", "unknown")),
                    "size": facts.get("size"),
                    "modify": facts.get("modify"),
                })
            return sorted(rows, key=lambda r: r["name"])
        except Exception:
            # Fallback only for servers/paths where MLSD is unavailable. Avoid cwd
            # probing every entry: mark type unknown and let path naming guide BFS.
            return [
                {"name": _basename(x), "type": "unknown", "size": None, "modify": None}
                for x in sorted(ftp.nlst())
                if _basename(x) not in {".", ".."}
            ]
    finally:
        ftp.cwd(cur)


def _retrieve_bytes(ftp: ftplib.FTP, path: str) -> bytes:
    buf = bytearray()
    ftp.retrbinary(f"RETR {path}", buf.extend)
    return bytes(buf)


def _file_like(name: str, typ: str) -> bool:
    if typ == "file":
        return True
    return bool(re.search(r"\.(gz|bin|dat|txt|nc|h5|hdf5)$", name, re.I))


def _dir_like(name: str, typ: str) -> bool:
    if typ == "dir":
        return True
    if typ == "file":
        return False
    # Unknown fallback: GSMaP hierarchy is dominated by YYYY/MM/DD-style dirs.
    return bool(re.fullmatch(r"(?:19|20)\d{2}|\d{1,3}|\d{2}", name))


def _find_2023_payload(ftp: ftplib.FTP) -> tuple[str | None, list[dict]]:
    """Search only the 2023 branch where possible; never enumerate all years deeply."""
    audit: list[dict] = []
    queue = deque([(TARGET_ROOT, 0)])
    seen: set[str] = set()
    fallback: str | None = None

    while queue:
        path, depth = queue.popleft()
        if path in seen or depth > 6:
            continue
        seen.add(path)
        try:
            rows = _mlsd(ftp, path)
        except Exception as exc:
            audit.append({"path": path, "depth": depth, "error_type": type(exc).__name__})
            continue

        audit.append({
            "path": path,
            "depth": depth,
            "entry_count": len(rows),
            "entries_sample": rows[:25],
        })

        files = []
        dirs = []
        for row in rows:
            name = row["name"]
            typ = row.get("type", "unknown")
            full = _join(path, name)
            if _file_like(name, typ):
                files.append(full)
            elif _dir_like(name, typ):
                dirs.append(full)

        # GSMaP hourly files are compressed/binary; choose a 2023 path first.
        candidates = [
            f for f in files
            if re.search(r"(gsmap|gauge|precip|hour|v8).*(\.gz|\.bin|\.dat|\.txt|\.nc)$", _basename(f), re.I)
            or re.search(r"\.(gz|bin|dat|nc)$", _basename(f), re.I)
        ]
        preferred = [f for f in candidates if YEAR in f]
        if preferred:
            return sorted(preferred)[0], audit
        if candidates and fallback is None:
            fallback = sorted(candidates)[0]

        # At first level, keep only a visible 2023 directory if present.
        year_dirs = [d for d in dirs if re.search(r"/(?:19|20)\d{2}$", d)]
        if year_dirs:
            exact = [d for d in year_dirs if d.endswith("/" + YEAR)]
            dirs = exact
        elif YEAR not in path and depth > 0:
            # If no explicit year branch exists, continue only a few likely numeric dirs.
            dirs = [d for d in dirs if re.search(r"/2023(?:/|$)", d) or re.search(r"/\d{1,3}$", d)]

        # Stable order; cap breadth aggressively.
        dirs.sort(key=lambda d: (0 if YEAR in d else 1, d))
        for d in dirs[:40]:
            queue.append((d, depth + 1))

    return fallback, audit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="reports/historical/gsmap_standard_v8_payload_probe.json")
    args = ap.parse_args()

    user = os.environ["GSMAP_FTP_USERNAME"]
    password = os.environ["GSMAP_FTP_PASSWORD"]
    report = {
        "schema_version": "0.2.0",
        "phase": "2F-gsmap-standard-v8-real-payload-proof",
        "source_id": "GSMAP_GAUGE_STANDARD_V8",
        "host": HOST,
        "target_root": TARGET_ROOT,
        "target_year": YEAR,
        "discovery_method": "MLSD_WITH_CONSERVATIVE_NLST_FALLBACK",
        "zero_cost_required": True,
        "secret_value_recorded": False,
        "raw_payload_persisted": False,
        "lpz_classification": None,
        "risk_score": None,
        "risk_engine_allowed": False,
    }

    try:
        with ftplib.FTP(timeout=45) as ftp:
            ftp.connect(HOST, 21)
            ftp.login(user, password)
            report["root_entries"] = _mlsd(ftp, ROOT)[:100]
            report["hourly_g_entries"] = _mlsd(ftp, TARGET_ROOT)[:100]

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
            report["traversal_audit"] = traversal[:100]
            report["payload_path"] = payload_path
            if payload_path is None:
                report["payload_gate"] = "BLOCKED_PAYLOAD_PATH_NOT_DISCOVERED"
            else:
                with tempfile.TemporaryDirectory() as td:
                    p = Path(td) / _basename(payload_path)
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
    return 0 if report.get("payload_gate") == "PASS_REAL_GSMAP_FILE_ACQUIRED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
