#!/usr/bin/env python3
"""O9 — IMERG Final V08 re-entry one-shot harness state machine.

This controller does not itself open ERA5 or execute the confirmatory test.  It
verifies the frozen Phase 2L-H/K2 protocol and a hash-linked chain of O9 evidence.
Later execution stages are not considered eligible until every earlier stage is
present, valid, and linked to the exact predecessor artifacts.

The design deliberately makes a WAIT state successful and normal while Final V08
is unavailable.  Any out-of-order later artifact is treated as a safety violation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
H_FREEZE = ROOT / "research/phase2/phase2l_h_validation_protocol_freeze_20260911.json"
K2_FREEZE = ROOT / "research/phase2/phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912.json"

H_GATE = "PASS_PHASE2L_H_DISCOVERY_AND_VALIDATION_PROTOCOL_FREEZE_PRIMARY_Q850_T0H"
K2_GATE = "PASS_PHASE2L_K2_V07_BOUNDARY_AND_V08_DEFERRED_VALIDATION_FREEZE"

# Exact byte hashes of the committed authoritative freeze artifacts.  Git history
# shows H has had exactly one commit (3944692...) and K2 exactly one commit
# (c0c5dec...).  K2 also records a different H hash that was captured from the
# local Windows working tree before/around commit time.  Preserve and verify that
# historical value, but do not mistake it for the canonical committed-file hash.
EXPECTED_H_COMMITTED_SHA256 = "0896cfae9be7785210b48f73fbce95fdfdda009c252838774d368c28819015fa"
EXPECTED_K2_COMMITTED_SHA256 = "895ccc5520f6512b74f420707fad3ebfe9c5229c17f204e151852cf7c47fcfef"
EXPECTED_K2_RECORDED_LOCAL_H_SHA256 = "6b3cac100513cb5be3e392eb3e9b68d250ddabd2c94c2c4ab93a0081b58b88fe"
H_FREEZE_COMMIT = "3944692a5f4ed8b108a31b76477321abcf3d4bd5"
H_FREEZE_GIT_BLOB = "bf8e2506e0a5dcad39f1bedf6ef7d544e5d72fae"
K2_FREEZE_COMMIT = "c0c5dec2f138901db84316fd03e28e502a0a7e65"

PRIMARY_METRIC = "q850_mean_kgkg"
PRIMARY_CONTRAST = "t+0h"
PRIMARY_TEST = "EXACT_ONE_SIDED_SIGN_TEST_ON_POSITIVE_DATE_UTC_CLUSTER_MEANS"


@dataclass(frozen=True)
class Stage:
    key: str
    filename: str
    gate: str | None
    requires: tuple[str, ...]
    validator: Callable[[dict[str, Any]], list[str]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"JSON object required: {path}")
    return obj


def _bool_error(obj: dict[str, Any], key: str, expected: bool) -> list[str]:
    return [] if obj.get(key) is expected else [f"{key} must be {expected}"]


def _version_errors(obj: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if str(obj.get("imerg_final_version")) != "08":
        errors.append("imerg_final_version must be 08")
    if str(obj.get("short_name")) != "GPM_3IMERGHH":
        errors.append("short_name must be GPM_3IMERGHH")
    errors.extend(_bool_error(obj, "risk_engine_allowed", False))
    return errors


def validate_availability(obj: dict[str, Any]) -> list[str]:
    e = _version_errors(obj)
    if obj.get("official_final_product") is not True:
        e.append("official_final_product must be true")
    if obj.get("metadata_result_count", 0) < 1:
        e.append("metadata_result_count must be >=1")
    return e


def validate_coverage(obj: dict[str, Any]) -> list[str]:
    e = _version_errors(obj)
    expected = {
        "development_region_day_count": 5943,
        "validation_region_day_count": 1218,
        "development_missing_slot_count": 0,
        "validation_missing_slot_count": 0,
    }
    for key, value in expected.items():
        if int(obj.get(key, -1)) != value:
            e.append(f"{key} must be {value}")
    if obj.get("all_required_slots_covered") is not True:
        e.append("all_required_slots_covered must be true")
    return e


def validate_dev_rebuild(obj: dict[str, Any]) -> list[str]:
    e = _version_errors(obj)
    if int(obj.get("region_day_count", -1)) != 5943:
        e.append("region_day_count must be 5943")
    if obj.get("split") != "DEVELOPMENT":
        e.append("split must be DEVELOPMENT")
    if obj.get("candidate_membership_changed") is not False:
        e.append("candidate_membership_changed must be false")
    if obj.get("environment_variables_used") is not False:
        e.append("environment_variables_used must be false")
    return e


def validate_validation_rebuild(obj: dict[str, Any]) -> list[str]:
    e = _version_errors(obj)
    if int(obj.get("region_day_count", -1)) != 1218:
        e.append("region_day_count must be 1218")
    if int(obj.get("official_positive_region_day_count", -1)) != 23:
        e.append("official_positive_region_day_count must be 23")
    if obj.get("split") != "VALIDATION_2025":
        e.append("split must be VALIDATION_2025")
    if obj.get("environment_variables_used") is not False:
        e.append("environment_variables_used must be false")
    return e


def validate_transform_freeze(obj: dict[str, Any]) -> list[str]:
    e = _version_errors(obj)
    if obj.get("fit_population") != "DEVELOPMENT_V08_ONLY":
        e.append("fit_population must be DEVELOPMENT_V08_ONLY")
    if int(obj.get("development_fit_row_count", -1)) != 5943:
        e.append("development_fit_row_count must be 5943")
    if int(obj.get("validation_fit_row_count", -1)) != 0:
        e.append("validation_fit_row_count must be 0")
    if obj.get("matching_components") != ["rain_pca_pc1", "rain_pca_pc2"]:
        e.append("matching_components must be PC1/PC2")
    return e


def validate_validation_transform(obj: dict[str, Any]) -> list[str]:
    e = _version_errors(obj)
    if int(obj.get("validation_row_count", -1)) != 1218:
        e.append("validation_row_count must be 1218")
    if obj.get("pca_refit_on_2025") is not False:
        e.append("pca_refit_on_2025 must be false")
    if obj.get("standardization_refit_on_2025") is not False:
        e.append("standardization_refit_on_2025 must be false")
    if obj.get("transform_source") != "FROZEN_DEVELOPMENT_V08_TRANSFORM":
        e.append("transform_source must be FROZEN_DEVELOPMENT_V08_TRANSFORM")
    return e


def validate_matching_freeze(obj: dict[str, Any]) -> list[str]:
    e = _version_errors(obj)
    expected_int = {
        "positive_match_set_count": 23,
        "comparison_case_count": 69,
        "match_ratio": 3,
        "season_window_days": 60,
        "positive_event_buffer_days": 3,
    }
    for key, value in expected_int.items():
        if int(obj.get(key, -1)) != value:
            e.append(f"{key} must be {value}")
    for key, value in {
        "same_primary_subdivision_required": True,
        "replacement_used": False,
        "environment_variables_used_for_selection": False,
        "pca_refit_on_2025": False,
    }.items():
        if obj.get(key) is not value:
            e.append(f"{key} must be {value}")
    return e


def validate_era5_opening(obj: dict[str, Any]) -> list[str]:
    e: list[str] = []
    if obj.get("validation_year") != 2025:
        e.append("validation_year must be 2025")
    if obj.get("opened_after_matching_freeze") is not True:
        e.append("opened_after_matching_freeze must be true")
    if obj.get("matching_membership_changed_by_era5") is not False:
        e.append("matching_membership_changed_by_era5 must be false")
    e.extend(_bool_error(obj, "risk_engine_allowed", False))
    return e


def validate_primary(obj: dict[str, Any]) -> list[str]:
    e: list[str] = []
    if int(obj.get("confirmatory_run_count", -1)) != 1:
        e.append("confirmatory_run_count must equal exactly 1")
    if obj.get("metric") != PRIMARY_METRIC:
        e.append(f"metric must be {PRIMARY_METRIC}")
    if obj.get("contrast") != PRIMARY_CONTRAST:
        e.append(f"contrast must be {PRIMARY_CONTRAST}")
    if obj.get("test") != PRIMARY_TEST:
        e.append(f"test must be {PRIMARY_TEST}")
    if float(obj.get("alpha", -1)) != 0.05:
        e.append("alpha must be 0.05")
    if obj.get("retuned_after_result") is not False:
        e.append("retuned_after_result must be false")
    if obj.get("primary_outcome") not in {"PASS", "FAIL"}:
        e.append("primary_outcome must be PASS or FAIL")
    e.extend(_bool_error(obj, "risk_engine_allowed", False))
    return e


STAGES = (
    Stage("availability", "o9_a_v08_availability.json", "PASS_O9_A_V08_OFFICIAL_FINAL_AVAILABILITY", (), validate_availability),
    Stage("coverage", "o9_c_v08_required_coverage.json", "PASS_O9_C_V08_FULL_REQUIRED_COVERAGE", ("availability",), validate_coverage),
    Stage("development_rebuild", "o9_d_development_v08_rebuild.json", "PASS_O9_D_V08_DEVELOPMENT_REBUILD_5943", ("coverage",), validate_dev_rebuild),
    Stage("validation_rebuild", "o9_d_validation_v08_rebuild.json", "PASS_O9_D_V08_VALIDATION_REBUILD_1218", ("development_rebuild",), validate_validation_rebuild),
    Stage("transform_freeze", "o9_e_development_v08_transform_freeze.json", "PASS_O9_E_V08_DEVELOPMENT_ONLY_TRANSFORM_FREEZE", ("development_rebuild", "validation_rebuild"), validate_transform_freeze),
    Stage("validation_transform", "o9_e_validation_v08_transform_application.json", "PASS_O9_E_V08_VALIDATION_TRANSFORM_NO_REFIT", ("transform_freeze", "validation_rebuild"), validate_validation_transform),
    Stage("matching_freeze", "o9_f_validation_matching_freeze.json", "PASS_O9_F_V08_2025_MATCHING_FREEZE", ("validation_transform",), validate_matching_freeze),
    Stage("era5_opening", "o9_g_2025_era5_opening_receipt.json", "PASS_O9_G_2025_ERA5_OPENED_AFTER_MATCHING_FREEZE", ("matching_freeze",), validate_era5_opening),
    Stage("primary_confirmatory", "o9_h_primary_confirmatory_result.json", None, ("era5_opening",), validate_primary),
)
STAGE_BY_KEY = {s.key: s for s in STAGES}


def verify_frozen_protocol(repo_root: Path) -> dict[str, Any]:
    h_path = repo_root / H_FREEZE.relative_to(ROOT)
    k2_path = repo_root / K2_FREEZE.relative_to(ROOT)
    h = read_json(h_path)
    k2 = read_json(k2_path)
    h_sha = sha256_file(h_path)
    k2_sha = sha256_file(k2_path)
    errors: list[str] = []

    # Canonical committed-file integrity.  These hashes correspond to the files
    # that GitHub has served unchanged since their one-time freeze commits.
    if h_sha != EXPECTED_H_COMMITTED_SHA256:
        errors.append("Phase H committed-file SHA256 changed from authoritative freeze")
    if k2_sha != EXPECTED_K2_COMMITTED_SHA256:
        errors.append("K2 committed-file SHA256 changed from authoritative freeze")

    if h.get("gate") != H_GATE:
        errors.append("Phase H gate mismatch")
    if k2.get("gate") != K2_GATE:
        errors.append("K2 gate mismatch")
    state = k2.get("validation_state", {})
    if state.get("status") != "DEFERRED_PENDING_IMERG_FINAL_V08":
        errors.append("K2 is no longer in deferred V08 state")
    if state.get("primary_confirmatory_test_run") is not False:
        errors.append("K2 says confirmatory test already ran")
    if state.get("primary_outcome_opened") is not False:
        errors.append("K2 says Primary outcome already opened")
    if state.get("2025_era5_environment_outcomes_may_be_opened_now") is not False:
        errors.append("K2 unexpectedly allows ERA5 opening before O9 matching freeze")
    if state.get("risk_engine_allowed") is not False:
        errors.append("K2 unexpectedly allows Risk Engine")

    primary = h.get("primary_hypothesis", {})
    test = h.get("primary_validation_test", {})
    if primary.get("metric") != PRIMARY_METRIC or primary.get("contrast") != PRIMARY_CONTRAST:
        errors.append("Phase H Primary metric/contrast mismatch")
    if test.get("test") != PRIMARY_TEST or float(test.get("alpha", -1)) != 0.05:
        errors.append("Phase H Primary test/alpha mismatch")

    # K2's source_integrity block captured a local-Windows byte hash for H.  Git
    # history proves the committed H blob has never changed; verify the historical
    # local value remains intact, but do not compare that pre-commit/local byte
    # representation directly to the canonical committed-file bytes.
    manifest = k2.get("source_integrity", {}).get("sha256", {})
    h_rel_win = str(H_FREEZE.relative_to(ROOT)).replace("/", "\\")
    h_meta = manifest.get(h_rel_win) or manifest.get(str(H_FREEZE.relative_to(ROOT)))
    recorded_local_h_sha = h_meta.get("sha256") if isinstance(h_meta, dict) else None
    if recorded_local_h_sha != EXPECTED_K2_RECORDED_LOCAL_H_SHA256:
        errors.append("K2 historical local Phase H SHA256 record changed or is missing")

    return {
        "state": "PASS" if not errors else "FAIL",
        "errors": errors,
        "h_sha256": h_sha,
        "h_expected_committed_sha256": EXPECTED_H_COMMITTED_SHA256,
        "h_freeze_commit": H_FREEZE_COMMIT,
        "h_freeze_git_blob": H_FREEZE_GIT_BLOB,
        "k2_sha256": k2_sha,
        "k2_expected_committed_sha256": EXPECTED_K2_COMMITTED_SHA256,
        "k2_freeze_commit": K2_FREEZE_COMMIT,
        "k2_recorded_local_h_sha256": recorded_local_h_sha,
        "k2_expected_recorded_local_h_sha256": EXPECTED_K2_RECORDED_LOCAL_H_SHA256,
        "historical_local_h_sha_matches_committed_h_bytes": (
            recorded_local_h_sha == h_sha
        ),
        "provenance_note": (
            "K2 preserved a local pre/around-commit Phase H byte hash. Git history "
            "shows the committed H blob has never changed since 3944692; O9 pins "
            "the canonical committed H/K2 byte SHA256 values separately and also "
            "verifies K2's historical local hash record remains unchanged."
        ),
        "primary_metric": PRIMARY_METRIC,
        "primary_contrast": PRIMARY_CONTRAST,
        "primary_test": PRIMARY_TEST,
        "risk_engine_allowed": False,
    }


def evaluate_chain(repo_root: Path, evidence_dir: Path) -> dict[str, Any]:
    frozen = verify_frozen_protocol(repo_root)
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "phase": "O9-IMERG-Final-V08-reentry-one-shot-harness",
        "generated_at_utc": utc_now(),
        "frozen_protocol": frozen,
        "evidence_dir": str(evidence_dir),
        "stages": [],
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
        "era5_2025_may_be_opened": False,
        "confirmatory_run_may_execute": False,
    }
    if frozen["state"] != "PASS":
        report.update({
            "state": "BLOCKED_O9_FROZEN_PROTOCOL_INTEGRITY_FAILURE",
            "blockers": frozen["errors"],
            "next_action": "RESTORE_AND_REVIEW_PHASE_H_K2_FREEZE",
        })
        return report

    existing = {s.key: (evidence_dir / s.filename).exists() for s in STAGES}
    seen_missing = False
    order_violations: list[str] = []
    for s in STAGES:
        if not existing[s.key]:
            seen_missing = True
        elif seen_missing:
            order_violations.append(s.key)
    if order_violations:
        report.update({
            "state": "BLOCKED_O9_SAFETY_ORDER_VIOLATION",
            "blockers": ["OUT_OF_ORDER_EVIDENCE:" + ",".join(order_violations)],
            "next_action": "REMOVE_OR_QUARANTINE_OUT_OF_ORDER_EVIDENCE_AND_REVIEW",
        })
        return report

    hashes: dict[str, str] = {}
    invalid: list[str] = []
    completed: list[str] = []
    for s in STAGES:
        path = evidence_dir / s.filename
        if not path.exists():
            report["stages"].append({"key": s.key, "filename": s.filename, "state": "WAIT"})
            continue
        try:
            obj = read_json(path)
        except Exception as exc:  # noqa: BLE001
            invalid.append(f"{s.key}: unreadable evidence: {type(exc).__name__}: {exc}")
            report["stages"].append({"key": s.key, "filename": s.filename, "state": "FAIL"})
            continue

        errors: list[str] = []
        if s.gate is not None and obj.get("gate") != s.gate:
            errors.append(f"gate must be {s.gate}")
        errors.extend(s.validator(obj))

        requires = obj.get("requires_sha256", {})
        if not isinstance(requires, dict):
            errors.append("requires_sha256 must be an object")
            requires = {}
        for req_key in s.requires:
            req_stage = STAGE_BY_KEY[req_key]
            expected = hashes.get(req_key)
            observed = requires.get(req_stage.filename)
            if expected is None:
                errors.append(f"prerequisite hash unavailable: {req_key}")
            elif observed != expected:
                errors.append(
                    f"requires_sha256[{req_stage.filename}] mismatch: expected {expected}, got {observed}"
                )

        digest = sha256_file(path)
        hashes[s.key] = digest
        state = "PASS" if not errors else "FAIL"
        report["stages"].append({
            "key": s.key,
            "filename": s.filename,
            "state": state,
            "sha256": digest,
            "errors": errors,
        })
        if errors:
            invalid.extend(f"{s.key}: {x}" for x in errors)
        else:
            completed.append(s.key)

    if invalid:
        report.update({
            "state": "BLOCKED_O9_SAFETY_INTEGRITY_VIOLATION",
            "blockers": invalid,
            "completed_stage_keys": completed,
            "next_action": "REVIEW_INVALID_O9_EVIDENCE",
        })
        return report

    next_stage = next((s for s in STAGES if not existing[s.key]), None)
    report["completed_stage_keys"] = completed
    report["completed_stage_count"] = len(completed)

    if next_stage is None:
        result = read_json(evidence_dir / STAGE_BY_KEY["primary_confirmatory"].filename)
        outcome = result["primary_outcome"]
        report.update({
            "state": f"O9_CONFIRMATORY_COMPLETE_{outcome}",
            "primary_outcome": outcome,
            "confirmatory_run_count": 1,
            "next_action": "FREEZE_RESULT_NO_RETUNING_AND_KEEP_RISK_ENGINE_LOCKED_PENDING_SEPARATE_RELEASE_GATES",
        })
        return report

    if next_stage.key == "availability":
        state = "WAIT_IMERG_FINAL_V08_NOT_AVAILABLE_OR_NOT_PROVEN"
        next_action = "PROVE_OFFICIAL_NASA_IMERG_FINAL_V08_AVAILABILITY"
    elif next_stage.key == "era5_opening":
        state = "READY_TO_OPEN_2025_ERA5_AFTER_MATCHING_FREEZE"
        next_action = "OPEN_2025_ERA5_USING_FROZEN_MATCHING_MEMBERSHIP_ONLY"
        report["era5_2025_may_be_opened"] = True
    elif next_stage.key == "primary_confirmatory":
        state = "READY_FOR_SINGLE_FROZEN_PRIMARY_CONFIRMATORY_RUN"
        next_action = "RUN_FROZEN_Q850_T0H_CONFIRMATORY_TEST_EXACTLY_ONCE"
        report["era5_2025_may_be_opened"] = True
        report["confirmatory_run_may_execute"] = True
    else:
        state = "WAIT_O9_NEXT_REENTRY_STAGE"
        next_action = f"COMPLETE_{next_stage.key.upper()}"

    report.update({
        "state": state,
        "next_stage_key": next_stage.key,
        "next_stage_filename": next_stage.filename,
        "next_action": next_action,
        "blockers": [] if next_stage.key != "availability" else ["OFFICIAL_FINAL_V08_AVAILABILITY_NOT_PROVEN"],
    })
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=ROOT)
    ap.add_argument("--evidence-dir", type=Path, default=ROOT / "research/o9/reentry")
    ap.add_argument("--output", type=Path, default=ROOT / "research/operations/o9_v08_reentry_latest.json")
    args = ap.parse_args()

    repo_root = args.repo_root.resolve()
    evidence_dir = args.evidence_dir.resolve()
    report = evaluate_chain(repo_root, evidence_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"O9 state={report['state']}")
    print(f"next_action={report.get('next_action')}")
    print("Risk Engine remains LOCKED.")
    return 2 if report["state"].startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
