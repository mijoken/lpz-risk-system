"""O9-E Development-only rainfall transform for IMERG Final V08.

This module deliberately reproduces the frozen Phase 2L-D rainfall transform
without sklearn and without any knowledge of Validation/ERA5 outcomes.

Frozen transform semantics
--------------------------
1. Four IMERG rolling-3h metrics in the original order.
2. log1p transform.
3. Global z-score using Development population mean/std (ddof=0).
4. PCA from covariance of standardized Development rows (ddof=0).
5. Eigenvalues sorted descending.
6. Original Phase 2L-D sign rules:
   - PC1 loading sum must be non-negative.
   - PC2 loading for ``imerg_3h_max_max_mm`` must be non-negative.
7. PC1/PC2 are the matching components.

Validation data can only be passed to ``apply_frozen_transform`` after a frozen
parameter object already exists.  No fit/refit API accepts a Validation frame.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

METRICS = (
    "imerg_3h_mean_max_mm",
    "imerg_3h_max_max_mm",
    "imerg_3h_p90_max_mm",
    "imerg_3h_p95_max_mm",
)
PCS = ("rain_pca_pc1", "rain_pca_pc2", "rain_pca_pc3", "rain_pca_pc4")
MATCHING_COMPONENTS = ("rain_pca_pc1", "rain_pca_pc2")
TRANSFORM_NAME = "log1p_then_global_zscore_on_frozen_5943_region_day_reservoir"
TRANSFORM_CONTRACT = "O9_E_V08_DEVELOPMENT_ONLY_PCA_V1"


def _metric_matrix(frame: pd.DataFrame) -> np.ndarray:
    missing = [m for m in METRICS if m not in frame.columns]
    if missing:
        raise ValueError(f"rainfall transform input missing metrics: {missing}")
    x = frame.loc[:, list(METRICS)].astype(float).to_numpy()
    if x.ndim != 2 or x.shape[1] != len(METRICS):
        raise ValueError(f"unexpected rainfall metric matrix shape: {x.shape}")
    if not np.isfinite(x).all():
        raise ValueError("rainfall transform metrics must all be finite")
    if np.any(x < 0.0):
        raise ValueError("rainfall transform metrics must be non-negative")
    return x


def _as_vector(mapping: Mapping[str, Any], key: str) -> np.ndarray:
    obj = mapping.get(key)
    if not isinstance(obj, Mapping):
        raise ValueError(f"frozen transform {key} must be a metric mapping")
    try:
        arr = np.asarray([float(obj[m]) for m in METRICS], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid frozen transform {key}") from exc
    if arr.shape != (4,) or not np.isfinite(arr).all():
        raise ValueError(f"invalid frozen transform {key} vector")
    return arr


def _loading_matrix(mapping: Mapping[str, Any]) -> np.ndarray:
    obj = mapping.get("loadings")
    if not isinstance(obj, Mapping):
        raise ValueError("frozen transform loadings must be an object")
    cols: list[list[float]] = []
    try:
        for i in range(1, 5):
            pc = obj[f"pc{i}"]
            if not isinstance(pc, Mapping):
                raise TypeError(f"pc{i} loading is not a mapping")
            cols.append([float(pc[m]) for m in METRICS])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid frozen PCA loadings") from exc
    matrix = np.asarray(cols, dtype=float).T
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError("invalid frozen PCA loading matrix")
    # eigh yields an orthonormal basis.  Reject corrupted evidence rather than
    # silently applying a non-orthonormal matrix.
    if not np.allclose(matrix.T @ matrix, np.eye(4), rtol=1e-9, atol=1e-9):
        raise ValueError("frozen PCA loading matrix is not orthonormal")
    return matrix


def fit_development_transform(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fit the frozen rainfall PCA on Development rows only.

    The caller is responsible for enforcing the 5,943-row Development membership
    before calling this pure mathematical function.  The returned metadata is
    sufficient to transform later Validation rows without any refit.
    """
    x = _metric_matrix(frame)
    if x.shape[0] < 2:
        raise ValueError("at least two Development rows are required to fit PCA")

    xlog = np.log1p(x)
    mu = xlog.mean(axis=0)
    sd = xlog.std(axis=0, ddof=0)
    if np.any(~np.isfinite(sd)) or np.any(sd <= 0.0):
        raise ValueError(f"non-positive Development log-metric standard deviation: {sd}")

    z = (xlog - mu) / sd
    cov = np.cov(z, rowvar=False, ddof=0)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]

    # Exactly the deterministic orientation used by frozen Phase 2L-D.
    if eigvecs[:, 0].sum() < 0:
        eigvecs[:, 0] *= -1
    max_metric_idx = METRICS.index("imerg_3h_max_max_mm")
    if eigvecs[max_metric_idx, 1] < 0:
        eigvecs[:, 1] *= -1

    scores = z @ eigvecs
    total = float(eigvals.sum())
    if not np.isfinite(total) or total <= 0.0:
        raise ValueError("Development PCA total variance must be positive")
    explained = eigvals / total

    out = frame.copy()
    for i, col in enumerate(PCS):
        out[col] = scores[:, i]

    meta: dict[str, Any] = {
        "transform_contract": TRANSFORM_CONTRACT,
        "transform": TRANSFORM_NAME,
        "metric_order": list(METRICS),
        "log_mean": {m: float(v) for m, v in zip(METRICS, mu)},
        "log_std_ddof0": {m: float(v) for m, v in zip(METRICS, sd)},
        "explained_variance_ratio": {
            f"pc{i+1}": float(explained[i]) for i in range(4)
        },
        "loadings": {
            f"pc{i+1}": {m: float(eigvecs[j, i]) for j, m in enumerate(METRICS)}
            for i in range(4)
        },
        "matching_components": list(MATCHING_COMPONENTS),
        "matching_components_cumulative_variance": float(explained[:2].sum()),
        "standardization_ddof": 0,
        "covariance_ddof": 0,
        "pc1_sign_rule": "SUM_OF_PC1_LOADINGS_NONNEGATIVE",
        "pc2_sign_rule": "LOADING_OF_IMERG_3H_MAX_MAX_MM_NONNEGATIVE",
    }
    return out, meta


