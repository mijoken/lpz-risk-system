#!/usr/bin/env python3
"""O9-F — freeze the 2025 rainfall-matched validation population.

This stage may execute only after O9-E has transferred the Development-only V08
rainfall transform to all 1,218 frozen 2025 target region-days.  It applies the
pre-specified Phase 2L-H/K2 matching contract and writes immutable evidence.

It never reads ERA5 or any environmental outcome, never refits PCA/standardization,
and exposes no CLI knobs for the frozen +/-60, +/-3, 1:3, PC1/PC2 policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from lpz_risk.o9_frozen_matching import (
    COMPARISON_ROLE,
    EVENT_BUFFER_DAYS,
    KEY,
    MATCH_COMPONENTS,
    MATCH_RATIO,
    MATCHING_CONTRACT,
    POSITIVE_ROLE,
    SEASON_WINDOW_DAYS,
    frozen_match_2025,
)
from lpz_risk.o9_v08_transform import METRICS

SOURCE_ID = "NASA_IMERG_FINAL_V08"
SHORT_NAME = "GPM_3IMERGHH"
VERSION = "08"
DEV_E_GATE = "PASS_O9_E_V08_DEVELOPMENT_ONLY_TRANSFORM_FREEZE"
VAL_E_GATE = "PASS_O9_E_V08_VALIDATION_TRANSFORM_NO_REFIT"
O9_F_GATE = "PASS_O9_F_V08_FROZEN_2025_MATCHING_23_POSITIVES_69_COMPARISONS"
H_GATE = "PASS_PHASE2L_H_DISCOVERY_AND_VALIDATION_PROTOCOL_FREEZE_PRIMARY_Q850_T0H"
K2_GATE = "PASS_PHASE2L_K2_V07_BOUNDARY_AND_V08_DEFERRED_VALIDATION_FREEZE"
TIME_ANCHOR_POLICY = "IMERG_3H_P95_MAX_WINDOW_START"
TIME_ANCHOR_START_COLUMN = "imerg_3h_p95_window_start_utc"
TIME_ANCHOR_END_COLUMN = "imerg_3h_p95_window_end_utc"
DEFAULT_H_FREEZE = Path("research/phase2/phase2l_h_validation_protocol_freeze_20260911.json")
DEFAULT_K2_FREEZE = Path("research/phase2/phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912.json")


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


def parse_bool_series(series: pd.Series, name: str) -> pd.Series:
    def one(value: Any) -> bool:
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
        raise ValueError(f"invalid boolean in {name}: {value!r}")

    return series.map(one).astype(bool)


def _require_v08_identity(obj: dict[str, Any], label: str) -> None:
    checks = {
        "source_id": obj.get("source_id") == SOURCE_ID,
        "short_name": obj.get("short_name") == SHORT_NAME,
        "version": str(obj.get("imerg_final_version")).zfill(2) == VERSION,
        "official_final_product": obj.get("official_final_product") is True,
        "risk_locked": obj.get("risk_engine_allowed") is False,
    }
    if not all(checks.values()):
        raise ValueError(f"{label} is not compatible with O9-F Final V08: {checks}")


def verify_frozen_protocol(h_path: Path, k2_path: Path) -> dict[str, str]:
    h = read_json(h_path)
    k2 = read_json(k2_path)
    hp = h.get("population_design") or {}
    kp = ((k2.get("upstream_protocol") or {}).get("frozen_matching") or {})

    expected_space = "LOG1P_STANDARDIZED_FOUR_IMERG_3H_METRICS_PCA_PC1_PC2"
    h_checks = {
        "gate": h.get("gate") == H_GATE,
        "ratio": hp.get("match_ratio") == "1_POSITIVE_TO_3_COMPARISONS",
        "same_region": hp.get("same_primary_subdivision_required") is True,
        "season": int(hp.get("season_window_calendar_days", -1)) == SEASON_WINDOW_DAYS,
        "buffer": int(hp.get("positive_event_exclusion_buffer_actual_days", -1)) == EVENT_BUFFER_DAYS,
        "space": hp.get("rainfall_matching_space") == expected_space,
        "role": hp.get("comparison_role") == COMPARISON_ROLE,
        "environment_unused": hp.get("environment_variables_used_for_matching") is False,
        "time_anchor": ((h.get("time_anchor") or {}).get("policy") == TIME_ANCHOR_POLICY),
        "risk_locked": h.get("risk_engine_allowed") is False,
    }
    k2_checks = {
        "gate": k2.get("gate") == K2_GATE,
        "ratio": kp.get("match_ratio") == "1_POSITIVE_TO_3_COMPARISONS",
        "same_region": kp.get("same_primary_subdivision_required") is True,
        "season": int(kp.get("season_window_calendar_days", -1)) == SEASON_WINDOW_DAYS,
        "buffer": int(kp.get("positive_event_exclusion_buffer_actual_days", -1)) == EVENT_BUFFER_DAYS,
        "space": kp.get("rainfall_matching_space") == expected_space,
        "role": kp.get("comparison_role") == COMPARISON_ROLE,
        "environment_unused": kp.get("environment_variables_used_for_matching") is False,
        "validation_deferred": ((k2.get("validation_state") or {}).get("status") == "DEFERRED_PENDING_IMERG_FINAL_V08"),
        "risk_locked": ((k2.get("validation_state") or {}).get("risk_engine_allowed") is False),
    }
    if not all(h_checks.values()):
        raise ValueError(f"Phase 2L-H frozen matching contract mismatch: {h_checks}")
    if not all(k2_checks.values()):
        raise ValueError(f"Phase 2L-K2 frozen matching contract mismatch: {k2_checks}")

    if MATCH_RATIO != 3 or tuple(MATCH_COMPONENTS) != ("rain_pca_pc1", "rain_pca_pc2"):
        raise AssertionError("O9-F code constants no longer match the frozen protocol")
    return {h_path.name: sha256_file(h_path), k2_path.name: sha256_file(k2_path)}


def verify_development_transform_evidence(path: Path) -> tuple[dict[str, Any], str]:
    obj = read_json(path)
    _require_v08_identity(obj, "O9-E Development transform evidence")
    checks = {
        "gate": obj.get("gate") == DEV_E_GATE,
        "fit_population": obj.get("fit_population") == "DEVELOPMENT_V08_ONLY",
        "dev_rows": int(obj.get("development_fit_row_count", -1)) == 5943,
        "validation_fit_zero": int(obj.get("validation_fit_row_count", -1)) == 0,
        "components": list(obj.get("matching_components") or []) == list(MATCH_COMPONENTS),
        "pca_refit_false": obj.get("pca_refit_on_2025") is False,
        "standardization_refit_false": obj.get("standardization_refit_on_2025") is False,
        "era5_unread": obj.get("validation_era5_environment_read") is False,
        "primary_unrun": obj.get("primary_confirmatory_test_run") is False,
        "public_locked": obj.get("public_risk_release_allowed") is False,
    }
    if not all(checks.values()):
        raise ValueError(f"O9-E Development evidence failed O9-F checks: {checks}")
    if not isinstance(obj.get("transform_parameter_sha256"), str):
        raise ValueError("O9-E Development evidence lacks transform_parameter_sha256")
    return obj, sha256_file(path)


def verify_validation_transform_evidence(
    path: Path,
    validation_csv: Path,
    development_transform_evidence: Path,
    development_transform: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    obj = read_json(path)
    _require_v08_identity(obj, "O9-E Validation transform evidence")
    requires = obj.get("requires_sha256") or {}
    checks = {
        "gate": obj.get("gate") == VAL_E_GATE,
        "rows": int(obj.get("validation_row_count", -1)) == 1218,
        "positives": int(obj.get("official_positive_region_day_count", -1)) == 23,
        "transform_source": obj.get("transform_source") == "FROZEN_DEVELOPMENT_V08_TRANSFORM",
        "components": list(obj.get("matching_components") or []) == list(MATCH_COMPONENTS),
        "parameter_link": obj.get("transform_parameter_sha256") == development_transform.get("transform_parameter_sha256"),
        "dev_evidence_link": requires.get(development_transform_evidence.name) == sha256_file(development_transform_evidence),
        "csv_hash": obj.get("validation_transformed_csv_sha256") == sha256_file(validation_csv),
        "pca_refit_false": obj.get("pca_refit_on_2025") is False,
        "standardization_refit_false": obj.get("standardization_refit_on_2025") is False,
        "validation_stats_unused": obj.get("validation_statistics_used_to_modify_transform") is False,
        "era5_unread": obj.get("validation_era5_environment_read") is False,
        "matching_not_pre_run": obj.get("matching_performed") is False,
        "primary_unrun": obj.get("primary_confirmatory_test_run") is False,
        "public_locked": obj.get("public_risk_release_allowed") is False,
    }
    if not all(checks.values()):
        raise ValueError(f"O9-E Validation evidence failed O9-F checks: {checks}")
    return obj, sha256_file(path)


def read_validation_transformed_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"primary_subdivision_code": "string"})
    required = (
        set(KEY)
        | set(MATCH_COMPONENTS)
        | set(METRICS)
        | {
            "is_official_positive",
            "source_id",
            "imerg_final_version",
            TIME_ANCHOR_START_COLUMN,
            TIME_ANCHOR_END_COLUMN,
        }
    )
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"O9-F Validation CSV missing required columns: {missing}")
    df = df.copy()
    df["date_utc"] = pd.to_datetime(df["date_utc"], utc=True).dt.strftime("%Y-%m-%d")
    df["primary_subdivision_code"] = df["primary_subdivision_code"].astype("string").str.zfill(6)
    if len(df) != 1218:
        raise ValueError(f"O9-F requires exactly 1218 validation rows, got {len(df)}")
    if df.duplicated(list(KEY)).any():
        raise ValueError("O9-F Validation CSV contains duplicate region-day keys")
    years = set(pd.to_datetime(df["date_utc"]).dt.year.astype(int))
    if years != {2025}:
        raise ValueError(f"O9-F Validation year must be 2025, got {sorted(years)}")
    if not (df["source_id"].astype(str) == SOURCE_ID).all():
        raise ValueError("O9-F Validation CSV contains a non-V08 source_id")
    versions = df["imerg_final_version"].astype(str).str.replace(".0", "", regex=False).str.zfill(2)
    if not (versions == VERSION).all():
        raise ValueError("O9-F Validation CSV contains a non-V08 version")
    df["is_official_positive"] = parse_bool_series(df["is_official_positive"], "is_official_positive")
    if int(df["is_official_positive"].sum()) != 23:
        raise ValueError("O9-F requires exactly 23 official Positive region-days")
    pcs = df.loc[:, list(MATCH_COMPONENTS)].astype(float).to_numpy()
    if not np.isfinite(pcs).all():
        raise ValueError("O9-F PC1/PC2 coordinates must be finite")
    metrics = df.loc[:, list(METRICS)].astype(float).to_numpy()
    if not np.isfinite(metrics).all() or np.any(metrics < 0.0):
        raise ValueError("O9-F rainfall metrics must be finite and non-negative")

    anchor_start = pd.to_datetime(df[TIME_ANCHOR_START_COLUMN], utc=True, errors="coerce")
    anchor_end = pd.to_datetime(df[TIME_ANCHOR_END_COLUMN], utc=True, errors="coerce")
    if anchor_start.isna().any() or anchor_end.isna().any():
        raise ValueError("O9-F requires complete parseable IMERG P95 time anchors")
    if (anchor_end <= anchor_start).any():
        raise ValueError("O9-F IMERG P95 window end must be after window start")

    return df.sort_values(list(KEY), kind="mergesort").reset_index(drop=True)


def _distance_summary(pairs: pd.DataFrame) -> dict[str, float]:
    s = pairs["rainfall_match_distance_pc12"].astype(float)
    return {
        "min": float(s.min()),
        "p25": float(s.quantile(0.25)),
        "median": float(s.median()),
        "p75": float(s.quantile(0.75)),
        "p90": float(s.quantile(0.90)),
        "max": float(s.max()),
    }


def run(args: argparse.Namespace) -> int:
    if args.evidence_output.exists():
        raise FileExistsError(f"immutable O9-F evidence already exists: {args.evidence_output}")

    protocol_hashes = verify_frozen_protocol(args.protocol_freeze, args.k2_freeze)
    dev_e, dev_e_sha = verify_development_transform_evidence(args.development_transform_evidence)
    _val_e, val_e_sha = verify_validation_transform_evidence(
        args.validation_transform_evidence,
        args.validation_transformed_csv,
        args.development_transform_evidence,
        dev_e,
    )
    validation = read_validation_transformed_csv(args.validation_transformed_csv)

    outputs = frozen_match_2025(validation)
    positives = outputs["positive_population"]
    pairs = outputs["matched_pairs"]
    comparisons = outputs["comparison_population"]
    final_population = outputs["final_matched_population"]
    eligibility = outputs["eligibility_audit"]

    if len(positives) != 23 or len(pairs) != 69 or len(comparisons) != 69:
        raise AssertionError(
            f"frozen O9-F cardinality changed: positives={len(positives)} "
            f"pairs={len(pairs)} comparisons={len(comparisons)}"
        )
    if len(final_population) != 92:
        raise AssertionError(f"O9-F final matched population must contain 92 rows, got {len(final_population)}")
    if comparisons[list(KEY)].duplicated().any() or final_population[list(KEY)].duplicated().any():
        raise AssertionError("O9-F final population is not globally no-replacement")
    if not (pairs["comparison_role"] == COMPARISON_ROLE).all():
        raise AssertionError("O9-F comparison role changed")
    if set(final_population["case_role"].astype(str)) != {POSITIVE_ROLE, COMPARISON_ROLE}:
        raise AssertionError("O9-F final population roles changed")
    if int(pairs["season_day_difference"].max()) > SEASON_WINDOW_DAYS:
        raise AssertionError("O9-F season window exceeded frozen +/-60 days")
    for label, frame in (("Positive", positives), ("Comparison", comparisons), ("Final", final_population)):
        if TIME_ANCHOR_START_COLUMN not in frame.columns or frame[TIME_ANCHOR_START_COLUMN].isna().any():
            raise AssertionError(f"O9-F {label} population lost frozen P95 time anchors")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "positive_population": args.output_dir / "o9_f_validation_positive_region_days.csv",
        "matched_pairs": args.output_dir / "o9_f_rainfall_matched_pairs.csv",
        "comparison_population": args.output_dir / "o9_f_rainfall_matched_comparison_population.csv",
        "final_matched_population": args.output_dir / "o9_f_final_matched_population.csv",
        "eligibility_audit": args.output_dir / "o9_f_matching_eligibility_audit.csv",
    }
    for key, path in paths.items():
        atomic_write_csv(path, outputs[key])

    evidence = {
        "schema_version": "1.1.0",
        "phase": "O9-F-V08-frozen-2025-rainfall-matching",
        "gate": O9_F_GATE,
        "source_id": SOURCE_ID,
        "short_name": SHORT_NAME,
        "imerg_final_version": VERSION,
        "official_final_product": True,
        "matching_contract": MATCHING_CONTRACT,
        "validation_region_day_count": 1218,
        "official_positive_region_day_count": 23,
        "comparison_pool_after_positive_exclusion": 1195,
        "match_ratio": "1_POSITIVE_TO_3_COMPARISONS",
        "matched_comparison_region_day_count": 69,
        "unique_comparison_region_day_count": 69,
        "final_matched_population_region_day_count": 92,
        "replacement_used": False,
        "same_primary_subdivision_required": True,
        "season_window_circular_calendar_days": SEASON_WINDOW_DAYS,
        "same_region_positive_event_buffer_actual_days": EVENT_BUFFER_DAYS,
        "rainfall_matching_space": "FROZEN_DEVELOPMENT_V08_TRANSFORM_PC1_PC2",
        "matching_components": list(MATCH_COMPONENTS),
        "rainfall_match_distance": "SQRT_MEAN_SQUARED_DIFFERENCE_PC1_PC2",
        "allocation_policy": "DETERMINISTIC_GREEDY_SCARCE_POSITIVES_FIRST_GLOBAL_NO_REPLACEMENT",
        "comparison_population_role": COMPARISON_ROLE,
        "time_anchor_policy": TIME_ANCHOR_POLICY,
        "time_anchor_start_column": TIME_ANCHOR_START_COLUMN,
        "time_anchor_end_column": TIME_ANCHOR_END_COLUMN,
        "time_anchor_preserved_for_all_final_cases": True,
        "minimum_eligible_comparison_count_before_no_replacement": int(
            eligibility["eligible_comparison_count_before_no_replacement"].min()
        ),
        "median_eligible_comparison_count_before_no_replacement": float(
            eligibility["eligible_comparison_count_before_no_replacement"].median()
        ),
        "match_distance_summary": _distance_summary(pairs),
        "validation_balance_gate_applied": False,
        "validation_balance_or_threshold_tuning_performed": False,
        "pca_refit_on_2025": False,
        "standardization_refit_on_2025": False,
        "validation_statistics_used_to_modify_transform": False,
        "environment_variables_used_for_selection": False,
        "validation_era5_environment_read": False,
        "primary_confirmatory_test_run": False,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
        "validation_transformed_csv_sha256": sha256_file(args.validation_transformed_csv),
        "transform_parameter_sha256": dev_e["transform_parameter_sha256"],
        "outputs": {
            key: {"path": str(path), "sha256": sha256_file(path), "rows": int(len(outputs[key]))}
            for key, path in paths.items()
        },
        "requires_sha256": {
            args.development_transform_evidence.name: dev_e_sha,
            args.validation_transform_evidence.name: val_e_sha,
            **protocol_hashes,
        },
    }
    atomic_write_json(args.evidence_output, evidence)
    print(json.dumps({
        "gate": O9_F_GATE,
        "positive_region_days": 23,
        "matched_comparisons": 69,
        "final_matched_population": 92,
        "replacement_used": False,
        "validation_era5_environment_read": False,
        "risk_engine_allowed": False,
    }))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--validation-transformed-csv", required=True, type=Path)
    ap.add_argument("--validation-transform-evidence", required=True, type=Path)
    ap.add_argument("--development-transform-evidence", required=True, type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument("--evidence-output", required=True, type=Path)
    ap.add_argument("--protocol-freeze", type=Path, default=DEFAULT_H_FREEZE)
    ap.add_argument("--k2-freeze", type=Path, default=DEFAULT_K2_FREEZE)
    return ap


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
