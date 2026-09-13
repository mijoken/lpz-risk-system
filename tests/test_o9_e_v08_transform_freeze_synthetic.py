from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lpz_risk.o9_v08_transform import (
    MATCHING_COMPONENTS,
    METRICS,
    PCS,
    apply_frozen_transform,
    fit_development_transform,
)
from scripts import o9_v08_transform_freeze as prod
from scripts.phase2l_d_rainfall_matched_comparison import build_pca as frozen_phase2l_d_build_pca


def _rain_values(n: int, *, offset: float = 0.0) -> np.ndarray:
    i = np.arange(n, dtype=float)
    t = np.sin(i * 0.013 + offset)
    u = np.cos(i * 0.037 - offset * 0.3)
    # log1p rainfall lies exactly in a two-latent-factor family.  This makes the
    # synthetic fixture strongly satisfy the frozen PC1+PC2 >=95% contract while
    # keeping all four metric variances non-zero and eigenvalues non-degenerate.
    xlog = np.column_stack([
        2.20 + 0.60 * t + 0.10 * u,
        2.50 + 0.82 * t - 0.14 * u,
        2.35 + 0.67 * t + 0.08 * u,
        2.42 + 0.72 * t + 0.02 * u,
    ])
    return np.expm1(xlog)


def _dev_frame(n: int = 5943) -> pd.DataFrame:
    i = np.arange(n)
    dates = pd.Timestamp("2023-01-01") + pd.to_timedelta(i // 20, unit="D")
    frame = pd.DataFrame({
        "date_utc": dates.strftime("%Y-%m-%d"),
        "primary_subdivision_code": pd.Series((i % 20) + 1).astype(str).str.zfill(6),
        "source_id": "NASA_IMERG_FINAL_V08",
        "imerg_final_version": "08",
    })
    values = _rain_values(n)
    for j, metric in enumerate(METRICS):
        frame[metric] = values[:, j]
    return frame


def _validation_frame(n: int = 1218, positives: int = 23, *, extreme: bool = False) -> pd.DataFrame:
    i = np.arange(n)
    dates = pd.Timestamp("2025-01-01") + pd.to_timedelta(i // 5, unit="D")
    frame = pd.DataFrame({
        "date_utc": dates.strftime("%Y-%m-%d"),
        "primary_subdivision_code": pd.Series((i % 5) + 101).astype(str).str.zfill(6),
        "source_id": "NASA_IMERG_FINAL_V08",
        "imerg_final_version": "08",
        "is_official_positive": i < positives,
    })
    values = _rain_values(n, offset=1.1)
    if extreme:
        # Deliberately move Validation far away.  A correct O9-E implementation
        # changes Validation PC scores but cannot alter Development parameters.
        values = (values + 1.0) * 1.0e4
    for j, metric in enumerate(METRICS):
        frame[metric] = values[:, j]
    return frame


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False)


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _d_evidence_pair(tmp_path: Path, dev_csv: Path, val_csv: Path) -> tuple[Path, Path]:
    dev_e = tmp_path / "o9_d_development_v08_rebuild.json"
    val_e = tmp_path / "o9_d_validation_v08_rebuild.json"
    dev_obj = {
        "gate": prod.DEV_D_GATE,
        "split": "DEVELOPMENT",
        "source_id": prod.SOURCE_ID,
        "short_name": prod.SHORT_NAME,
        "imerg_final_version": "08",
        "official_final_product": True,
        "region_day_count": 5943,
        "candidate_membership_changed": False,
        "environment_variables_used": False,
        "validation_era5_environment_read": False,
        "matching_performed": False,
        "pca_fit_performed": False,
        "primary_confirmatory_test_run": False,
        "risk_engine_allowed": False,
        "output_csv_sha256": prod.sha256_file(dev_csv),
        "requires_sha256": {},
    }
    _write_json(dev_e, dev_obj)
    val_obj = {
        "gate": prod.VAL_D_GATE,
        "split": "VALIDATION_2025",
        "source_id": prod.SOURCE_ID,
        "short_name": prod.SHORT_NAME,
        "imerg_final_version": "08",
        "official_final_product": True,
        "region_day_count": 1218,
        "official_positive_region_day_count": 23,
        "candidate_membership_changed": False,
        "environment_variables_used": False,
        "validation_era5_environment_read": False,
        "matching_performed": False,
        "pca_fit_performed": False,
        "primary_confirmatory_test_run": False,
        "risk_engine_allowed": False,
        "output_csv_sha256": prod.sha256_file(val_csv),
        "requires_sha256": {dev_e.name: prod.sha256_file(dev_e)},
    }
    _write_json(val_e, val_obj)
    return dev_e, val_e


def _fit_args(tmp_path: Path, dev_csv: Path, dev_e: Path, val_e: Path) -> argparse.Namespace:
    return argparse.Namespace(
        development_csv=dev_csv,
        development_evidence=dev_e,
        validation_evidence=val_e,
        output_csv=tmp_path / "dev_transformed.csv",
        evidence_output=tmp_path / "o9_e_development_v08_transform_freeze.json",
    )


def _apply_args(tmp_path: Path, val_csv: Path, val_e: Path, transform_e: Path) -> argparse.Namespace:
    return argparse.Namespace(
        validation_csv=val_csv,
        validation_evidence=val_e,
        transform_evidence=transform_e,
        output_csv=tmp_path / "validation_transformed.csv",
        evidence_output=tmp_path / "o9_e_validation_v08_transform_application.json",
    )


def test_pure_transform_is_equivalent_to_frozen_phase2l_d_math():
    frame = _dev_frame(800)
    old_out, old_meta = frozen_phase2l_d_build_pca(frame.copy())
    new_out, new_meta = fit_development_transform(frame.copy())

    assert np.allclose(old_out[list(PCS)], new_out[list(PCS)], rtol=1e-12, atol=1e-12)
    assert old_meta["metric_order"] == new_meta["metric_order"]
    assert old_meta["matching_components"] == new_meta["matching_components"]
    for metric in METRICS:
        assert old_meta["log_mean"][metric] == pytest.approx(new_meta["log_mean"][metric], abs=1e-14)
        assert old_meta["log_std_ddof0"][metric] == pytest.approx(new_meta["log_std_ddof0"][metric], abs=1e-14)
    for pc in ("pc1", "pc2", "pc3", "pc4"):
        for metric in METRICS:
            assert old_meta["loadings"][pc][metric] == pytest.approx(new_meta["loadings"][pc][metric], abs=1e-12)


def test_exact_frozen_sign_orientation_and_pc12_contract():
    _, meta = fit_development_transform(_dev_frame(1200))
    pc1_sum = sum(meta["loadings"]["pc1"].values())
    pc2_max = meta["loadings"]["pc2"]["imerg_3h_max_max_mm"]
    assert pc1_sum >= 0.0
    assert pc2_max >= 0.0
    assert meta["matching_components"] == list(MATCHING_COMPONENTS)
    assert meta["matching_components_cumulative_variance"] >= 0.95


def test_fit_is_row_order_invariant_to_numerical_tolerance():
    frame = _dev_frame(1400)
    _, a = fit_development_transform(frame)
    shuffled = frame.sample(frac=1.0, random_state=34848).reset_index(drop=True)
    _, b = fit_development_transform(shuffled)
    for metric in METRICS:
        assert a["log_mean"][metric] == pytest.approx(b["log_mean"][metric], abs=2e-14)
        assert a["log_std_ddof0"][metric] == pytest.approx(b["log_std_ddof0"][metric], abs=2e-14)
    for pc in ("pc1", "pc2", "pc3", "pc4"):
        for metric in METRICS:
            assert a["loadings"][pc][metric] == pytest.approx(b["loadings"][pc][metric], abs=2e-12)


def test_frozen_application_is_deterministic_and_manual_formula_matches():
    dev = _dev_frame(1000)
    val = _validation_frame(100, positives=23, extreme=True)
    _, meta = fit_development_transform(dev)
    a = apply_frozen_transform(val, meta)
    b = apply_frozen_transform(val, meta)
    assert np.array_equal(a[list(PCS)].to_numpy(), b[list(PCS)].to_numpy())

    mu = np.array([meta["log_mean"][m] for m in METRICS])
    sd = np.array([meta["log_std_ddof0"][m] for m in METRICS])
    load = np.array([[meta["loadings"][f"pc{i}"][m] for i in range(1, 5)] for m in METRICS])
    expected = ((np.log1p(val[list(METRICS)].to_numpy()) - mu) / sd) @ load
    assert np.allclose(a[list(PCS)].to_numpy(), expected, rtol=1e-13, atol=1e-13)


def test_extreme_validation_values_cannot_change_development_fit():
    dev = _dev_frame(1600)
    _, before = fit_development_transform(dev)
    validation = _validation_frame(300, positives=23, extreme=True)
    _ = apply_frozen_transform(validation, before)
    _, after = fit_development_transform(dev)
    assert prod.parameter_sha256(before) == prod.parameter_sha256(after)


def test_negative_metric_is_rejected():
    frame = _dev_frame(50)
    frame.loc[0, METRICS[0]] = -0.1
    with pytest.raises(ValueError, match="non-negative"):
        fit_development_transform(frame)


def test_development_population_guard_rejects_5942(tmp_path: Path):
    path = tmp_path / "bad_dev.csv"
    _write_csv(path, _dev_frame(5942))
    with pytest.raises(ValueError, match="5943"):
        prod.read_development_csv(path)


def test_validation_population_and_positive_guards(tmp_path: Path):
    short_path = tmp_path / "short_val.csv"
    _write_csv(short_path, _validation_frame(1217, positives=23))
    with pytest.raises(ValueError, match="1218"):
        prod.read_validation_csv(short_path)

    positives_path = tmp_path / "wrong_pos.csv"
    _write_csv(positives_path, _validation_frame(1218, positives=22))
    with pytest.raises(ValueError, match="23"):
        prod.read_validation_csv(positives_path)


def test_non_v08_source_is_rejected(tmp_path: Path):
    frame = _dev_frame()
    frame.loc[0, "source_id"] = "NASA_IMERG_FINAL_V07"
    path = tmp_path / "v07_mix.csv"
    _write_csv(path, frame)
    with pytest.raises(ValueError, match="non-V08"):
        prod.read_development_csv(path)


def test_production_fit_freezes_only_development_and_hash_links_both_d_evidences(tmp_path: Path):
    dev_csv = tmp_path / "dev.csv"
    val_csv = tmp_path / "val.csv"
    _write_csv(dev_csv, _dev_frame())
    _write_csv(val_csv, _validation_frame(extreme=True))
    dev_e, val_e = _d_evidence_pair(tmp_path, dev_csv, val_csv)
    args = _fit_args(tmp_path, dev_csv, dev_e, val_e)

    assert prod.fit_development(args) == 0
    evidence = json.loads(args.evidence_output.read_text(encoding="utf-8"))
    assert evidence["gate"] == prod.DEV_E_GATE
    assert evidence["fit_population"] == "DEVELOPMENT_V08_ONLY"
    assert evidence["development_fit_row_count"] == 5943
    assert evidence["validation_fit_row_count"] == 0
    assert evidence["validation_rainfall_csv_read_during_fit"] is False
    assert evidence["requires_sha256"][dev_e.name] == prod.sha256_file(dev_e)
    assert evidence["requires_sha256"][val_e.name] == prod.sha256_file(val_e)
    assert evidence["matching_components"] == list(MATCHING_COMPONENTS)
    assert evidence["matching_components_cumulative_variance"] >= 0.95
    assert evidence["validation_era5_environment_read"] is False
    assert evidence["risk_engine_allowed"] is False
    assert len(pd.read_csv(args.output_csv)) == 5943


def test_production_validation_application_is_transform_only_and_preserves_membership(tmp_path: Path):
    dev_csv = tmp_path / "dev.csv"
    val_csv = tmp_path / "val.csv"
    _write_csv(dev_csv, _dev_frame())
    _write_csv(val_csv, _validation_frame(extreme=True))
    dev_e, val_e = _d_evidence_pair(tmp_path, dev_csv, val_csv)
    fit_args = _fit_args(tmp_path, dev_csv, dev_e, val_e)
    prod.fit_development(fit_args)

    apply_args = _apply_args(tmp_path, val_csv, val_e, fit_args.evidence_output)
    assert prod.apply_validation(apply_args) == 0
    evidence = json.loads(apply_args.evidence_output.read_text(encoding="utf-8"))
    out = pd.read_csv(apply_args.output_csv)
    assert evidence["gate"] == prod.VAL_E_GATE
    assert evidence["validation_row_count"] == 1218
    assert evidence["official_positive_region_day_count"] == 23
    assert evidence["transform_source"] == "FROZEN_DEVELOPMENT_V08_TRANSFORM"
    assert evidence["pca_refit_on_2025"] is False
    assert evidence["standardization_refit_on_2025"] is False
    assert evidence["validation_statistics_used_to_modify_transform"] is False
    assert evidence["validation_era5_environment_read"] is False
    assert evidence["risk_engine_allowed"] is False
    assert len(out) == 1218
    assert int(out["is_official_positive"].astype(bool).sum()) == 23
    assert not out[list(PCS)].isna().any().any()

    transform = json.loads(fit_args.evidence_output.read_text(encoding="utf-8"))
    manual = apply_frozen_transform(prod.read_validation_csv(val_csv), transform)
    assert np.allclose(out[list(PCS)], manual[list(PCS)], rtol=1e-12, atol=1e-12)


def test_immutable_evidence_refuses_second_scientific_fit_and_application(tmp_path: Path):
    dev_csv = tmp_path / "dev.csv"
    val_csv = tmp_path / "val.csv"
    _write_csv(dev_csv, _dev_frame())
    _write_csv(val_csv, _validation_frame())
    dev_e, val_e = _d_evidence_pair(tmp_path, dev_csv, val_csv)
    fit_args = _fit_args(tmp_path, dev_csv, dev_e, val_e)
    prod.fit_development(fit_args)
    with pytest.raises(FileExistsError, match="immutable"):
        prod.fit_development(fit_args)

    apply_args = _apply_args(tmp_path, val_csv, val_e, fit_args.evidence_output)
    prod.apply_validation(apply_args)
    with pytest.raises(FileExistsError, match="immutable"):
        prod.apply_validation(apply_args)
