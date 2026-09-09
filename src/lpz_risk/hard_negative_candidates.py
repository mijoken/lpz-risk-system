"""Generate research-safe hard-negative candidates from rainfall screening records.

This module deliberately stops at UNCONFIRMED_HARD_NEGATIVE_CANDIDATE.
Rainfall intensity alone may never emit a final HARD_NEGATIVE label.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

UTC = timezone.utc


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone-aware UTC timestamp required")
    return dt.astimezone(UTC)


def _stable_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "HNCCAND-" + hashlib.sha256(raw).hexdigest()[:16]


def _threshold_area(record: dict[str, Any], threshold_mm: float) -> float:
    for row in record.get("threshold_descriptors", []):
        if abs(float(row["threshold_mm"]) - float(threshold_mm)) < 1e-9:
            return float(row["area_km2"])
    raise ValueError(f"screening record lacks threshold descriptor {threshold_mm} mm")


def _metrics(record: dict[str, Any]) -> dict[str, float]:
    return {
        "max_accumulation_mm": float(record["max_accumulation_mm"]),
        "area_ge_80mm_km2": _threshold_area(record, 80.0),
        "area_ge_100mm_km2": _threshold_area(record, 100.0),
        "area_ge_150mm_km2": _threshold_area(record, 150.0),
    }


def _condition(metric_values: dict[str, float], condition: dict[str, Any]) -> bool:
    metric = str(condition["metric"])
    op = str(condition["operator"])
    value = float(condition["value"])
    actual = float(metric_values[metric])
    if op == ">=":
        return actual >= value
    if op == ">":
        return actual > value
    if op == "<=":
        return actual <= value
    if op == "<":
        return actual < value
    raise ValueError(f"unsupported operator: {op}")


def _compound(metric_values: dict[str, float], rule: dict[str, Any]) -> bool:
    conditions = list(rule.get("conditions") or [])
    op = str(rule.get("operator", "AND")).upper()
    values = [_condition(metric_values, c) for c in conditions]
    if not values:
        raise ValueError("compound rule has no conditions")
    if op == "AND":
        return all(values)
    if op == "OR":
        return any(values)
    raise ValueError(f"unsupported compound operator: {op}")


def _positive_anchor_windows(positive_registry: dict[str, Any], before_min: int, after_min: int) -> dict[str, list[tuple[datetime, datetime, str]]]:
    result: dict[str, list[tuple[datetime, datetime, str]]] = {}
    for anchor in positive_registry.get("realized_positive_anchors", []):
        code = str(anchor["primary_subdivision_code"])
        t = _parse_utc(anchor["analysis_time_utc"])
        result.setdefault(code, []).append((t - timedelta(minutes=before_min), t + timedelta(minutes=after_min), str(anchor["anchor_id"])))
    for code in result:
        result[code].sort(key=lambda x: x[0])
    return result


def build_hard_negative_candidates(
    screening_records: list[dict[str, Any]],
    positive_registry: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    if policy.get("hard_negative_label_allowed") is not False:
        raise ValueError("candidate policy must forbid final hard-negative labeling")
    if policy.get("risk_engine_allowed") is not False:
        raise ValueError("risk engine must remain disabled")

    exclusion = policy["positive_exclusion"]
    windows = _positive_anchor_windows(
        positive_registry,
        int(exclusion["minutes_before_anchor"]),
        int(exclusion["minutes_after_anchor"]),
    )
    entry_rule = policy["candidate_generation"]["broad_entry_rule"]
    tag_rules = list(policy["candidate_generation"].get("strength_tags", []))

    candidates: list[dict[str, Any]] = []
    rejected_by_entry = 0
    excluded_near_positive = 0

    for record in screening_records:
        if record.get("entity_type") != "THREE_HOUR_RAINFALL_SCREENING_RECORD":
            raise ValueError("unexpected screening entity type")
        metrics = _metrics(record)
        if not _compound(metrics, entry_rule):
            rejected_by_entry += 1
            continue

        valid_time = _parse_utc(record["valid_time_utc"])
        code = str(record["primary_subdivision_code"])
        matched_anchors: list[str] = []
        for start, end, anchor_id in windows.get(code, []):
            if start <= valid_time <= end:
                matched_anchors.append(anchor_id)

        tags: list[str] = []
        for rule in tag_rules:
            if "metric" in rule:
                passed = _condition(metrics, rule)
            else:
                passed = _compound(metrics, rule)
            if passed:
                tags.append(str(rule["tag"]))

        candidate_id = _stable_id({
            "valid_time_utc": valid_time.isoformat(),
            "primary_subdivision_code": code,
            "source_product": record.get("source_product"),
            "metrics": metrics,
        })
        excluded = bool(matched_anchors)
        if excluded:
            excluded_near_positive += 1

        candidates.append({
            "entity_type": "HARD_NEGATIVE_CANDIDATE",
            "candidate_id": candidate_id,
            "valid_time_utc": valid_time.isoformat().replace("+00:00", "Z"),
            "primary_subdivision_code": code,
            "source_product": record.get("source_product"),
            "candidate_status": "EXCLUDED_NEAR_OFFICIAL_POSITIVE" if excluded else policy["candidate_status_after_generation"],
            "positive_exclusion_applied": True,
            "matched_positive_anchor_ids": matched_anchors,
            "strength_tags": sorted(tags),
            "rainfall_metrics": metrics,
            "rainfall_screening_record": record,
            "hard_negative_label": None,
            "lpz_classification": None,
            "risk_score": None,
        })

    eligible = [c for c in candidates if c["candidate_status"] == policy["candidate_status_after_generation"]]
    ids = [c["candidate_id"] for c in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate hard-negative candidate ID")

    return {
        "schema_version": "0.1.0",
        "phase": "2C-hard-negative-candidate-registry",
        "source": policy["source_required"],
        "policy_status": policy["policy_status"],
        "screening_record_count": len(screening_records),
        "entry_rejected_count": rejected_by_entry,
        "broad_candidate_count": len(candidates),
        "excluded_near_positive_count": excluded_near_positive,
        "eligible_unconfirmed_candidate_count": len(eligible),
        "candidates": candidates,
        "hard_negative_registry_complete": False,
        "hard_negative_label_allowed": False,
        "risk_engine_allowed": False,
    }
