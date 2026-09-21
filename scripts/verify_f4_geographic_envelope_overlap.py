#!/usr/bin/env python3
"""F4-5: verify archived F4-4 research envelopes against future observed envelopes.

Only exact future radar frames are eligible. Same-object comparison requires a
continuous F4-3 primary-match chain. Unresolved identity is UNKNOWN, never a
zero-overlap score or negative LPZ label. Boundary-truncated source/target
components are excluded from envelope-overlap metrics.

The evaluated source polygons must already exist in the archived prospective
F4-4 product; this script does not regenerate or retune the source projection.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

from build_f4_research_motion_baseline import utc
from trace_f4_radar_identity_across_slots import trace_identity
from lpz_risk.polygon_overlap import convex_polygon_overlap_metrics


def _read(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _component_signature(component: dict) -> tuple:
    return (
        component["local_id"],
        component["pixel_count"],
        json.dumps(component["centroid_pixel"], sort_keys=True),
        json.dumps(component["centroid"], sort_keys=True),
        tuple(component["bbox_pixel"]),
        component["boundary_truncated"],
    )


def _safe_tracking_bundle(bundle: dict) -> bool:
    tracking = bundle.get("components", {}).get("radar_tracking", {})
    return bool(
        bundle.get("bundle_complete") is True
        and bundle.get("as_of_time_guard_pass") is True
        and bundle.get("risk_engine_allowed") is False
        and tracking.get("execution_ok") is True
        and tracking.get("scientific_tracking_proven") is True
        and tracking.get("fixed_mosaic") is not None
    )


def _collect_bundles(roots: list[Path]) -> list[dict]:
    records: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for root in roots:
        manifest = _read(root / "batch_manifest.json")
        if manifest.get("risk_engine_allowed") is not False:
            raise ValueError("comparison batch risk lock not proven")
        run_id = str(manifest.get("run_id") or "")
        rows = manifest.get("slot_results")
        if not isinstance(rows, list) or len(rows) != manifest.get("requested_slot_count"):
            raise ValueError("comparison batch slot count mismatch")
        for row in rows:
            slot = row.get("collection_slot_utc")
            name = utc(slot).strftime("%Y%m%dT%H%M%SZ.json")
            key = (run_id, name)
            if key in seen:
                raise ValueError("duplicate comparison bundle")
            seen.add(key)
            bundle = _read(root / "slots" / name)
            if bundle.get("collection_slot_utc") != slot:
                raise ValueError("comparison bundle slot mismatch")
            if not _safe_tracking_bundle(bundle):
                continue
            records.append({
                "root": root,
                "run_id": run_id,
                "source_file": name,
                "bundle": bundle,
            })
    return records


def _exact_target_bundle(
    records: list[dict],
    *,
    source_bundle: dict,
    source_run_id: str,
    source_file: str,
    target_valid_time_utc: str,
) -> dict | None:
    source_as_of = utc(source_bundle["prospective_as_of_utc"])
    target_time = utc(target_valid_time_utc)
    source_grid = source_bundle["components"]["radar_tracking"]["fixed_mosaic"]
    candidates = []
    for record in records:
        bundle = record["bundle"]
        if record["run_id"] == source_run_id and record["source_file"] == source_file:
            continue
        tracking = bundle["components"]["radar_tracking"]
        if tracking["fixed_mosaic"] != source_grid:
            continue
        as_of = utc(bundle["prospective_as_of_utc"])
        if as_of < target_time or as_of <= source_as_of:
            continue
        frames = tracking["tracking"]["30"]["frames"]
        if any(frame["valid_time"] == target_valid_time_utc for frame in frames):
            candidates.append(record)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda record: (
            utc(record["bundle"]["prospective_as_of_utc"]),
            record["bundle"]["collection_slot_utc"],
            record["run_id"],
        ),
    )


def _target_component_from_selected_bundle(
    identity_component: dict,
    target_bundle: dict,
    target_valid_time_utc: str,
) -> dict:
    frames = target_bundle["components"]["radar_tracking"]["tracking"]["30"]["frames"]
    matches = [frame for frame in frames if frame["valid_time"] == target_valid_time_utc]
    if len(matches) != 1:
        raise ValueError("selected target exact frame is not unique")
    signature = _component_signature(identity_component)
    components = [
        component for component in matches[0]["components"]
        if _component_signature(component) == signature
    ]
    if len(components) != 1:
        raise ValueError("identity target component absent from selected exact target frame")
    return components[0]


def _envelope_geometry(component: dict) -> dict | None:
    envelope = component.get("geographic_envelope")
    if envelope is None:
        return None
    if (
        not isinstance(envelope, dict)
        or envelope.get("method") != "CONVEX_HULL_OF_COMPONENT_PIXEL_CELLS"
        or envelope.get("exact_precipitation_contour") is not False
        or not isinstance(envelope.get("geometry"), dict)
        or envelope["geometry"].get("type") != "Polygon"
    ):
        raise ValueError("invalid component geographic envelope")
    return envelope["geometry"]


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _counter_dict(values) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values if value).items()))


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("percentile fraction outside [0, 1]")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _break_geometry_summary(rows: list[dict]) -> dict:
    diagnostics = [
        row.get("identity_break_diagnostic") or {}
        for row in rows
        if row["verification_status"] == "IDENTITY_UNRESOLVED_UNKNOWN"
    ]
    nearest = [
        diag.get("nearest_next_frame_component")
        for diag in diagnostics
        if isinstance(diag.get("nearest_next_frame_component"), dict)
    ]
    distances = [
        float(item["centroid_displacement_pixels"])
        for item in nearest
        if item.get("centroid_displacement_pixels") is not None
    ]
    size_ratios = []
    bbox_intersects_true = 0
    bbox_intersects_false = 0
    for row, diag in zip(
        [
            row for row in rows
            if row["verification_status"] == "IDENTITY_UNRESOLVED_UNKNOWN"
        ],
        diagnostics,
    ):
        item = diag.get("nearest_next_frame_component")
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox_intersects")
        if bbox is True:
            bbox_intersects_true += 1
        elif bbox is False:
            bbox_intersects_false += 1
        previous_pixels = diag.get("previous_component_pixel_count")
        next_pixels = item.get("pixel_count")
        if (
            isinstance(previous_pixels, (int, float))
            and isinstance(next_pixels, (int, float))
            and previous_pixels > 0
            and next_pixels > 0
        ):
            size_ratios.append(float(next_pixels) / float(previous_pixels))

    thresholds = (1, 2, 3, 5, 8, 10, 15, 20)
    return {
        "nearest_component_available_count": len(nearest),
        "nearest_centroid_displacement_pixels": {
            "min": min(distances) if distances else None,
            "median": _median(distances),
            "p75": _percentile(distances, 0.75),
            "p90": _percentile(distances, 0.90),
            "max": max(distances) if distances else None,
            "within_threshold_counts": {
                str(threshold): sum(value <= threshold for value in distances)
                for threshold in thresholds
            },
        },
        "nearest_bbox_intersects_true_count": bbox_intersects_true,
        "nearest_bbox_intersects_false_count": bbox_intersects_false,
        "nearest_to_previous_pixel_count_ratio": {
            "median": _median(size_ratios),
            "p10": _percentile(size_ratios, 0.10),
            "p90": _percentile(size_ratios, 0.90),
        },
        "death_record_count_distribution": _counter_dict(
            str(diag.get("death_records"))
            for diag in diagnostics
            if diag.get("death_records") is not None
        ),
    }


def _identity_diagnostics(rows: list[dict]) -> dict:
    unresolved = [
        row for row in rows
        if row["verification_status"] == "IDENTITY_UNRESOLVED_UNKNOWN"
    ]
    break_categories = [
        (row.get("identity_break_diagnostic") or {}).get("association_category")
        for row in unresolved
    ]
    by_category = {}
    for category in sorted(set(value for value in break_categories if value)):
        category_rows = [
            row for row in unresolved
            if (row.get("identity_break_diagnostic") or {}).get(
                "association_category"
            ) == category
        ]
        by_category[category] = {
            "count": len(category_rows),
            "geometry": _break_geometry_summary(category_rows),
        }

    return {
        "unresolved_count": len(unresolved),
        "identity_status_counts": _counter_dict(
            row.get("identity_status") for row in unresolved
        ),
        "break_association_category_counts": _counter_dict(break_categories),
        "all_break_geometry": _break_geometry_summary(unresolved),
        "break_geometry_by_category": by_category,
    }


def _horizon_summary(rows: list[dict], lead: int) -> dict:
    horizon_rows = [
        row for row in rows if row["lead_from_as_of_minutes"] == lead
    ]
    comparable = [
        row for row in horizon_rows
        if row["verification_status"] == "IDENTITY_MATCHED_ENVELOPE_COMPARISON"
    ]
    exact_targets = [
        row for row in horizon_rows if row["target_run_id"] is not None
    ]
    verified = [row for row in horizon_rows if row["identity_verified"]]
    motion_iou = [row["motion_envelope"]["iou"] for row in comparable]
    persistence_iou = [row["persistence_envelope"]["iou"] for row in comparable]
    deltas = [a - b for a, b in zip(motion_iou, persistence_iou)]
    tolerance = 1e-12
    diagnostics = _identity_diagnostics(horizon_rows)
    return {
        "projection_count": len(horizon_rows),
        "exact_target_count": len(exact_targets),
        "identity_verified_count": len(verified),
        "identity_unresolved_count": diagnostics["unresolved_count"],
        "identity_verification_rate_among_exact_targets": (
            len(verified) / len(exact_targets) if exact_targets else None
        ),
        "identity_status_counts": diagnostics["identity_status_counts"],
        "break_association_category_counts": diagnostics[
            "break_association_category_counts"
        ],
        "comparison_count": len(comparable),
        "motion_iou_mean": _mean(motion_iou),
        "motion_iou_median": _median(motion_iou),
        "persistence_iou_mean": _mean(persistence_iou),
        "persistence_iou_median": _median(persistence_iou),
        "motion_minus_persistence_iou_mean": _mean(deltas),
        "motion_minus_persistence_iou_median": _median(deltas),
        "motion_higher_iou_count": sum(delta > tolerance for delta in deltas),
        "persistence_higher_iou_count": sum(delta < -tolerance for delta in deltas),
        "equal_iou_count": sum(abs(delta) <= tolerance for delta in deltas),
        "motion_predicted_overlap_fraction_median": _median([
            row["motion_envelope"]["predicted_overlap_fraction"] for row in comparable
        ]),
        "motion_observed_coverage_fraction_median": _median([
            row["motion_envelope"]["observed_coverage_fraction"] for row in comparable
        ]),
        "persistence_predicted_overlap_fraction_median": _median([
            row["persistence_envelope"]["predicted_overlap_fraction"] for row in comparable
        ]),
        "persistence_observed_coverage_fraction_median": _median([
            row["persistence_envelope"]["observed_coverage_fraction"] for row in comparable
        ]),
    }


def evaluate(source_root: Path, comparison_roots: list[Path]) -> dict:
    source_manifest = _read(source_root / "batch_manifest.json")
    geo_manifest = _read(source_root / "f4_geographic_envelopes" / "manifest.json")
    origin_manifest = _read(source_root / "f4_observed_origins" / "manifest.json")
    run_id = str(source_manifest.get("run_id") or "")

    if (
        source_manifest.get("risk_engine_allowed") is not False
        or geo_manifest.get("product") != "F4_RESEARCH_GEOGRAPHIC_ENVELOPE_BATCH"
        or geo_manifest.get("source_run_id") != run_id
        or geo_manifest.get("risk_engine_allowed") is not False
        or geo_manifest.get("official_risk_output") is not False
        or geo_manifest.get("lpz_forecast_generated") is not False
        or geo_manifest.get("probability_generated") is not False
        or geo_manifest.get("severity_generated") is not False
        or origin_manifest.get("product") != "F4_OBSERVED_ORIGIN_BATCH"
        or origin_manifest.get("source_run_id") != run_id
        or origin_manifest.get("risk_engine_allowed") is not False
        or origin_manifest.get("forecast_generated") is not False
    ):
        raise ValueError("source F4-0/F4-4 research contract mismatch")

    geo_rows = geo_manifest.get("slot_results")
    origin_rows = origin_manifest.get("slot_results")
    if (
        not isinstance(geo_rows, list)
        or not isinstance(origin_rows, list)
        or len(geo_rows) != geo_manifest.get("source_slot_count")
        or len(origin_rows) != origin_manifest.get("source_slot_count")
    ):
        raise ValueError("source F4 slot manifest mismatch")
    origin_by_file = {row["source_file"]: row for row in origin_rows}
    if len(origin_by_file) != len(origin_rows):
        raise ValueError("duplicate F4-0 source file")

    roots = [source_root, *comparison_roots]
    records = _collect_bundles(roots)
    comparison_run_ids = sorted({
        record["run_id"] for record in records if record["run_id"] != run_id
    })

    results: list[dict] = []

    for geo_row in geo_rows:
        if geo_row["research_status"] != "RESEARCH_GEOGRAPHIC_ENVELOPE":
            continue
        name = geo_row["source_file"]
        if Path(name).name != name:
            raise ValueError("invalid F4-4 source file")
        source_bundle = _read(source_root / "slots" / name)
        if not _safe_tracking_bundle(source_bundle):
            raise ValueError("unsafe source tracking bundle")
        if source_bundle.get("collection_slot_utc") != geo_row["collection_slot_utc"]:
            raise ValueError("source F4-4 slot mismatch")

        origin_row = origin_by_file.get(name)
        if origin_row is None or origin_row.get("join_status") != "OBSERVED_INPUT_JOINED":
            raise ValueError("F4-4 slot lacks F4-0 observed-origin source")

        geo_path = source_root / geo_row["output_file"]
        expected_geo = source_root / "f4_geographic_envelopes" / "slots" / name
        if geo_path.resolve() != expected_geo.resolve():
            raise ValueError("F4-4 output path mismatch")
        geo_payload = _read(geo_path)

        origin_path = source_root / origin_row["output_file"]
        expected_origin = source_root / "f4_observed_origins" / "slots" / name
        if origin_path.resolve() != expected_origin.resolve():
            raise ValueError("F4-0 output path mismatch")
        origin_payload = _read(origin_path)

        if (
            geo_payload.get("product") != "F4_RESEARCH_GEOGRAPHIC_ENVELOPES"
            or geo_payload.get("risk_engine_allowed") is not False
            or geo_payload.get("official_risk_output") is not False
            or geo_payload.get("lpz_forecast_generated") is not False
            or geo_payload.get("probability_generated") is not False
            or geo_payload.get("severity_generated") is not False
            or geo_payload.get("source_as_of_utc") != source_bundle.get("prospective_as_of_utc")
            or origin_payload.get("source_as_of_utc") != geo_payload.get("source_as_of_utc")
        ):
            raise ValueError("F4-4 slot research contract mismatch")

        origin_objects = {
            row["research_object_id"]: row for row in origin_payload.get("objects", [])
        }
        if len(origin_objects) != origin_payload.get("research_object_count"):
            raise ValueError("duplicate or missing F4-0 research object")

        features = geo_payload.get("features")
        if not isinstance(features, list) or len(features) != geo_payload.get("feature_count"):
            raise ValueError("F4-4 feature count mismatch")

        observed_features: dict[str, dict] = {}
        projections: list[dict] = []
        for feature in features:
            props = feature.get("properties") or {}
            object_id = str(props.get("research_object_id") or "")
            if not object_id:
                raise ValueError("F4-4 feature research_object_id missing")
            if props.get("kind") == "OBSERVED_THRESHOLD_COMPONENT_ENVELOPE":
                if object_id in observed_features:
                    raise ValueError("duplicate F4-4 observed envelope")
                observed_features[object_id] = feature
            elif props.get("kind") == "PROJECTED_RESEARCH_GEOGRAPHIC_ENVELOPE":
                projections.append(feature)
            else:
                raise ValueError("unexpected F4-4 feature kind")

        if (
            len(observed_features) != geo_payload.get("source_envelope_count")
            or len(projections) != geo_payload.get("projected_envelope_count")
        ):
            raise ValueError("F4-4 observed/projected envelope counts disagree")

        for feature in projections:
            props = feature["properties"]
            object_id = str(props["research_object_id"])
            lead = int(props["lead_from_as_of_minutes"])
            if lead not in (15, 30):
                raise ValueError("unexpected F4-4 lead")
            observed_feature = observed_features.get(object_id)
            origin = origin_objects.get(object_id)
            if observed_feature is None or origin is None:
                raise ValueError("F4-4 projection lacks observed origin")
            if (
                origin.get("origin_status") != "OBSERVED_AT_LATEST_FRAME"
                or origin.get("parent_lineage_id") != props.get("parent_lineage_id")
                or observed_feature["properties"].get("parent_lineage_id")
                != props.get("parent_lineage_id")
            ):
                raise ValueError("F4-4 origin lineage mismatch")

            observed_component = origin.get("observed_component") or {}
            source_geometry = _envelope_geometry(observed_component)
            if source_geometry is None:
                raise ValueError("F4-4 projection source envelope missing")
            if source_geometry != observed_feature.get("geometry"):
                raise ValueError("F4-4 observed feature differs from F4-0 envelope")

            target_valid = props["target_valid_time_utc"]
            target_record = _exact_target_bundle(
                records,
                source_bundle=source_bundle,
                source_run_id=run_id,
                source_file=name,
                target_valid_time_utc=target_valid,
            )
            row = {
                "source_run_id": run_id,
                "source_file": name,
                "source_slot_utc": source_bundle["collection_slot_utc"],
                "source_as_of_utc": geo_payload["source_as_of_utc"],
                "research_object_id": object_id,
                "parent_lineage_id": props["parent_lineage_id"],
                "lead_from_as_of_minutes": lead,
                "target_valid_time_utc": target_valid,
                "target_run_id": None,
                "target_slot_utc": None,
                "target_as_of_utc": None,
                "verification_status": None,
                "identity_status": "NOT_EVALUATED",
                "identity_verified": False,
                "verified_transition_count": None,
                "identity_break_diagnostic": None,
                "source_boundary_truncated": bool(observed_component.get("boundary_truncated")),
                "target_boundary_truncated": None,
                "motion_envelope": None,
                "persistence_envelope": None,
                "motion_minus_persistence_iou": None,
                "risk_engine_allowed": False,
                "lpz_forecast_generated": False,
                "probability": None,
                "severity": None,
            }

            if target_record is None:
                row["verification_status"] = "NO_EXACT_FUTURE_TARGET_IN_PROVIDED_ARTIFACTS"
                results.append(row)
                continue

            target_bundle = target_record["bundle"]
            row["target_run_id"] = target_record["run_id"]
            row["target_slot_utc"] = target_bundle["collection_slot_utc"]
            row["target_as_of_utc"] = target_bundle["prospective_as_of_utc"]

            bridges = [
                record["bundle"] for record in records
                if not (
                    record["run_id"] == run_id
                    and record["source_file"] == name
                )
            ]
            identity = trace_identity(
                source_bundle,
                str(props["parent_lineage_id"]),
                target_valid,
                bridges,
            )
            row["identity_status"] = identity["status"]
            row["identity_verified"] = bool(identity["identity_verified"])
            row["verified_transition_count"] = identity.get("verified_transition_count")
            row["identity_break_diagnostic"] = identity.get("break_diagnostic")

            if not identity["identity_verified"]:
                row["verification_status"] = "IDENTITY_UNRESOLVED_UNKNOWN"
                results.append(row)
                continue

            actual = _target_component_from_selected_bundle(
                identity["target_component"],
                target_bundle,
                target_valid,
            )
            row["target_boundary_truncated"] = bool(actual.get("boundary_truncated"))
            if row["source_boundary_truncated"] or row["target_boundary_truncated"]:
                # Validate a present envelope but do not require one for an
                # already-excluded boundary-truncated target.
                if actual.get("geographic_envelope") is not None:
                    _envelope_geometry(actual)
                row["verification_status"] = "BOUNDARY_TRUNCATED_EXCLUDED"
                results.append(row)
                continue

            target_geometry = _envelope_geometry(actual)
            if target_geometry is None:
                row["verification_status"] = "TARGET_GEOGRAPHIC_ENVELOPE_MISSING"
                results.append(row)
                continue

            motion = convex_polygon_overlap_metrics(feature["geometry"], target_geometry)
            persistence = convex_polygon_overlap_metrics(source_geometry, target_geometry)
            row["motion_envelope"] = motion
            row["persistence_envelope"] = persistence
            row["motion_minus_persistence_iou"] = motion["iou"] - persistence["iou"]
            row["verification_status"] = "IDENTITY_MATCHED_ENVELOPE_COMPARISON"
            results.append(row)

    counts = {
        "projection_count": len(results),
        "exact_target_count": sum(
            row["target_run_id"] is not None for row in results
        ),
        "identity_verified_count": sum(row["identity_verified"] for row in results),
        "identity_unresolved_count": sum(
            row["verification_status"] == "IDENTITY_UNRESOLVED_UNKNOWN"
            for row in results
        ),
        "boundary_truncated_excluded_count": sum(
            row["verification_status"] == "BOUNDARY_TRUNCATED_EXCLUDED"
            for row in results
        ),
        "target_envelope_missing_count": sum(
            row["verification_status"] == "TARGET_GEOGRAPHIC_ENVELOPE_MISSING"
            for row in results
        ),
        "comparable_envelope_count": sum(
            row["verification_status"] == "IDENTITY_MATCHED_ENVELOPE_COMPARISON"
            for row in results
        ),
        "no_exact_target_count": sum(
            row["verification_status"] == "NO_EXACT_FUTURE_TARGET_IN_PROVIDED_ARTIFACTS"
            for row in results
        ),
    }

    identity_diagnostics = _identity_diagnostics(results)

    return {
        "schema_version": "0.2.0",
        "product": "F4_RESEARCH_GEOGRAPHIC_ENVELOPE_OVERLAP_VERIFICATION",
        "source_run_id": run_id,
        "comparison_run_ids": comparison_run_ids,
        "research_mode": "ARCHIVED_PROSPECTIVE_SOURCE_RETROSPECTIVE_VERIFICATION",
        "counts": counts,
        "identity_diagnostics": identity_diagnostics,
        "horizons_from_as_of_minutes": {
            str(lead): _horizon_summary(results, lead) for lead in (15, 30)
        },
        "results": results,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
        "validated_forecast": False,
        "metric_projection": "WEB_MERCATOR_TRACKING_PLANE",
        "object_identity_semantics": (
            "Same-object comparison requires continuous F4-3 radar primary-match "
            "continuity. This is algorithmic identity, not independent meteorological truth."
        ),
        "envelope_semantics": (
            "Overlap metrics compare convex hulls of threshold-component pixel cells in the "
            "native Web Mercator tracking plane. Concavities and holes are filled; planar area "
            "fields are not geodesic area. These are research envelopes, not exact precipitation footprints."
        ),
        "interpretation": (
            "Research-only overlap verification of already-archived prospective F4-4 envelopes. "
            "Unresolved identity and boundary-truncated geometry are excluded rather than scored as failures. "
            "Motion and persistence IoU are descriptive comparisons and do not establish validated LPZ forecast skill."
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
        help="Additional archived prospective batch root; may be repeated.",
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
        "source_run_id": result["source_run_id"],
        **result["counts"],
        "horizons_from_as_of_minutes": result["horizons_from_as_of_minutes"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
