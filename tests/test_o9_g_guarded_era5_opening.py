from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

import pandas as pd
import pytest

from lpz_risk.o9_era5_opening import (
    COMPARISON_ROLE,
    EXPECTED_SNAPSHOT_COUNT,
    POSITIVE_ROLE,
    build_era5_request_manifest,
    validate_final_matched_population,
)
from scripts import o9_g_guarded_era5_opening as prod
from scripts import o9_v08_reentry_harness as harness


def _write_json(path: Path, obj: dict) -> str:
    path.write_text(json.dumps(obj, sort_keys=True) + "\n", encoding="utf-8")
    return prod.sha256_file(path)


def _population() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2025-01-01", periods=92, freq="D", tz="UTC")
    n = 0
    for set_i in range(23):
        match_set_id = f"O9F-{set_i:02d}"
        for rank in range(4):
            date = dates[n]
            n += 1
            role = POSITIVE_ROLE if rank == 0 else COMPARISON_ROLE
            start = date + pd.Timedelta(hours=12, minutes=30)
            rows.append(
                {
                    "date_utc": date.strftime("%Y-%m-%d"),
                    "primary_subdivision_code": "020010",
                    "case_role": role,
                    "match_set_id": match_set_id,
                    "match_rank": rank,
                    "is_official_positive": rank == 0,
                    "source_id": prod.SOURCE_ID,
                    "imerg_final_version": "08",
                    "imerg_3h_p95_window_start_utc": start.isoformat().replace("+00:00", "Z"),
                    "imerg_3h_p95_window_end_utc": (start + pd.Timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
                }
            )
    return pd.DataFrame(rows)


def _common() -> dict:
    return {
        "short_name": "GPM_3IMERGHH",
        "imerg_final_version": "08",
        "official_final_product": True,
        "risk_engine_allowed": False,
    }


def _seed_a_to_f(tmp_path: Path, population_csv: Path) -> Path:
    e = tmp_path / "evidence"
    e.mkdir()
    hashes: dict[str, str] = {}

    def write(name: str, payload: dict, requires: tuple[str, ...] = ()) -> None:
        payload = dict(payload)
        payload["requires_sha256"] = {r: hashes[r] for r in requires}
        hashes[name] = _write_json(e / name, payload)

    write(
        prod.A_FILE,
        {**_common(), "phase": "O9-A-v08-official-final-availability", "gate": prod.EXPECTED_GATES[prod.A_FILE], "metadata_result_count": 3},
    )
    write(
        prod.C_FILE,
        {
            **_common(),
            "phase": "O9-C-v08-required-coverage",
            "gate": prod.EXPECTED_GATES[prod.C_FILE],
            "development_region_day_count": 5943,
            "validation_region_day_count": 1218,
            "development_missing_slot_count": 0,
            "validation_missing_slot_count": 0,
            "all_required_slots_covered": True,
            "validation_era5_environment_read": False,
        },
        (prod.A_FILE,),
    )
    write(
        prod.D_DEV_FILE,
        {
            **_common(),
            "source_id": prod.SOURCE_ID,
            "phase": "O9-D-V08-rainfall-rebuild-complete",
            "gate": prod.EXPECTED_GATES[prod.D_DEV_FILE],
            "split": "DEVELOPMENT",
            "region_day_count": 5943,
            "candidate_membership_changed": False,
            "environment_variables_used": False,
            "validation_era5_environment_read": False,
            "matching_performed": False,
            "pca_fit_performed": False,
            "primary_confirmatory_test_run": False,
        },
        (prod.C_FILE,),
    )
    write(
        prod.D_VAL_FILE,
        {
            **_common(),
            "source_id": prod.SOURCE_ID,
            "phase": "O9-D-V08-rainfall-rebuild-complete",
            "gate": prod.EXPECTED_GATES[prod.D_VAL_FILE],
            "split": "VALIDATION_2025",
            "region_day_count": 1218,
            "official_positive_region_day_count": 23,
            "environment_variables_used": False,
            "validation_era5_environment_read": False,
            "matching_performed": False,
            "pca_fit_performed": False,
            "primary_confirmatory_test_run": False,
        },
        (prod.C_FILE, prod.D_DEV_FILE),
    )
    write(
        prod.E_DEV_FILE,
        {
            **_common(),
            "source_id": prod.SOURCE_ID,
            "phase": "O9-E-V08-development-only-transform-freeze",
            "gate": prod.EXPECTED_GATES[prod.E_DEV_FILE],
            "fit_population": "DEVELOPMENT_V08_ONLY",
            "development_fit_row_count": 5943,
            "validation_fit_row_count": 0,
            "matching_components": ["rain_pca_pc1", "rain_pca_pc2"],
            "pca_refit_on_2025": False,
            "standardization_refit_on_2025": False,
            "validation_era5_environment_read": False,
            "matching_performed": False,
            "primary_confirmatory_test_run": False,
        },
        (prod.D_DEV_FILE, prod.D_VAL_FILE),
    )
    write(
        prod.E_VAL_FILE,
        {
            **_common(),
            "source_id": prod.SOURCE_ID,
            "phase": "O9-E-V08-validation-transform-application",
            "gate": prod.EXPECTED_GATES[prod.E_VAL_FILE],
            "validation_row_count": 1218,
            "official_positive_region_day_count": 23,
            "transform_source": "FROZEN_DEVELOPMENT_V08_TRANSFORM",
            "matching_components": ["rain_pca_pc1", "rain_pca_pc2"],
            "pca_refit_on_2025": False,
            "standardization_refit_on_2025": False,
            "validation_statistics_used_to_modify_transform": False,
            "validation_era5_environment_read": False,
            "matching_performed": False,
            "primary_confirmatory_test_run": False,
        },
        (prod.E_DEV_FILE, prod.D_VAL_FILE),
    )

    frozen = harness.verify_frozen_protocol(harness.ROOT)
    assert frozen["state"] == "PASS"
    f = {
        **_common(),
        "source_id": prod.SOURCE_ID,
        "phase": "O9-F-V08-frozen-2025-rainfall-matching",
        "gate": prod.F_GATE,
        "validation_region_day_count": 1218,
        "official_positive_region_day_count": 23,
        "matched_comparison_region_day_count": 69,
        "unique_comparison_region_day_count": 69,
        "final_matched_population_region_day_count": 92,
        "match_ratio": "1_POSITIVE_TO_3_COMPARISONS",
        "replacement_used": False,
        "same_primary_subdivision_required": True,
        "season_window_circular_calendar_days": 60,
        "same_region_positive_event_buffer_actual_days": 3,
        "matching_components": ["rain_pca_pc1", "rain_pca_pc2"],
        "comparison_population_role": COMPARISON_ROLE,
        "time_anchor_policy": "IMERG_3H_P95_MAX_WINDOW_START",
        "time_anchor_start_column": "imerg_3h_p95_window_start_utc",
        "time_anchor_preserved_for_all_final_cases": True,
        "environment_variables_used_for_selection": False,
        "validation_era5_environment_read": False,
        "primary_confirmatory_test_run": False,
        "pca_refit_on_2025": False,
        "standardization_refit_on_2025": False,
        "outputs": {
            "final_matched_population": {
                "path": str(population_csv),
                "sha256": prod.sha256_file(population_csv),
                "rows": 92,
            }
        },
        "requires_sha256": {
            prod.E_DEV_FILE: hashes[prod.E_DEV_FILE],
            prod.E_VAL_FILE: hashes[prod.E_VAL_FILE],
            harness.H_FREEZE.name: frozen["h_sha256"],
            harness.K2_FREEZE.name: frozen["k2_sha256"],
        },
    }
    hashes[prod.F_FILE] = _write_json(e / prod.F_FILE, f)
    return e


def _args(tmp_path: Path, evidence_dir: Path, population_csv: Path) -> argparse.Namespace:
    return argparse.Namespace(
        repo_root=harness.ROOT,
        evidence_dir=evidence_dir,
        final_matched_population=population_csv,
        era5_config=harness.ROOT / "config/historical_environment_era5.json",
        geometry_registry=harness.ROOT / "research/phase2/primary_subdivision_geometry_registry_20260909.json",
        manifest_output=tmp_path / "o9_g_era5_request_manifest.json",
        receipt_output=tmp_path / "o9_g_2025_era5_opening_receipt.json",
    )


def test_complete_real_style_a_to_f_authorizes_92x4_without_network(tmp_path: Path):
    population_csv = tmp_path / "o9_f_final_matched_population.csv"
    _population().to_csv(population_csv, index=False)
    evidence = _seed_a_to_f(tmp_path, population_csv)
    args = _args(tmp_path, evidence, population_csv)
    assert prod.run(args) == 0

    receipt = json.loads(args.receipt_output.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest_output.read_text(encoding="utf-8"))
    assert receipt["gate"] == prod.PASS_GATE
    assert receipt["matched_case_count"] == 92
    assert receipt["snapshot_mapping_count"] == EXPECTED_SNAPSHOT_COUNT == 368
    assert receipt["network_access_performed"] is False
    assert receipt["era5_environment_values_read"] is False
    assert receipt["era5_retrieval_completed"] is False
    assert receipt["confirmatory_run_may_execute"] is False
    assert receipt["risk_engine_allowed"] is False
    assert manifest["snapshot_mapping_count"] == 368
    assert len(manifest["snapshot_mappings"]) == 368
    for m in manifest["snapshot_mappings"]:
        requested = pd.Timestamp(m["requested_snapshot_time_utc"])
        source = pd.Timestamp(m["era5_source_time_utc"])
        assert source <= requested
        assert 0 <= int(m["era5_source_lag_minutes"]) <= 59


def test_gate_has_no_network_retrieval_imports():
    source = (harness.ROOT / "scripts/o9_g_guarded_era5_opening.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots.isdisjoint({"cdsapi", "earthaccess", "requests", "urllib"})


def test_missing_predecessor_denies_authorization(tmp_path: Path):
    population_csv = tmp_path / "o9_f_final_matched_population.csv"
    _population().to_csv(population_csv, index=False)
    evidence = _seed_a_to_f(tmp_path, population_csv)
    (evidence / prod.D_VAL_FILE).unlink()
    with pytest.raises(FileNotFoundError, match="complete real O9-A..F evidence"):
        prod.run(_args(tmp_path, evidence, population_csv))


def test_tampered_predecessor_hash_denies_authorization(tmp_path: Path):
    population_csv = tmp_path / "o9_f_final_matched_population.csv"
    _population().to_csv(population_csv, index=False)
    evidence = _seed_a_to_f(tmp_path, population_csv)
    c = json.loads((evidence / prod.C_FILE).read_text(encoding="utf-8"))
    c["tampered_after_freeze"] = True
    _write_json(evidence / prod.C_FILE, c)
    with pytest.raises(ValueError, match="hash-linked"):
        prod.run(_args(tmp_path, evidence, population_csv))


def test_wrong_f_output_sha_denies_authorization(tmp_path: Path):
    population_csv = tmp_path / "o9_f_final_matched_population.csv"
    _population().to_csv(population_csv, index=False)
    evidence = _seed_a_to_f(tmp_path, population_csv)
    fpath = evidence / prod.F_FILE
    f = json.loads(fpath.read_text(encoding="utf-8"))
    f["outputs"]["final_matched_population"]["sha256"] = "0" * 64
    _write_json(fpath, f)
    with pytest.raises(ValueError, match="SHA256"):
        prod.run(_args(tmp_path, evidence, population_csv))


@pytest.mark.parametrize("mutation", ["91_rows", "duplicate_key", "wrong_roles", "missing_anchor"])
def test_population_integrity_failures_are_rejected(mutation: str):
    df = _population()
    if mutation == "91_rows":
        df = df.iloc[:-1].copy()
    elif mutation == "duplicate_key":
        df.loc[1, ["date_utc", "primary_subdivision_code"]] = df.loc[0, ["date_utc", "primary_subdivision_code"]].values
    elif mutation == "wrong_roles":
        df.loc[0, "case_role"] = COMPARISON_ROLE
        df.loc[0, "is_official_positive"] = False
    elif mutation == "missing_anchor":
        df.loc[0, "imerg_3h_p95_window_start_utc"] = None
    with pytest.raises((ValueError, TypeError)):
        validate_final_matched_population(df)


def test_manifest_is_exactly_four_frozen_offsets_per_case():
    frame = _population()
    era5 = json.loads((harness.ROOT / "config/historical_environment_era5.json").read_text(encoding="utf-8"))
    geometry = json.loads((harness.ROOT / "research/phase2/primary_subdivision_geometry_registry_20260909.json").read_text(encoding="utf-8"))
    manifest = build_era5_request_manifest(frame, era5_config=era5, geometry_registry=geometry)
    assert manifest["snapshot_mapping_count"] == 368
    counts = pd.DataFrame(manifest["snapshot_mappings"]).groupby(["match_set_id", "match_rank"]).size()
    assert set(counts.tolist()) == {4}
    assert set(m["snapshot_offset_hours"] for m in manifest["snapshot_mappings"]) == {-12, -6, -3, 0}
