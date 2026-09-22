#!/usr/bin/env python3
"""Publish F4 field-motion research forecasts for the research dashboard.

This is a display-only product. It reads frozen F4-9C prospective case
artifacts and converts the Lucas-Kanade/semi-Lagrangian component-label
forecasts into geographic convex-hull envelopes.

The F4-9D terminal decision, when supplied, changes only the displayed
research-decision label. It never changes forecast geometry or eligibility.

This publisher never unlocks the Risk Engine and never emits LPZ probability,
severity, warning, or production risk output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from lpz_risk.radar_geographic_envelope import component_geographic_envelope
from lpz_risk.radar_morphology import EARTH_RADIUS_M, TILE_SIZE


PRODUCT = "LPZ_F4_FIELD_MOTION_RESEARCH"
MODEL_ID = "LUCAS_KANADE_SEMILAGRANGIAN"
COVERAGE = "SELECTED_FIXED_MOSAIC_NOT_NATIONWIDE"


@dataclass(frozen=True)
class _PixelComponent:
    flat_indices: tuple[int, ...]
    pixel_count: int


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"expected UTC Z timestamp: {value!r}")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def _pixel_stats(
    flat_indices: np.ndarray,
    *,
    width: int,
    zoom: int,
    origin_tile_x: int,
    origin_tile_y: int,
) -> tuple[list[float] | None, float | None]:
    if flat_indices.size == 0:
        return None, None

    rows, cols = np.divmod(flat_indices.astype(np.int64), int(width))
    world_px = TILE_SIZE * (2 ** int(zoom))
    gx = origin_tile_x * TILE_SIZE + cols.astype(float) + 0.5
    gy = origin_tile_y * TILE_SIZE + rows.astype(float) + 0.5

    lon = gx / world_px * 360.0 - 180.0
    merc_y = math.pi * (1.0 - 2.0 * gy / world_px)
    lat = np.degrees(np.arctan(np.sinh(merc_y)))

    circumference = 2.0 * math.pi * EARTH_RADIUS_M
    mpp = (
        circumference
        * np.cos(np.radians(lat))
        / (TILE_SIZE * (2 ** int(zoom)))
    )
    area_km2 = float(np.sum((mpp * mpp) / 1_000_000.0))
    centroid = [float(np.mean(lon)), float(np.mean(lat))]
    return centroid, area_km2


def _decision(decision_path: Path | None) -> tuple[str, bool]:
    if decision_path is None or not decision_path.is_file():
        return "PENDING", False

    payload = _read(decision_path)
    if (
        payload.get("product") != "F4_9D_TERMINAL_DECISION"
        or payload.get("f4_closed") is not True
        or payload.get("risk_engine_allowed") is not False
        or payload.get("validated_forecast") is not False
    ):
        raise ValueError("F4-9D decision contract mismatch")

    decision = str(payload.get("decision") or "")
    if decision not in {"GO", "NO_GO"}:
        raise ValueError("unexpected F4-9D decision")
    return decision, True


def _empty(
    *,
    status: str,
    terminal_decision: str,
    f4_closed: bool,
    source_case_id: str = "",
    source_slot_utc: str | None = None,
    source_as_of_utc: str | None = None,
    age_minutes: float | None = None,
    max_age_minutes: int = 90,
) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "schema_version": "1.0.0",
        "product": PRODUCT,
        "status": status,
        "model_id": MODEL_ID,
        "terminal_decision": terminal_decision,
        "f4_closed": f4_closed,
        "source_case_id": source_case_id,
        "source_slot_utc": source_slot_utc,
        "source_as_of_utc": source_as_of_utc,
        "coverage": COVERAGE,
        "display_scope": "LATEST_FROZEN_PROSPECTIVE_CASE",
        "research_only": True,
        "validated_forecast": False,
        "production_integration_enabled": False,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
        "age_minutes_at_publish": age_minutes,
        "max_age_minutes": max_age_minutes,
        "historical_research": False,
        "feature_count": 0,
        "projected_component_count": 0,
        "horizons_from_as_of_minutes": [],
        "features": [],
        "interpretation": (
            "Display-only Lucas-Kanade/semi-Lagrangian F4 research forecast. "
            "The F4-9D decision changes only the research label, never the geometry. "
            "Not an LPZ probability, severity, warning, or production risk output."
        ),
    }


def build_public(
    cohort_root: Path,
    *,
    decision_path: Path | None = None,
    now_utc: datetime | None = None,
    max_age_minutes: int = 90,
) -> dict[str, Any]:
    if max_age_minutes <= 0:
        raise ValueError("max_age_minutes must be positive")

    terminal_decision, f4_closed = _decision(decision_path)

    case_root = cohort_root / "cases"
    case_paths = sorted(case_root.glob("*.json")) if case_root.is_dir() else []
    if not case_paths:
        return _empty(
            status="NOT_PUBLISHED",
            terminal_decision=terminal_decision,
            f4_closed=f4_closed,
            max_age_minutes=max_age_minutes,
        )

    cases = [_read(path) for path in case_paths]
    for case in cases:
        if (
            case.get("product") != "F4_9C_PROSPECTIVE_CASE"
            or case.get("future_observations_read_at_capture") is not False
            or case.get("forecast_skill_scored_at_capture") is not False
            or case.get("parameter_tuning_performed") is not False
            or case.get("risk_engine_allowed") is not False
        ):
            raise ValueError("F4-9C case contract mismatch")

    cases.sort(key=lambda row: _parse_utc(row["source_slot_utc"]))
    case = cases[-1]
    case_id = str(case["case_id"])
    source_as_of = str(case["prospective_as_of_utc"])
    source_slot = str(case["source_slot_utc"])

    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    age_minutes = max(
        0.0,
        (now.astimezone(timezone.utc) - _parse_utc(source_as_of)).total_seconds()
        / 60.0,
    )
    # Historical research must remain explorable after collection stops.
    # Distinguish historical geometry from a fresh prospective projection
    # instead of silently deleting the only published research artifact.
    is_archived = age_minutes > max_age_minutes

    component_path = cohort_root / "component_forecasts" / f"{case_id}.npz"
    if not component_path.is_file():
        raise FileNotFoundError(
            f"component forecast artifact missing for case {case_id}: {component_path}"
        )

    expected_sha = case.get("component_forecast_sha256")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise ValueError(f"frozen component forecast SHA-256 missing: {case_id}")
    digest = hashlib.sha256()
    with component_path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha:
        raise ValueError(f"frozen component forecast SHA-256 mismatch: {case_id}")

    with np.load(component_path) as payload:
        forecast_labels = np.asarray(payload["forecast_component_labels"])
        leads = np.asarray(payload["lead_minutes"]).astype(int).tolist()
        target_unix = np.asarray(payload["target_valid_time_unix_s"]).astype(np.int64)

    if forecast_labels.ndim != 3 or forecast_labels.shape[0] != 2:
        raise ValueError("forecast component labels must have shape (2, H, W)")
    if leads != [15, 30]:
        raise ValueError("unexpected F4-9C lead contract")
    if target_unix.shape != (2,):
        raise ValueError("target time vector mismatch")

    fixed = case.get("fixed_mosaic") or {}
    zoom = int(fixed.get("zoom"))
    origin_x = int(fixed.get("origin_tile_x"))
    origin_y = int(fixed.get("origin_tile_y"))
    height, width = map(int, forecast_labels.shape[1:])

    source_components = case.get("source_components")
    if not isinstance(source_components, list):
        raise ValueError("source component list missing")

    source_by_id = {
        int(row["component_id"]): row
        for row in source_components
        if isinstance(row, dict) and row.get("component_id") is not None
    }

    features: list[dict[str, Any]] = []
    projected_ids: set[int] = set()
    for lead_index, lead in enumerate(leads):
        labels = forecast_labels[lead_index]
        for component_id in sorted(source_by_id):
            flat = np.flatnonzero(labels == component_id).astype(np.int64)
            if flat.size == 0:
                continue

            proxy = _PixelComponent(
                flat_indices=tuple(map(int, flat.tolist())),
                pixel_count=int(flat.size),
            )
            envelope = component_geographic_envelope(
                proxy,
                mosaic_width=width,
                zoom=zoom,
                origin_tile_x=origin_x,
                origin_tile_y=origin_y,
            )
            if envelope is None:
                continue

            centroid, area_km2 = _pixel_stats(
                flat,
                width=width,
                zoom=zoom,
                origin_tile_x=origin_x,
                origin_tile_y=origin_y,
            )
            target_time = datetime.fromtimestamp(
                int(target_unix[lead_index]),
                tz=timezone.utc,
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

            source_row = source_by_id[component_id]
            research_object_id = f"FM:{case_id}:{component_id}"
            projected_ids.add(component_id)
            features.append(
                {
                    "type": "Feature",
                    "geometry": envelope["geometry"],
                    "properties": {
                        "kind": "FIELD_MOTION_RESEARCH_ENVELOPE",
                        "model_id": MODEL_ID,
                        "research_object_id": research_object_id,
                        "source_component_id": component_id,
                        "source_pixel_count": int(source_row.get("pixel_count") or 0),
                        "projected_pixel_count": int(flat.size),
                        "projected_approx_area_km2": area_km2,
                        "projected_centroid_lon_lat": centroid,
                        "source_slot_utc": source_slot,
                        "source_as_of_utc": source_as_of,
                        "target_valid_time_utc": target_time,
                        "lead_from_as_of_minutes": int(lead),
                        "terminal_decision": terminal_decision,
                        "research_only": True,
                        "validated_forecast": False,
                        "production_integration_enabled": False,
                        "risk_engine_allowed": False,
                        "lpz_forecast_generated": False,
                        "probability": None,
                        "severity": None,
                        "intensity": None,
                        "exact_precipitation_contour": False,
                        "geometry_method": envelope["method"],
                        "public_display_only": True,
                    },
                }
            )

    return {
        "type": "FeatureCollection",
        "schema_version": "1.0.0",
        "product": PRODUCT,
        "status": ("ARCHIVED" if is_archived else "AVAILABLE") if features else "NO_PROJECTED_ENVELOPES",
        "model_id": MODEL_ID,
        "terminal_decision": terminal_decision,
        "f4_closed": f4_closed,
        "source_case_id": case_id,
        "source_slot_utc": source_slot,
        "source_as_of_utc": source_as_of,
        "coverage": COVERAGE,
        "display_scope": "LATEST_FROZEN_PROSPECTIVE_CASE",
        "research_only": True,
        "validated_forecast": False,
        "production_integration_enabled": False,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
        "age_minutes_at_publish": round(age_minutes, 3),
        "max_age_minutes": max_age_minutes,
        "historical_research": is_archived,
        "feature_count": len(features),
        "projected_component_count": len(projected_ids),
        "horizons_from_as_of_minutes": leads,
        "features": features,
        "interpretation": (
            "Display-only Lucas-Kanade/semi-Lagrangian F4 research forecast "
            "from the latest frozen prospective case. GO/NO-GO changes only "
            "the research-decision label. Coverage is a selected fixed mosaic, "
            "not nationwide. This is not an LPZ probability, severity, warning, "
            "or production risk output."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-root", required=True, type=Path)
    parser.add_argument("--decision-json", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-age-minutes", type=int, default=90)
    args = parser.parse_args()

    result = build_public(
        args.cohort_root,
        decision_path=args.decision_json,
        max_age_minutes=args.max_age_minutes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status": result["status"],
                "terminal_decision": result["terminal_decision"],
                "source_case_id": result["source_case_id"],
                "projected_component_count": result["projected_component_count"],
                "feature_count": result["feature_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
