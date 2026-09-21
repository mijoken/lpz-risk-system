#!/usr/bin/env python3
"""F4-6B research-only candidate study for zero-overlap identity breaks.

Calibrates motion-distance plus competitor-margin gates on archived cases where
the existing overlap-based tracker already has a known clean primary match.
Then applies the SAME gates to F4-5 NO_RECORDED_OVERLAP_CANDIDATE breaks.

The output contains candidate counts only. It does not create identity links,
change tracking, score LPZ risk, or validate zero-overlap identities.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

from evaluate_f4_motion_association_separability import evaluate as evaluate_separability
from verify_f4_geographic_envelope_overlap import evaluate as evaluate_envelopes


DISTANCE_GATES_PIXELS = (3, 5, 8, 10, 15, 20)
MARGIN_GATES_PIXELS = (0, 1, 2, 3, 5, 8)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _summary(values: list[float]) -> dict:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "median": statistics.median(values) if values else None,
        "p75": _percentile(values, 0.75),
        "p90": _percentile(values, 0.90),
        "max": max(values) if values else None,
    }


def _margin_passes(margin: float | None, minimum_margin: float) -> bool:
    # No second component means no competing candidate in that frame.
    return margin is None or margin >= minimum_margin


def _calibration_rows(separability: dict) -> list[dict]:
    return [
        row for row in separability.get("samples", [])
        if row.get("clean_sample") is True
    ]


def _calibration_gate_table(rows: list[dict]) -> dict:
    total = len(rows)
    output = {}
    for distance in DISTANCE_GATES_PIXELS:
        for margin in MARGIN_GATES_PIXELS:
            accepted = [
                row for row in rows
                if float(row["motion_nearest_distance_pixels"]) <= distance
                and _margin_passes(
                    row.get("motion_true_vs_nearest_competitor_margin_pixels"),
                    margin,
                )
            ]
            correct = [
                row for row in accepted
                if row.get("motion_top1_matches_primary") is True
            ]
            wrong = len(accepted) - len(correct)
            output[f"d{distance}_m{margin}"] = {
                "distance_gate_pixels": distance,
                "minimum_competitor_margin_pixels": margin,
                "accepted_count": len(accepted),
                "correct_count": len(correct),
                "wrong_count": wrong,
                "proxy_precision": (
                    len(correct) / len(accepted) if accepted else None
                ),
                "correct_coverage_of_all_clean_samples": (
                    len(correct) / total if total else None
                ),
            }
    return output


def _rescue_rows(f4_result: dict) -> list[dict]:
    rows = []
    for row in f4_result.get("results", []):
        if row.get("verification_status") != "IDENTITY_UNRESOLVED_UNKNOWN":
            continue
        diagnostic = row.get("identity_break_diagnostic") or {}
        if diagnostic.get("association_category") != "NO_RECORDED_OVERLAP_CANDIDATE":
            continue
        motion = diagnostic.get("motion_candidate_diagnostic")
        candidate = motion.get("nearest_candidate") if isinstance(motion, dict) else None
        output = {
            "source_slot_utc": row.get("source_slot_utc"),
            "research_object_id": row.get("research_object_id"),
            "lead_from_as_of_minutes": row.get("lead_from_as_of_minutes"),
            "break_from_valid_time_utc": diagnostic.get("from_valid_time_utc"),
            "break_to_valid_time_utc": diagnostic.get("to_valid_time_utc"),
            "motion_reference_available": isinstance(motion, dict),
            "previous_component_boundary_truncated": bool(
                diagnostic.get("previous_component_boundary_truncated")
            ),
            "motion_error_pixels": None,
            "competitor_margin_pixels": None,
            "candidate_count": None,
            "candidate_pixel_count_ratio_to_current": None,
            "candidate_boundary_truncated": None,
            "candidate_local_id": None,
            "research_candidate_only": True,
        }
        if isinstance(motion, dict) and isinstance(candidate, dict):
            output.update({
                "motion_error_pixels": float(candidate["motion_error_pixels"]),
                "competitor_margin_pixels": (
                    float(motion["nearest_to_second_margin_pixels"])
                    if motion.get("nearest_to_second_margin_pixels") is not None
                    else None
                ),
                "candidate_count": int(motion["candidate_count"]),
                "candidate_pixel_count_ratio_to_current": (
                    float(candidate["pixel_count_ratio_to_current"])
                    if candidate.get("pixel_count_ratio_to_current") is not None
                    else None
                ),
                "candidate_boundary_truncated": bool(
                    candidate.get("boundary_truncated")
                ),
                "candidate_local_id": int(candidate["local_id"]),
            })
        rows.append(output)
    return rows


def _rescue_gate_table(rows: list[dict]) -> dict:
    eligible = [
        row for row in rows
        if row["motion_reference_available"]
        and not row["previous_component_boundary_truncated"]
        and row["candidate_boundary_truncated"] is False
        and row["motion_error_pixels"] is not None
    ]
    output = {}
    for distance in DISTANCE_GATES_PIXELS:
        for margin in MARGIN_GATES_PIXELS:
            accepted = [
                row for row in eligible
                if float(row["motion_error_pixels"]) <= distance
                and _margin_passes(row["competitor_margin_pixels"], margin)
            ]
            ratios = [
                float(row["candidate_pixel_count_ratio_to_current"])
                for row in accepted
                if row["candidate_pixel_count_ratio_to_current"] is not None
            ]
            output[f"d{distance}_m{margin}"] = {
                "distance_gate_pixels": distance,
                "minimum_competitor_margin_pixels": margin,
                "candidate_count": len(accepted),
                "lead_15_candidate_count": sum(
                    int(row["lead_from_as_of_minutes"]) == 15
                    for row in accepted
                ),
                "lead_30_candidate_count": sum(
                    int(row["lead_from_as_of_minutes"]) == 30
                    for row in accepted
                ),
                "candidate_fraction_of_all_no_overlap_breaks": (
                    len(accepted) / len(rows) if rows else None
                ),
                "candidate_pixel_count_ratio": _summary(ratios),
            }
    return output


def evaluate(
    source_root: Path,
    comparison_roots: list[Path],
    all_batch_roots: list[Path],
) -> dict:
    f4_result = evaluate_envelopes(source_root, comparison_roots)
    separability = evaluate_separability(all_batch_roots)

    if (
        f4_result.get("risk_engine_allowed") is not False
        or f4_result.get("lpz_forecast_generated") is not False
        or f4_result.get("validated_forecast") is not False
        or separability.get("risk_engine_allowed") is not False
        or separability.get("tracking_changed") is not False
        or separability.get("identity_inference_generated") is not False
    ):
        raise ValueError("research locks not proven")

    calibration_rows = _calibration_rows(separability)
    rescue_rows = _rescue_rows(f4_result)
    motion_available = [
        row for row in rescue_rows if row["motion_reference_available"]
    ]
    clean_motion_available = [
        row for row in motion_available
        if not row["previous_component_boundary_truncated"]
        and row["candidate_boundary_truncated"] is False
    ]

    motion_errors = [
        float(row["motion_error_pixels"])
        for row in clean_motion_available
        if row["motion_error_pixels"] is not None
    ]
    margins = [
        float(row["competitor_margin_pixels"])
        for row in clean_motion_available
        if row["competitor_margin_pixels"] is not None
    ]
    ratios = [
        float(row["candidate_pixel_count_ratio_to_current"])
        for row in clean_motion_available
        if row["candidate_pixel_count_ratio_to_current"] is not None
    ]

    return {
        "schema_version": "0.1.0",
        "product": "F4_ZERO_OVERLAP_MOTION_RESCUE_CANDIDATE_RESEARCH",
        "source_run_id": f4_result["source_run_id"],
        "comparison_run_ids": f4_result["comparison_run_ids"],
        "calibration_source_run_ids": separability["source_run_ids"],
        "research_mode": "KNOWN_MATCH_CALIBRATION_THEN_ZERO_OVERLAP_CANDIDATE_SCREEN",
        "calibration_clean_known_match_count": len(calibration_rows),
        "zero_overlap_break_count": len(rescue_rows),
        "motion_reference_available_count": len(motion_available),
        "clean_motion_candidate_count": len(clean_motion_available),
        "motion_error_pixels": _summary(motion_errors),
        "competitor_margin_pixels": _summary(margins),
        "candidate_pixel_count_ratio": _summary(ratios),
        "calibration_gate_table": _calibration_gate_table(calibration_rows),
        "rescue_gate_table": _rescue_gate_table(rescue_rows),
        "candidates": rescue_rows,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "tracking_changed": False,
        "identity_inference_generated": False,
        "zero_overlap_identity_verified": False,
        "interpretation": (
            "Candidate-screening research only. Gate precision is calibrated against existing "
            "clean overlap-based primary matches, which are an engineering proxy rather than "
            "independent truth. Applying the same gate to zero-overlap breaks does NOT verify "
            "identity. No production tracking decision is made by this artifact."
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
    parser.add_argument(
        "--batch-root",
        action="append",
        required=True,
        type=Path,
        help="Archived batch root for known-match calibration; repeat as needed.",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing overwrite: {args.output}")
    result = evaluate(
        args.source_root,
        args.comparison_root,
        args.batch_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2, allow_nan=False)
        fp.write("\n")
    print(json.dumps({
        "calibration_clean_known_match_count": result[
            "calibration_clean_known_match_count"
        ],
        "zero_overlap_break_count": result["zero_overlap_break_count"],
        "motion_reference_available_count": result[
            "motion_reference_available_count"
        ],
        "clean_motion_candidate_count": result["clean_motion_candidate_count"],
        "motion_error_pixels": result["motion_error_pixels"],
        "competitor_margin_pixels": result["competitor_margin_pixels"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
