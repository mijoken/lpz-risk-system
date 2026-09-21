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


def _horizon_summary(rows: list[dict], lead: int) -> dict:
    comparable = [
        row for row in rows
        if row["lead_from_as_of_minutes"] == lead
        and row["verification_status"] == "IDENTITY_MATCHED_ENVELOPE_COMPARISON"
    ]
    motion_iou = [row["motion_envelope"]["iou"] for row in comparable]
    persistence_iou = [row["persistence_envelope"]["iou"] for row in comparable]
    deltas = [a - b for a, b in zip(motion_iou, persistence_iou)]
    tolerance = 1e-12
    return {
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

        observed_features: dict[str, dict] = {}
        projections: list[dict] = []
        for feature in geo_payload.get("features", []):
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
            target_geometry = _envelope_geometry(actual)
            if target_geometry is None:
                row["verification_status"] = "TARGET_GEOGRAPHIC_ENVELOPE_MISSING"
                results.append(row)
                continue

            if row["source_boundary_truncated"] or row["target_boundary_truncated"]:
                row["verification_status"] = "BOUNDARY_TRUNCATED_EXCLUDED"
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

    return {
        "schema_version": "0.1.0",
        "product": "F4_RESEARCH_GEOGRAPHIC_ENVELOPE_OVERLAP_VERIFICATION",
        "source_run_id": run_id,
        "comparison_run_ids": comparison_run_ids,
        "research_mode": "ARCHIVED_PROSPECTIVE_SOURCE_RETROSPECTIVE_VERIFICATION",
        "counts": counts,
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
        "object_identity_semantics": (
            "Same-object comparison requires continuous F4-3 radar primary-match "
            "continuity. This is algorithmic identity, not independent meteorological truth."
        ),
        "envelope_semantics": (
            "Overlap metrics compare convex hulls of threshold-component pixel cells. "
            "Concavities and holes are filled; these are research envelopes, not exact precipitation footprints."
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
