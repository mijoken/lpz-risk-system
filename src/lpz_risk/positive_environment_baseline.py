"""Development-only positive-episode environmental baseline.

This module joins the frozen two-provider rainfall episode representatives to
ERA5 precursor snapshots. It is intentionally descriptive: no thresholds,
hard-negative labels, source fusion, or risk score are produced.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np

IMERG = "NASA_IMERG_FINAL_V07"
CMORPH = "NOAA_CMORPH_CDR"
PROVIDERS = (IMERG, CMORPH)
OFFSETS = (-180, -120, -90, -60, -30, 0)
RAIN_METRICS = (
    "max_accumulation_mm",
    "mean_accumulation_mm",
    "p90_accumulation_mm",
    "p95_accumulation_mm",
    "p99_accumulation_mm",
)
ENV_RAW_FIELDS = (
    "rh500_mean_pct",
    "rh700_mean_pct",
    "rh500_rh700_gt60_fraction",
    "wind600_speed_mean_mps",
    "wind600_from_direction_median_deg",
    "wind850_speed_mean_mps",
    "wind850_from_direction_median_deg",
    "q1000_mean_kgkg",
    "q925_mean_kgkg",
    "q850_mean_kgkg",
)
ENV_SCALAR_FIELDS = (
    "rh500_mean_pct",
    "rh700_mean_pct",
    "rh500_rh700_gt60_fraction",
    "wind600_speed_mean_mps",
    "wind850_speed_mean_mps",
    "q1000_mean_kgkg",
    "q925_mean_kgkg",
    "q850_mean_kgkg",
    "midlevel_rh_mean_pct",
    "low_level_q_mean_kgkg",
    "wind850_600_direction_difference_deg",
)


def _rank_average(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    i = 0
    while i < len(values):
        j = i + 1
        while j < len(values) and values[order[j]] == values[order[i]]:
            j += 1
        ranks[order[i:j]] = (i + 1 + j) / 2.0
        i = j
    return ranks


def _corr(a: np.ndarray, b: np.ndarray) -> tuple[float | None, float | None]:
    mask = np.isfinite(a) & np.isfinite(b)
    aa, bb = a[mask], b[mask]
    if len(aa) < 2 or np.std(aa) == 0 or np.std(bb) == 0:
        return None, None
    pearson = float(np.corrcoef(aa, bb)[0, 1])
    spearman = float(np.corrcoef(_rank_average(aa), _rank_average(bb))[0, 1])
    return pearson, spearman


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    arr = np.asarray(
        [float(v) for v in values if v is not None and np.isfinite(float(v))],
        dtype=float,
    )
    if len(arr) == 0:
        return {
            "n": 0,
            "mean": None,
            "min": None,
            "p10": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p90": None,
            "max": None,
        }
    return {
        "n": int(len(arr)),
        "mean": float(np.mean(arr)),
        "min": float(np.min(arr)),
        "p10": float(np.percentile(arr, 10)),
        "p25": float(np.percentile(arr, 25)),
        "p50": float(np.percentile(arr, 50)),
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
        "max": float(np.max(arr)),
    }


def _circular_abs_difference_deg(a: float, b: float) -> float:
    return float(abs(((float(a) - float(b) + 180.0) % 360.0) - 180.0))


def _circular_signed_change_deg(new: float, old: float) -> float:
    return float(((float(new) - float(old) + 180.0) % 360.0) - 180.0)


def _augment_environment(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: row[k] for k in ENV_RAW_FIELDS}
    out["midlevel_rh_mean_pct"] = float(
        (float(row["rh500_mean_pct"]) + float(row["rh700_mean_pct"])) / 2.0
    )
    out["low_level_q_mean_kgkg"] = float(
        np.mean(
            [
                float(row["q1000_mean_kgkg"]),
                float(row["q925_mean_kgkg"]),
                float(row["q850_mean_kgkg"]),
            ]
        )
    )
    out["wind850_600_direction_difference_deg"] = _circular_abs_difference_deg(
        float(row["wind850_from_direction_median_deg"]),
        float(row["wind600_from_direction_median_deg"]),
    )
    return out


def _rain_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": row["source_id"],
        **{metric: float(row[metric]) for metric in RAIN_METRICS},
        "finite_polygon_area_km2": row.get("finite_polygon_area_km2"),
        "finite_coverage_fraction": row.get("finite_coverage_fraction"),
    }


def _correlation_entry(xs: list[float], ys: list[float]) -> dict[str, Any]:
    a, b = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    pearson, spearman = _corr(a, b)
    return {
        "n": int(np.sum(mask)),
        "pearson": pearson,
        "spearman": spearman,
    }


def build_development_positive_environment_baseline(
    rainfall_episode_representatives: list[dict[str, Any]],
    era5_feature_table: dict[str, Any],
    *,
    expected_episode_count: int = 65,
) -> dict[str, Any]:
    """Build a strict Development-only descriptive positive baseline."""
    if era5_feature_table.get("source") != "ERA5":
        raise ValueError("ERA5 feature table required")
    if era5_feature_table.get("available_window_complete") is not True:
        raise ValueError("ERA5 available window is not complete")
    if era5_feature_table.get("risk_engine_allowed") is not False:
        raise ValueError("ERA5 input unexpectedly enables risk engine")

    grouped_rain: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rainfall_episode_representatives:
        source = str(row.get("source_id", ""))
        if source not in PROVIDERS:
            continue
        episode = str(row.get("local_episode_id", ""))
        if not episode:
            raise ValueError("rainfall representative missing local_episode_id")
        if source in grouped_rain[episode]:
            raise ValueError(f"duplicate rainfall representative: {episode} {source}")
        if row.get("risk_score") is not None:
            raise ValueError(
                "rainfall representative unexpectedly contains risk score"
            )
        grouped_rain[episode][source] = row

    complete_ids = sorted(
        e for e, providers in grouped_rain.items() if set(providers) == set(PROVIDERS)
    )
    incomplete_ids = sorted(
        e for e, providers in grouped_rain.items() if set(providers) != set(PROVIDERS)
    )
    if incomplete_ids or len(complete_ids) != expected_episode_count:
        raise ValueError(
            f"rainfall episode completeness failed: complete={len(complete_ids)} "
            f"expected={expected_episode_count} incomplete={incomplete_ids[:10]}"
        )

    # The two provider representatives must resolve to the same frozen anchor
    # before environment data are joined; otherwise fail closed.
    chosen_anchor_by_episode: dict[str, str] = {}
    for episode in complete_ids:
        a, b = grouped_rain[episode][IMERG], grouped_rain[episode][CMORPH]
        identity_a = (
            str(a.get("anchor_id")),
            str(a.get("primary_subdivision_code")),
            str(a.get("analysis_time_utc")),
        )
        identity_b = (
            str(b.get("anchor_id")),
            str(b.get("primary_subdivision_code")),
            str(b.get("analysis_time_utc")),
        )
        if identity_a != identity_b:
            raise ValueError(
                f"provider representative identity mismatch for {episode}: "
                f"{identity_a} != {identity_b}"
            )
        chosen_anchor_by_episode[episode] = identity_a[0]

    era_rows_by_anchor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    chosen_anchor_ids = set(chosen_anchor_by_episode.values())
    for row in era5_feature_table.get("snapshot_features", []):
        anchor = str(row.get("anchor_id", ""))
        if anchor in chosen_anchor_ids:
            era_rows_by_anchor[anchor].append(row)

    episode_rows: list[dict[str, Any]] = []
    for episode in complete_ids:
        imerg = grouped_rain[episode][IMERG]
        cmorph = grouped_rain[episode][CMORPH]
        anchor = chosen_anchor_by_episode[episode]
        env_rows = era_rows_by_anchor.get(anchor, [])
        by_offset: dict[int, dict[str, Any]] = {}
        for row in env_rows:
            if (
                row.get("source") != "ERA5"
                or row.get("exactness") != "PROXY_REANALYSIS"
            ):
                raise ValueError(f"unexpected ERA5 semantics for {anchor}")
            if row.get("future_source_time_used") is not False:
                raise ValueError(f"future ERA5 source time used for {anchor}")
            if row.get("risk_score") is not None:
                raise ValueError(
                    f"ERA5 risk score unexpectedly populated for {anchor}"
                )
            offset = int(row["snapshot_offset_minutes"])
            if offset in by_offset:
                raise ValueError(
                    f"duplicate ERA5 snapshot offset for {anchor}: {offset}"
                )
            by_offset[offset] = row
        if set(by_offset) != set(OFFSETS):
            raise ValueError(
                f"ERA5 snapshot offsets incomplete for {episode}/{anchor}: "
                f"{sorted(by_offset)}"
            )

        snapshots = []
        augmented_by_offset: dict[int, dict[str, Any]] = {}
        for offset in OFFSETS:
            raw = by_offset[offset]
            env = _augment_environment(raw)
            augmented_by_offset[offset] = env
            snapshots.append(
                {
                    "snapshot_offset_minutes": offset,
                    "requested_snapshot_time_utc": raw[
                        "requested_snapshot_time_utc"
                    ],
                    "era5_source_time_utc": raw["era5_source_time_utc"],
                    "source_lag_minutes": int(raw["source_lag_minutes"]),
                    "spatial_semantics": raw["spatial_semantics"],
                    **env,
                }
            )

        start, end = augmented_by_offset[-180], augmented_by_offset[0]
        delta = {
            f"{field}_delta": float(end[field]) - float(start[field])
            for field in ENV_SCALAR_FIELDS
        }
        delta["wind600_direction_change_signed_deg"] = _circular_signed_change_deg(
            end["wind600_from_direction_median_deg"],
            start["wind600_from_direction_median_deg"],
        )
        delta["wind850_direction_change_signed_deg"] = _circular_signed_change_deg(
            end["wind850_from_direction_median_deg"],
            start["wind850_from_direction_median_deg"],
        )

        episode_rows.append(
            {
                "local_episode_id": episode,
                "anchor_id": anchor,
                "primary_subdivision_code": str(
                    imerg["primary_subdivision_code"]
                ),
                "analysis_time_utc": str(imerg["analysis_time_utc"]),
                "representative_policy": str(
                    imerg.get(
                        "representative_policy",
                        "EARLIEST_REALIZED_POSITIVE_ANCHOR_PER_LOCAL_EPISODE_PROVIDER",
                    )
                ),
                "rainfall_source_native": {
                    IMERG: _rain_payload(imerg),
                    CMORPH: _rain_payload(cmorph),
                },
                "era5_snapshots": snapshots,
                "trajectory_t0_minus_t180": delta,
            }
        )

    # Preserve the six precursor times rather than collapsing them.
    offset_distributions: dict[str, Any] = {}
    for offset in OFFSETS:
        rows = [
            next(
                s
                for s in e["era5_snapshots"]
                if s["snapshot_offset_minutes"] == offset
            )
            for e in episode_rows
        ]
        offset_distributions[str(offset)] = {
            field: _distribution([float(r[field]) for r in rows])
            for field in ENV_SCALAR_FIELDS
        }

    delta_fields = (
        sorted(episode_rows[0]["trajectory_t0_minus_t180"])
        if episode_rows
        else []
    )
    delta_distributions = {
        field: _distribution(
            [
                float(e["trajectory_t0_minus_t180"][field])
                for e in episode_rows
            ]
        )
        for field in delta_fields
    }

    rainfall_distributions: dict[str, Any] = {}
    for source in PROVIDERS:
        rainfall_distributions[source] = {
            metric: _distribution(
                [
                    float(e["rainfall_source_native"][source][metric])
                    for e in episode_rows
                ]
            )
            for metric in RAIN_METRICS
        }

    # Compact environmental coordinate set for descriptive multivariate structure.
    selected_delta_fields = (
        "midlevel_rh_mean_pct_delta",
        "low_level_q_mean_kgkg_delta",
        "rh500_rh700_gt60_fraction_delta",
        "wind600_speed_mean_mps_delta",
        "wind850_speed_mean_mps_delta",
        "wind850_600_direction_difference_deg_delta",
    )
    coordinate_names = [f"t0_{f}" for f in ENV_SCALAR_FIELDS] + [
        f"t0_minus_t180_{field.removesuffix('_delta')}"
        for field in selected_delta_fields
    ]
    coordinate_values: dict[str, list[float]] = {
        name: [] for name in coordinate_names
    }
    for episode in episode_rows:
        t0 = next(
            s
            for s in episode["era5_snapshots"]
            if s["snapshot_offset_minutes"] == 0
        )
        for field in ENV_SCALAR_FIELDS:
            coordinate_values[f"t0_{field}"].append(float(t0[field]))
        for field in selected_delta_fields:
            name = f"t0_minus_t180_{field.removesuffix('_delta')}"
            coordinate_values[name].append(
                float(episode["trajectory_t0_minus_t180"][field])
            )

    environmental_spearman_matrix: dict[
        str, dict[str, float | None]
    ] = {}
    for left in coordinate_names:
        environmental_spearman_matrix[left] = {}
        for right in coordinate_names:
            _, spearman = _corr(
                np.asarray(coordinate_values[left], dtype=float),
                np.asarray(coordinate_values[right], dtype=float),
            )
            environmental_spearman_matrix[left][right] = spearman

    rainfall_environment_correlations: dict[str, Any] = {}
    for source in PROVIDERS:
        rainfall_environment_correlations[source] = {}
        for metric in ("max_accumulation_mm", "mean_accumulation_mm"):
            rain_values = [
                float(e["rainfall_source_native"][source][metric])
                for e in episode_rows
            ]
            rainfall_environment_correlations[source][metric] = {
                coord: _correlation_entry(
                    rain_values, coordinate_values[coord]
                )
                for coord in coordinate_names
            }

    snapshot_count = sum(len(e["era5_snapshots"]) for e in episode_rows)
    expected_snapshot_count = expected_episode_count * len(OFFSETS)
    if snapshot_count != expected_snapshot_count:
        raise ValueError(
            "ERA5 Development snapshot accounting mismatch: "
            f"{snapshot_count} != {expected_snapshot_count}"
        )

    return {
        "schema_version": "0.1.0",
        "phase": "2K-development-positive-environment-baseline",
        "split": "DEVELOPMENT",
        "development_years": [2023, 2024],
        "expected_episode_count": expected_episode_count,
        "episode_count": len(episode_rows),
        "expected_era5_snapshot_count": expected_snapshot_count,
        "era5_snapshot_count": snapshot_count,
        "snapshot_offsets_minutes": list(OFFSETS),
        "rainfall_providers": list(PROVIDERS),
        "rainfall_semantics": (
            "SOURCE_NATIVE_INDEPENDENT_OBSERVATION_SYSTEMS_NO_FUSION"
        ),
        "era5_exactness": "PROXY_REANALYSIS",
        "era5_spatial_semantics": (
            "REQUEST_BBOX_CONTEXT_NOT_SUBDIVISION_POLYGON_MEAN"
        ),
        "episode_representative_policy": (
            "EARLIEST_REALIZED_POSITIVE_ANCHOR_PER_LOCAL_EPISODE_PROVIDER"
        ),
        "cross_subdivision_episode_grouping_complete": False,
        "environment_feature_semantics": {
            "midlevel_rh_mean_pct": (
                "DESCRIPTIVE_ARITHMETIC_MEAN_OF_RH500_AND_RH700_"
                "NOT_A_PAPER_THRESHOLD"
            ),
            "low_level_q_mean_kgkg": (
                "DESCRIPTIVE_ARITHMETIC_MEAN_OF_Q1000_Q925_Q850_NOT_IWVF"
            ),
            "wind850_600_direction_difference_deg": (
                "CIRCULAR_DIFFERENCE_OF_REPORTED_FROM_DIRECTIONS_"
                "NOT_VECTOR_SHEAR"
            ),
        },
        "convergence_feature_status": (
            "NOT_AVAILABLE_IN_CURRENT_ERA5_DESCRIPTOR_DO_NOT_INFER"
        ),
        "convergence_feature_reason": (
            "Current historical ERA5 descriptor does not carry the "
            "pressure-level set and horizontal derivatives required for "
            "evidence-defined IWVF divergence/moisture-flux convergence."
        ),
        "episode_rows": episode_rows,
        "environment_distributions_by_offset": offset_distributions,
        "trajectory_delta_distributions_t0_minus_t180": delta_distributions,
        "rainfall_source_native_distributions": rainfall_distributions,
        "environmental_coordinate_names": coordinate_names,
        "environmental_spearman_matrix": environmental_spearman_matrix,
        "rainfall_environment_correlations": rainfall_environment_correlations,
        "analysis_role": (
            "POSITIVE_SIDE_DESCRIPTIVE_REFERENCE_COORDINATES_FOR_FUTURE_"
            "HARD_NEGATIVE_DESIGN"
        ),
        "source_fusion_used": False,
        "gsmap_used": False,
        "convergence_inferred": False,
        "candidate_threshold_selected": False,
        "hard_negative_label": None,
        "validation_data_used": False,
        "retrospective_test_data_used": False,
        "prospective_holdout_data_used": False,
        "risk_score": None,
        "risk_engine_allowed": False,
        "gate": "PASS_COMPLETE_DEVELOPMENT_POSITIVE_ENVIRONMENT_BASELINE",
    }
