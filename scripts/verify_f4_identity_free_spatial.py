#!/usr/bin/env python3
"""F4-7 identity-free spatial verification of archived F4-4 projections.

Question answered:
Did the archived F4-4 projected envelope overlap ANY observed >=30 mm/h
component in the exact future radar frame?

This deliberately does NOT require same-object identity. It evaluates spatial
forecast usefulness of the archived prospective polygon itself. Persistence
uses the source observed envelope left in place as a baseline.

Observed target components that are boundary-truncated or lack a valid
geographic envelope are excluded from scoring. Source boundary-truncated
objects are excluded. Convex-hull envelopes are not exact precipitation
contours and may fill holes/concavities.

No LPZ classification, probability, severity, or production tracking changes
are generated.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

from verify_f4_geographic_envelope_overlap import (
    _collect_bundles,
    _envelope_geometry,
    _exact_target_bundle,
    _read,
    _safe_tracking_bundle,
)
from lpz_risk.polygon_overlap import convex_polygon_overlap_metrics


EARTH_RADIUS_KM = 6371.0088


def _haversine_km(a_lon: float, a_lat: float, b_lon: float, b_lat: float) -> float:
    lat1 = math.radians(a_lat)
    lat2 = math.radians(b_lat)
    dlat = lat2 - lat1
    dlon = math.radians(((b_lon - a_lon + 180.0) % 360.0) - 180.0)
    h = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _exact_target_frame(target_bundle: dict, target_valid_time_utc: str) -> dict:
    frames = target_bundle["components"]["radar_tracking"]["tracking"]["30"]["frames"]
    matches = [frame for frame in frames if frame["valid_time"] == target_valid_time_utc]
    if len(matches) != 1:
        raise ValueError("selected target exact frame is not unique")
    return matches[0]


def _usable_target_components(frame: dict) -> tuple[list[dict], dict]:
    usable = []
    boundary = 0
    missing_envelope = 0
    for component in frame.get("components", []):
        if bool(component.get("boundary_truncated")):
            boundary += 1
            if component.get("geographic_envelope") is not None:
                _envelope_geometry(component)
            continue
        geometry = _envelope_geometry(component)
        if geometry is None:
            missing_envelope += 1
            continue
        usable.append({
            "component": component,
            "geometry": geometry,
        })
    return usable, {
        "target_component_count": len(frame.get("components", [])),
        "usable_target_component_count": len(usable),
        "boundary_target_component_count": boundary,
        "missing_envelope_target_component_count": missing_envelope,
    }


def _best_spatial_match(
    predicted_geometry: dict,
    predicted_centroid_lon_lat: list[float],
    target_components: list[dict],
) -> dict:
    if len(predicted_centroid_lon_lat) != 2:
        raise ValueError("predicted centroid must be [lon, lat]")
    lon0, lat0 = map(float, predicted_centroid_lon_lat)

    rows = []
    for item in target_components:
        component = item["component"]
        metrics = convex_polygon_overlap_metrics(
            predicted_geometry,
            item["geometry"],
        )
        centroid = component.get("centroid") or {}
        lon1 = float(centroid["lon"])
        lat1 = float(centroid["lat"])
        rows.append({
            "local_id": int(component["local_id"]),
            "pixel_count": int(component["pixel_count"]),
            "approx_area_km2": float(component["approx_area_km2"]),
            "centroid_distance_km": _haversine_km(lon0, lat0, lon1, lat1),
            "metrics": metrics,
        })

    if not rows:
        return {
            "target_component_count": 0,
            "any_overlap": False,
            "best_iou": None,
            "best_predicted_overlap_fraction": None,
            "best_observed_coverage_fraction": None,
            "best_target_local_id": None,
            "best_target_pixel_count": None,
            "best_target_approx_area_km2": None,
            "nearest_centroid_distance_km": None,
            "nearest_centroid_target_local_id": None,
        }

    best = max(
        rows,
        key=lambda row: (
            float(row["metrics"]["iou"]),
            float(row["metrics"]["intersection_planar_area_km2"]),
            -float(row["centroid_distance_km"]),
            -int(row["local_id"]),
        ),
    )
    nearest = min(
        rows,
        key=lambda row: (float(row["centroid_distance_km"]), int(row["local_id"])),
    )
    return {
        "target_component_count": len(rows),
        "any_overlap": any(
            float(row["metrics"]["intersection_planar_area_km2"]) > 0.0
            for row in rows
        ),
        "best_iou": float(best["metrics"]["iou"]),
        "best_predicted_overlap_fraction": float(
            best["metrics"]["predicted_overlap_fraction"]
        ),
        "best_observed_coverage_fraction": float(
            best["metrics"]["observed_coverage_fraction"]
        ),
        "best_target_local_id": int(best["local_id"]),
        "best_target_pixel_count": int(best["pixel_count"]),
        "best_target_approx_area_km2": float(best["approx_area_km2"]),
        "nearest_centroid_distance_km": float(nearest["centroid_distance_km"]),
        "nearest_centroid_target_local_id": int(nearest["local_id"]),
    }


def _horizon_summary(rows: list[dict], lead: int) -> dict:
    eligible = [
        row for row in rows
        if row["lead_from_as_of_minutes"] == lead
        and row["verification_status"] == "IDENTITY_FREE_SPATIAL_COMPARISON"
    ]
    motion_iou = [float(row["motion_spatial"]["best_iou"]) for row in eligible]
    persistence_iou = [
        float(row["persistence_spatial"]["best_iou"]) for row in eligible
    ]
    deltas = [a - b for a, b in zip(motion_iou, persistence_iou)]
    tolerance = 1e-12
    return {
        "comparison_count": len(eligible),
        "motion_any_overlap_count": sum(
            bool(row["motion_spatial"]["any_overlap"]) for row in eligible
        ),
        "persistence_any_overlap_count": sum(
            bool(row["persistence_spatial"]["any_overlap"]) for row in eligible
        ),
        "motion_any_overlap_rate": (
            sum(bool(row["motion_spatial"]["any_overlap"]) for row in eligible)
            / len(eligible)
            if eligible
            else None
        ),
        "persistence_any_overlap_rate": (
            sum(bool(row["persistence_spatial"]["any_overlap"]) for row in eligible)
            / len(eligible)
            if eligible
            else None
        ),
        "motion_best_iou_mean": _mean(motion_iou),
        "motion_best_iou_median": _median(motion_iou),
        "persistence_best_iou_mean": _mean(persistence_iou),
        "persistence_best_iou_median": _median(persistence_iou),
        "motion_minus_persistence_best_iou_mean": _mean(deltas),
        "motion_minus_persistence_best_iou_median": _median(deltas),
        "motion_higher_best_iou_count": sum(delta > tolerance for delta in deltas),
        "persistence_higher_best_iou_count": sum(delta < -tolerance for delta in deltas),
        "equal_best_iou_count": sum(abs(delta) <= tolerance for delta in deltas),
        "motion_nearest_centroid_distance_km_median": _median([
            float(row["motion_spatial"]["nearest_centroid_distance_km"])
            for row in eligible
        ]),
        "persistence_nearest_centroid_distance_km_median": _median([
            float(row["persistence_spatial"]["nearest_centroid_distance_km"])
            for row in eligible
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
        raise ValueError("source F4 research contract mismatch")

    geo_rows = geo_manifest.get("slot_results")
    origin_rows = origin_manifest.get("slot_results")
    if not isinstance(geo_rows, list) or not isinstance(origin_rows, list):
        raise ValueError("source F4 manifest rows missing")
    origin_by_file = {row["source_file"]: row for row in origin_rows}

    records = _collect_bundles([source_root, *comparison_roots])
    comparison_run_ids = sorted({
        record["run_id"] for record in records if record["run_id"] != run_id
    })
    results = []

    for geo_row in geo_rows:
        if geo_row.get("research_status") != "RESEARCH_GEOGRAPHIC_ENVELOPE":
            continue
        name = geo_row["source_file"]
        source_bundle = _read(source_root / "slots" / name)
        if not _safe_tracking_bundle(source_bundle):
            raise ValueError("unsafe source tracking bundle")

        origin_row = origin_by_file.get(name)
        if origin_row is None or origin_row.get("join_status") != "OBSERVED_INPUT_JOINED":
            raise ValueError("F4-4 slot lacks observed-origin source")

        geo_payload = _read(source_root / geo_row["output_file"])
        origin_payload = _read(source_root / origin_row["output_file"])
        if (
            geo_payload.get("product") != "F4_RESEARCH_GEOGRAPHIC_ENVELOPES"
            or geo_payload.get("risk_engine_allowed") is not False
            or geo_payload.get("lpz_forecast_generated") is not False
            or origin_payload.get("risk_engine_allowed") is not False
            or origin_payload.get("forecast_generated") is not False
        ):
            raise ValueError("F4-4 slot research lock mismatch")

        origin_objects = {
            str(row["research_object_id"]): row
            for row in origin_payload.get("objects", [])
        }
        observed_features = {}
        projections = []
        for feature in geo_payload.get("features", []):
            props = feature.get("properties") or {}
            object_id = str(props.get("research_object_id") or "")
            if props.get("kind") == "OBSERVED_THRESHOLD_COMPONENT_ENVELOPE":
                observed_features[object_id] = feature
            elif props.get("kind") == "PROJECTED_RESEARCH_GEOGRAPHIC_ENVELOPE":
                projections.append(feature)

        for feature in projections:
            props = feature["properties"]
            object_id = str(props["research_object_id"])
            lead = int(props["lead_from_as_of_minutes"])
            if lead not in (15, 30):
                raise ValueError("unexpected F4-4 lead")

            origin = origin_objects.get(object_id)
            observed_feature = observed_features.get(object_id)
            if origin is None or observed_feature is None:
                raise ValueError("projection lacks observed source")

            source_component = origin.get("observed_component") or {}
            source_geometry = _envelope_geometry(source_component)
            if source_geometry is None:
                raise ValueError("source envelope missing")
            if source_geometry != observed_feature.get("geometry"):
                raise ValueError("source feature/envelope mismatch")

            source_centroid = source_component.get("centroid") or {}
            source_lon_lat = [
                float(source_centroid["lon"]),
                float(source_centroid["lat"]),
            ]
            projected_lon_lat = props.get("projected_centroid_lon_lat")
            if (
                not isinstance(projected_lon_lat, list)
                or len(projected_lon_lat) != 2
            ):
                raise ValueError("projected centroid missing")

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
                "parent_lineage_id": props.get("parent_lineage_id"),
                "lead_from_as_of_minutes": lead,
                "target_valid_time_utc": target_valid,
                "target_run_id": None,
                "target_slot_utc": None,
                "target_as_of_utc": None,
                "source_boundary_truncated": bool(
                    source_component.get("boundary_truncated")
                ),
                "target_component_count": None,
                "usable_target_component_count": None,
                "boundary_target_component_count": None,
                "missing_envelope_target_component_count": None,
                "verification_status": None,
                "motion_spatial": None,
                "persistence_spatial": None,
                "motion_minus_persistence_best_iou": None,
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

            if row["source_boundary_truncated"]:
                row["verification_status"] = "SOURCE_BOUNDARY_TRUNCATED_EXCLUDED"
                results.append(row)
                continue

            target_frame = _exact_target_frame(target_bundle, target_valid)
            usable_targets, target_counts = _usable_target_components(target_frame)
            row.update(target_counts)
            if not usable_targets:
                row["verification_status"] = "NO_NONBOUNDARY_TARGET_ENVELOPES"
                results.append(row)
                continue

            motion = _best_spatial_match(
                feature["geometry"],
                projected_lon_lat,
                usable_targets,
            )
            persistence = _best_spatial_match(
                source_geometry,
                source_lon_lat,
                usable_targets,
            )
            row["motion_spatial"] = motion
            row["persistence_spatial"] = persistence
            row["motion_minus_persistence_best_iou"] = (
                float(motion["best_iou"]) - float(persistence["best_iou"])
            )
            row["verification_status"] = "IDENTITY_FREE_SPATIAL_COMPARISON"
            results.append(row)

    counts = {
        "projection_count": len(results),
        "exact_target_count": sum(
            row["target_run_id"] is not None for row in results
        ),
        "comparison_count": sum(
            row["verification_status"] == "IDENTITY_FREE_SPATIAL_COMPARISON"
            for row in results
        ),
        "source_boundary_excluded_count": sum(
            row["verification_status"] == "SOURCE_BOUNDARY_TRUNCATED_EXCLUDED"
            for row in results
        ),
        "no_nonboundary_target_envelope_count": sum(
            row["verification_status"] == "NO_NONBOUNDARY_TARGET_ENVELOPES"
            for row in results
        ),
        "no_exact_target_count": sum(
            row["verification_status"] == "NO_EXACT_FUTURE_TARGET_IN_PROVIDED_ARTIFACTS"
            for row in results
        ),
    }

    return {
        "schema_version": "0.1.0",
        "product": "F4_IDENTITY_FREE_SPATIAL_ENVELOPE_VERIFICATION",
        "source_run_id": run_id,
        "comparison_run_ids": comparison_run_ids,
        "research_mode": "ARCHIVED_PROSPECTIVE_IDENTITY_FREE_SPATIAL_VERIFICATION",
        "threshold_mmph": 30,
        "metric_projection": "WEB_MERCATOR_TRACKING_PLANE",
        "counts": counts,
        "horizons_from_as_of_minutes": {
            "15": _horizon_summary(results, 15),
            "30": _horizon_summary(results, 30),
        },
        "results": results,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
        "identity_required": False,
        "identity_inference_generated": False,
        "validated_forecast": False,
        "interpretation": (
            "Identity-free spatial verification of archived F4-4 projected convex-hull "
            "envelopes against any non-boundary observed >=30 mm/h component in the exact "
            "future frame. This measures spatial overlap, not persistent object identity "
            "and not LPZ classification/probability. Persistence leaves the source envelope "
            "unmoved. Target best-match components may differ between motion and persistence."
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
        "source_run_id": result["source_run_id"],
        **result["counts"],
        "horizons_from_as_of_minutes": result["horizons_from_as_of_minutes"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
