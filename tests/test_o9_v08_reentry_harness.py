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


def payload_for(key: str, *, run_count: int = 1, outcome: str = "PASS") -> dict:
    common = {
        "short_name": "GPM_3IMERGHH",
        "imerg_final_version": "08",
        "risk_engine_allowed": False,
    }
    if key == "availability":
        return {**common, "gate": "PASS_O9_A_V08_OFFICIAL_FINAL_AVAILABILITY", "official_final_product": True, "metadata_result_count": 1}
    if key == "coverage":
        return {**common, "gate": "PASS_O9_C_V08_FULL_REQUIRED_COVERAGE", "development_region_day_count": 5943, "validation_region_day_count": 1218, "development_missing_slot_count": 0, "validation_missing_slot_count": 0, "all_required_slots_covered": True}
    if key == "development_rebuild":
        return {**common, "gate": "PASS_O9_D_V08_DEVELOPMENT_REBUILD_5943", "region_day_count": 5943, "split": "DEVELOPMENT", "candidate_membership_changed": False, "environment_variables_used": False}
    if key == "validation_rebuild":
        return {**common, "gate": "PASS_O9_D_V08_VALIDATION_REBUILD_1218", "region_day_count": 1218, "official_positive_region_day_count": 23, "split": "VALIDATION_2025", "environment_variables_used": False}
    if key == "transform_freeze":
        return {**common, "gate": "PASS_O9_E_V08_DEVELOPMENT_ONLY_TRANSFORM_FREEZE", "fit_population": "DEVELOPMENT_V08_ONLY", "development_fit_row_count": 5943, "validation_fit_row_count": 0, "matching_components": ["rain_pca_pc1", "rain_pca_pc2"]}
    if key == "validation_transform":
        return {**common, "gate": "PASS_O9_E_V08_VALIDATION_TRANSFORM_NO_REFIT", "validation_row_count": 1218, "pca_refit_on_2025": False, "standardization_refit_on_2025": False, "transform_source": "FROZEN_DEVELOPMENT_V08_TRANSFORM"}
    if key == "matching_freeze":
        return {**common, "gate": "PASS_O9_F_V08_2025_MATCHING_FREEZE", "positive_match_set_count": 23, "comparison_case_count": 69, "match_ratio": 3, "season_window_days": 60, "positive_event_buffer_days": 3, "same_primary_subdivision_required": True, "replacement_used": False, "environment_variables_used_for_selection": False, "pca_refit_on_2025": False}
    if key == "era5_opening":
        return {"gate": "PASS_O9_G_2025_ERA5_OPENED_AFTER_MATCHING_FREEZE", "validation_year": 2025, "opened_after_matching_freeze": True, "matching_membership_changed_by_era5": False, "risk_engine_allowed": False}
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
    (tmp_path / mod.STAGE_BY_KEY["era5_opening"].filename).write_text("{}\n", encoding="utf-8")
    report = mod.evaluate_chain(mod.ROOT, tmp_path)
    assert report["state"] == "BLOCKED_O9_SAFETY_ORDER_VIOLATION"
    assert report["era5_2025_may_be_opened"] is False


def test_availability_alone_opens_only_coverage_stage(tmp_path: Path):
    seed_through(tmp_path, "availability")
    report = mod.evaluate_chain(mod.ROOT, tmp_path)
    assert report["state"] == "WAIT_O9_NEXT_REENTRY_STAGE"
    assert report["next_stage_key"] == "coverage"
    assert report["era5_2025_may_be_opened"] is False


def test_matching_freeze_is_first_state_that_allows_era5_opening(tmp_path: Path):
    seed_through(tmp_path, "matching_freeze")
    report = mod.evaluate_chain(mod.ROOT, tmp_path)
    assert report["state"] == "READY_TO_OPEN_2025_ERA5_AFTER_MATCHING_FREEZE"
    assert report["era5_2025_may_be_opened"] is True
    assert report["confirmatory_run_may_execute"] is False
    assert report["risk_engine_allowed"] is False


def test_era5_receipt_allows_exactly_one_primary_run(tmp_path: Path):
    seed_through(tmp_path, "era5_opening")
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
