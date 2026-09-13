from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import o9_v08_reentry_harness as mod


def write_stage(root: Path, stage: mod.Stage, payload: dict, hashes: dict[str, str]) -> str:
    requires = {}
    for req_key in stage.requires:
        req = mod.STAGE_BY_KEY[req_key]
        requires[req.filename] = hashes[req_key]
    payload = dict(payload)
    payload["requires_sha256"] = requires
    path = root / stage.filename
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    hashes[stage.key] = digest
    return digest


def common() -> dict:
    return {
        "short_name": "GPM_3IMERGHH",
        "imerg_final_version": "08",
        "official_final_product": True,
        "risk_engine_allowed": False,
    }


def payload_for(key: str, *, run_count: int = 1, outcome: str = "PASS") -> dict:
    c = common()
    if key == "availability":
        return {**c, "phase": "O9-A-v08-official-final-availability", "gate": "PASS_O9_A_V08_OFFICIAL_FINAL_AVAILABILITY", "metadata_result_count": 1}
    if key == "coverage":
        return {**c, "phase": "O9-C-v08-required-coverage", "gate": "PASS_O9_C_V08_FULL_REQUIRED_COVERAGE", "development_region_day_count": 5943, "validation_region_day_count": 1218, "development_missing_slot_count": 0, "validation_missing_slot_count": 0, "all_required_slots_covered": True}
    if key == "development_rebuild":
        return {**c, "source_id": "NASA_IMERG_FINAL_V08", "phase": "O9-D-V08-rainfall-rebuild-complete", "gate": "PASS_O9_D_V08_DEVELOPMENT_REBUILD_5943", "region_day_count": 5943, "split": "DEVELOPMENT", "candidate_membership_changed": False, "environment_variables_used": False, "validation_era5_environment_read": False}
    if key == "validation_rebuild":
        return {**c, "source_id": "NASA_IMERG_FINAL_V08", "phase": "O9-D-V08-rainfall-rebuild-complete", "gate": "PASS_O9_D_V08_VALIDATION_REBUILD_1218", "region_day_count": 1218, "official_positive_region_day_count": 23, "split": "VALIDATION_2025", "environment_variables_used": False, "validation_era5_environment_read": False}
    if key == "transform_freeze":
        return {**c, "source_id": "NASA_IMERG_FINAL_V08", "phase": "O9-E-V08-development-only-transform-freeze", "gate": "PASS_O9_E_V08_DEVELOPMENT_ONLY_TRANSFORM_FREEZE", "fit_population": "DEVELOPMENT_V08_ONLY", "development_fit_row_count": 5943, "validation_fit_row_count": 0, "matching_components": ["rain_pca_pc1", "rain_pca_pc2"], "pca_refit_on_2025": False, "standardization_refit_on_2025": False, "validation_era5_environment_read": False}
    if key == "validation_transform":
        return {**c, "source_id": "NASA_IMERG_FINAL_V08", "phase": "O9-E-V08-validation-transform-application", "gate": "PASS_O9_E_V08_VALIDATION_TRANSFORM_NO_REFIT", "validation_row_count": 1218, "official_positive_region_day_count": 23, "pca_refit_on_2025": False, "standardization_refit_on_2025": False, "validation_statistics_used_to_modify_transform": False, "transform_source": "FROZEN_DEVELOPMENT_V08_TRANSFORM", "validation_era5_environment_read": False}
    if key == "matching_freeze":
        return {
            **c,
            "source_id": "NASA_IMERG_FINAL_V08",
            "phase": "O9-F-V08-frozen-2025-rainfall-matching",
            "gate": mod.F_GATE,
            "validation_region_day_count": 1218,
            "official_positive_region_day_count": 23,
            "matched_comparison_region_day_count": 69,
            "unique_comparison_region_day_count": 69,
            "final_matched_population_region_day_count": 92,
            "match_ratio": "1_POSITIVE_TO_3_COMPARISONS",
            "same_primary_subdivision_required": True,
            "season_window_circular_calendar_days": 60,
            "same_region_positive_event_buffer_actual_days": 3,
            "replacement_used": False,
            "environment_variables_used_for_selection": False,
            "pca_refit_on_2025": False,
            "standardization_refit_on_2025": False,
            "time_anchor_policy": "IMERG_3H_P95_MAX_WINDOW_START",
            "time_anchor_start_column": "imerg_3h_p95_window_start_utc",
            "time_anchor_preserved_for_all_final_cases": True,
            "validation_era5_environment_read": False,
            "outputs": {"final_matched_population": {"rows": 92, "sha256": "a" * 64}},
        }
    if key == "era5_authorization":
        return {
            "phase": "O9-G-guarded-2025-ERA5-retrieval-authorization",
            "gate": mod.G_AUTH_GATE,
            "validation_year": 2025,
            "opened_after_matching_freeze": True,
            "era5_retrieval_authorized": True,
            "era5_retrieval_completed": False,
            "matching_membership_changed_by_era5": False,
            "matched_case_count": 92,
            "positive_case_count": 23,
            "comparison_case_count": 69,
            "snapshot_mapping_count": 368,
            "time_anchor_policy": "IMERG_3H_P95_MAX_WINDOW_START",
            "future_source_time_allowed": False,
            "network_access_performed": False,
            "era5_environment_values_read": False,
            "primary_confirmatory_test_run": False,
            "confirmatory_run_may_execute": False,
            "risk_engine_allowed": False,
            "public_risk_release_allowed": False,
        }
    if key == "era5_reconstruction":
        return {
            "phase": "O9-G-2025-ERA5-reconstruction-complete",
            "gate": mod.G_COMPLETE_GATE,
            "validation_year": 2025,
            "era5_retrieval_authorized": True,
            "era5_retrieval_completed": True,
            "matched_case_count": 92,
            "snapshot_mapping_count": 368,
            "matching_membership_changed_by_era5": False,
            "primary_confirmatory_test_run": False,
            "risk_engine_allowed": False,
            "public_risk_release_allowed": False,
        }
    if key == "primary_confirmatory":
        return {"confirmatory_run_count": run_count, "metric": "q850_mean_kgkg", "contrast": "t+0h", "test": "EXACT_ONE_SIDED_SIGN_TEST_ON_POSITIVE_DATE_UTC_CLUSTER_MEANS", "alpha": 0.05, "retuned_after_result": False, "primary_outcome": outcome, "risk_engine_allowed": False}
    raise AssertionError(key)


