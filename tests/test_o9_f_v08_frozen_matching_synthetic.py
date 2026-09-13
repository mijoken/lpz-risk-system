from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lpz_risk.o9_frozen_matching import (
    COMPARISON_ROLE,
    EVENT_BUFFER_DAYS,
    MATCH_COMPONENTS,
    MATCH_RATIO,
    SEASON_WINDOW_DAYS,
    _eligible_pool_for_positive,
    circular_calendar_day_distance,
    frozen_match_2025,
    normalize_matching_frame,
)
from lpz_risk.o9_v08_transform import METRICS
from scripts import o9_v08_frozen_matching as prod


def _kernel_frame(rows: list[tuple[str, str, bool, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=[
            "date_utc",
            "primary_subdivision_code",
            "is_official_positive",
            "rain_pca_pc1",
            "rain_pca_pc2",
        ],
    )


def _validation_frame() -> pd.DataFrame:
    # 6 regions x 203 UTC days = exactly 1,218 frozen validation region-days.
    dates = pd.date_range("2025-01-01", periods=203, freq="D", tz="UTC")
    regions = [f"{101 + i:06d}" for i in range(6)]
    rows: list[dict] = []
    ordinal = 0
    for day_i, date in enumerate(dates):
        for region_i, region in enumerate(regions):
            phase = day_i * 0.071 + region_i * 0.19
            row = {
                "date_utc": date.strftime("%Y-%m-%d"),
                "primary_subdivision_code": region,
                "source_id": prod.SOURCE_ID,
                "imerg_final_version": "08",
                "is_official_positive": ordinal < 23,
                "rain_pca_pc1": float(np.sin(phase) + 0.03 * region_i),
                "rain_pca_pc2": float(np.cos(phase * 0.77) - 0.02 * region_i),
            }
            for j, metric in enumerate(METRICS):
                row[metric] = float(8.0 + j * 3.0 + 2.0 * np.sin(phase + j * 0.2))
            rows.append(row)
            ordinal += 1
    out = pd.DataFrame(rows)
    assert len(out) == 1218
    assert int(out["is_official_positive"].sum()) == 23
    return out


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False)


def _freeze_files(tmp_path: Path) -> tuple[Path, Path]:
    h = tmp_path / "phase2l_h_validation_protocol_freeze_20260911.json"
    k2 = tmp_path / "phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912.json"
    pop = {
        "match_ratio": "1_POSITIVE_TO_3_COMPARISONS",
        "same_primary_subdivision_required": True,
        "season_window_calendar_days": 60,
        "positive_event_exclusion_buffer_actual_days": 3,
        "rainfall_matching_space": "LOG1P_STANDARDIZED_FOUR_IMERG_3H_METRICS_PCA_PC1_PC2",
        "comparison_role": COMPARISON_ROLE,
        "environment_variables_used_for_matching": False,
    }
    _write_json(
        h,
        {
            "gate": prod.H_GATE,
            "population_design": pop,
            "risk_engine_allowed": False,
        },
    )
    _write_json(
        k2,
        {
            "gate": prod.K2_GATE,
            "upstream_protocol": {"frozen_matching": pop},
            "validation_state": {
                "status": "DEFERRED_PENDING_IMERG_FINAL_V08",
                "risk_engine_allowed": False,
            },
        },
    )
    return h, k2


def _evidence_files(tmp_path: Path, validation_csv: Path) -> tuple[Path, Path]:
    dev_e = tmp_path / "o9_e_development_v08_transform_freeze.json"
    val_e = tmp_path / "o9_e_validation_v08_transform_application.json"
    parameter_sha = "a" * 64
    _write_json(
        dev_e,
        {
            "gate": prod.DEV_E_GATE,
            "source_id": prod.SOURCE_ID,
            "short_name": prod.SHORT_NAME,
            "imerg_final_version": "08",
            "official_final_product": True,
            "fit_population": "DEVELOPMENT_V08_ONLY",
            "development_fit_row_count": 5943,
            "validation_fit_row_count": 0,
            "matching_components": list(MATCH_COMPONENTS),
            "transform_parameter_sha256": parameter_sha,
            "pca_refit_on_2025": False,
            "standardization_refit_on_2025": False,
            "validation_era5_environment_read": False,
            "primary_confirmatory_test_run": False,
            "risk_engine_allowed": False,
            "public_risk_release_allowed": False,
        },
    )
    _write_json(
        val_e,
        {
            "gate": prod.VAL_E_GATE,
            "source_id": prod.SOURCE_ID,
            "short_name": prod.SHORT_NAME,
            "imerg_final_version": "08",
            "official_final_product": True,
            "validation_row_count": 1218,
            "official_positive_region_day_count": 23,
            "transform_source": "FROZEN_DEVELOPMENT_V08_TRANSFORM",
            "matching_components": list(MATCH_COMPONENTS),
            "transform_parameter_sha256": parameter_sha,
            "validation_transformed_csv_sha256": prod.sha256_file(validation_csv),
            "pca_refit_on_2025": False,
            "standardization_refit_on_2025": False,
            "validation_statistics_used_to_modify_transform": False,
            "validation_era5_environment_read": False,
            "matching_performed": False,
            "primary_confirmatory_test_run": False,
            "risk_engine_allowed": False,
            "public_risk_release_allowed": False,
            "requires_sha256": {dev_e.name: prod.sha256_file(dev_e)},
        },
    )
    return dev_e, val_e


def _args(tmp_path: Path, val_csv: Path, dev_e: Path, val_e: Path, h: Path, k2: Path) -> argparse.Namespace:
    return argparse.Namespace(
        validation_transformed_csv=val_csv,
        validation_transform_evidence=val_e,
        development_transform_evidence=dev_e,
        output_dir=tmp_path / "o9f",
        evidence_output=tmp_path / "o9_f_v08_frozen_2025_matching.json",
        protocol_freeze=h,
        k2_freeze=k2,
    )


def test_frozen_constants_are_exactly_prespecified():
    assert MATCH_RATIO == 3
    assert SEASON_WINDOW_DAYS == 60
    assert EVENT_BUFFER_DAYS == 3
    assert tuple(MATCH_COMPONENTS) == ("rain_pca_pc1", "rain_pca_pc2")
    assert COMPARISON_ROLE == "RAINFALL_MATCHED_COMPARISON_NOT_NEGATIVE_LABEL"


def test_circular_calendar_distance_preserves_year_boundary_and_feb29():
    assert circular_calendar_day_distance(pd.Timestamp("2025-12-31"), pd.Timestamp("2025-01-01")) == 1
    assert circular_calendar_day_distance(pd.Timestamp("2024-02-29"), pd.Timestamp("2025-03-01")) == 1
    assert circular_calendar_day_distance(pd.Timestamp("2025-01-01"), pd.Timestamp("2025-03-01")) == 60


def test_eligibility_is_same_region_60_inclusive_61_excluded_and_actual_3day_buffer():
    frame = _kernel_frame(
        [
            ("2025-01-01", "000101", True, 0.0, 0.0),
            ("2024-12-31", "000101", False, 0.1, 0.1),  # actual +/−1 => excluded
            ("2025-01-04", "000101", False, 0.1, 0.1),  # actual +3 => excluded
            ("2025-01-05", "000101", False, 0.1, 0.1),  # +4 => eligible
            ("2025-03-01", "000101", False, 0.2, 0.2),  # circular distance 60 => eligible
            ("2025-03-02", "000101", False, 0.01, 0.01), # 61 => excluded despite best PC
            ("2025-01-05", "000102", False, 0.0, 0.0),  # wrong region => excluded
        ]
    )
    norm = normalize_matching_frame(frame)
    p = norm.loc[norm["is_official_positive"]].iloc[0]
    controls = norm.loc[~norm["is_official_positive"]]
    dates = {"000101": [p["_o9f_date_ts"]]}
    pool = _eligible_pool_for_positive(p, controls, dates)
    assert set(pool["date_utc"]) == {"2025-01-05", "2025-03-01"}
    assert set(pool["primary_subdivision_code"].astype(str)) == {"000101"}


def test_buffer_excludes_candidate_near_any_positive_in_same_region():
    frame = _kernel_frame(
        [
            ("2025-01-01", "000101", True, 0.0, 0.0),
            ("2025-01-20", "000101", True, 0.3, 0.3),
            ("2025-01-05", "000101", False, 0.1, 0.1),
            ("2025-01-18", "000101", False, 0.1, 0.1), # near second positive
            ("2025-01-24", "000101", False, 0.1, 0.1),
        ]
    )
    norm = normalize_matching_frame(frame)
    positives = norm.loc[norm["is_official_positive"]]
    p = positives.iloc[0]
    controls = norm.loc[~norm["is_official_positive"]]
    dates = {"000101": list(positives["_o9f_date_ts"])}
    pool = _eligible_pool_for_positive(p, controls, dates)
    assert "2025-01-18" not in set(pool["date_utc"])
    assert {"2025-01-05", "2025-01-24"}.issubset(set(pool["date_utc"]))


def test_distance_formula_and_tie_break_are_exact_phase2l_d_semantics():
    frame = _kernel_frame(
        [
            ("2025-06-15", "000101", True, 0.0, 0.0),
            ("2025-06-25", "000101", False, 1.0, 1.0),
            ("2025-06-05", "000101", False, 1.0, 1.0),
            ("2025-06-20", "000101", False, 1.0, 1.0),
            ("2025-06-19", "000101", False, 2.0, 0.0),
        ]
    )
    out = frozen_match_2025(frame)["matched_pairs"]
    # sqrt(mean([1^2,1^2])) = 1.  The +5 day candidate wins first, then equal
    # distance/equal 10-day candidates are ordered by date.
    assert out.iloc[0]["comparison_date_utc"] == "2025-06-20"
    assert out.iloc[1]["comparison_date_utc"] == "2025-06-05"
    assert out.iloc[2]["comparison_date_utc"] == "2025-06-25"
    assert out.iloc[0]["rainfall_match_distance_pc12"] == pytest.approx(1.0)


def test_scarce_positive_first_and_global_no_replacement():
    frame = _kernel_frame(
        [
            ("2025-01-01", "000101", True, 0.0, 0.0),
            ("2025-02-20", "000101", True, 0.0, 0.0),
            ("2025-01-05", "000101", False, 0.0, 0.0),
            ("2025-01-06", "000101", False, 0.0, 0.0),
            ("2025-01-07", "000101", False, 0.0, 0.0),
            ("2025-03-03", "000101", False, 5.0, 5.0),
            ("2025-03-04", "000101", False, 5.0, 5.0),
            ("2025-03-05", "000101", False, 5.0, 5.0),
        ]
    )
    result = frozen_match_2025(frame)
    pairs = result["matched_pairs"]
    jan = pairs.loc[pairs["positive_date_utc"] == "2025-01-01"]
    feb = pairs.loc[pairs["positive_date_utc"] == "2025-02-20"]
    assert set(jan["comparison_date_utc"]) == {"2025-01-05", "2025-01-06", "2025-01-07"}
    assert set(feb["comparison_date_utc"]) == {"2025-03-03", "2025-03-04", "2025-03-05"}
    assert not pairs[["comparison_date_utc", "primary_subdivision_code"]].duplicated().any()


def test_matching_is_input_order_invariant_and_environment_columns_are_inert():
    base = _validation_frame()
    a = frozen_match_2025(base)["matched_pairs"]
    changed = base.sample(frac=1.0, random_state=34848).reset_index(drop=True)
    changed["q850_mean_kgkg"] = np.random.default_rng(7).normal(size=len(changed))
    changed["future_primary_outcome"] = np.random.default_rng(8).normal(size=len(changed))
    b = frozen_match_2025(changed)["matched_pairs"]
    pd.testing.assert_frame_equal(a, b, check_exact=True)


def test_positive_rows_are_never_controls_and_23_yields_69_unique_comparisons():
    base = _validation_frame()
    result = frozen_match_2025(base)
    pairs = result["matched_pairs"]
    positive_keys = set(map(tuple, base.loc[base["is_official_positive"], list(prod.KEY)].astype(str).to_numpy()))
    comparison_keys = set(map(tuple, pairs[["comparison_date_utc", "primary_subdivision_code"]].astype(str).to_numpy()))
    assert len(result["positive_population"]) == 23
    assert len(pairs) == 69
    assert len(result["comparison_population"]) == 69
    assert len(comparison_keys) == 69
    assert positive_keys.isdisjoint(comparison_keys)


def test_production_wrapper_has_no_matching_tuning_cli_options():
    options = {
        option
        for action in prod.build_parser()._actions
        for option in getattr(action, "option_strings", [])
    }
    assert "--match-ratio" not in options
    assert "--season-window-days" not in options
    assert "--event-buffer-days" not in options
    assert "--matching-components" not in options


def test_protocol_drift_is_rejected(tmp_path: Path):
    h, k2 = _freeze_files(tmp_path)
    obj = json.loads(k2.read_text(encoding="utf-8"))
    obj["upstream_protocol"]["frozen_matching"]["season_window_calendar_days"] = 59
    _write_json(k2, obj)
    with pytest.raises(ValueError, match="K2 frozen matching contract mismatch"):
        prod.verify_frozen_protocol(h, k2)


def test_production_run_freezes_23_to_69_without_opening_era5(tmp_path: Path):
    val_csv = tmp_path / "validation_transformed.csv"
    _write_csv(val_csv, _validation_frame())
    dev_e, val_e = _evidence_files(tmp_path, val_csv)
    h, k2 = _freeze_files(tmp_path)
    args = _args(tmp_path, val_csv, dev_e, val_e, h, k2)
    assert prod.run(args) == 0

    evidence = json.loads(args.evidence_output.read_text(encoding="utf-8"))
    assert evidence["gate"] == prod.O9_F_GATE
    assert evidence["official_positive_region_day_count"] == 23
    assert evidence["matched_comparison_region_day_count"] == 69
    assert evidence["unique_comparison_region_day_count"] == 69
    assert evidence["replacement_used"] is False
    assert evidence["same_primary_subdivision_required"] is True
    assert evidence["season_window_circular_calendar_days"] == 60
    assert evidence["same_region_positive_event_buffer_actual_days"] == 3
    assert evidence["matching_components"] == list(MATCH_COMPONENTS)
    assert evidence["validation_balance_gate_applied"] is False
    assert evidence["environment_variables_used_for_selection"] is False
    assert evidence["validation_era5_environment_read"] is False
    assert evidence["primary_confirmatory_test_run"] is False
    assert evidence["risk_engine_allowed"] is False
    assert evidence["public_risk_release_allowed"] is False
    assert evidence["validation_transformed_csv_sha256"] == prod.sha256_file(val_csv)
    assert evidence["requires_sha256"][dev_e.name] == prod.sha256_file(dev_e)
    assert evidence["requires_sha256"][val_e.name] == prod.sha256_file(val_e)
    assert evidence["outputs"]["matched_pairs"]["rows"] == 69


def test_structurally_valid_wrong_validation_csv_is_rejected_by_sha(tmp_path: Path):
    val_csv = tmp_path / "validation_transformed.csv"
    frame = _validation_frame()
    _write_csv(val_csv, frame)
    dev_e, val_e = _evidence_files(tmp_path, val_csv)
    h, k2 = _freeze_files(tmp_path)

    frame.loc[100, "rain_pca_pc1"] += 0.001
    _write_csv(val_csv, frame)
    args = _args(tmp_path, val_csv, dev_e, val_e, h, k2)
    with pytest.raises(ValueError, match="csv_hash"):
        prod.run(args)


def test_o9_f_evidence_is_immutable(tmp_path: Path):
    val_csv = tmp_path / "validation_transformed.csv"
    _write_csv(val_csv, _validation_frame())
    dev_e, val_e = _evidence_files(tmp_path, val_csv)
    h, k2 = _freeze_files(tmp_path)
    args = _args(tmp_path, val_csv, dev_e, val_e, h, k2)
    prod.run(args)
    with pytest.raises(FileExistsError, match="immutable"):
        prod.run(args)
