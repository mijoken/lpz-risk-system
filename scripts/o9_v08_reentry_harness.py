#!/usr/bin/env python3
"""O9 Final-V08 re-entry state machine.

Fail-closed controller for the immutable O9 evidence chain.  It never downloads
IMERG/ERA5 and never runs the Primary.  O9-G is intentionally split into:
1) guarded retrieval authorization after the frozen 92-case O9-F population;
2) later ERA5 reconstruction completion.
The Primary is not eligible until the second receipt exists and validates.
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
EXPECTED_H_COMMITTED_SHA256 = "0896cfae9be7785210b48f73fbce95fdfdda009c252838774d368c28819015fa"
EXPECTED_K2_COMMITTED_SHA256 = "895ccc5520f6512b74f420707fad3ebfe9c5229c17f204e151852cf7c47fcfef"
EXPECTED_K2_RECORDED_LOCAL_H_SHA256 = "6b3cac100513cb5be3e392eb3e9b68d250ddabd2c94c2c4ab93a0081b58b88fe"
H_FREEZE_COMMIT = "3944692a5f4ed8b108a31b76477321abcf3d4bd5"
H_FREEZE_GIT_BLOB = "bf8e2506e0a5dcad39f1bedf6ef7d544e5d72fae"
K2_FREEZE_COMMIT = "c0c5dec2f138901db84316fd03e28e502a0a7e65"

PRIMARY_METRIC = "q850_mean_kgkg"
PRIMARY_CONTRAST = "t+0h"
PRIMARY_TEST = "EXACT_ONE_SIDED_SIGN_TEST_ON_POSITIVE_DATE_UTC_CLUSTER_MEANS"
F_GATE = "PASS_O9_F_V08_FROZEN_2025_MATCHING_23_POSITIVES_69_COMPARISONS"
G_AUTH_GATE = "PASS_O9_G_2025_ERA5_RETRIEVAL_AUTHORIZED_AFTER_MATCHING_FREEZE"
G_COMPLETE_GATE = "PASS_O9_G_2025_ERA5_RECONSTRUCTION_COMPLETE_92_CASES_368_SNAPSHOTS"


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


def _version_errors(obj: dict[str, Any], *, source_required: bool = False) -> list[str]:
    e: list[str] = []
    if str(obj.get("imerg_final_version")).replace(".0", "").zfill(2) != "08":
        e.append("imerg_final_version must be 08")
    if obj.get("short_name") != "GPM_3IMERGHH":
        e.append("short_name must be GPM_3IMERGHH")
    if obj.get("official_final_product") is not True:
        e.append("official_final_product must be true")
    if source_required and obj.get("source_id") != "NASA_IMERG_FINAL_V08":
        e.append("source_id must be NASA_IMERG_FINAL_V08")
    e.extend(_bool_error(obj, "risk_engine_allowed", False))
    if "SYNTHETIC" in str(obj.get("phase", "")).upper() or obj.get("synthetic") is True:
        e.append("synthetic evidence cannot enter real O9 re-entry chain")
    return e


def validate_availability(obj: dict[str, Any]) -> list[str]:
    e = _version_errors(obj)
    if int(obj.get("metadata_result_count", 0)) < 1:
        e.append("metadata_result_count must be >=1")
    return e


def validate_coverage(obj: dict[str, Any]) -> list[str]:
    e = _version_errors(obj)
    for key, value in {
        "development_region_day_count": 5943,
        "validation_region_day_count": 1218,
        "development_missing_slot_count": 0,
        "validation_missing_slot_count": 0,
    }.items():
        if int(obj.get(key, -1)) != value:
            e.append(f"{key} must be {value}")
    if obj.get("all_required_slots_covered") is not True:
        e.append("all_required_slots_covered must be true")
    return e


def validate_dev_rebuild(obj: dict[str, Any]) -> list[str]:
    e = _version_errors(obj, source_required=True)
    checks = {
        "region_day_count": int(obj.get("region_day_count", -1)) == 5943,
        "split": obj.get("split") == "DEVELOPMENT",
        "candidate_membership_changed": obj.get("candidate_membership_changed") is False,
        "environment_variables_used": obj.get("environment_variables_used") is False,
        "validation_era5_environment_read": obj.get("validation_era5_environment_read") is False,
    }
    e.extend([f"{k} invalid" for k, ok in checks.items() if not ok])
    return e


def validate_validation_rebuild(obj: dict[str, Any]) -> list[str]:
    e = _version_errors(obj, source_required=True)
    checks = {
        "region_day_count": int(obj.get("region_day_count", -1)) == 1218,
        "official_positive_region_day_count": int(obj.get("official_positive_region_day_count", -1)) == 23,
        "split": obj.get("split") == "VALIDATION_2025",
        "environment_variables_used": obj.get("environment_variables_used") is False,
        "validation_era5_environment_read": obj.get("validation_era5_environment_read") is False,
    }
    e.extend([f"{k} invalid" for k, ok in checks.items() if not ok])
    return e


def validate_transform_freeze(obj: dict[str, Any]) -> list[str]:
    e = _version_errors(obj, source_required=True)
    checks = {
        "fit_population": obj.get("fit_population") == "DEVELOPMENT_V08_ONLY",
        "development_fit_row_count": int(obj.get("development_fit_row_count", -1)) == 5943,
        "validation_fit_row_count": int(obj.get("validation_fit_row_count", -1)) == 0,
        "matching_components": obj.get("matching_components") == ["rain_pca_pc1", "rain_pca_pc2"],
        "pca_refit_on_2025": obj.get("pca_refit_on_2025") is False,
        "standardization_refit_on_2025": obj.get("standardization_refit_on_2025") is False,
        "validation_era5_environment_read": obj.get("validation_era5_environment_read") is False,
    }
    e.extend([f"{k} invalid" for k, ok in checks.items() if not ok])
    return e


def validate_validation_transform(obj: dict[str, Any]) -> list[str]:
    e = _version_errors(obj, source_required=True)
    checks = {
        "validation_row_count": int(obj.get("validation_row_count", -1)) == 1218,
        "official_positive_region_day_count": int(obj.get("official_positive_region_day_count", -1)) == 23,
        "pca_refit_on_2025": obj.get("pca_refit_on_2025") is False,
        "standardization_refit_on_2025": obj.get("standardization_refit_on_2025") is False,
        "validation_statistics_used_to_modify_transform": obj.get("validation_statistics_used_to_modify_transform") is False,
        "transform_source": obj.get("transform_source") == "FROZEN_DEVELOPMENT_V08_TRANSFORM",
        "validation_era5_environment_read": obj.get("validation_era5_environment_read") is False,
    }
    e.extend([f"{k} invalid" for k, ok in checks.items() if not ok])
    return e


def validate_matching_freeze(obj: dict[str, Any]) -> list[str]:
    e = _version_errors(obj, source_required=True)
    checks = {
        "validation_region_day_count": int(obj.get("validation_region_day_count", -1)) == 1218,
        "official_positive_region_day_count": int(obj.get("official_positive_region_day_count", -1)) == 23,
        "matched_comparison_region_day_count": int(obj.get("matched_comparison_region_day_count", -1)) == 69,
        "unique_comparison_region_day_count": int(obj.get("unique_comparison_region_day_count", -1)) == 69,
        "final_matched_population_region_day_count": int(obj.get("final_matched_population_region_day_count", -1)) == 92,
        "match_ratio": obj.get("match_ratio") == "1_POSITIVE_TO_3_COMPARISONS",
        "same_primary_subdivision_required": obj.get("same_primary_subdivision_required") is True,
        "season_window": int(obj.get("season_window_circular_calendar_days", -1)) == 60,
        "positive_event_buffer": int(obj.get("same_region_positive_event_buffer_actual_days", -1)) == 3,
        "replacement_used": obj.get("replacement_used") is False,
        "environment_variables_used_for_selection": obj.get("environment_variables_used_for_selection") is False,
        "pca_refit_on_2025": obj.get("pca_refit_on_2025") is False,
        "standardization_refit_on_2025": obj.get("standardization_refit_on_2025") is False,
        "time_anchor_policy": obj.get("time_anchor_policy") == "IMERG_3H_P95_MAX_WINDOW_START",
        "time_anchor_start_column": obj.get("time_anchor_start_column") == "imerg_3h_p95_window_start_utc",
        "time_anchor_preserved": obj.get("time_anchor_preserved_for_all_final_cases") is True,
        "validation_era5_environment_read": obj.get("validation_era5_environment_read") is False,
    }
    e.extend([f"{k} invalid" for k, ok in checks.items() if not ok])
    meta = ((obj.get("outputs") or {}).get("final_matched_population") or {})
    if int(meta.get("rows", -1)) != 92 or not isinstance(meta.get("sha256"), str):
        e.append("final_matched_population output metadata invalid")
    return e


def validate_era5_authorization(obj: dict[str, Any]) -> list[str]:
    e: list[str] = []
    checks = {
        "validation_year": int(obj.get("validation_year", -1)) == 2025,
        "opened_after_matching_freeze": obj.get("opened_after_matching_freeze") is True,
        "era5_retrieval_authorized": obj.get("era5_retrieval_authorized") is True,
        "era5_retrieval_completed": obj.get("era5_retrieval_completed") is False,
        "matching_membership_changed_by_era5": obj.get("matching_membership_changed_by_era5") is False,
        "matched_case_count": int(obj.get("matched_case_count", -1)) == 92,
        "positive_case_count": int(obj.get("positive_case_count", -1)) == 23,
        "comparison_case_count": int(obj.get("comparison_case_count", -1)) == 69,
        "snapshot_mapping_count": int(obj.get("snapshot_mapping_count", -1)) == 368,
        "time_anchor_policy": obj.get("time_anchor_policy") == "IMERG_3H_P95_MAX_WINDOW_START",
        "future_source_time_allowed": obj.get("future_source_time_allowed") is False,
        "network_access_performed": obj.get("network_access_performed") is False,
        "era5_environment_values_read": obj.get("era5_environment_values_read") is False,
        "primary_confirmatory_test_run": obj.get("primary_confirmatory_test_run") is False,
        "confirmatory_run_may_execute": obj.get("confirmatory_run_may_execute") is False,
        "risk_engine_allowed": obj.get("risk_engine_allowed") is False,
        "public_risk_release_allowed": obj.get("public_risk_release_allowed") is False,
    }
    e.extend([f"{k} invalid" for k, ok in checks.items() if not ok])
    return e


def validate_era5_completion(obj: dict[str, Any]) -> list[str]:
    e: list[str] = []
    checks = {
        "validation_year": int(obj.get("validation_year", -1)) == 2025,
        "era5_retrieval_authorized": obj.get("era5_retrieval_authorized") is True,
        "era5_retrieval_completed": obj.get("era5_retrieval_completed") is True,
        "matched_case_count": int(obj.get("matched_case_count", -1)) == 92,
        "snapshot_mapping_count": int(obj.get("snapshot_mapping_count", -1)) == 368,
        "matching_membership_changed_by_era5": obj.get("matching_membership_changed_by_era5") is False,
        "primary_confirmatory_test_run": obj.get("primary_confirmatory_test_run") is False,
        "risk_engine_allowed": obj.get("risk_engine_allowed") is False,
        "public_risk_release_allowed": obj.get("public_risk_release_allowed") is False,
    }
    e.extend([f"{k} invalid" for k, ok in checks.items() if not ok])
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
    Stage("validation_rebuild", "o9_d_validation_v08_rebuild.json", "PASS_O9_D_V08_VALIDATION_REBUILD_1218", ("coverage", "development_rebuild"), validate_validation_rebuild),
    Stage("transform_freeze", "o9_e_development_v08_transform_freeze.json", "PASS_O9_E_V08_DEVELOPMENT_ONLY_TRANSFORM_FREEZE", ("development_rebuild", "validation_rebuild"), validate_transform_freeze),
    Stage("validation_transform", "o9_e_validation_v08_transform_application.json", "PASS_O9_E_V08_VALIDATION_TRANSFORM_NO_REFIT", ("transform_freeze", "validation_rebuild"), validate_validation_transform),
    Stage("matching_freeze", "o9_f_validation_matching_freeze.json", F_GATE, ("validation_transform",), validate_matching_freeze),
    Stage("era5_authorization", "o9_g_2025_era5_opening_receipt.json", G_AUTH_GATE, ("matching_freeze",), validate_era5_authorization),
    Stage("era5_reconstruction", "o9_g_2025_era5_reconstruction_complete.json", G_COMPLETE_GATE, ("era5_authorization",), validate_era5_completion),
    Stage("primary_confirmatory", "o9_h_primary_confirmatory_result.json", None, ("era5_reconstruction",), validate_primary),
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
    if h_sha != EXPECTED_H_COMMITTED_SHA256:
        errors.append("Phase H committed-file SHA256 changed from authoritative freeze")
    if k2_sha != EXPECTED_K2_COMMITTED_SHA256:
        errors.append("K2 committed-file SHA256 changed from authoritative freeze")
    if h.get("gate") != H_GATE:
        errors.append("Phase H gate mismatch")
    if k2.get("gate") != K2_GATE:
        errors.append("K2 gate mismatch")
    state = k2.get("validation_state") or {}
    if state.get("status") != "DEFERRED_PENDING_IMERG_FINAL_V08":
        errors.append("K2 deferred V08 state changed")
    if state.get("primary_confirmatory_test_run") is not False:
        errors.append("K2 says Primary already ran")
    if state.get("primary_outcome_opened") is not False:
        errors.append("K2 says Primary outcome already opened")
    if state.get("risk_engine_allowed") is not False:
        errors.append("K2 unexpectedly allows Risk Engine")
    primary = h.get("primary_hypothesis") or {}
    test = h.get("primary_validation_test") or {}
    if primary.get("metric") != PRIMARY_METRIC or primary.get("contrast") != PRIMARY_CONTRAST:
        errors.append("Phase H Primary metric/contrast mismatch")
    if test.get("test") != PRIMARY_TEST or float(test.get("alpha", -1)) != 0.05:
        errors.append("Phase H Primary test/alpha mismatch")
    manifest = (k2.get("source_integrity") or {}).get("sha256") or {}
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
    }


def evaluate_chain(repo_root: Path, evidence_dir: Path) -> dict[str, Any]:
    frozen = verify_frozen_protocol(repo_root)
    report: dict[str, Any] = {
        "schema_version": "1.1.0",
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
            "blockers": list(frozen["errors"]),
            "next_stage_key": None,
        })
        return report

    present = {s.key: (evidence_dir / s.filename).exists() for s in STAGES}
    first_missing_idx = next((i for i, s in enumerate(STAGES) if not present[s.key]), len(STAGES))
    later_present = [s.key for s in STAGES[first_missing_idx + 1 :] if present[s.key]] if first_missing_idx < len(STAGES) else []
    if later_present:
        report.update({
            "state": "BLOCKED_O9_SAFETY_ORDER_VIOLATION",
            "blockers": [f"later evidence exists before {STAGES[first_missing_idx].key}: {later_present}"],
            "next_stage_key": STAGES[first_missing_idx].key,
        })
        return report

    hashes: dict[str, str] = {}
    blockers: list[str] = []
    for stage in STAGES[:first_missing_idx]:
        path = evidence_dir / stage.filename
        try:
            obj = read_json(path)
        except Exception as exc:  # noqa: BLE001
            blockers.append(f"{stage.key}: unreadable evidence: {type(exc).__name__}: {exc}")
            continue
        if stage.gate is not None and obj.get("gate") != stage.gate:
            blockers.append(f"{stage.key}: gate must be {stage.gate}, got {obj.get('gate')!r}")
        blockers.extend(f"{stage.key}: {x}" for x in stage.validator(obj))
        requires = obj.get("requires_sha256") or {}
        for req_key in stage.requires:
            req = STAGE_BY_KEY[req_key]
            expected = hashes.get(req_key)
            if expected is None or requires.get(req.filename) != expected:
                blockers.append(f"{stage.key}: requires_sha256 mismatch for {req.filename}")
        digest = sha256_file(path)
        hashes[stage.key] = digest
        report["stages"].append({
            "key": stage.key,
            "filename": stage.filename,
            "sha256": digest,
            "gate": obj.get("gate"),
        })

    if blockers:
        report.update({
            "state": "BLOCKED_O9_SAFETY_INTEGRITY_VIOLATION",
            "blockers": blockers,
            "next_stage_key": STAGES[first_missing_idx].key if first_missing_idx < len(STAGES) else None,
        })
        return report

    if first_missing_idx < len(STAGES):
        next_stage = STAGES[first_missing_idx]
        report["next_stage_key"] = next_stage.key
        if next_stage.key == "availability":
            state = "WAIT_IMERG_FINAL_V08_NOT_AVAILABLE_OR_NOT_PROVEN"
            next_action = "PROVE_OFFICIAL_NASA_IMERG_FINAL_V08_AVAILABILITY"
        elif next_stage.key == "era5_authorization":
            state = "READY_TO_CREATE_2025_ERA5_RETRIEVAL_AUTHORIZATION"
            next_action = "RUN_O9_G_GUARDED_ERA5_AUTHORIZATION_GATE"
        elif next_stage.key == "era5_reconstruction":
            state = "READY_TO_RETRIEVE_2025_ERA5_WITH_GUARDED_RECEIPT"
            next_action = "RETRIEVE_AND_RECONSTRUCT_92_CASES_X_4_FROZEN_SNAPSHOTS"
            report["era5_2025_may_be_opened"] = True
        elif next_stage.key == "primary_confirmatory":
            state = "READY_FOR_SINGLE_FROZEN_PRIMARY_CONFIRMATORY_RUN"
            next_action = "RUN_FROZEN_Q850_T0H_CONFIRMATORY_TEST_EXACTLY_ONCE"
            report["era5_2025_may_be_opened"] = True
            report["confirmatory_run_may_execute"] = True
        else:
            state = "WAIT_O9_NEXT_REENTRY_STAGE"
            next_action = f"COMPLETE_{next_stage.key.upper()}"
        report.update({"state": state, "next_action": next_action, "blockers": []})
        return report

    # Entire chain including Primary exists and validated.
    primary = read_json(evidence_dir / STAGE_BY_KEY["primary_confirmatory"].filename)
    outcome = primary.get("primary_outcome")
    report.update({
        "state": f"O9_CONFIRMATORY_COMPLETE_{outcome}",
        "next_stage_key": None,
        "next_action": "NO_RETUNING;_PRESERVE_RESULT_AND_KEEP_PUBLIC_RISK_LEGAL_GATE_SEPARATE",
        "blockers": [],
        "era5_2025_may_be_opened": True,
        "confirmatory_run_may_execute": False,
        "confirmatory_run_count": int(primary.get("confirmatory_run_count", -1)),
        "primary_outcome": outcome,
    })
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=ROOT)
    ap.add_argument("--evidence-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    report = evaluate_chain(args.repo_root, args.evidence_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": report["state"],
        "next_action": report.get("next_action"),
        "era5_2025_may_be_opened": report["era5_2025_may_be_opened"],
        "confirmatory_run_may_execute": report["confirmatory_run_may_execute"],
        "risk_engine_allowed": False,
    }))
    return 2 if report["state"].startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