def seed_through(root: Path, through_key: str, *, run_count: int = 1, outcome: str = "PASS") -> None:
    hashes: dict[str, str] = {}
    for stage in mod.STAGES:
        write_stage(root, stage, payload_for(stage.key, run_count=run_count, outcome=outcome), hashes)
        if stage.key == through_key:
            return
    raise AssertionError(through_key)


def test_current_empty_evidence_is_safe_wait(tmp_path: Path):
    report = mod.evaluate_chain(mod.ROOT, tmp_path)
    assert report["state"] == "WAIT_IMERG_FINAL_V08_NOT_AVAILABLE_OR_NOT_PROVEN"
    assert report["next_stage_key"] == "availability"
    assert report["era5_2025_may_be_opened"] is False
    assert report["confirmatory_run_may_execute"] is False
    assert report["risk_engine_allowed"] is False


def test_out_of_order_later_evidence_is_blocked(tmp_path: Path):
    (tmp_path / mod.STAGE_BY_KEY["era5_authorization"].filename).write_text("{}\n", encoding="utf-8")
    report = mod.evaluate_chain(mod.ROOT, tmp_path)
    assert report["state"] == "BLOCKED_O9_SAFETY_ORDER_VIOLATION"
    assert report["era5_2025_may_be_opened"] is False


def test_matching_freeze_only_allows_creation_of_guarded_authorization(tmp_path: Path):
    seed_through(tmp_path, "matching_freeze")
    report = mod.evaluate_chain(mod.ROOT, tmp_path)
    assert report["state"] == "READY_TO_CREATE_2025_ERA5_RETRIEVAL_AUTHORIZATION"
    assert report["next_stage_key"] == "era5_authorization"
    assert report["era5_2025_may_be_opened"] is False
    assert report["confirmatory_run_may_execute"] is False


def test_authorization_receipt_allows_retrieval_but_not_primary(tmp_path: Path):
    seed_through(tmp_path, "era5_authorization")
    report = mod.evaluate_chain(mod.ROOT, tmp_path)
    assert report["state"] == "READY_TO_RETRIEVE_2025_ERA5_WITH_GUARDED_RECEIPT"
    assert report["era5_2025_may_be_opened"] is True
    assert report["confirmatory_run_may_execute"] is False
    assert report["risk_engine_allowed"] is False


def test_reconstruction_completion_is_required_before_primary(tmp_path: Path):
    seed_through(tmp_path, "era5_reconstruction")
    report = mod.evaluate_chain(mod.ROOT, tmp_path)
    assert report["state"] == "READY_FOR_SINGLE_FROZEN_PRIMARY_CONFIRMATORY_RUN"
    assert report["confirmatory_run_may_execute"] is True
    assert report["risk_engine_allowed"] is False


def test_second_confirmatory_run_is_rejected(tmp_path: Path):
    seed_through(tmp_path, "primary_confirmatory", run_count=2)
    report = mod.evaluate_chain(mod.ROOT, tmp_path)
    assert report["state"] == "BLOCKED_O9_SAFETY_INTEGRITY_VIOLATION"
    assert any("confirmatory_run_count" in x for x in report["blockers"])
    assert report["risk_engine_allowed"] is False


def test_single_confirmatory_result_completes_chain_but_does_not_unlock_risk(tmp_path: Path):
    seed_through(tmp_path, "primary_confirmatory", run_count=1, outcome="PASS")
    report = mod.evaluate_chain(mod.ROOT, tmp_path)
    assert report["state"] == "O9_CONFIRMATORY_COMPLETE_PASS"
    assert report["confirmatory_run_count"] == 1
    assert report["risk_engine_allowed"] is False
    assert report["public_risk_release_allowed"] is False
