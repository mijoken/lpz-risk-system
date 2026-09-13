#!/usr/bin/env python3
"""O9-E — freeze Development-only IMERG V08 transform and apply to 2025.

This stage preserves the frozen Phase 2L-D transform semantics while enforcing
one-way information flow:

Development V08 5,943 rows -> fit log1p/z-score/PCA once -> immutable transform
                                                     |
                                                     v
Validation V08 1,218 rows ------------------------> apply only (no refit)

No ERA5, environmental outcome, matching, Primary result, or Risk Engine input is
read here.  Development fitting verifies the Validation O9-D *evidence metadata*
only because the O9 evidence chain requires both V08 rainfall populations to be
frozen before the transform artifact is created.  It never reads the Validation
rainfall CSV during fitting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from lpz_risk.o9_v08_transform import (
    MATCHING_COMPONENTS,
    METRICS,
    PCS,
    TRANSFORM_CONTRACT,
    TRANSFORM_NAME,
    apply_frozen_transform,
    fit_development_transform,
    transform_parameter_fingerprint_payload,
    validate_frozen_transform,
)

DEV_D_GATE = "PASS_O9_D_V08_DEVELOPMENT_REBUILD_5943"
VAL_D_GATE = "PASS_O9_D_V08_VALIDATION_REBUILD_1218"
DEV_E_GATE = "PASS_O9_E_V08_DEVELOPMENT_ONLY_TRANSFORM_FREEZE"
VAL_E_GATE = "PASS_O9_E_V08_VALIDATION_TRANSFORM_NO_REFIT"
SHORT_NAME = "GPM_3IMERGHH"
VERSION = "08"
SOURCE_ID = "NASA_IMERG_FINAL_V08"
KEY = ["date_utc", "primary_subdivision_code"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def parameter_sha256(meta: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(transform_parameter_fingerprint_payload(meta))).hexdigest()


def atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(tmp, index=False)
    _ = pd.read_csv(tmp, dtype={"primary_subdivision_code": "string"})
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"JSON object required: {path}")
    return obj


def _require_v08_identity(obj: dict[str, Any], label: str) -> None:
    checks = {
        "short_name": obj.get("short_name") == SHORT_NAME,
        "version": str(obj.get("imerg_final_version")).zfill(2) == VERSION,
        "source_id": obj.get("source_id") == SOURCE_ID,
        "official_final_product": obj.get("official_final_product") is True,
        "risk_locked": obj.get("risk_engine_allowed") is False,
    }
    if not all(checks.values()):
        raise ValueError(f"{label} is not compatible with Final V08 O9-E: {checks}")


def verify_development_rebuild_evidence(path: Path, csv_path: Path) -> tuple[dict[str, Any], str]:
    obj = read_json(path)
    _require_v08_identity(obj, "Development O9-D evidence")
    checks = {
        "gate": obj.get("gate") == DEV_D_GATE,
        "split": obj.get("split") == "DEVELOPMENT",
        "rows": int(obj.get("region_day_count", -1)) == 5943,
        "membership_unchanged": obj.get("candidate_membership_changed") is False,
        "environment_unused": obj.get("environment_variables_used") is False,
        "era5_unread": obj.get("validation_era5_environment_read") is False,
        "matching_unrun": obj.get("matching_performed") is False,
        "pca_unrun": obj.get("pca_fit_performed") is False,
        "primary_unrun": obj.get("primary_confirmatory_test_run") is False,
        "csv_sha": obj.get("output_csv_sha256") == sha256_file(csv_path),
    }
    if not all(checks.values()):
        raise ValueError(f"Development O9-D evidence failed O9-E checks: {checks}")
    return obj, sha256_file(path)


def verify_validation_rebuild_evidence(
    path: Path,
    development_evidence_path: Path,
) -> tuple[dict[str, Any], str]:
    obj = read_json(path)
    _require_v08_identity(obj, "Validation O9-D evidence")
    dev_sha = sha256_file(development_evidence_path)
    requires = obj.get("requires_sha256") or {}
    checks = {
        "gate": obj.get("gate") == VAL_D_GATE,
        "split": obj.get("split") == "VALIDATION_2025",
        "rows": int(obj.get("region_day_count", -1)) == 1218,
        "positives": int(obj.get("official_positive_region_day_count", -1)) == 23,
        "environment_unused": obj.get("environment_variables_used") is False,
        "era5_unread": obj.get("validation_era5_environment_read") is False,
        "matching_unrun": obj.get("matching_performed") is False,
        "pca_unrun": obj.get("pca_fit_performed") is False,
        "primary_unrun": obj.get("primary_confirmatory_test_run") is False,
        "dev_hash_link": requires.get(development_evidence_path.name) == dev_sha,
    }
    if not all(checks.values()):
        raise ValueError(f"Validation O9-D evidence failed O9-E checks: {checks}")
    return obj, sha256_file(path)


def _normalize_frame(path: Path, *, split: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"primary_subdivision_code": "string"})
    required = set(KEY) | set(METRICS) | {"source_id", "imerg_final_version"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{split} O9-D CSV missing columns: {missing}")
    df = df.copy()
    df["date_utc"] = pd.to_datetime(df["date_utc"], utc=True).dt.strftime("%Y-%m-%d")
    df["primary_subdivision_code"] = df["primary_subdivision_code"].astype("string").str.zfill(6)
    if df.duplicated(KEY).any():
        raise ValueError(f"{split} O9-D CSV contains duplicate region-day keys")
    if not (df["source_id"].astype(str) == SOURCE_ID).all():
        raise ValueError(f"{split} O9-D CSV contains a non-V08 source_id")
    versions = df["imerg_final_version"].astype(str).str.replace(".0", "", regex=False).str.zfill(2)
    if not (versions == VERSION).all():
        raise ValueError(f"{split} O9-D CSV contains a non-V08 version")
    metrics = df.loc[:, list(METRICS)].astype(float).to_numpy()
    if not np.isfinite(metrics).all() or np.any(metrics < 0.0):
        raise ValueError(f"{split} rainfall metrics must be finite and non-negative")
    return df.sort_values(KEY, kind="mergesort").reset_index(drop=True)


def read_development_csv(path: Path) -> pd.DataFrame:
    df = _normalize_frame(path, split="DEVELOPMENT")
    if len(df) != 5943:
        raise ValueError(f"Development O9-E fit requires exactly 5943 rows, got {len(df)}")
    years = set(pd.to_datetime(df["date_utc"]).dt.year.astype(int))
    if not years or not years.issubset({2023, 2024}):
        raise ValueError(f"Development O9-E years must be 2023-2024, got {sorted(years)}")
    return df


def _parse_bool_series(series: pd.Series, name: str) -> pd.Series:
    def one(v: Any) -> bool:
        if isinstance(v, (bool, np.bool_)):
            return bool(v)
        text = str(v).strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
        raise ValueError(f"invalid boolean in {name}: {v!r}")
    return series.map(one).astype(bool)


def read_validation_csv(path: Path) -> pd.DataFrame:
    df = _normalize_frame(path, split="VALIDATION_2025")
    if len(df) != 1218:
        raise ValueError(f"Validation O9-E application requires exactly 1218 rows, got {len(df)}")
    years = set(pd.to_datetime(df["date_utc"]).dt.year.astype(int))
    if years != {2025}:
        raise ValueError(f"Validation O9-E year must be 2025, got {sorted(years)}")
    if "is_official_positive" not in df.columns:
        raise ValueError("Validation O9-D CSV requires is_official_positive")
    df["is_official_positive"] = _parse_bool_series(df["is_official_positive"], "is_official_positive")
    positives = int(df["is_official_positive"].sum())
    if positives != 23:
        raise ValueError(f"Validation O9-E requires exactly 23 official positives, got {positives}")
    return df


def fit_development(args: argparse.Namespace) -> int:
    if args.evidence_output.exists():
        raise FileExistsError(f"immutable O9-E Development evidence already exists: {args.evidence_output}")

    _dev_obj, dev_evidence_sha = verify_development_rebuild_evidence(
        args.development_evidence, args.development_csv
    )
    _val_obj, val_evidence_sha = verify_validation_rebuild_evidence(
        args.validation_evidence, args.development_evidence
    )
    dev = read_development_csv(args.development_csv)

    transformed, meta = fit_development_transform(dev)
    cumulative = float(meta["matching_components_cumulative_variance"])
    if cumulative < 0.95:
        raise ValueError(
            "Frozen Phase 2L-D contract requires PC1+PC2 cumulative variance >=0.95; "
            f"observed {cumulative:.12f}. Stop for scientific review; do not change components."
        )

    atomic_write_csv(args.output_csv, transformed)
    params_sha = parameter_sha256(meta)
    evidence: dict[str, Any] = {
        "schema_version": "1.0.0",
        "phase": "O9-E-V08-development-only-transform-freeze",
        "gate": DEV_E_GATE,
        "source_id": SOURCE_ID,
        "short_name": SHORT_NAME,
        "imerg_final_version": VERSION,
        "official_final_product": True,
        "fit_population": "DEVELOPMENT_V08_ONLY",
        "development_fit_row_count": 5943,
        "validation_fit_row_count": 0,
        "validation_rainfall_csv_read_during_fit": False,
        "validation_evidence_metadata_verified_before_fit": True,
        "transform_contract": TRANSFORM_CONTRACT,
        "transform": TRANSFORM_NAME,
        "metric_order": list(meta["metric_order"]),
        "log_mean": meta["log_mean"],
        "log_std_ddof0": meta["log_std_ddof0"],
        "explained_variance_ratio": meta["explained_variance_ratio"],
        "loadings": meta["loadings"],
        "matching_components": list(MATCHING_COMPONENTS),
        "matching_components_cumulative_variance": cumulative,
        "standardization_ddof": 0,
        "covariance_ddof": 0,
        "pc1_sign_rule": meta["pc1_sign_rule"],
        "pc2_sign_rule": meta["pc2_sign_rule"],
        "transform_parameter_sha256": params_sha,
        "development_source_csv_sha256": sha256_file(args.development_csv),
        "development_transformed_csv": str(args.output_csv),
        "development_transformed_csv_sha256": sha256_file(args.output_csv),
        "requires_sha256": {
            args.development_evidence.name: dev_evidence_sha,
            args.validation_evidence.name: val_evidence_sha,
        },
        "environment_variables_used": False,
        "validation_era5_environment_read": False,
        "matching_performed": False,
        "pca_refit_on_2025": False,
        "standardization_refit_on_2025": False,
        "primary_confirmatory_test_run": False,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
    }
    validate_frozen_transform(evidence)
    atomic_write_json(args.evidence_output, evidence)
    print(json.dumps({
        "gate": DEV_E_GATE,
        "development_fit_row_count": 5943,
        "validation_fit_row_count": 0,
        "pc12_cumulative_variance": cumulative,
        "risk_engine_allowed": False,
    }))
    return 0


def verify_transform_evidence(path: Path, validation_evidence: Path) -> tuple[dict[str, Any], str]:
    obj = read_json(path)
    _require_v08_identity(obj, "O9-E Development transform evidence")
    validate_frozen_transform(obj)
    requires = obj.get("requires_sha256") or {}
    checks = {
        "gate": obj.get("gate") == DEV_E_GATE,
        "fit_population": obj.get("fit_population") == "DEVELOPMENT_V08_ONLY",
        "development_rows": int(obj.get("development_fit_row_count", -1)) == 5943,
        "validation_fit_zero": int(obj.get("validation_fit_row_count", -1)) == 0,
        "validation_csv_unread": obj.get("validation_rainfall_csv_read_during_fit") is False,
        "validation_evidence_link": requires.get(validation_evidence.name) == sha256_file(validation_evidence),
        "parameter_sha": obj.get("transform_parameter_sha256") == parameter_sha256(obj),
        "era5_unread": obj.get("validation_era5_environment_read") is False,
        "risk_locked": obj.get("risk_engine_allowed") is False,
    }
    if not all(checks.values()):
        raise ValueError(f"O9-E Development transform evidence failed checks: {checks}")
    return obj, sha256_file(path)


def apply_validation(args: argparse.Namespace) -> int:
    if args.evidence_output.exists():
        raise FileExistsError(f"immutable O9-E Validation evidence already exists: {args.evidence_output}")

    val_obj = read_json(args.validation_evidence)
    _require_v08_identity(val_obj, "Validation O9-D evidence")
    if val_obj.get("gate") != VAL_D_GATE or int(val_obj.get("region_day_count", -1)) != 1218:
        raise ValueError("Validation O9-D evidence is not a complete 1,218-row rebuild")
    if int(val_obj.get("official_positive_region_day_count", -1)) != 23:
        raise ValueError("Validation O9-D evidence does not contain exactly 23 official positives")
    if val_obj.get("validation_era5_environment_read") is not False:
        raise ValueError("Validation O9-D evidence indicates ERA5 was read")

    # Bind the exact Validation CSV bytes to the immutable O9-D rebuild evidence.
    # A structurally valid 1,218-row file is not sufficient: it must be the exact
    # rainfall population frozen by O9-D, otherwise O9-E refuses to transform it.
    validation_csv_sha = sha256_file(args.validation_csv)
    if val_obj.get("output_csv_sha256") != validation_csv_sha:
        raise ValueError(
            "Validation O9-D CSV SHA256 does not match the immutable rebuild evidence"
        )
    val_evidence_sha = sha256_file(args.validation_evidence)

    transform, transform_sha = verify_transform_evidence(
        args.transform_evidence, args.validation_evidence
    )
    validation = read_validation_csv(args.validation_csv)
    # This is the only transformation operation on 2025: a matrix multiply with
    # parameters already frozen in Development evidence.  No covariance/eigh/fit.
    transformed = apply_frozen_transform(validation, transform)
    if len(transformed) != 1218 or transformed.duplicated(KEY).any():
        raise AssertionError("Validation transform changed frozen 1,218-row membership")
    if int(_parse_bool_series(transformed["is_official_positive"], "is_official_positive").sum()) != 23:
        raise AssertionError("Validation transform changed official Positive membership")
    if not np.isfinite(transformed.loc[:, list(PCS)].to_numpy(dtype=float)).all():
        raise ValueError("Validation frozen transform produced non-finite PCA scores")

    atomic_write_csv(args.output_csv, transformed)
    evidence: dict[str, Any] = {
        "schema_version": "1.0.0",
        "phase": "O9-E-V08-validation-transform-application",
        "gate": VAL_E_GATE,
        "source_id": SOURCE_ID,
        "short_name": SHORT_NAME,
        "imerg_final_version": VERSION,
        "official_final_product": True,
        "validation_row_count": 1218,
        "official_positive_region_day_count": 23,
        "transform_source": "FROZEN_DEVELOPMENT_V08_TRANSFORM",
        "transform_contract": TRANSFORM_CONTRACT,
        "transform_parameter_sha256": transform["transform_parameter_sha256"],
        "matching_components": list(MATCHING_COMPONENTS),
        "pca_refit_on_2025": False,
        "standardization_refit_on_2025": False,
        "validation_statistics_used_to_modify_transform": False,
        "validation_source_csv_sha256": validation_csv_sha,
        "validation_transformed_csv": str(args.output_csv),
        "validation_transformed_csv_sha256": sha256_file(args.output_csv),
        "requires_sha256": {
            args.transform_evidence.name: transform_sha,
            args.validation_evidence.name: val_evidence_sha,
        },
        "environment_variables_used": False,
        "validation_era5_environment_read": False,
        "matching_performed": False,
        "primary_confirmatory_test_run": False,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
    }
    atomic_write_json(args.evidence_output, evidence)
    print(json.dumps({
        "gate": VAL_E_GATE,
        "validation_row_count": 1218,
        "pca_refit_on_2025": False,
        "standardization_refit_on_2025": False,
        "risk_engine_allowed": False,
    }))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    fit = sub.add_parser("fit-development", help="fit/freeze transform on Development V08 only")
    fit.add_argument("--development-csv", required=True, type=Path)
    fit.add_argument("--development-evidence", required=True, type=Path)
    fit.add_argument("--validation-evidence", required=True, type=Path)
    fit.add_argument("--output-csv", required=True, type=Path)
    fit.add_argument("--evidence-output", required=True, type=Path)

    apply = sub.add_parser("apply-validation", help="apply frozen Development transform to Validation")
    apply.add_argument("--validation-csv", required=True, type=Path)
    apply.add_argument("--validation-evidence", required=True, type=Path)
    apply.add_argument("--transform-evidence", required=True, type=Path)
    apply.add_argument("--output-csv", required=True, type=Path)
    apply.add_argument("--evidence-output", required=True, type=Path)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "fit-development":
        return fit_development(args)
    if args.command == "apply-validation":
        return apply_validation(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
