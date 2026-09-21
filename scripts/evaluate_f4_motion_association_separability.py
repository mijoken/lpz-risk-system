#!/usr/bin/env python3
"""F4-6A research-only separability study for motion-aware radar association.

Uses archived transitions where the current overlap-based tracker already has
an explicit primary match. The overlap identity is treated only as a proxy
reference for engineering calibration. The candidate selector itself receives
no overlap metrics: it extrapolates the previous two centroids by one 5-minute
step and ranks all current components by centroid distance.

This script does NOT alter tracking, create new identities, generate LPZ
forecasts, or tune the production Risk Engine.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path


DISTANCE_GATES_PIXELS = (3, 5, 8, 10, 15, 20)


def _read(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _slot_filename(value: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"expected UTC Z slot timestamp: {value!r}")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"slot timestamp is not UTC: {value!r}")
    return parsed.strftime("%Y%m%dT%H%M%SZ.json")


def _component_signature(component: dict) -> tuple:
    return (
        int(component["local_id"]),
        int(component["pixel_count"]),
        round(float(component["centroid_pixel"]["row"]), 9),
        round(float(component["centroid_pixel"]["col"]), 9),
        tuple(int(v) for v in component["bbox_pixel"]),
        bool(component["boundary_truncated"]),
    )


def _distance(a_row: float, a_col: float, b_row: float, b_col: float) -> float:
    return math.hypot(b_row - a_row, b_col - a_col)


def _nearest(
    components: list[dict],
    target_row: float,
    target_col: float,
) -> tuple[int, float, bool]:
    ranked = sorted(
        (
            (
                _distance(
                    target_row,
                    target_col,
                    float(component["centroid_pixel"]["row"]),
                    float(component["centroid_pixel"]["col"]),
                ),
                int(component["local_id"]),
            )
            for component in components
        ),
        key=lambda item: (item[0], item[1]),
    )
    if not ranked:
        raise ValueError("cannot rank empty current component set")
    best_distance, best_id = ranked[0]
    tied = len(ranked) > 1 and abs(ranked[1][0] - best_distance) <= 1e-12
    return best_id, best_distance, tied


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


def _structure_flags(transition: dict, previous_id: int, current_id: int) -> tuple[bool, bool]:
    split = any(
        int(row.get("previous_id")) == previous_id
        for row in transition.get("split_candidates", [])
    )
    merge = any(
        int(row.get("current_id")) == current_id
        and previous_id in [int(v) for v in row.get("previous_ids", [])]
        for row in transition.get("merge_candidates", [])
    )
    return split, merge


def _safe_bundle(bundle: dict) -> bool:
    radar = bundle.get("components", {}).get("radar_tracking", {})
    return bool(
        bundle.get("bundle_complete") is True
        and bundle.get("as_of_time_guard_pass") is True
        and bundle.get("risk_engine_allowed") is False
        and radar.get("execution_ok") is True
        and radar.get("scientific_tracking_proven") is True
        and radar.get("fixed_mosaic") is not None
    )


def _iter_bundle_samples(bundle: dict, run_id: str, source_file: str):
    radar = bundle["components"]["radar_tracking"]
    tracking = radar["tracking"]["30"]
    frames = tracking["frames"]
    transitions = tracking["transitions"]
    if len(frames) < 3 or len(transitions) != len(frames) - 1:
        raise ValueError("unexpected radar frame/transition cardinality")

    for transition_index in range(1, len(transitions)):
        prior_transition = transitions[transition_index - 1]
        transition = transitions[transition_index]
        previous_frame = frames[transition_index]
        prior_frame = frames[transition_index - 1]
        current_frame = frames[transition_index + 1]

        if (
            prior_transition["to_valid_time"] != transition["from_valid_time"]
            or prior_transition["from_valid_time"] != prior_frame["valid_time"]
            or transition["from_valid_time"] != previous_frame["valid_time"]
            or transition["to_valid_time"] != current_frame["valid_time"]
        ):
            raise ValueError("transition/frame time mismatch")
        if (
            float(prior_transition.get("elapsed_seconds", 0)) != 300.0
            or float(transition.get("elapsed_seconds", 0)) != 300.0
        ):
            continue

        prior_by_current: dict[int, list[dict]] = {}
        for match in prior_transition.get("primary_matches", []):
            prior_by_current.setdefault(int(match["current_id"]), []).append(match)

        prior_components = {
            int(component["local_id"]): component
            for component in prior_frame["components"]
        }
        previous_components = {
            int(component["local_id"]): component
            for component in previous_frame["components"]
        }
        current_components = {
            int(component["local_id"]): component
            for component in current_frame["components"]
        }

        for match in transition.get("primary_matches", []):
            previous_id = int(match["previous_id"])
            current_id = int(match["current_id"])
            history = prior_by_current.get(previous_id, [])
            if len(history) != 1:
                yield {
                    "status": "NO_UNIQUE_TWO_FRAME_HISTORY",
                    "run_id": run_id,
                    "source_file": source_file,
                    "from_valid_time_utc": transition["from_valid_time"],
                    "to_valid_time_utc": transition["to_valid_time"],
                }
                continue

            prior_previous_id = int(history[0]["previous_id"])
            prior_component = prior_components.get(prior_previous_id)
            previous_component = previous_components.get(previous_id)
            current_component = current_components.get(current_id)
            if prior_component is None or previous_component is None or current_component is None:
                raise ValueError("primary match component missing from archived frame")

            current_list = list(current_components.values())
            if not current_list:
                raise ValueError("primary match exists with empty current frame")

            prior_row = float(prior_component["centroid_pixel"]["row"])
            prior_col = float(prior_component["centroid_pixel"]["col"])
            previous_row = float(previous_component["centroid_pixel"]["row"])
            previous_col = float(previous_component["centroid_pixel"]["col"])
            actual_row = float(current_component["centroid_pixel"]["row"])
            actual_col = float(current_component["centroid_pixel"]["col"])

            velocity_row = previous_row - prior_row
            velocity_col = previous_col - prior_col
            predicted_row = previous_row + velocity_row
            predicted_col = previous_col + velocity_col

            motion_id, motion_nearest_distance, motion_tied = _nearest(
                current_list, predicted_row, predicted_col
            )
            persistence_id, persistence_nearest_distance, persistence_tied = _nearest(
                current_list, previous_row, previous_col
            )
            true_motion_distance = _distance(
                predicted_row, predicted_col, actual_row, actual_col
            )
            true_persistence_distance = _distance(
                previous_row, previous_col, actual_row, actual_col
            )
            competitors = [
                _distance(
                    predicted_row,
                    predicted_col,
                    float(component["centroid_pixel"]["row"]),
                    float(component["centroid_pixel"]["col"]),
                )
                for cid, component in current_components.items()
                if cid != current_id
            ]
            nearest_competitor_distance = min(competitors) if competitors else None
            margin = (
                nearest_competitor_distance - true_motion_distance
                if nearest_competitor_distance is not None
                else None
            )
            split, merge = _structure_flags(transition, previous_id, current_id)
            boundary = any(
                bool(component.get("boundary_truncated"))
                for component in (prior_component, previous_component, current_component)
            )
            previous_pixels = int(previous_component["pixel_count"])
            current_pixels = int(current_component["pixel_count"])
            size_ratio = current_pixels / previous_pixels if previous_pixels > 0 else None

            yield {
                "status": "KNOWN_PRIMARY_MATCH_SAMPLE",
                "run_id": run_id,
                "source_file": source_file,
                "from_valid_time_utc": transition["from_valid_time"],
                "to_valid_time_utc": transition["to_valid_time"],
                "previous_id": previous_id,
                "current_id": current_id,
                "prior_previous_id": prior_previous_id,
                "prior_component_signature": _component_signature(prior_component),
                "previous_component_signature": _component_signature(previous_component),
                "current_component_signature": _component_signature(current_component),
                "current_component_count": len(current_list),
                "split_candidate": split,
                "merge_candidate": merge,
                "boundary_truncated": boundary,
                "clean_sample": not split and not merge and not boundary,
                "velocity_row_pixels_per_5min": velocity_row,
                "velocity_col_pixels_per_5min": velocity_col,
                "prior_displacement_pixels": math.hypot(velocity_row, velocity_col),
                "actual_displacement_pixels": true_persistence_distance,
                "motion_true_distance_pixels": true_motion_distance,
                "motion_nearest_distance_pixels": motion_nearest_distance,
                "motion_top1_current_id": motion_id,
                "motion_top1_matches_primary": motion_id == current_id and not motion_tied,
                "motion_top1_tied": motion_tied,
                "persistence_nearest_distance_pixels": persistence_nearest_distance,
                "persistence_top1_current_id": persistence_id,
                "persistence_top1_matches_primary": persistence_id == current_id and not persistence_tied,
                "persistence_top1_tied": persistence_tied,
                "motion_true_vs_nearest_competitor_margin_pixels": margin,
                "current_to_previous_pixel_count_ratio": size_ratio,
            }


def _deduplicate(samples: list[dict]) -> list[dict]:
    unique = {}
    for row in samples:
        if row["status"] != "KNOWN_PRIMARY_MATCH_SAMPLE":
            key = (
                row["status"],
                row["run_id"],
                row["source_file"],
                row["from_valid_time_utc"],
                row["to_valid_time_utc"],
            )
        else:
            key = (
                row["from_valid_time_utc"],
                row["to_valid_time_utc"],
                tuple(row["prior_component_signature"]),
                tuple(row["previous_component_signature"]),
                tuple(row["current_component_signature"]),
            )
        unique.setdefault(key, row)
    return list(unique.values())


def _gate_table(samples: list[dict], field: str, correct_field: str) -> dict:
    output = {}
    total = len(samples)
    for threshold in DISTANCE_GATES_PIXELS:
        accepted = [row for row in samples if float(row[field]) <= threshold]
        correct = [row for row in accepted if row[correct_field] is True]
        output[str(threshold)] = {
            "accepted_count": len(accepted),
            "correct_count": len(correct),
            "proxy_precision": len(correct) / len(accepted) if accepted else None,
            "correct_coverage_of_all_samples": len(correct) / total if total else None,
        }
    return output


def _sample_summary(samples: list[dict]) -> dict:
    if not samples:
        return {
            "sample_count": 0,
            "motion_top1_correct_count": 0,
            "motion_top1_accuracy": None,
            "persistence_top1_correct_count": 0,
            "persistence_top1_accuracy": None,
            "motion_better_count": 0,
            "persistence_better_count": 0,
            "equal_distance_count": 0,
            "motion_true_distance_pixels": _summary([]),
            "persistence_true_distance_pixels": _summary([]),
            "motion_competitor_margin_pixels": _summary([]),
            "pixel_count_ratio": _summary([]),
            "motion_distance_gate_proxy": {},
            "persistence_distance_gate_proxy": {},
        }

    motion_correct = sum(row["motion_top1_matches_primary"] for row in samples)
    persistence_correct = sum(row["persistence_top1_matches_primary"] for row in samples)
    tolerance = 1e-12
    motion_better = sum(
        row["motion_true_distance_pixels"] + tolerance
        < row["actual_displacement_pixels"]
        for row in samples
    )
    persistence_better = sum(
        row["actual_displacement_pixels"] + tolerance
        < row["motion_true_distance_pixels"]
        for row in samples
    )
    equal = len(samples) - motion_better - persistence_better
    margins = [
        float(row["motion_true_vs_nearest_competitor_margin_pixels"])
        for row in samples
        if row["motion_true_vs_nearest_competitor_margin_pixels"] is not None
    ]
    ratios = [
        float(row["current_to_previous_pixel_count_ratio"])
        for row in samples
        if row["current_to_previous_pixel_count_ratio"] is not None
    ]
    return {
        "sample_count": len(samples),
        "motion_top1_correct_count": motion_correct,
        "motion_top1_accuracy": motion_correct / len(samples),
        "persistence_top1_correct_count": persistence_correct,
        "persistence_top1_accuracy": persistence_correct / len(samples),
        "motion_better_count": motion_better,
        "persistence_better_count": persistence_better,
        "equal_distance_count": equal,
        "motion_true_distance_pixels": _summary([
            float(row["motion_true_distance_pixels"]) for row in samples
        ]),
        "persistence_true_distance_pixels": _summary([
            float(row["actual_displacement_pixels"]) for row in samples
        ]),
        "motion_competitor_margin_pixels": _summary(margins),
        "pixel_count_ratio": _summary(ratios),
        "motion_distance_gate_proxy": _gate_table(
            samples,
            "motion_nearest_distance_pixels",
            "motion_top1_matches_primary",
        ),
        "persistence_distance_gate_proxy": _gate_table(
            samples,
            "persistence_nearest_distance_pixels",
            "persistence_top1_matches_primary",
        ),
    }


def evaluate(batch_roots: list[Path]) -> dict:
    if not batch_roots:
        raise ValueError("at least one batch root required")

    all_samples = []
    run_ids = []
    unsafe_bundle_count = 0
    for root in batch_roots:
        manifest = _read(root / "batch_manifest.json")
        if manifest.get("risk_engine_allowed") is not False:
            raise ValueError("batch risk lock not proven")
        run_id = str(manifest.get("run_id") or "")
        if not run_id:
            raise ValueError("batch run_id missing")
        run_ids.append(run_id)
        rows = manifest.get("slot_results")
        if not isinstance(rows, list) or len(rows) != manifest.get("requested_slot_count"):
            raise ValueError("batch slot count mismatch")
        for row in rows:
            slot = row["collection_slot_utc"]
            name = _slot_filename(slot)
            path = root / "slots" / name
            bundle = _read(path)
            if bundle.get("collection_slot_utc") != slot:
                raise ValueError("bundle slot mismatch")
            if not _safe_bundle(bundle):
                unsafe_bundle_count += 1
                continue
            all_samples.extend(_iter_bundle_samples(bundle, run_id, path.name))

    deduped = _deduplicate(all_samples)
    known = [row for row in deduped if row["status"] == "KNOWN_PRIMARY_MATCH_SAMPLE"]
    no_history = [row for row in deduped if row["status"] == "NO_UNIQUE_TWO_FRAME_HISTORY"]
    clean = [row for row in known if row["clean_sample"]]
    structured = [row for row in known if row["split_candidate"] or row["merge_candidate"]]
    boundary = [row for row in known if row["boundary_truncated"]]

    return {
        "schema_version": "0.1.0",
        "product": "F4_MOTION_ASSOCIATION_SEPARABILITY_RESEARCH",
        "source_run_ids": sorted(set(run_ids)),
        "threshold_mmph": 30,
        "research_mode": "ARCHIVED_KNOWN_PRIMARY_MATCH_PROXY_CALIBRATION",
        "raw_sample_count": len(all_samples),
        "deduplicated_known_match_count": len(known),
        "no_unique_two_frame_history_count": len(no_history),
        "unsafe_bundle_count": unsafe_bundle_count,
        "structured_sample_count": len(structured),
        "boundary_sample_count": len(boundary),
        "all_known_matches": _sample_summary(known),
        "clean_known_matches": _sample_summary(clean),
        "samples": known,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "tracking_changed": False,
        "identity_inference_generated": False,
        "interpretation": (
            "Engineering separability study only. Existing overlap-based primary matches are "
            "used as proxy references. Motion candidate ranking itself uses only centroid history "
            "and current component centroids, not overlap. Results do not validate identity in "
            "zero-overlap cases and do not justify production tracking changes by themselves."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batch-root",
        action="append",
        required=True,
        type=Path,
        help="Archived prospective batch root; repeat for multiple runs.",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing overwrite: {args.output}")
    result = evaluate(args.batch_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2, allow_nan=False)
        fp.write("\n")
    print(json.dumps({
        "source_run_ids": result["source_run_ids"],
        "deduplicated_known_match_count": result["deduplicated_known_match_count"],
        "clean_known_match_count": result["clean_known_matches"]["sample_count"],
        "motion_top1_accuracy_clean": result["clean_known_matches"]["motion_top1_accuracy"],
        "persistence_top1_accuracy_clean": result["clean_known_matches"]["persistence_top1_accuracy"],
        "motion_distance_gate_proxy_clean": result["clean_known_matches"]["motion_distance_gate_proxy"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
