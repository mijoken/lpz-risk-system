#!/usr/bin/env python3
"""F4-8 descriptive diagnostics for F4-1 constant-motion spatial skill.

This stage intentionally does NOT retune the motion model. It enriches the
identity-free F4-7 verification rows with source area, projected translation,
and implied source motion speed, then describes how those variables relate to
motion-minus-persistence skill.

All results are post-hoc diagnostics on the same archived sample and MUST NOT
be used as validation or as a basis for parameter selection without a separate
prospective evaluation.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

from verify_f4_geographic_envelope_overlap import _read
from verify_f4_identity_free_spatial import (
    _haversine_km,
    evaluate as evaluate_identity_free,
)


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _rank(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        average_rank = ((i + 1) + j) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = average_rank
        i = j
    return ranks


def _pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) != len(y):
        raise ValueError("correlation length mismatch")
    if len(x) < 2:
        return None
    mx = statistics.fmean(x)
    my = statistics.fmean(y)
    dx = [value - mx for value in x]
    dy = [value - my for value in y]
    sx2 = sum(value * value for value in dx)
    sy2 = sum(value * value for value in dy)
    if sx2 <= 0.0 or sy2 <= 0.0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / math.sqrt(sx2 * sy2)


def _spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) != len(y):
        raise ValueError("correlation length mismatch")
    if len(x) < 2:
        return None
    return _pearson(_rank(x), _rank(y))


def _quantile_edges(values: list[float]) -> list[float]:
    if not values:
        return []
    ordered = sorted(values)

    def quantile(fraction: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        position = fraction * (len(ordered) - 1)
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        weight = position - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    return [quantile(0.25), quantile(0.50), quantile(0.75)]


def _quartile_label(value: float, edges: list[float]) -> str:
    if len(edges) != 3:
        raise ValueError("quartile edges missing")
    if value <= edges[0]:
        return "Q1"
    if value <= edges[1]:
        return "Q2"
    if value <= edges[2]:
        return "Q3"
    return "Q4"


def _group_summary(rows: list[dict]) -> dict:
    deltas = [float(row["motion_minus_persistence_best_iou"]) for row in rows]
    distance_deltas = [
        float(row["motion_minus_persistence_nearest_distance_km"])
        for row in rows
    ]
    tolerance = 1e-12
    return {
        "count": len(rows),
        "motion_higher_iou_count": sum(delta > tolerance for delta in deltas),
        "persistence_higher_iou_count": sum(delta < -tolerance for delta in deltas),
        "equal_iou_count": sum(abs(delta) <= tolerance for delta in deltas),
        "motion_minus_persistence_best_iou_mean": _mean(deltas),
        "motion_minus_persistence_best_iou_median": _median(deltas),
        "motion_minus_persistence_nearest_distance_km_mean": _mean(
            distance_deltas
        ),
        "motion_minus_persistence_nearest_distance_km_median": _median(
            distance_deltas
        ),
        "motion_any_overlap_rate": (
            sum(bool(row["motion_spatial"]["any_overlap"]) for row in rows)
            / len(rows)
            if rows
            else None
        ),
        "persistence_any_overlap_rate": (
            sum(bool(row["persistence_spatial"]["any_overlap"]) for row in rows)
            / len(rows)
            if rows
            else None
        ),
        "implied_motion_speed_mps_median": _median([
            float(row["implied_motion_speed_mps"]) for row in rows
        ]),
        "source_area_km2_median": _median([
            float(row["source_area_km2"]) for row in rows
        ]),
        "projected_translation_km_median": _median([
            float(row["projected_translation_km"]) for row in rows
        ]),
    }


def _correlations(rows: list[dict]) -> dict:
    if not rows:
        return {}

    delta_iou = [
        float(row["motion_minus_persistence_best_iou"]) for row in rows
    ]
    delta_distance = [
        float(row["motion_minus_persistence_nearest_distance_km"])
        for row in rows
    ]

    factors = {
        "implied_motion_speed_mps": [
            float(row["implied_motion_speed_mps"]) for row in rows
        ],
        "source_area_km2": [
            float(row["source_area_km2"]) for row in rows
        ],
        "projected_translation_km": [
            float(row["projected_translation_km"]) for row in rows
        ],
    }

    output = {}
    for name, values in factors.items():
        output[name] = {
            "spearman_vs_delta_iou": _spearman(values, delta_iou),
            "pearson_vs_delta_iou": _pearson(values, delta_iou),
            "spearman_vs_delta_nearest_distance_km": _spearman(
                values, delta_distance
            ),
            "pearson_vs_delta_nearest_distance_km": _pearson(
                values, delta_distance
            ),
        }
    return output


def _winner_summary(rows: list[dict]) -> dict:
    tolerance = 1e-12
    groups = {
        "MOTION_BETTER": [],
        "PERSISTENCE_BETTER": [],
        "EQUAL": [],
    }
    for row in rows:
        delta = float(row["motion_minus_persistence_best_iou"])
        if delta > tolerance:
            groups["MOTION_BETTER"].append(row)
        elif delta < -tolerance:
            groups["PERSISTENCE_BETTER"].append(row)
        else:
            groups["EQUAL"].append(row)
    return {
        name: _group_summary(group_rows)
        for name, group_rows in groups.items()
    }


def _feature_index(source_root: Path) -> dict[tuple[str, str, int], dict]:
    geo_manifest = _read(
        source_root / "f4_geographic_envelopes" / "manifest.json"
    )
    index = {}
    for slot in geo_manifest.get("slot_results", []):
        if slot.get("research_status") != "RESEARCH_GEOGRAPHIC_ENVELOPE":
            continue
        source_file = slot["source_file"]
        payload = _read(source_root / slot["output_file"])
        for feature in payload.get("features", []):
            props = feature.get("properties") or {}
            if props.get("kind") != "PROJECTED_RESEARCH_GEOGRAPHIC_ENVELOPE":
                continue
            key = (
                source_file,
                str(props["research_object_id"]),
                int(props["lead_from_as_of_minutes"]),
            )
            if key in index:
                raise ValueError(f"duplicate F4-4 projected feature: {key}")
            index[key] = feature
    return index


def _enrich_rows(source_root: Path, rows: list[dict]) -> list[dict]:
    features = _feature_index(source_root)
    output = []

    for row in rows:
        if row.get("verification_status") != "IDENTITY_FREE_SPATIAL_COMPARISON":
            continue
        key = (
            row["source_file"],
            str(row["research_object_id"]),
            int(row["lead_from_as_of_minutes"]),
        )
        feature = features.get(key)
        if feature is None:
            raise ValueError(f"F4-4 projected feature missing: {key}")
        props = feature["properties"]

        observed = props.get("observed_centroid_lon_lat")
        projected = props.get("projected_centroid_lon_lat")
        area = props.get("observed_approx_area_km2")
        lead_from_obs = props.get("lead_from_last_observation_minutes")

        if (
            not isinstance(observed, list)
            or len(observed) != 2
            or not isinstance(projected, list)
            or len(projected) != 2
            or area is None
            or lead_from_obs is None
            or float(lead_from_obs) <= 0.0
        ):
            raise ValueError(f"F4-4 diagnostic metadata missing: {key}")

        translation_km = _haversine_km(
            float(observed[0]),
            float(observed[1]),
            float(projected[0]),
            float(projected[1]),
        )
        speed_mps = translation_km * 1000.0 / (float(lead_from_obs) * 60.0)
        distance_delta = (
            float(row["motion_spatial"]["nearest_centroid_distance_km"])
            - float(
                row["persistence_spatial"]["nearest_centroid_distance_km"]
            )
        )

        output.append({
            **row,
            "source_area_km2": float(area),
            "lead_from_last_observation_minutes": float(lead_from_obs),
            "projected_translation_km": translation_km,
            "implied_motion_speed_mps": speed_mps,
            "motion_minus_persistence_nearest_distance_km": distance_delta,
        })

    return output


def _quartile_summaries(rows: list[dict], field: str) -> dict:
    values = [float(row[field]) for row in rows]
    edges = _quantile_edges(values)
    grouped = {"Q1": [], "Q2": [], "Q3": [], "Q4": []}
    for row in rows:
        grouped[_quartile_label(float(row[field]), edges)].append(row)
    return {
        "field": field,
        "quartile_edges": {
            "q25": edges[0] if edges else None,
            "q50": edges[1] if edges else None,
            "q75": edges[2] if edges else None,
        },
        "groups": {
            name: _group_summary(group_rows)
            for name, group_rows in grouped.items()
        },
    }


def evaluate(source_root: Path, comparison_roots: list[Path]) -> dict:
    f4 = evaluate_identity_free(source_root, comparison_roots)
    if (
        f4.get("product") != "F4_IDENTITY_FREE_SPATIAL_ENVELOPE_VERIFICATION"
        or f4.get("risk_engine_allowed") is not False
        or f4.get("lpz_forecast_generated") is not False
        or f4.get("validated_forecast") is not False
        or f4.get("identity_required") is not False
    ):
        raise ValueError("F4-7 lock/contract not proven")

    rows = _enrich_rows(source_root, f4["results"])
    lead_rows = {
        lead: [
            row for row in rows
            if int(row["lead_from_as_of_minutes"]) == lead
        ]
        for lead in (15, 30)
    }

    return {
        "schema_version": "0.1.0",
        "product": "F4_CONSTANT_MOTION_FAILURE_DIAGNOSTICS",
        "research_mode": "POSTHOC_DESCRIPTIVE_DIAGNOSTICS_ONLY",
        "source_run_id": f4["source_run_id"],
        "comparison_run_ids": f4["comparison_run_ids"],
        "comparison_count": len(rows),
        "overall": {
            "summary": _group_summary(rows),
            "correlations": _correlations(rows),
            "winner_groups": _winner_summary(rows),
            "speed_quartiles": _quartile_summaries(
                rows, "implied_motion_speed_mps"
            ),
            "area_quartiles": _quartile_summaries(
                rows, "source_area_km2"
            ),
        },
        "by_lead": {
            str(lead): {
                "summary": _group_summary(group),
                "correlations": _correlations(group),
                "winner_groups": _winner_summary(group),
                "speed_quartiles": _quartile_summaries(
                    group, "implied_motion_speed_mps"
                ),
                "area_quartiles": _quartile_summaries(
                    group, "source_area_km2"
                ),
            }
            for lead, group in lead_rows.items()
        },
        "rows": rows,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
        "parameter_tuning_performed": False,
        "model_selection_allowed_from_this_sample": False,
        "validated_forecast": False,
        "interpretation": (
            "Post-hoc descriptive diagnostics of the already evaluated F4-1 "
            "constant-motion baseline. Associations between source motion/area "
            "and skill differences are hypothesis-generating only. No threshold, "
            "speed scale, area filter, or alternate model may be selected as "
            "validated from this same sample."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument(
        "--comparison-root",
        action="append",
        default=[],
        type=Path,
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if args.output.exists():
        parser.error(f"refusing overwrite: {args.output}")

    result = evaluate(args.source_root, args.comparison_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2, allow_nan=False)
        fp.write("\n")

    print(json.dumps({
        "comparison_count": result["comparison_count"],
        "overall_correlations": result["overall"]["correlations"],
        "winner_groups": result["overall"]["winner_groups"],
        "by_lead_correlations": {
            lead: value["correlations"]
            for lead, value in result["by_lead"].items()
        },
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
