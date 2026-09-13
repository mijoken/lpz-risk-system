#!/usr/bin/env python3
"""O9-G — fail-closed authorization gate for 2025 ERA5 retrieval.

The gate can produce an ERA5 request manifest and an immutable authorization
receipt only after the complete real Final-V08 O9-A..F evidence chain is present,
valid, hash-linked, and bound to the exact frozen 92-case O9-F population.

This script is intentionally network-free: it does not import cdsapi, does not
contact CDS, does not read any ERA5 environmental value, and does not run the
frozen Primary.  A later retriever must validate the receipt before network access.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from lpz_risk.o9_era5_opening import (
    COMPARISON_ROLE,
    EXPECTED_CASE_COUNT,
    EXPECTED_COMPARISON_COUNT,
    EXPECTED_POSITIVE_COUNT,
    EXPECTED_SNAPSHOT_COUNT,
    IMERG_VERSION,
    POSITIVE_ROLE,
    SHORT_NAME,
    SOURCE_ID,
    SNAPSHOT_OFFSETS_HOURS,
    TIME_ANCHOR_POLICY,
    TIME_ANCHOR_START_COLUMN,
    build_era5_request_manifest,
    read_json,
    sha256_file,
    validate_final_matched_population,
)
from scripts import o9_v08_reentry_harness as harness

PASS_GATE = "PASS_O9_G_2025_ERA5_RETRIEVAL_AUTHORIZED_AFTER_MATCHING_FREEZE"
F_GATE = "PASS_O9_F_V08_FROZEN_2025_MATCHING_23_POSITIVES_69_COMPARISONS"

A_FILE = "o9_a_v08_availability.json"
C_FILE = "o9_c_v08_required_coverage.json"
D_DEV_FILE = "o9_d_development_v08_rebuild.json"
D_VAL_FILE = "o9_d_validation_v08_rebuild.json"
E_DEV_FILE = "o9_e_development_v08_transform_freeze.json"
E_VAL_FILE = "o9_e_validation_v08_transform_application.json"
F_FILE = "o9_f_validation_matching_freeze.json"

EXPECTED_GATES = {
    A_FILE: "PASS_O9_A_V08_OFFICIAL_FINAL_AVAILABILITY",
    C_FILE: "PASS_O9_C_V08_FULL_REQUIRED_COVERAGE",
    D_DEV_FILE: "PASS_O9_D_V08_DEVELOPMENT_REBUILD_5943",
    D_VAL_FILE: "PASS_O9_D_V08_VALIDATION_REBUILD_1218",
    E_DEV_FILE: "PASS_O9_E_V08_DEVELOPMENT_ONLY_TRANSFORM_FREEZE",
    E_VAL_FILE: "PASS_O9_E_V08_VALIDATION_TRANSFORM_NO_REFIT",
    F_FILE: F_GATE,
}

PREDECESSORS = {
    A_FILE: (),
    C_FILE: (A_FILE,),
    D_DEV_FILE: (C_FILE,),
    D_VAL_FILE: (C_FILE, D_DEV_FILE),
    E_DEV_FILE: (D_DEV_FILE, D_VAL_FILE),
    E_VAL_FILE: (E_DEV_FILE, D_VAL_FILE),
    F_FILE: (E_DEV_FILE, E_VAL_FILE),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _common_v08_errors(obj: dict[str, Any], *, require_source_id: bool) -> list[str]:
    e: list[str] = []
    if str(obj.get("short_name")) != SHORT_NAME:
        e.append("short_name must be GPM_3IMERGHH")
    if str(obj.get("imerg_final_version")).replace(".0", "").zfill(2) != IMERG_VERSION:
        e.append("imerg_final_version must be 08")
    if obj.get("official_final_product") is not True:
        e.append("official_final_product must be true")
    if require_source_id and obj.get("source_id") != SOURCE_ID:
        e.append("source_id must be NASA_IMERG_FINAL_V08")
    if obj.get("risk_engine_allowed") is not False:
        e.append("risk_engine_allowed must remain false")
    phase = str(obj.get("phase", "")).upper()
    if "SYNTHETIC" in phase or obj.get("synthetic") is True:
        e.append("synthetic evidence cannot authorize real 2025 ERA5")
    return e


def _validate_a(obj: dict[str, Any]) -> list[str]:
    e = _common_v08_errors(obj, require_source_id=False)
    if int(obj.get("metadata_result_count", 0)) < 1:
        e.append("O9-A metadata_result_count must be >=1")
    return e


def _validate_c(obj: dict[str, Any]) -> list[str]:
    e = _common_v08_errors(obj, require_source_id=False)
    expected = {
        "development_region_day_count": 5943,
        "validation_region_day_count": 1218,
        "development_missing_slot_count": 0,
        "validation_missing_slot_count": 0,
    }
    for key, value in expected.items():
        if int(obj.get(key, -1)) != value:
            e.append(f"O9-C {key} must be {value}")
    if obj.get("all_required_slots_covered") is not True:
        e.append("O9-C all_required_slots_covered must be true")
    if obj.get("validation_era5_environment_read") is not False:
        e.append("O9-C must not have read 2025 ERA5")
    return e


def _validate_d_dev(obj: dict[str, Any]) -> list[str]:
    e = _common_v08_errors(obj, require_source_id=True)
    checks = {
        "split": obj.get("split") == "DEVELOPMENT",
        "region_day_count": int(obj.get("region_day_count", -1)) == 5943,
        "candidate_membership_changed": obj.get("candidate_membership_changed") is False,
        "environment_variables_used": obj.get("environment_variables_used") is False,
        "validation_era5_environment_read": obj.get("validation_era5_environment_read") is False,
        "matching_performed": obj.get("matching_performed") is False,
        "pca_fit_performed": obj.get("pca_fit_performed") is False,
        "primary_confirmatory_test_run": obj.get("primary_confirmatory_test_run") is False,
    }
    e.extend([f"O9-D Development failed {k}" for k, ok in checks.items() if not ok])
    return e


def _validate_d_val(obj: dict[str, Any]) -> list[str]:
    e = _common_v08_errors(obj, require_source_id=True)
    checks = {
        "split": obj.get("split") == "VALIDATION_2025",
        "region_day_count": int(obj.get("region_day_count", -1)) == 1218,
        "official_positive_region_day_count": int(obj.get("official_positive_region_day_count", -1)) == 23,
        "environment_variables_used": obj.get("environment_variables_used") is False,
        "validation_era5_environment_read": obj.get("validation_era5_environment_read") is False,
        "matching_performed": obj.get("matching_performed") is False,
        "pca_fit_performed": obj.get("pca_fit_performed") is False,
        "primary_confirmatory_test_run": obj.get("primary_confirmatory_test_run") is False,
    }
    e.extend([f"O9-D Validation failed {k}" for k, ok in checks.items() if not ok])
    return e


def _validate_e_dev(obj: dict[str, Any]) -> list[str]:
    e = _common_v08_errors(obj, require_source_id=True)
    checks = {
        "fit_population": obj.get("fit_population") == "DEVELOPMENT_V08_ONLY",
        "development_fit_row_count": int(obj.get("development_fit_row_count", -1)) == 5943,
        "validation_fit_row_count": int(obj.get("validation_fit_row_count", -1)) == 0,
        "matching_components": obj.get("matching_components") == ["rain_pca_pc1", "rain_pca_pc2"],
        "pca_refit_on_2025": obj.get("pca_refit_on_2025") is False,
        "standardization_refit_on_2025": obj.get("standardization_refit_on_2025") is False,
        "validation_era5_environment_read": obj.get("validation_era5_environment_read") is False,
        "matching_performed": obj.get("matching_performed") is False,
        "primary_confirmatory_test_run": obj.get("primary_confirmatory_test_run") is False,
    }
    e.extend([f"O9-E Development failed {k}" for k, ok in checks.items() if not ok])
    return e


def _validate_e_val(obj: dict[str, Any]) -> list[str]:
    e = _common_v08_errors(obj, require_source_id=True)
    checks = {
        "validation_row_count": int(obj.get("validation_row_count", -1)) == 1218,
        "official_positive_region_day_count": int(obj.get("official_positive_region_day_count", -1)) == 23,
        "transform_source": obj.get("transform_source") == "FROZEN_DEVELOPMENT_V08_TRANSFORM",
        "matching_components": obj.get("matching_components") == ["rain_pca_pc1", "rain_pca_pc2"],
        "pca_refit_on_2025": obj.get("pca_refit_on_2025") is False,
        "standardization_refit_on_2025": obj.get("standardization_refit_on_2025") is False,
        "validation_statistics_used_to_modify_transform": obj.get("validation_statistics_used_to_modify_transform") is False,
        "validation_era5_environment_read": obj.get("validation_era5_environment_read") is False,
        "matching_performed": obj.get("matching_performed") is False,
        "primary_confirmatory_test_run": obj.get("primary_confirmatory_test_run") is False,
    }
    e.extend([f"O9-E Validation failed {k}" for k, ok in checks.items() if not ok])
    return e


def _validate_f(obj: dict[str, Any]) -> list[str]:
    e = _common_v08_errors(obj, require_source_id=True)
    checks = {
        "validation_region_day_count": int(obj.get("validation_region_day_count", -1)) == 1218,
        "official_positive_region_day_count": int(obj.get("official_positive_region_day_count", -1)) == EXPECTED_POSITIVE_COUNT,
        "matched_comparison_region_day_count": int(obj.get("matched_comparison_region_day_count", -1)) == EXPECTED_COMPARISON_COUNT,
        "unique_comparison_region_day_count": int(obj.get("unique_comparison_region_day_count", -1)) == EXPECTED_COMPARISON_COUNT,
        "final_matched_population_region_day_count": int(obj.get("final_matched_population_region_day_count", -1)) == EXPECTED_CASE_COUNT,
        "match_ratio": obj.get("match_ratio") == "1_POSITIVE_TO_3_COMPARISONS",
        "replacement_used": obj.get("replacement_used") is False,
        "same_primary_subdivision_required": obj.get("same_primary_subdivision_required") is True,
        "season_window": int(obj.get("season_window_circular_calendar_days", -1)) == 60,
        "event_buffer": int(obj.get("same_region_positive_event_buffer_actual_days", -1)) == 3,
        "matching_components": obj.get("matching_components") == ["rain_pca_pc1", "rain_pca_pc2"],
        "comparison_role": obj.get("comparison_population_role") == COMPARISON_ROLE,
        "time_anchor_policy": obj.get("time_anchor_policy") == TIME_ANCHOR_POLICY,
        "time_anchor_start_column": obj.get("time_anchor_start_column") == TIME_ANCHOR_START_COLUMN,
        "time_anchor_preserved": obj.get("time_anchor_preserved_for_all_final_cases") is True,
        "environment_unused": obj.get("environment_variables_used_for_selection") is False,
        "validation_era5_environment_read": obj.get("validation_era5_environment_read") is False,
        "primary_unrun": obj.get("primary_confirmatory_test_run") is False,
        "pca_refit_on_2025": obj.get("pca_refit_on_2025") is False,
        "standardization_refit_on_2025": obj.get("standardization_refit_on_2025") is False,
    }
    e.extend([f"O9-F failed {k}" for k, ok in checks.items() if not ok])
    outputs = obj.get("outputs") or {}
    meta = outputs.get("final_matched_population") or {}
    if int(meta.get("rows", -1)) != EXPECTED_CASE_COUNT or not isinstance(meta.get("sha256"), str):
        e.append("O9-F final_matched_population output metadata invalid")
    return e


VALIDATORS: dict[str, Callable[[dict[str, Any]], list[str]]] = {
    A_FILE: _validate_a,
    C_FILE: _validate_c,
    D_DEV_FILE: _validate_d_dev,
    D_VAL_FILE: _validate_d_val,
    E_DEV_FILE: _validate_e_dev,
    E_VAL_FILE: _validate_e_val,
    F_FILE: _validate_f,
}


def verify_real_a_to_f_chain(evidence_dir: Path, repo_root: Path) -> dict[str, Any]:
    frozen = harness.verify_frozen_protocol(repo_root)
    if frozen.get("state") != "PASS":
        raise ValueError(f"Frozen H/K2 protocol integrity failed: {frozen.get('errors')}")

    paths = {name: evidence_dir / name for name in EXPECTED_GATES}
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"O9-G requires complete real O9-A..F evidence; missing: {missing}")

    objects: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    for name in EXPECTED_GATES:
        obj = read_json(paths[name])
        if obj.get("gate") != EXPECTED_GATES[name]:
            raise ValueError(f"{name} gate mismatch: {obj.get('gate')!r}")
        errors = VALIDATORS[name](obj)
        if errors:
            raise ValueError(f"{name} failed O9-G validation: {errors}")
        objects[name] = obj
        hashes[name] = sha256_file(paths[name])

    for name, predecessors in PREDECESSORS.items():
        if not predecessors:
            continue
        requires = objects[name].get("requires_sha256") or {}
        for predecessor in predecessors:
            if requires.get(predecessor) != hashes[predecessor]:
                raise ValueError(
                    f"{name} is not hash-linked to exact predecessor {predecessor}"
                )

    # O9-F also binds directly to the immutable H/K2 freezes.
    f_requires = objects[F_FILE].get("requires_sha256") or {}
    h_name = harness.H_FREEZE.name
    k2_name = harness.K2_FREEZE.name
    if f_requires.get(h_name) != frozen["h_sha256"]:
        raise ValueError("O9-F is not bound to the exact authoritative Phase H freeze")
    if f_requires.get(k2_name) != frozen["k2_sha256"]:
        raise ValueError("O9-F is not bound to the exact authoritative K2 freeze")

    return {
        "frozen_protocol": frozen,
        "paths": paths,
        "objects": objects,
        "hashes": hashes,
    }


def verify_final_population_binding(
    final_population_path: Path,
    f_evidence: dict[str, Any],
) -> tuple[pd.DataFrame, str]:
    actual_sha = sha256_file(final_population_path)
    meta = ((f_evidence.get("outputs") or {}).get("final_matched_population") or {})
    if meta.get("sha256") != actual_sha:
        raise ValueError("O9-G final population SHA256 does not match immutable O9-F evidence")
    if int(meta.get("rows", -1)) != EXPECTED_CASE_COUNT:
        raise ValueError("O9-G O9-F output metadata does not say 92 final cases")
    frame = pd.read_csv(final_population_path, dtype={"primary_subdivision_code": "string"})
    frame = validate_final_matched_population(frame)
    return frame, actual_sha


def run(args: argparse.Namespace) -> int:
    if args.receipt_output.exists():
        raise FileExistsError(f"immutable O9-G receipt already exists: {args.receipt_output}")
    if args.manifest_output.exists():
        raise FileExistsError(f"immutable O9-G manifest already exists: {args.manifest_output}")

    chain = verify_real_a_to_f_chain(args.evidence_dir, args.repo_root)
    f_obj = chain["objects"][F_FILE]
    frame, population_sha = verify_final_population_binding(args.final_matched_population, f_obj)

    era5_config = read_json(args.era5_config)
    geometry = read_json(args.geometry_registry)
    manifest = build_era5_request_manifest(
        frame,
        era5_config=era5_config,
        geometry_registry=geometry,
    )
    manifest.update(
        {
            "generated_at_utc": utc_now(),
            "authorization_gate": PASS_GATE,
            "o9_f_evidence_sha256": chain["hashes"][F_FILE],
            "final_matched_population_sha256": population_sha,
            "era5_config_sha256": sha256_file(args.era5_config),
            "geometry_registry_sha256": sha256_file(args.geometry_registry),
        }
    )
    atomic_write_json(args.manifest_output, manifest)
    manifest_sha = sha256_file(args.manifest_output)

    requires = dict(chain["hashes"])
    requires[harness.H_FREEZE.name] = chain["frozen_protocol"]["h_sha256"]
    requires[harness.K2_FREEZE.name] = chain["frozen_protocol"]["k2_sha256"]
    receipt = {
        "schema_version": "1.0.0",
        "phase": "O9-G-guarded-2025-ERA5-retrieval-authorization",
        "gate": PASS_GATE,
        "generated_at_utc": utc_now(),
        "validation_year": 2025,
        "opened_after_matching_freeze": True,
        "era5_retrieval_authorized": True,
        "era5_retrieval_completed": False,
        "matching_membership_changed_by_era5": False,
        "matched_case_count": EXPECTED_CASE_COUNT,
        "positive_case_count": EXPECTED_POSITIVE_COUNT,
        "comparison_case_count": EXPECTED_COMPARISON_COUNT,
        "snapshot_offsets_hours": list(SNAPSHOT_OFFSETS_HOURS),
        "snapshot_mapping_count": EXPECTED_SNAPSHOT_COUNT,
        "time_anchor_policy": TIME_ANCHOR_POLICY,
        "time_anchor_start_column": TIME_ANCHOR_START_COLUMN,
        "future_source_time_allowed": False,
        "final_matched_population_sha256": population_sha,
        "request_manifest": str(args.manifest_output),
        "request_manifest_sha256": manifest_sha,
        "era5_config_sha256": sha256_file(args.era5_config),
        "geometry_registry_sha256": sha256_file(args.geometry_registry),
        "requires_sha256": requires,
        "network_access_performed": False,
        "era5_environment_values_read": False,
        "primary_confirmatory_test_run": False,
        "confirmatory_run_may_execute": False,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
        "next_required_stage": "O9_G_ERA5_RETRIEVAL_AND_RECONSTRUCTION_COMPLETE_RECEIPT",
    }
    atomic_write_json(args.receipt_output, receipt)
    print(json.dumps({
        "gate": PASS_GATE,
        "matched_cases": EXPECTED_CASE_COUNT,
        "snapshot_mappings": EXPECTED_SNAPSHOT_COUNT,
        "network_access_performed": False,
        "primary_confirmatory_test_run": False,
        "risk_engine_allowed": False,
    }))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=harness.ROOT)
    ap.add_argument("--evidence-dir", required=True, type=Path)
    ap.add_argument("--final-matched-population", required=True, type=Path)
    ap.add_argument("--era5-config", type=Path, default=Path("config/historical_environment_era5.json"))
    ap.add_argument(
        "--geometry-registry",
        type=Path,
        default=Path("research/phase2/primary_subdivision_geometry_registry_20260909.json"),
    )
    ap.add_argument("--manifest-output", required=True, type=Path)
    ap.add_argument("--receipt-output", required=True, type=Path)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    # Resolve repo-relative defaults without changing explicit absolute paths.
    if not args.era5_config.is_absolute():
        args.era5_config = args.repo_root / args.era5_config
    if not args.geometry_registry.is_absolute():
        args.geometry_registry = args.repo_root / args.geometry_registry
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