def validate_frozen_transform(meta: Mapping[str, Any]) -> None:
    if meta.get("transform_contract") != TRANSFORM_CONTRACT:
        raise ValueError("unexpected O9-E transform contract")
    if meta.get("transform") != TRANSFORM_NAME:
        raise ValueError("unexpected frozen transform description")
    if list(meta.get("metric_order") or []) != list(METRICS):
        raise ValueError("frozen transform metric order changed")
    if list(meta.get("matching_components") or []) != list(MATCHING_COMPONENTS):
        raise ValueError("frozen matching components changed")
    sd = _as_vector(meta, "log_std_ddof0")
    if np.any(sd <= 0.0):
        raise ValueError("frozen transform contains non-positive standard deviation")
    _as_vector(meta, "log_mean")
    loadings = _loading_matrix(meta)
    if loadings[:, 0].sum() < -1e-12:
        raise ValueError("frozen PC1 sign orientation is invalid")
    max_metric_idx = METRICS.index("imerg_3h_max_max_mm")
    if loadings[max_metric_idx, 1] < -1e-12:
        raise ValueError("frozen PC2 sign orientation is invalid")


def apply_frozen_transform(
    frame: pd.DataFrame,
    frozen_meta: Mapping[str, Any],
) -> pd.DataFrame:
    """Apply a pre-fitted Development transform; no fitting occurs here."""
    validate_frozen_transform(frozen_meta)
    x = _metric_matrix(frame)
    mu = _as_vector(frozen_meta, "log_mean")
    sd = _as_vector(frozen_meta, "log_std_ddof0")
    loadings = _loading_matrix(frozen_meta)
    z = (np.log1p(x) - mu) / sd
    scores = z @ loadings
    if not np.isfinite(scores).all():
        raise ValueError("non-finite PCA score produced by frozen transform")
    out = frame.copy()
    for i, col in enumerate(PCS):
        out[col] = scores[:, i]
    return out


def transform_parameter_fingerprint_payload(meta: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the scientific parameters that define the frozen transform."""
    validate_frozen_transform(meta)
    return {
        "transform_contract": meta["transform_contract"],
        "transform": meta["transform"],
        "metric_order": list(meta["metric_order"]),
        "log_mean": dict(meta["log_mean"]),
        "log_std_ddof0": dict(meta["log_std_ddof0"]),
        "explained_variance_ratio": dict(meta["explained_variance_ratio"]),
        "loadings": dict(meta["loadings"]),
        "matching_components": list(meta["matching_components"]),
        "matching_components_cumulative_variance": float(
            meta["matching_components_cumulative_variance"]
        ),
        "standardization_ddof": int(meta["standardization_ddof"]),
        "covariance_ddof": int(meta["covariance_ddof"]),
        "pc1_sign_rule": str(meta["pc1_sign_rule"]),
        "pc2_sign_rule": str(meta["pc2_sign_rule"]),
    }
