"""Validation helpers for Phase 2 historical-reconstruction policy files."""

from __future__ import annotations

from typing import Any

ALLOWED_FEATURE_STATUSES = {
    "EXACT",
    "EXACT_SOURCE_PRODUCT",
    "DERIVABLE",
    "PROXY_REANALYSIS",
    "BLOCKED_PENDING_HIGH_RES_RADAR",
    "BLOCKED_EXACT_REPRODUCTION_NOT_YET_PROVEN",
}


def validate_reconstruction_matrix(matrix: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if matrix.get("risk_engine_allowed") is not False:
        errors.append("historical reconstruction matrix must keep risk_engine_allowed=false")

    sources = matrix.get("sources") or {}
    required_sources = {
        "JMA_OFFICIAL_LPZ_CSV",
        "JMA_ANALYZED_RAINFALL_ANNUAL",
        "DIAS_XRAIN_CXMP",
        "ERA5",
    }
    missing_sources = sorted(required_sources - set(sources))
    if missing_sources:
        errors.append(f"missing required historical sources: {missing_sources}")

    xrain = sources.get("DIAS_XRAIN_CXMP", {})
    if xrain.get("status") != "REQUIRES_PERMISSION":
        errors.append("DIAS XRAIN must remain REQUIRES_PERMISSION until permission is actually proven")
    if xrain.get("original_data_redistribution_allowed") is not False:
        errors.append("XRAIN original-data redistribution must remain false")

    features = matrix.get("feature_capabilities") or []
    ids: set[str] = set()
    for row in features:
        feature_id = str(row.get("feature_id", ""))
        if not feature_id:
            errors.append("feature capability missing feature_id")
            continue
        if feature_id in ids:
            errors.append(f"duplicate feature_id: {feature_id}")
        ids.add(feature_id)
        status = row.get("historical_status")
        if status not in ALLOWED_FEATURE_STATUSES:
            errors.append(f"unsupported historical_status for {feature_id}: {status}")

    blocked = {row["feature_id"] for row in features if str(row.get("historical_status", "")).startswith("BLOCKED_")}
    expected_blocked = {
        "live_public_png_30_50_80_object_morphology",
        "multi_frame_parent_tracking",
        "embedded_50_80_core_genesis",
        "parent_relative_genesis_geometry",
        "850hPa_inflow_relative_genesis_geometry",
        "Hirockawa_exact_3h_HRA",
    }
    if not expected_blocked.issubset(blocked):
        errors.append("high-resolution historical radar-dependent features were opened prematurely")
    return errors


def validate_hard_negative_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if policy.get("risk_engine_allowed") is not False:
        errors.append("hard-negative policy must keep risk_engine_allowed=false")
    if policy.get("negative_registry_built") is not False:
        errors.append("negative_registry_built must remain false before candidate data exist")
    if policy.get("selection_status") != "POLICY_FROZEN_SCHEMA_ONLY":
        errors.append("unexpected hard-negative selection status")

    classes = policy.get("candidate_classes") or []
    class_ids = [str(item.get("class_id", "")) for item in classes]
    if len(class_ids) != len(set(class_ids)):
        errors.append("duplicate hard-negative class_id")
    required_classes = {
        "HEAVY_RAIN_NO_OFFICIAL_LPZ",
        "MOVING_LINEAR_RAINBAND_NO_LPZ",
        "SHORT_LIVED_ORGANIZED_CONVECTION",
        "INTENSE_CONVECTIVE_CLUSTER_NO_PERSISTENCE",
        "HIGH_ENVIRONMENTAL_FAVORABILITY_NO_LPZ",
        "NEAR_MISS_OBJECTIVE_RAINFALL_CASE",
    }
    if not required_classes.issubset(set(class_ids)):
        errors.append("required hard-negative candidate classes are missing")

    protected = policy.get("protected_positive_window") or {}
    if int(protected.get("time_before_minutes", -1)) < 0 or int(protected.get("time_after_minutes", -1)) < 0:
        errors.append("protected positive time windows must be non-negative")
    if protected.get("spatial_key") != "primary_subdivision_code":
        errors.append("initial protected spatial key must remain primary_subdivision_code")

    future = policy.get("future_information_policy") or {}
    if future.get("predictor_features_must_use_only_information_available_at_snapshot_time") is not True:
        errors.append("snapshot-time information barrier must be enabled")
    if future.get("negative_selection_must_not_condition_on_future_model_score_or_future_predictor_feature_values") is not True:
        errors.append("future model-score leakage guardrail must be enabled")

    split = policy.get("split_policy") or {}
    if split.get("no_random_row_split") is not True:
        errors.append("random row split must remain forbidden")
    return errors
