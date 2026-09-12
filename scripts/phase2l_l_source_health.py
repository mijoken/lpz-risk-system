#!/usr/bin/env python3
"""Phase 2L-L — Source Health & Operational Readiness.

Purpose
-------
Build one machine-readable operational health snapshot without opening the
deferred 2025 Primary environmental outcome.

The script:
- verifies the Phase 2L-K2 freeze and its SHA256 manifest,
- runs the existing acquisition_probe.py for configured live sources,
- applies explicit operational freshness thresholds,
- checks NASA Earthdata authentication and IMERG V07/V08 metadata availability,
- keeps Final V08 absence as EXPECTED_PENDING, not an operational failure,
- never retrieves 2025 ERA5,
- never computes an LPZ risk score.

Outputs are local operational artifacts under local_data/ by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

K2_FREEZE = (
    ROOT
    / "research"
    / "phase2"
    / "phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912.json"
)
K2_MD = (
    ROOT
    / "research"
    / "phase2"
    / "phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912.md"
)
K2_SHA = (
    ROOT
    / "research"
    / "phase2"
    / "phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912_sha256.json"
)
DATA_SOURCES = ROOT / "config" / "data_sources.json"
ACQUISITION_PROBE = ROOT / "scripts" / "acquisition_probe.py"

EXPECTED_K2_GATE = (
    "PASS_PHASE2L_K2_V07_BOUNDARY_AND_V08_DEFERRED_VALIDATION_FREEZE"
)
PASS_GATE = "PASS_PHASE2L_L_SOURCE_HEALTH_OPERATIONAL_READINESS"
REVIEW_GATE = "REVIEW_PHASE2L_L_SOURCE_HEALTH_OPERATIONAL_READINESS"

# These are operational staleness limits, not scientific thresholds.
# They only determine whether a live source is healthy enough to operate.
FRESHNESS_LIMIT_SECONDS = {
    "jma_nowc": 30 * 60,
    "jma_rasrf": 2 * 60 * 60,
    "jma_amedas": 30 * 60,
    "jma_himawari": 30 * 60,
    "noaa_gfs": 12 * 60 * 60,
}

# Acceptable evidence status by configured source.
# RASRF config explicitly declares a METADATA probe, so fresh META_PASS is valid.
ACCEPTABLE_STATUS = {
    "jma_nowc": {"PASS"},
    "jma_rasrf": {"PASS", "META_PASS"},
    "jma_amedas": {"PASS"},
    "jma_windas": {"PASS", "META_PASS", "PENDING"},
    "jma_himawari": {"PASS", "META_PASS"},
    "noaa_gfs": {"PASS"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    json.loads(text)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def atomic_write_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False)
    pd.read_csv(tmp)
    tmp.replace(path)


def verify_k2_freeze() -> dict[str, Any]:
    for p in (K2_FREEZE, K2_MD, K2_SHA):
        if not p.exists():
            raise FileNotFoundError(p)

    freeze = json.loads(K2_FREEZE.read_text(encoding="utf-8"))
    manifest = json.loads(K2_SHA.read_text(encoding="utf-8"))

    if freeze.get("gate") != EXPECTED_K2_GATE:
        raise RuntimeError(
            f"K2 gate mismatch: {freeze.get('gate')!r}"
        )

    state = freeze.get("validation_state", {})
    if state.get("status") != "DEFERRED_PENDING_IMERG_FINAL_V08":
        raise RuntimeError("K2 validation state is no longer deferred to Final V08")
    if bool(state.get("primary_confirmatory_test_run")):
        raise RuntimeError("K2 says the Primary confirmatory test has already run")
    if bool(state.get("primary_outcome_opened")):
        raise RuntimeError("K2 says the Primary outcome has been opened")
    if bool(state.get("2025_era5_environment_outcomes_may_be_opened_now")):
        raise RuntimeError("K2 unexpectedly allows opening 2025 ERA5 outcomes")
    if bool(state.get("risk_engine_allowed")):
        raise RuntimeError("K2 unexpectedly allows the risk engine")

    artifacts = manifest.get("artifacts", {})
    checks: list[dict[str, Any]] = []

    for path in (K2_FREEZE, K2_MD):
        rel = str(path.relative_to(ROOT))
        # Manifest may have Windows separators.
        key = rel if rel in artifacts else rel.replace("/", "\\")
        meta = artifacts.get(key)
        if not isinstance(meta, dict):
            raise RuntimeError(f"K2 SHA manifest missing artifact: {rel}")
        observed = sha256_file(path)
        expected = str(meta.get("sha256"))
        ok = observed == expected
        checks.append(
            {
                "path": rel,
                "expected_sha256": expected,
                "observed_sha256": observed,
                "ok": ok,
            }
        )
        if not ok:
            raise RuntimeError(f"K2 artifact SHA mismatch: {rel}")

    return {
        "status": "PASS",
        "gate": freeze.get("gate"),
        "validation_status": state.get("status"),
        "risk_engine_allowed": False,
        "artifact_hash_checks": checks,
    }


def run_acquisition_probe(output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(
        [
            sys.executable,
            str(ACQUISITION_PROBE),
            "--output",
            str(output),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if not output.exists():
        raise RuntimeError(
            "acquisition_probe.py did not produce its report. "
            f"exit={cp.returncode} stdout={cp.stdout!r} stderr={cp.stderr!r}"
        )
    report = json.loads(output.read_text(encoding="utf-8"))
    report["_process"] = {
        "exit_code": cp.returncode,
        "stdout": cp.stdout,
        "stderr": cp.stderr,
    }
    return report


def evaluate_live_sources(
    source_config: dict[str, Any],
    acquisition: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    cfg_by_id = {
        str(x["id"]): x
        for x in source_config.get("sources", [])
    }
    probe_by_id = {
        str(x["source_id"]): x
        for x in acquisition.get("results", [])
    }

    rows: list[dict[str, Any]] = []
    mandatory_ok = True

    for source_id, cfg in cfg_by_id.items():
        role = str(cfg.get("role", "UNKNOWN"))
        probe = probe_by_id.get(source_id)
        if probe is None:
            health = "FAIL" if role == "LIVE_MANDATORY" else "DEGRADED"
            reason = "NO_PROBE_RESULT"
            row = {
                "source_id": source_id,
                "source_name": cfg.get("name"),
                "role": role,
                "health": health,
                "probe_status": None,
                "data_time": None,
                "data_age_seconds": None,
                "freshness_limit_seconds": FRESHNESS_LIMIT_SECONDS.get(source_id),
                "reason": reason,
            }
            rows.append(row)
            if role == "LIVE_MANDATORY":
                mandatory_ok = False
            continue

        status = str(probe.get("status"))
        acceptable = status in ACCEPTABLE_STATUS.get(source_id, {"PASS"})
        age = probe.get("data_age_seconds")
        limit = FRESHNESS_LIMIT_SECONDS.get(source_id)

        fresh = True
        if limit is not None:
            if age is None:
                fresh = False
            else:
                fresh = int(age) <= int(limit)

        if status == "PENDING" and role != "LIVE_MANDATORY":
            health = "PENDING"
            reason = "SUPPLEMENTARY_DISCOVERY_PENDING"
        elif acceptable and fresh:
            health = "PASS"
            reason = "STATUS_AND_FRESHNESS_OK"
        elif acceptable and not fresh:
            health = "STALE"
            reason = "DATA_TOO_OLD"
        else:
            health = "FAIL" if role == "LIVE_MANDATORY" else "DEGRADED"
            reason = "PROBE_STATUS_NOT_ACCEPTABLE"

        if role == "LIVE_MANDATORY" and health != "PASS":
            mandatory_ok = False

        rows.append(
            {
                "source_id": source_id,
                "source_name": cfg.get("name"),
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

    return rows, mandatory_ok


def probe_earthdata_imerg() -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_id": "nasa_earthdata_imerg",
        "authentication": "UNKNOWN",
        "imerg_final_v07_metadata": "UNKNOWN",
        "imerg_final_v08_metadata": "UNKNOWN",
        "v8_available": False,
        "operational_requirement": "RESEARCH_DEFERRED_NOT_LIVE_MANDATORY",
    }
    try:
        import earthaccess
    except Exception as exc:
        result.update(
            {
                "authentication": "FAIL",
                "health": "DEGRADED",
                "error": f"earthaccess import failed: {type(exc).__name__}: {exc}",
            }
        )
        return result

    try:
        auth = earthaccess.login()
        authenticated = bool(getattr(auth, "authenticated", False))
        result["authentication"] = "PASS" if authenticated else "FAIL"
        if not authenticated:
            result["health"] = "DEGRADED"
            result["error"] = "earthaccess session is not authenticated"
            return result
    except Exception as exc:
        result.update(
            {
                "authentication": "FAIL",
                "health": "DEGRADED",
                "error": f"Earthdata login failed: {type(exc).__name__}: {exc}",
            }
        )
        return result

    try:
        v07 = earthaccess.search_data(
            short_name="GPM_3IMERGHH",
            version="07",
            temporal=("2025-09-30T22:00:00Z", "2025-09-30T23:00:00Z"),
            count=1,
        )
        result["imerg_final_v07_metadata"] = "PASS" if len(v07) >= 1 else "NOT_FOUND"
        result["v07_result_count"] = int(len(v07))
    except Exception as exc:
        result["imerg_final_v07_metadata"] = "ERROR"
        result["v07_error"] = f"{type(exc).__name__}: {exc}"

    # Metadata-only detection. It does not download rainfall payloads and does
    # not open any 2025 environmental outcome.
    try:
        v08 = earthaccess.search_data(
            short_name="GPM_3IMERGHH",
            version="08",
            temporal=("2025-10-01T00:00:00Z", "2025-10-01T01:00:00Z"),
            count=1,
        )
        available = len(v08) >= 1
        result["v8_available"] = bool(available)
        result["v08_result_count"] = int(len(v08))
        result["imerg_final_v08_metadata"] = (
            "AVAILABLE_ACTION_REQUIRED" if available else "EXPECTED_PENDING"
        )
    except Exception as exc:
        result["imerg_final_v08_metadata"] = "CHECK_ERROR"
        result["v08_error"] = f"{type(exc).__name__}: {exc}"

    # V8 absence is expected and must not degrade live operational readiness.
    result["health"] = (
        "ACTION_REQUIRED_V8_AVAILABLE"
        if result["v8_available"]
        else "PASS_WITH_V8_PENDING"
    )
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "local_data" / "phase2l_l_source_health",
    )
    args = p.parse_args()
    outdir = args.output_dir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    k2 = verify_k2_freeze()

    source_config = json.loads(DATA_SOURCES.read_text(encoding="utf-8"))
    acquisition_path = outdir / "phase2l_l_acquisition_probe.json"
    acquisition = run_acquisition_probe(acquisition_path)
    live_rows, mandatory_ok = evaluate_live_sources(source_config, acquisition)

    earthdata = probe_earthdata_imerg()

    mandatory_rows = [r for r in live_rows if r["role"] == "LIVE_MANDATORY"]
    supplementary_rows = [r for r in live_rows if r["role"] != "LIVE_MANDATORY"]

    # Overall V1 operational readiness here means source/acquisition readiness
    # only. It does NOT mean the scientific risk engine is validated or enabled.
    operational_source_ready = bool(mandatory_ok)
    gate = PASS_GATE if operational_source_ready else REVIEW_GATE

    report = {
        "schema_version": "1.0.0",
        "phase": "2L-L-source-health-and-operational-readiness",
        "generated_at_utc": utc_now(),
        "gate": gate,
        "purpose": (
            "Verify live source health and operational acquisition readiness "
            "while preserving the Phase 2L-K2 deferred-validation seal."
        ),
        "k2_freeze_integrity": k2,
        "live_source_health": live_rows,
        "earthdata_imerg_research_source": earthdata,
        "summary": {
            "configured_live_mandatory_count": len(mandatory_rows),
            "live_mandatory_pass_count": sum(
                r["health"] == "PASS" for r in mandatory_rows
            ),
            "configured_supplementary_count": len(supplementary_rows),
            "operational_source_ready": operational_source_ready,
            "research_validation_status": "DEFERRED_PENDING_IMERG_FINAL_V08",
            "imerg_final_v08_available_by_metadata_probe": bool(
                earthdata.get("v8_available")
            ),
            "2025_era5_environment_opened": False,
            "primary_confirmatory_test_run": False,
            "risk_engine_allowed": False,
        },
        "policy": {
            "freshness_thresholds_are_operational_not_scientific": True,
            "mandatory_stale_or_failed_source_suspends_future_risk_output": True,
            "v8_absence_is_expected_and_does_not_fail_live_source_readiness": True,
            "v8_detection_does_not_auto_resume_validation": True,
        },
        "next_phase_if_pass": {
            "phase": "2L-M",
            "name": "PROSPECTIVE_COLLECTOR_OPERATIONALIZATION",
        },
    }

    report_path = outdir / "phase2l_l_source_health_report.json"
    csv_path = outdir / "phase2l_l_source_health_summary.csv"
    atomic_write_json(report_path, report)
    atomic_write_csv(csv_path, pd.DataFrame(live_rows))

    print("=" * 104)
    print("LPZ PHASE 2L-L — SOURCE HEALTH & OPERATIONAL READINESS")
    print("=" * 104)
    for row in live_rows:
        age = row.get("data_age_seconds")
        age_text = "n/a" if age is None else f"{int(age)}s"
        print(
            f"{row['source_id']:<16} "
            f"{row['role']:<18} "
            f"{row['health']:<10} "
            f"probe={str(row.get('probe_status')):<12} age={age_text}"
        )
    print("-" * 104)
    print(
        f"Mandatory live sources             : "
        f"{sum(r['health']=='PASS' for r in mandatory_rows)} / {len(mandatory_rows)} PASS"
    )
    print(f"NASA Earthdata authentication      : {earthdata.get('authentication')}")
    print(f"IMERG Final V07 metadata           : {earthdata.get('imerg_final_v07_metadata')}")
    print(f"IMERG Final V08 metadata           : {earthdata.get('imerg_final_v08_metadata')}")
    print("K2 freeze integrity                : PASS")
    print("2025 ERA5 environment opened       : NO")
    print("Primary confirmatory test run      : NO")
    print("Risk engine                        : NOT ALLOWED")
    print(f"Operational source readiness       : {'PASS' if operational_source_ready else 'REVIEW'}")
    print("")
    print(f"Gate                               : {gate}")
    print(f"Report                             : {report_path}")
    print(f"Summary CSV                        : {csv_path}")
    print("=" * 104)

    return 0 if operational_source_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
