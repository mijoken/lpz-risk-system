from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lpz_risk.o9_v08_transform import METRICS, fit_development_transform
from scripts import o9_v08_transform_freeze as prod


def _frame(n: int, *, year: int, positive_count: int | None = None, offset: float = 0.0) -> pd.DataFrame:
    i = np.arange(n, dtype=float)
    t = np.sin(i * 0.017 + offset)
    u = np.cos(i * 0.041 - offset)
    v = np.sin(i * 0.073 + 0.2)
    w = np.cos(i * 0.101 - 0.3)
    xlog = np.column_stack([
        2.0 + 0.60 * t + 0.12 * u + 0.010 * v + 0.004 * w,
        2.4 + 0.80 * t - 0.10 * u - 0.006 * v + 0.012 * w,
        2.2 + 0.68 * t + 0.07 * u + 0.014 * v - 0.005 * w,
        2.3 + 0.73 * t + 0.03 * u - 0.009 * v - 0.011 * w,
    ])
    rain = np.expm1(xlog)
    idx = np.arange(n)
    df = pd.DataFrame({
        "date_utc": (pd.Timestamp(f"{year}-01-01") + pd.to_timedelta(idx // 5, unit="D")).strftime("%Y-%m-%d"),
        "primary_subdivision_code": pd.Series((idx % 5) + 100).astype(str).str.zfill(6),
        "source_id": prod.SOURCE_ID,
        "imerg_final_version": "08",
    })
    if positive_count is not None:
        df["is_official_positive"] = idx < positive_count
    for j, metric in enumerate(METRICS):
        df[metric] = rain[:, j]
    return df


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_validation_application_rejects_structurally_valid_but_wrong_csv_bytes(tmp_path: Path):
    original = _frame(1218, year=2025, positive_count=23, offset=0.4)
    original_csv = tmp_path / "validation_original.csv"
    original.to_csv(original_csv, index=False)

    validation_evidence = tmp_path / "o9_d_validation_v08_rebuild.json"
    _write_json(validation_evidence, {
        "gate": prod.VAL_D_GATE,
        "split": "VALIDATION_2025",
        "source_id": prod.SOURCE_ID,
        "short_name": prod.SHORT_NAME,
        "imerg_final_version": "08",
        "official_final_product": True,
        "region_day_count": 1218,
        "official_positive_region_day_count": 23,
        "output_csv_sha256": prod.sha256_file(original_csv),
        "environment_variables_used": False,
        "validation_era5_environment_read": False,
        "matching_performed": False,
        "pca_fit_performed": False,
        "primary_confirmatory_test_run": False,
        "risk_engine_allowed": False,
    })

    _, meta = fit_development_transform(_frame(600, year=2023, offset=0.0))
    meta.update({
        "gate": prod.DEV_E_GATE,
        "source_id": prod.SOURCE_ID,
        "short_name": prod.SHORT_NAME,
        "imerg_final_version": "08",
        "official_final_product": True,
        "fit_population": "DEVELOPMENT_V08_ONLY",
        "development_fit_row_count": 5943,
        "validation_fit_row_count": 0,
        "validation_rainfall_csv_read_during_fit": False,
        "validation_era5_environment_read": False,
        "risk_engine_allowed": False,
        "requires_sha256": {validation_evidence.name: prod.sha256_file(validation_evidence)},
    })
    meta["transform_parameter_sha256"] = prod.parameter_sha256(meta)
    transform_evidence = tmp_path / "o9_e_development_v08_transform_freeze.json"
    _write_json(transform_evidence, meta)

    altered = original.copy()
    altered.loc[100, "imerg_3h_mean_max_mm"] *= 1.0001
    altered_csv = tmp_path / "validation_altered_but_structurally_valid.csv"
    altered.to_csv(altered_csv, index=False)

    args = argparse.Namespace(
        validation_csv=altered_csv,
        validation_evidence=validation_evidence,
        transform_evidence=transform_evidence,
        output_csv=tmp_path / "must_not_exist.csv",
        evidence_output=tmp_path / "must_not_exist.json",
    )
    with pytest.raises(ValueError, match="CSV SHA256 does not match"):
        prod.apply_validation(args)

    assert not args.output_csv.exists()
    assert not args.evidence_output.exists()
