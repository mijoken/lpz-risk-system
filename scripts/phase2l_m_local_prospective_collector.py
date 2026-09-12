#!/usr/bin/env python3
"""Phase 2L-M — local prospective collector operationalization.

This is the local-PC equivalent of the frozen GitHub prospective feature
collector. It deliberately reuses the existing scientific scripts rather than
creating new predictors.

One invocation:
1. verifies a recent PASS Phase 2L-L source-health report,
2. runs the existing 9-component prospective scientific pipeline,
3. builds one derived-feature bundle,
4. asserts that classification/risk output remains locked,
5. updates a local immutable-style daily gzip JSONL archive,
6. writes an auditable run manifest.

It never reads 2025 ERA5 validation outcomes and never produces an LPZ risk
score or classification.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_L_GATE = "PASS_PHASE2L_L_SOURCE_HEALTH_OPERATIONAL_READINESS"
PASS_GATE = "PASS_PHASE2L_M_LOCAL_PROSPECTIVE_COLLECTOR_CYCLE"
FAIL_GATE = "FAIL_PHASE2L_M_LOCAL_PROSPECTIVE_COLLECTOR_CYCLE"

DEFAULT_L_REPORT = (
    ROOT
    / "local_data"
    / "phase2l_l_source_health"
    / "phase2l_l_source_health_report.json"
)

BUILDER = ROOT / "scripts" / "build_prospective_feature_bundle.py"
CONSOLIDATOR = ROOT / "scripts" / "consolidate_prospective_feature_bundles.py"


def utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(dt: datetime | None = None) -> str:
    value = dt or utc_now_dt()
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    json.loads(text)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def git_head() -> str:
    cp = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    sha = cp.stdout.strip()
    if len(sha) < 7:
        raise RuntimeError(f"invalid git HEAD: {sha!r}")
    return sha


def verify_recent_source_health(
    path: Path,
    max_age_seconds: int,
) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Phase 2L-L report not found: {path}. "
            "Run scripts/phase2l_l_source_health.py first."
        )
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("gate") != EXPECTED_L_GATE:
        raise RuntimeError(
            f"Phase 2L-L gate is not PASS: {report.get('gate')!r}"
        )

    summary = report.get("summary", {})
    if summary.get("operational_source_ready") is not True:
        raise RuntimeError("Phase 2L-L operational_source_ready is not true")
    if summary.get("2025_era5_environment_opened") is not False:
        raise RuntimeError("Phase 2L-L indicates 2025 ERA5 was opened")
    if summary.get("primary_confirmatory_test_run") is not False:
        raise RuntimeError("Phase 2L-L indicates Primary confirmatory test ran")
    if summary.get("risk_engine_allowed") is not False:
        raise RuntimeError("Phase 2L-L unexpectedly allows risk engine")

    generated = parse_utc(str(report["generated_at_utc"]))
    age = max(0, int((utc_now_dt() - generated).total_seconds()))
    if age > max_age_seconds:
        raise RuntimeError(
            f"Phase 2L-L report is stale for collector use: age={age}s "
            f"> limit={max_age_seconds}s. Re-run phase2l_l_source_health.py."
        )

    return {
        "gate": report.get("gate"),
        "generated_at_utc": report.get("generated_at_utc"),
        "age_seconds_at_collector_start": age,
        "max_allowed_age_seconds": max_age_seconds,
        "operational_source_ready": True,
        "risk_engine_allowed": False,
    }


def command_specs(scientific_dir: Path) -> list[tuple[str, list[str]]]:
    return [
        (
            "radar_scientific_decode",
            [
                sys.executable,
                str(ROOT / "scripts" / "radar_scientific_decode_probe.py"),
                "--output",
                str(scientific_dir / "radar_scientific_decode.json"),
            ],
        ),
        (
            "radar_morphology",
            [
                sys.executable,
                str(ROOT / "scripts" / "radar_morphology_probe.py"),
                "--output",
                str(scientific_dir / "radar_morphology.json"),
            ],
        ),
        (
            "radar_wind_orientation",
            [
                sys.executable,
                str(ROOT / "scripts" / "radar_wind_orientation_probe.py"),
                "--morphology",
                str(scientific_dir / "radar_morphology.json"),
                "--output",
                str(scientific_dir / "radar_wind_orientation.json"),
            ],
        ),
        (
            "radar_tracking",
            [
                sys.executable,
                str(ROOT / "scripts" / "radar_tracking_probe.py"),
                "--output",
                str(scientific_dir / "radar_tracking.json"),
            ],
        ),
        (
            "radar_hierarchy",
            [
                sys.executable,
                str(ROOT / "scripts" / "radar_hierarchy_probe.py"),
                "--tracking",
                str(scientific_dir / "radar_tracking.json"),
                "--output",
                str(scientific_dir / "radar_hierarchy.json"),
            ],
        ),
        (
            "radar_temporal",
            [
                sys.executable,
                str(ROOT / "scripts" / "radar_temporal_descriptor.py"),
                "--tracking",
                str(scientific_dir / "radar_tracking.json"),
                "--hierarchy",
                str(scientific_dir / "radar_hierarchy.json"),
                "--output",
                str(scientific_dir / "radar_temporal.json"),
            ],
        ),
        (
            "radar_genesis_geometry",
            [
                sys.executable,
                str(ROOT / "scripts" / "radar_genesis_geometry_report.py"),
                "--tracking",
                str(scientific_dir / "radar_tracking.json"),
                "--hierarchy",
                str(scientific_dir / "radar_hierarchy.json"),
                "--output",
                str(scientific_dir / "radar_genesis_geometry.json"),
            ],
        ),
        (
            "radar_inflow_geometry",
            [
                sys.executable,
                str(ROOT / "scripts" / "radar_inflow_geometry_probe.py"),
                "--genesis",
                str(scientific_dir / "radar_genesis_geometry.json"),
                "--output",
                str(scientific_dir / "radar_inflow_geometry.json"),
            ],
        ),
        (
            "parent_precursor_features",
            [
                sys.executable,
                str(ROOT / "scripts" / "build_parent_precursor_report.py"),
                "--temporal",
                str(scientific_dir / "radar_temporal.json"),
                "--inflow",
                str(scientific_dir / "radar_inflow_geometry.json"),
                "--output",
                str(scientific_dir / "parent_precursor_features.json"),
                "--csv-output",
                str(scientific_dir / "parent_precursor_features.csv"),
            ],
        ),
    ]


def run_step(
    name: str,
    cmd: list[str],
    log_dir: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    cp = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter() - started
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{name}.stdout.txt"
    stderr_path = log_dir / f"{name}.stderr.txt"
    stdout_path.write_text(cp.stdout or "", encoding="utf-8")
    stderr_path.write_text(cp.stderr or "", encoding="utf-8")

    row = {
        "name": name,
        "exit_code": int(cp.returncode),
        "elapsed_seconds": round(elapsed, 3),
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "ok": cp.returncode == 0,
    }
    print(
        f"[{name}] {'PASS' if row['ok'] else 'FAIL'} "
        f"elapsed={elapsed:.1f}s exit={cp.returncode}"
    )
    if cp.returncode != 0:
        tail = (cp.stderr or cp.stdout or "")[-3000:]
        raise RuntimeError(
            f"step failed: {name}; exit={cp.returncode}\n{tail}"
        )
    return row


def build_bundle(
    scientific_dir: Path,
    bundle_path: Path,
    run_id: str,
    commit_sha: str,
    log_dir: Path,
) -> dict[str, Any]:
    step = run_step(
        "build_prospective_feature_bundle",
        [
            sys.executable,
            str(BUILDER),
            "--scientific-dir",
            str(scientific_dir),
            "--output",
            str(bundle_path),
            "--run-id",
            run_id,
            "--commit-sha",
            commit_sha,
        ],
        log_dir,
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))

    required_assertions = {
        "bundle_complete": True,
        "raw_radar_archived": False,
        "raw_grib_archived": False,
        "lpz_classification": None,
        "risk_score": None,
        "risk_engine_allowed": False,
    }
    for key, expected in required_assertions.items():
        observed = bundle.get(key)
        if observed != expected:
            raise RuntimeError(
                f"prospective bundle safety assertion failed: "
                f"{key} expected {expected!r}, observed {observed!r}"
            )

    if int(bundle.get("component_count", -1)) != 9:
        raise RuntimeError(
            f"expected 9 bundle components, got {bundle.get('component_count')}"
        )

    step["bundle_safety_assertions"] = "PASS"
    return {"step": step, "bundle": bundle}


def consolidate_day(
    input_root: Path,
    archive_root: Path,
    date_utc: str,
    log_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    y, m, _ = date_utc.split("-")
    daily_dir = archive_root / y / m
    gz_path = daily_dir / f"{date_utc}.jsonl.gz"
    manifest_path = daily_dir / f"{date_utc}.manifest.json"

    step = run_step(
        "consolidate_prospective_feature_bundles",
        [
            sys.executable,
            str(CONSOLIDATOR),
            "--input-root",
            str(input_root),
            "--date-utc",
            date_utc,
            "--output-gz",
            str(gz_path),
            "--manifest-output",
            str(manifest_path),
        ],
        log_dir,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("risk_engine_allowed") is not False:
        raise RuntimeError("daily prospective archive unexpectedly allows risk engine")
    if int(manifest.get("parse_error_count", -1)) != 0:
        raise RuntimeError(
            f"daily archive parse errors: {manifest.get('parse_errors')}"
        )

    step["archive_gz"] = str(gz_path)
    step["archive_manifest"] = str(manifest_path)
    return step, manifest


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--source-health-report",
        type=Path,
        default=DEFAULT_L_REPORT,
    )
    p.add_argument(
        "--max-source-health-age-seconds",
        type=int,
        default=5400,
        help="Require the Phase 2L-L health snapshot to be no older than this.",
    )
    p.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "local_data" / "phase2l_m_prospective_collector",
    )
    args = p.parse_args()

    if args.max_source_health_age_seconds < 60:
        raise ValueError("--max-source-health-age-seconds must be >= 60")

    started_dt = utc_now_dt()
    started_iso = utc_iso(started_dt)
    run_id = "LOCAL-" + started_dt.strftime("%Y%m%dT%H%M%SZ")
    output_root = args.output_root.resolve()
    run_dir = (
        output_root
        / "runs"
        / started_dt.strftime("%Y")
        / started_dt.strftime("%m")
        / started_dt.strftime("%d")
        / run_id
    )
    scientific_dir = run_dir / "scientific"
    log_dir = run_dir / "logs"
    bundle_path = run_dir / "prospective_feature_bundle.json"
    manifest_path = run_dir / "phase2l_m_run_manifest.json"

    run_dir.mkdir(parents=True, exist_ok=False)
    scientific_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "schema_version": "1.0.0",
        "phase": "2L-M-local-prospective-collector-operationalization",
        "gate": FAIL_GATE,
        "run_id": run_id,
        "started_at_utc": started_iso,
        "completed_at_utc": None,
        "git_commit_sha": None,
        "source_health": None,
        "steps": [],
        "bundle_path": str(bundle_path),
        "daily_archive": None,
        "scientific_policy": {
            "new_predictor_created": False,
            "2025_era5_environment_opened": False,
            "primary_confirmatory_test_run": False,
            "lpz_classification_produced": False,
            "risk_score_produced": False,
            "risk_engine_allowed": False,
        },
        "error": None,
    }

    try:
        source_health = verify_recent_source_health(
            args.source_health_report.resolve(),
            args.max_source_health_age_seconds,
        )
        manifest["source_health"] = source_health

        commit_sha = git_head()
        manifest["git_commit_sha"] = commit_sha

        print("=" * 104)
        print("LPZ PHASE 2L-M — LOCAL PROSPECTIVE COLLECTOR CYCLE")
        print("=" * 104)
        print(f"Run ID                         : {run_id}")
        print(f"Git commit                     : {commit_sha}")
        print(
            f"Phase 2L-L health age          : "
            f"{source_health['age_seconds_at_collector_start']}s"
        )
        print("2025 ERA5 environment opened   : NO")
        print("Risk engine                    : NOT ALLOWED")
        print("-" * 104)

        for name, cmd in command_specs(scientific_dir):
            manifest["steps"].append(run_step(name, cmd, log_dir))

        bundle_result = build_bundle(
            scientific_dir,
            bundle_path,
            run_id,
            commit_sha,
            log_dir,
        )
        manifest["steps"].append(bundle_result["step"])
        bundle = bundle_result["bundle"]

        bundle_date = parse_utc(str(bundle["generated_at_utc"])).date().isoformat()

        consolidate_step, daily_manifest = consolidate_day(
            output_root / "runs",
            output_root / "daily",
            bundle_date,
            log_dir,
        )
        manifest["steps"].append(consolidate_step)
        manifest["daily_archive"] = {
            "date_utc": bundle_date,
            "bundle_count": daily_manifest.get("bundle_count"),
            "complete_bundle_count": daily_manifest.get("complete_bundle_count"),
            "coverage_fraction": daily_manifest.get("coverage_fraction"),
            "collector_gap_count": daily_manifest.get("collector_gap_count"),
            "prospective_day_quality": daily_manifest.get("prospective_day_quality"),
            "risk_engine_allowed": False,
            "archive_file": daily_manifest.get("archive_file"),
        }

        manifest["gate"] = PASS_GATE
        manifest["completed_at_utc"] = utc_iso()
        atomic_write_json(manifest_path, manifest)

        print("-" * 104)
        print(f"Bundle complete                 : {bundle.get('bundle_complete')}")
        print(f"Bundle components               : {bundle.get('component_count')} / 9")
        print(f"LPZ classification              : NONE")
        print(f"Risk score                      : NONE")
        print(f"Risk engine                     : NOT ALLOWED")
        print(f"Daily archive bundle count      : {daily_manifest.get('bundle_count')}")
        print(
            f"Daily archive coverage          : "
            f"{float(daily_manifest.get('coverage_fraction', 0.0)):.3%}"
        )
        print(f"Gate                            : {PASS_GATE}")
        print(f"Run manifest                    : {manifest_path}")
        print("=" * 104)
        return 0

    except Exception as exc:
        manifest["completed_at_utc"] = utc_iso()
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        atomic_write_json(manifest_path, manifest)
        print("")
        print("=" * 104)
        print("LPZ PHASE 2L-M — COLLECTOR CYCLE FAILED SAFELY")
        print("=" * 104)
        print(f"Run ID      : {run_id}")
        print(f"Error       : {manifest['error']}")
        print(f"Run manifest: {manifest_path}")
        print("No risk score/classification was produced.")
        print("Re-run after correcting the source or step failure; successful runs are never overwritten.")
        print("=" * 104)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
