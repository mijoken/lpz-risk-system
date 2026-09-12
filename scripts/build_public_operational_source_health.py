#!/usr/bin/env python3
"""Build a Phase-2L-L-compatible operational source-health report for Pages.

This is the GitHub production-cycle adapter. It runs the existing acquisition
probe, applies the same operational freshness policy used by Phase 2L-L, and
performs an unauthenticated NASA CMR metadata check for IMERG Final V08.

It never opens 2025 ERA5, never runs the frozen Primary confirmatory test, and
never enables the LPZ risk engine.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA_SOURCES = ROOT / "config" / "data_sources.json"
ACQUISITION_PROBE = ROOT / "scripts" / "acquisition_probe.py"
EXPECTED_VALIDATION = "DEFERRED_PENDING_IMERG_FINAL_V08"

FRESHNESS_LIMIT_SECONDS = {
    "jma_nowc": 30 * 60,
    "jma_rasrf": 2 * 60 * 60,
    "jma_amedas": 30 * 60,
    "jma_himawari": 30 * 60,
    "noaa_gfs": 12 * 60 * 60,
}

ACCEPTABLE_STATUS = {
    "jma_nowc": {"PASS"},
    "jma_rasrf": {"PASS", "META_PASS"},
    "jma_amedas": {"PASS"},
    "jma_windas": {"PASS", "META_PASS", "PENDING"},
    "jma_himawari": {"PASS", "META_PASS"},
    # Production availability accepts the validated service fallback as
    # DEGRADED evidence rather than silently calling it a full PASS.
    "noaa_gfs": {"PASS", "SERVICE_PASS"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    json.loads(text)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def run_acquisition_probe(path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(
        [sys.executable, str(ACQUISITION_PROBE), "--output", str(path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if not path.exists():
        raise RuntimeError(
            "acquisition probe did not create a report: "
            f"exit={cp.returncode} stdout={cp.stdout!r} stderr={cp.stderr!r}"
        )
    report = json.loads(path.read_text(encoding="utf-8"))
    report["_process"] = {
        "exit_code": cp.returncode,
        "stdout": cp.stdout,
        "stderr": cp.stderr,
    }
    return report


def evaluate_sources(config: dict[str, Any], acquisition: dict[str, Any]) -> list[dict[str, Any]]:
    probe_by_id = {
        str(row.get("source_id")): row
        for row in acquisition.get("results", [])
        if isinstance(row, dict)
    }
    output: list[dict[str, Any]] = []

    for cfg in config.get("sources", []):
        source_id = str(cfg["id"])
        role = str(cfg.get("role", "LIVE_SUPPLEMENTARY"))
        probe = probe_by_id.get(source_id)
        limit = FRESHNESS_LIMIT_SECONDS.get(source_id)

        if probe is None:
            output.append(
                {
                    "source_id": source_id,
                    "source_name": cfg.get("name"),
                    "role": role,
                    "health": "FAIL" if role == "LIVE_MANDATORY" else "DEGRADED",
                    "probe_status": None,
                    "data_time": None,
                    "data_age_seconds": None,
                    "freshness_limit_seconds": limit,
                    "reason": "NO_PROBE_RESULT",
                    "error": None,
                }
            )
            continue

        status = str(probe.get("status") or "UNKNOWN")
        age = probe.get("data_age_seconds")
        acceptable = status in ACCEPTABLE_STATUS.get(source_id, {"PASS"})
        fresh = True
        if limit is not None:
            fresh = age is not None and int(age) <= limit

        if status == "PENDING" and role != "LIVE_MANDATORY":
            health = "PENDING"
            reason = "SUPPLEMENTARY_DISCOVERY_PENDING"
        elif source_id == "noaa_gfs" and status == "SERVICE_PASS":
            health = "DEGRADED"
            reason = "SERVICE_AVAILABLE_SAMPLE_PAYLOAD_NOT_CONFIRMED"
        elif acceptable and fresh:
            health = "PASS"
            reason = "STATUS_AND_FRESHNESS_OK"
        elif acceptable and not fresh:
            health = "STALE"
            reason = "DATA_TOO_OLD"
        else:
            health = "FAIL" if role == "LIVE_MANDATORY" else "DEGRADED"
            reason = "PROBE_STATUS_NOT_ACCEPTABLE"

        output.append(
            {
                "source_id": source_id,
                "source_name": probe.get("source_name") or cfg.get("name"),
                "role": role,
                "health": health,
                "probe_status": status,
                "probe_type": probe.get("probe_type"),
                "data_time": probe.get("data_time"),
                "data_age_seconds": age,
                "freshness_limit_seconds": limit,
                "http_status": probe.get("http_status"),
                "latency_ms": probe.get("latency_ms"),
                "parse_status": probe.get("parse_status"),
                "reason": reason,
                "error": probe.get("error"),
            }
        )
    return output


def cmr_count(version: str) -> int:
    params = urlencode(
        {
            "short_name": "GPM_3IMERGHH",
            "version": version,
            "temporal": "2025-10-01T00:00:00Z,2025-10-01T01:00:00Z",
            "page_size": "1",
        }
    )
    url = f"https://cmr.earthdata.nasa.gov/search/granules.json?{params}"
    req = Request(
        url,
        headers={
            "User-Agent": "lpz-risk-system/0.1.0 (+https://github.com/mijoken/lpz-risk-system)",
            "Accept": "application/json",
        },
    )
    with urlopen(req, timeout=25) as response:
        body = json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))
    return int(len(body.get("feed", {}).get("entry", [])))


def probe_imerg_cmr() -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_id": "nasa_earthdata_imerg",
        "authentication": "NOT_REQUIRED_CMR_METADATA",
        "imerg_final_v07_metadata": "UNKNOWN",
        "imerg_final_v08_metadata": "UNKNOWN",
        "v8_available": False,
        "operational_requirement": "RESEARCH_DEFERRED_NOT_LIVE_MANDATORY",
    }
    try:
        v07 = cmr_count("07")
        result["v07_result_count"] = v07
        result["imerg_final_v07_metadata"] = "PASS" if v07 else "NOT_FOUND"
    except Exception as exc:
        result["imerg_final_v07_metadata"] = "CHECK_ERROR"
        result["v07_error"] = f"{type(exc).__name__}: {exc}"

    try:
        v08 = cmr_count("08")
        available = v08 > 0
        result["v08_result_count"] = v08
        result["v8_available"] = available
        result["imerg_final_v08_metadata"] = (
            "AVAILABLE_ACTION_REQUIRED" if available else "EXPECTED_PENDING"
        )
    except Exception as exc:
        result["imerg_final_v08_metadata"] = "CHECK_ERROR"
        result["v08_error"] = f"{type(exc).__name__}: {exc}"

    result["health"] = (
        "ACTION_REQUIRED_V8_AVAILABLE"
        if result["v8_available"]
        else "PASS_WITH_V8_PENDING"
        if result["imerg_final_v08_metadata"] == "EXPECTED_PENDING"
        else "DEGRADED"
    )
    return result


def build_report(acquisition: dict[str, Any], live_rows: list[dict[str, Any]]) -> dict[str, Any]:
    earthdata = probe_imerg_cmr()
    mandatory = [row for row in live_rows if row["role"] == "LIVE_MANDATORY"]
    mandatory_pass = sum(row["health"] == "PASS" for row in mandatory)
    mandatory_healthy = bool(mandatory) and mandatory_pass == len(mandatory)

    return {
        "schema_version": "1.0.0",
        "phase": "2L-O6-github-production-source-health",
        "generated_at_utc": utc_now(),
        "gate": (
            "PASS_PHASE2L_O6_GITHUB_PRODUCTION_SOURCE_HEALTH"
            if mandatory_healthy
            else "DEGRADED_PHASE2L_O6_GITHUB_PRODUCTION_SOURCE_HEALTH"
        ),
        "purpose": (
            "Build public operational source health on GitHub while preserving "
            "the frozen K2 scientific release boundary."
        ),
        "live_source_health": live_rows,
        "earthdata_imerg_research_source": earthdata,
        "summary": {
            "configured_live_mandatory_count": len(mandatory),
            "live_mandatory_pass_count": mandatory_pass,
            "operational_source_ready": mandatory_healthy,
            "research_validation_status": EXPECTED_VALIDATION,
            "imerg_final_v08_available_by_metadata_probe": bool(earthdata.get("v8_available")),
            "2025_era5_environment_opened": False,
            "primary_confirmatory_test_run": False,
            "risk_engine_allowed": False,
            "acquisition_probe_exit_code": acquisition.get("_process", {}).get("exit_code"),
        },
        "policy": {
            "freshness_thresholds_are_operational_not_scientific": True,
            "public_source_health_may_degrade_without_changing_scientific_lock": True,
            "cmr_probe_is_metadata_only": True,
            "2025_era5_environment_opened": False,
            "risk_engine_allowed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "public" / "o6_source_health.json",
    )
    parser.add_argument(
        "--acquisition-output",
        type=Path,
        default=ROOT / "reports" / "public" / "o6_acquisition_probe.json",
    )
    args = parser.parse_args()

    config = json.loads(DATA_SOURCES.read_text(encoding="utf-8"))
    acquisition = run_acquisition_probe(args.acquisition_output.resolve())
    rows = evaluate_sources(config, acquisition)
    report = build_report(acquisition, rows)
    atomic_json(args.output.resolve(), report)

    print("=" * 96)
    print("LPZ O6 — GITHUB PRODUCTION SOURCE HEALTH")
    print("=" * 96)
    for row in rows:
        print(
            f"{row['source_id']:<16} {row['role']:<18} "
            f"{row['health']:<10} probe={str(row.get('probe_status'))}"
        )
    print("-" * 96)
    print(f"Mandatory PASS : {report['summary']['live_mandatory_pass_count']} / {report['summary']['configured_live_mandatory_count']}")
    print(f"IMERG Final V08: {report['earthdata_imerg_research_source']['imerg_final_v08_metadata']}")
    print("2025 ERA5      : SEALED")
    print("Risk engine     : LOCKED")
    print(f"Report          : {args.output.resolve()}")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
