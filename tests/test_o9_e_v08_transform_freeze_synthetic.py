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
    v = np.sin(i * 0.071 + 0.4)
    w = np.cos(i * 0.097 - 0.2)
    # Two dominant latent factors preserve the frozen PC1+PC2 >=95% contract.
    # Tiny independent v/w contributions make the fixture full-rank so PC3/PC4
    # are also mathematically identifiable instead of an arbitrary null-space basis.
    xlog = np.column_stack([
        2.20 + 0.60 * t + 0.10 * u + 0.010 * v + 0.004 * w,
        2.50 + 0.82 * t - 0.14 * u - 0.006 * v + 0.012 * w,
        2.35 + 0.67 * t + 0.08 * u + 0.014 * v - 0.005 * w,
        2.42 + 0.72 * t + 0.02 * u - 0.009 * v - 0.011 * w,
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
    _write_json(dev_e, {
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
    })
    _write_json(val_e, {
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
    })
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


def test_math_exactly_reproduces_frozen_phase2l_d_algorithm():
    frame = _dev_frame(900)
    old_out, old = frozen_phase2l_d_build_pca(frame.copy())
    new_out, new = fit_development_transform(frame.copy())
    assert np.allclose(old_out[list(PCS)], new_out[list(PCS)], rtol=1e-12, atol=1e-12)
    assert old["metric_order"] == new["metric_order"]
    assert old["matching_components"] == new["matching_components"]
    for m in METRICS:
        assert old["log_mean"][m] == pytest.approx(new["log_mean"][m], abs=1e-14)
        assert old["log_std_ddof0"][m] == pytest.approx(new["log_std_ddof0"][m], abs=1e-14)
    for pc in ("pc1", "pc2", "pc3", "pc4"):
        for m in METRICS:
            assert old["loadings"][pc][m] == pytest.approx(new["loadings"][pc][m], abs=1e-12)


def test_sign_rules_and_pc12_variance_contract():
    _, meta = fit_development_transform(_dev_frame(1600))
    assert sum(meta["loadings"]["pc1"].values()) >= 0.0
    assert meta["loadings"]["pc2"]["imerg_3h_max_max_mm"] >= 0.0
    assert meta["matching_components"] == list(MATCHING_COMPONENTS)
    assert meta["matching_components_cumulative_variance"] >= 0.95


def test_full_rank_fit_is_row_order_invariant_to_roundoff():
    frame = _dev_frame(1800)
    _, a = fit_development_transform(frame)
    _, b = fit_development_transform(frame.sample(frac=1.0, random_state=34848).reset_index(drop=True))
    for m in METRICS:
        assert a["log_mean"][m] == pytest.approx(b["log_mean"][m], abs=2e-14)
        assert a["log_std_ddof0"][m] == pytest.approx(b["log_std_ddof0"][m], abs=2e-14)
    for pc in ("pc1", "pc2", "pc3", "pc4"):
        for m in METRICS:
            assert a["loadings"][pc][m] == pytest.approx(b["loadings"][pc][m], abs=2e-11)


def test_frozen_application_is_deterministic_and_matches_manual_matrix_formula():
    _, meta = fit_development_transform(_dev_frame(1000))
    val = _validation_frame(100, extreme=True)
    a = apply_frozen_transform(val, meta)
    b = apply_frozen_transform(val, meta)
    assert np.array_equal(a[list(PCS)].to_numpy(), b[list(PCS)].to_numpy())
    mu = np.array([meta["log_mean"][m] for m in METRICS])
    sd = np.array([meta["log_std_ddof0"][m] for m in METRICS])
    load = np.array([[meta["loadings"][f"pc{i}"][m] for i in range(1, 5)] for m in METRICS])
    expected = ((np.log1p(val[list(METRICS)].to_numpy()) - mu) / sd) @ load
    assert np.allclose(a[list(PCS)], expected, rtol=1e-13, atol=1e-13)


def test_extreme_validation_cannot_change_development_parameters():
    dev = _dev_frame(1600)
    _, before = fit_development_transform(dev)
    _ = apply_frozen_transform(_validation_frame(300, extreme=True), before)
    _, after = fit_development_transform(dev)
    assert prod.parameter_sha256(before) == prod.parameter_sha256(after)


def test_invalid_metric_and_wrong_v08_identity_are_rejected(tmp_path: Path):
    bad = _dev_frame(50)
    bad.loc[0, METRICS[0]] = -0.1
    with pytest.raises(ValueError, match="non-negative"):
        fit_development_transform(bad)

    mixed = _dev_frame()
    mixed.loc[0, "source_id"] = "NASA_IMERG_FINAL_V07"
    p = tmp_path / "mixed.csv"
    _write_csv(p, mixed)
    with pytest.raises(ValueError, match="non-V08"):
        prod.read_development_csv(p)


def test_frozen_population_guards(tmp_path: Path):
    p = tmp_path / "dev5942.csv"
    _write_csv(p, _dev_frame(5942))
    with pytest.raises(ValueError, match="5943"):
        prod.read_development_csv(p)

    p = tmp_path / "val1217.csv"
    _write_csv(p, _validation_frame(1217))
    with pytest.raises(ValueError, match="1218"):
        prod.read_validation_csv(p)

    p = tmp_path / "val22pos.csv"
    _write_csv(p, _validation_frame(1218, positives=22))
    with pytest.raises(ValueError, match="23"):
        prod.read_validation_csv(p)


def test_production_fit_uses_dev_only_and_hash_links_both_rebuild_evidences(tmp_path: Path):
    dev_csv, val_csv = tmp_path / "dev.csv", tmp_path / "val.csv"
    _write_csv(dev_csv, _dev_frame())
    _write_csv(val_csv, _validation_frame(extreme=True))
    dev_e, val_e = _d_evidence_pair(tmp_path, dev_csv, val_csv)
    args = _fit_args(tmp_path, dev_csv, dev_e, val_e)
    assert prod.fit_development(args) == 0
    e = json.loads(args.evidence_output.read_text(encoding="utf-8"))
    assert e["gate"] == prod.DEV_E_GATE
    assert e["fit_population"] == "DEVELOPMENT_V08_ONLY"
    assert e["development_fit_row_count"] == 5943 and e["validation_fit_row_count"] == 0
    assert e["validation_rainfall_csv_read_during_fit"] is False
    assert e["requires_sha256"][dev_e.name] == prod.sha256_file(dev_e)
    assert e["requires_sha256"][val_e.name] == prod.sha256_file(val_e)
    assert e["matching_components"] == list(MATCHING_COMPONENTS)
    assert e["matching_components_cumulative_variance"] >= 0.95
    assert e["validation_era5_environment_read"] is False and e["risk_engine_allowed"] is False
    assert len(pd.read_csv(args.output_csv)) == 5943


def test_production_validation_is_apply_only_and_preserves_1218_23(tmp_path: Path):
    dev_csv, val_csv = tmp_path / "dev.csv", tmp_path / "val.csv"
    _write_csv(dev_csv, _dev_frame())
    _write_csv(val_csv, _validation_frame(extreme=True))
    dev_e, val_e = _d_evidence_pair(tmp_path, dev_csv, val_csv)
    fit_args = _fit_args(tmp_path, dev_csv, dev_e, val_e)
    prod.fit_development(fit_args)
    apply_args = _apply_args(tmp_path, val_csv, val_e, fit_args.evidence_output)
    assert prod.apply_validation(apply_args) == 0
    e = json.loads(apply_args.evidence_output.read_text(encoding="utf-8"))
    out = pd.read_csv(apply_args.output_csv)
    assert e["gate"] == prod.VAL_E_GATE
    assert e["validation_row_count"] == 1218 and e["official_positive_region_day_count"] == 23
    assert e["transform_source"] == "FROZEN_DEVELOPMENT_V08_TRANSFORM"
    assert e["pca_refit_on_2025"] is False and e["standardization_refit_on_2025"] is False
    assert e["validation_statistics_used_to_modify_transform"] is False
    assert e["validation_era5_environment_read"] is False and e["risk_engine_allowed"] is False
    assert len(out) == 1218 and int(out["is_official_positive"].astype(bool).sum()) == 23
    frozen = json.loads(fit_args.evidence_output.read_text(encoding="utf-8"))
    manual = apply_frozen_transform(prod.read_validation_csv(val_csv), frozen)
    assert np.allclose(out[list(PCS)], manual[list(PCS)], rtol=1e-12, atol=1e-12)


def test_evidence_is_immutable_for_fit_and_application(tmp_path: Path):
    dev_csv, val_csv = tmp_path / "dev.csv", tmp_path / "val.csv"
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
