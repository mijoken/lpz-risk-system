#!/usr/bin/env python3
"""Publish the latest F4-4 prospective research envelopes for the public map.

The output is display-only research data. It never unlocks the Risk Engine,
never creates LPZ probabilities/severity, and suppresses stale geometry rather
than presenting an old research projection as current.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


PRODUCT = "LPZ_F4_LIVE_RESEARCH_ENVELOPES"
MAX_SCHEMA_MAJOR = 1


def _read(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"expected UTC Z timestamp: {value!r}")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"timestamp is not UTC: {value!r}")
    return parsed


def _find_manifest(search_root: Path) -> Path | None:
    matches = sorted(search_root.rglob("f4_geographic_envelopes/manifest.json"))
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f"expected one F4-4 batch manifest, found {len(matches)}")
    return matches[0]


def _empty_output(
    *,
    source_run_id: str,
    source_slot_utc: str | None,
    source_as_of_utc: str | None,
    latest_observation_utc: str | None,
    status: str,
    age_minutes: float | None,
    max_age_minutes: int,
    source_manifest_path: str,
) -> dict:
    return {
        "type": "FeatureCollection",
        "schema_version": "1.0.0",
        "product": PRODUCT,
        "status": status,
        "source_run_id": source_run_id,
        "source_slot_utc": source_slot_utc,
        "source_as_of_utc": source_as_of_utc,
        "latest_observation_utc": latest_observation_utc,
        "source_manifest_path": source_manifest_path,
        "coverage": "SELECTED_FIXED_MOSAIC_NOT_NATIONWIDE",
        "display_scope": "LATEST_SUCCESSFUL_PROSPECTIVE_SLOT",
        "research_only": True,
        "validated_forecast": False,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
        "stale_suppressed": status == "STALE_SUPPRESSED",
        "age_minutes_at_publish": age_minutes,
        "max_age_minutes": max_age_minutes,
        "projected_object_count": 0,
        "feature_count": 0,
        "horizons_from_as_of_minutes": [],
        "features": [],
        "interpretation": (
            "Display-only F4-4 research envelopes from a selected fixed radar mosaic. "
            "Not nationwide coverage and not a validated LPZ forecast, probability, severity, "
            "warning, or exact future precipitation footprint."
        ),
    }


def build_public(
    search_root: Path,
    *,
    now_utc: datetime | None = None,
    max_age_minutes: int = 90,
) -> dict:
    if max_age_minutes <= 0:
        raise ValueError("max_age_minutes must be positive")

    manifest_path = _find_manifest(search_root)
    if manifest_path is None:
        return _empty_output(
            source_run_id="",
            source_slot_utc=None,
            source_as_of_utc=None,
            latest_observation_utc=None,
            status="NOT_PUBLISHED",
            age_minutes=None,
            max_age_minutes=max_age_minutes,
            source_manifest_path="",
        )
    manifest = _read(manifest_path)
    if (manifest.get("product") != "F4_RESEARCH_GEOGRAPHIC_ENVELOPE_BATCH"
            or manifest.get("risk_engine_allowed") is not False
            or manifest.get("official_risk_output") is not False
            or manifest.get("lpz_forecast_generated") is not False
            or manifest.get("probability_generated") is not False
            or manifest.get("severity_generated") is not False):
        raise ValueError("F4-4 batch manifest contract mismatch")

    rows = manifest.get("slot_results")
    if not isinstance(rows, list) or manifest.get("source_slot_count") != len(rows):
        raise ValueError("F4-4 slot manifest mismatch")

    eligible = [
        row for row in rows
        if row.get("research_status") == "RESEARCH_GEOGRAPHIC_ENVELOPE"
        and isinstance(row.get("output_file"), str)
        and row.get("output_file")
    ]
    if not eligible:
        return _empty_output(
            source_run_id=str(manifest.get("source_run_id") or ""),
            source_slot_utc=None,
            source_as_of_utc=None,
            latest_observation_utc=None,
            status="NO_RESEARCH_SLOT",
            age_minutes=None,
            max_age_minutes=max_age_minutes,
            source_manifest_path=str(manifest_path.relative_to(search_root)),
        )

    eligible.sort(key=lambda row: _utc(row["collection_slot_utc"]))
    row = eligible[-1]

    # The output_file path is relative to the O8.1 batch root, which is the
    # directory containing f4_geographic_envelopes/.
    batch_root = manifest_path.parent.parent
    payload_path = batch_root / row["output_file"]
    payload = _read(payload_path)

    if (payload.get("product") != "F4_RESEARCH_GEOGRAPHIC_ENVELOPES"
            or payload.get("risk_engine_allowed") is not False
            or payload.get("official_risk_output") is not False
            or payload.get("lpz_forecast_generated") is not False
            or payload.get("probability_generated") is not False
            or payload.get("severity_generated") is not False):
        raise ValueError("F4-4 slot payload contract mismatch")

    source_as_of = payload.get("source_as_of_utc")
    latest_obs = payload.get("latest_observation_utc")
    if not source_as_of or not latest_obs:
        raise ValueError("F4-4 slot timing metadata missing")

    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    age_minutes = max(0.0, (now.astimezone(timezone.utc) - _utc(source_as_of)).total_seconds() / 60.0)

    manifest_rel = str(manifest_path.relative_to(search_root))
    if age_minutes > max_age_minutes:
        return _empty_output(
            source_run_id=str(manifest.get("source_run_id") or ""),
            source_slot_utc=row["collection_slot_utc"],
            source_as_of_utc=source_as_of,
            latest_observation_utc=latest_obs,
            status="STALE_SUPPRESSED",
            age_minutes=round(age_minutes, 3),
            max_age_minutes=max_age_minutes,
            source_manifest_path=manifest_rel,
        )

    source_features = payload.get("features")
    if not isinstance(source_features, list):
        raise ValueError("F4-4 slot features missing")

    features = []
    object_ids = set()
    horizons = set()
    for feature in source_features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError("invalid F4-4 feature")
        props = feature.get("properties")
        geom = feature.get("geometry")
        if not isinstance(props, dict) or not isinstance(geom, dict) or geom.get("type") != "Polygon":
            raise ValueError("invalid F4-4 projected geometry")
        if props.get("kind") != "PROJECTED_RESEARCH_GEOGRAPHIC_ENVELOPE":
            continue
        if (props.get("research_only") is not True
                or props.get("risk_engine_allowed") is not False
                or props.get("lpz_forecast_generated") is not False
                or props.get("probability") is not None
                or props.get("severity") is not None
                or props.get("intensity") is not None
                or props.get("exact_precipitation_contour") is not False):
            raise ValueError("F4-4 projected feature violates public research lock")

        lead = props.get("lead_from_as_of_minutes")
        if lead not in (15, 30):
            raise ValueError("unexpected F4-4 public lead")
        object_id = str(props.get("research_object_id") or "")
        if not object_id:
            raise ValueError("F4-4 research object id missing")
        object_ids.add(object_id)
        horizons.add(lead)

        public_props = dict(props)
        public_props["public_display_only"] = True
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": public_props,
        })

    return {
        "type": "FeatureCollection",
        "schema_version": "1.0.0",
        "product": PRODUCT,
        "status": "AVAILABLE" if features else "NO_PROJECTED_ENVELOPES",
        "source_run_id": str(manifest.get("source_run_id") or ""),
        "source_slot_utc": row["collection_slot_utc"],
        "source_as_of_utc": source_as_of,
        "latest_observation_utc": latest_obs,
        "source_manifest_path": manifest_rel,
        "coverage": "SELECTED_FIXED_MOSAIC_NOT_NATIONWIDE",
        "display_scope": "LATEST_SUCCESSFUL_PROSPECTIVE_SLOT",
        "research_only": True,
        "validated_forecast": False,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
        "stale_suppressed": False,
        "age_minutes_at_publish": round(age_minutes, 3),
        "max_age_minutes": max_age_minutes,
        "projected_object_count": len(object_ids),
        "feature_count": len(features),
        "horizons_from_as_of_minutes": sorted(horizons),
        "features": features,
        "interpretation": (
            "Display-only F4-4 research envelopes translated from observed >=30 mm/h "
            "threshold-component envelopes by the F4-1 constant-motion baseline. "
            "Coverage is a selected fixed radar mosaic, not nationwide. This is not a "
            "validated LPZ forecast, probability, severity, warning, or exact future precipitation footprint."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-search-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-age-minutes", type=int, default=90)
    args = parser.parse_args()

    if args.output.exists():
        parser.error(f"refusing overwrite: {args.output}")

    result = build_public(
        args.artifact_search_root,
        max_age_minutes=args.max_age_minutes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2, allow_nan=False)
        fp.write("\n")

    print(json.dumps({
        key: result[key]
        for key in (
            "status",
            "source_run_id",
            "source_slot_utc",
            "source_as_of_utc",
            "projected_object_count",
            "feature_count",
            "stale_suppressed",
        )
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
