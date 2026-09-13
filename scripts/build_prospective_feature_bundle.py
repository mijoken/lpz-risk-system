#!/usr/bin/env python3
"""Build one prospective derived-feature bundle from audited live scientific reports.

The bundle intentionally contains derived scientific JSON only. Raw radar PNG/tiles and
GRIB payloads are never archived here. No risk score or LPZ classification is produced.

Normal live weather can stop at different descriptive stages without being a pipeline
failure:
- no precipitation at an exact O8.1 slot;
- no temporally trackable precipitation component;
- trackable components exist, but no embedded-core genesis event is observed;
- full downstream precursor descriptors are available.

These states are archived explicitly. None is an LPZ-positive/negative classification.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

COMPONENTS = {
    "radar_scientific_decode": "radar_scientific_decode.json",
    "radar_morphology": "radar_morphology.json",
    "radar_wind_orientation": "radar_wind_orientation.json",
    "radar_tracking": "radar_tracking.json",
    "radar_hierarchy": "radar_hierarchy.json",
    "radar_temporal": "radar_temporal.json",
    "radar_genesis_geometry": "radar_genesis_geometry.json",
    "radar_inflow_geometry": "radar_inflow_geometry.json",
    "parent_precursor_features": "parent_precursor_features.json",
}

TRACKING_STAGE = {
    "radar_scientific_decode",
    "radar_morphology",
    "radar_wind_orientation",
    "radar_tracking",
}

HIERARCHY_STAGE = TRACKING_STAGE | {
    "radar_hierarchy",
    "radar_temporal",
}

EVENT_STAGE = set(COMPONENTS) - HIERARCHY_STAGE


def _load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"component is not a JSON object: {path}")
    return payload


def _tracking_no_event(tracking: dict | None) -> bool:
    """True only for a successful exact/no-match descriptive collection cycle."""
    if not isinstance(tracking, dict):
        return False
    gates = tracking.get("gates")
    if not isinstance(gates, dict):
        return False

    frame_times = tracking.get("frame_valid_times")
    exact_no_precip = (
        tracking.get("execution_ok") is True
        and tracking.get("scientific_tracking_proven") is False
        and tracking.get("sample_status") == "NO_PRECIPITATION_AT_TARGET"
        and gates.get("exact_four_frame_sequence") is True
        and isinstance(frame_times, list)
        and len(frame_times) == 4
    )
    if exact_no_precip:
        return True

    return (
        tracking.get("execution_ok") is True
        and tracking.get("scientific_tracking_proven") is False
        and gates.get("fixed_multiframe_mosaic") is True
        and gates.get("component_tracking") is False
        and isinstance(tracking.get("tracking"), dict)
        and isinstance(frame_times, list)
        and len(frame_times) >= 2
    )


def _hierarchy_no_genesis(hierarchy: dict | None, temporal: dict | None) -> bool:
    """True only when hierarchy + temporal processing succeeded and genesis count is zero."""
    if not isinstance(hierarchy, dict) or not isinstance(temporal, dict):
        return False
    return (
        hierarchy.get("execution_ok") is True
        and hierarchy.get("scientific_hierarchy_proven") is True
        and hierarchy.get("embedded_core_genesis_event_count") == 0
        and temporal.get("execution_ok") is True
    )


def _component_failure(name: str, payload: dict) -> list[str]:
    failed: list[str] = []
    if payload.get("execution_ok") is False:
        failed.append(f"{name}:execution_ok")
    if name == "radar_scientific_decode" and payload.get("scientific_decode_proven") is False:
        failed.append(f"{name}:scientific_decode_proven")
    return failed


def build_bundle(
    *,
    scientific_dir: Path,
    run_id: str = "",
    commit_sha: str = "",
    generated_at_utc: str | None = None,
) -> dict:
    components: dict[str, dict] = {}
    missing: list[str] = []
    failed: list[str] = []

    for name, filename in COMPONENTS.items():
        path = scientific_dir / filename
        if not path.exists():
            missing.append(name)
            continue
        payload = _load(path)
        components[name] = payload
        failed.extend(_component_failure(name, payload))

    present = set(components)
    missing_set = set(missing)
    no_trackable_event = _tracking_no_event(components.get("radar_tracking"))
    no_embedded_genesis = _hierarchy_no_genesis(
        components.get("radar_hierarchy"),
        components.get("radar_temporal"),
    )

    if no_trackable_event:
        complete = (
            TRACKING_STAGE.issubset(present)
            and not failed
            and missing_set.issubset(set(COMPONENTS) - TRACKING_STAGE)
        )
        collection_status = "COMPLETE_NO_TRACKABLE_EVENT" if complete else "TECHNICAL_INCOMPLETE"
        tracking = components.get("radar_tracking") or {}
        if tracking.get("sample_status") == "NO_PRECIPITATION_AT_TARGET":
            candidate_structure_state = "NO_PRECIPITATION_AT_TARGET"
            interpretation = (
                "Collection completed normally for the exact four-frame slot, and the target "
                "analysis contained no precipitation in the national scan. This is descriptive "
                "absence only and is not an LPZ-negative label."
            )
        else:
            candidate_structure_state = "NO_TEMPORALLY_TRACKABLE_COMPONENT"
            interpretation = (
                "Collection completed normally, but this four-frame live tracking window "
                "contained no temporally trackable precipitation component under the "
                "conservative overlap association. This is not an LPZ-negative label."
            )
    elif no_embedded_genesis:
        complete = (
            HIERARCHY_STAGE.issubset(present)
            and not failed
            and missing_set.issubset(EVENT_STAGE)
        )
        collection_status = "COMPLETE_NO_EMBEDDED_GENESIS" if complete else "TECHNICAL_INCOMPLETE"
        candidate_structure_state = "TRACKABLE_COMPONENT_NO_EMBEDDED_GENESIS"
        interpretation = (
            "Collection completed normally with temporally trackable precipitation "
            "components, but no embedded-core genesis event was observed in this live "
            "window. This is descriptive absence of the downstream event, not an "
            "LPZ-negative label."
        )
    else:
        complete = present == set(COMPONENTS) and not failed
        collection_status = "COMPLETE_FEATURES" if complete else "TECHNICAL_INCOMPLETE"
        candidate_structure_state = "TRACKABLE_COMPONENT_WITH_FEATURES" if complete else "UNKNOWN"
        interpretation = "Prospective derived-feature collection only; no LPZ classification is produced."

    generated = generated_at_utc or (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    tracking = components.get("radar_tracking") or {}
    hierarchy = components.get("radar_hierarchy") or {}
    bundle = {
        "schema_version": "0.3.0",
        "phase": "2E-prospective-derived-feature-archive",
        "entity_type": "PROSPECTIVE_DERIVED_FEATURE_BUNDLE",
        "generated_at_utc": generated,
        "github_run_id": str(run_id),
        "github_commit_sha": str(commit_sha),
        "source_family": "JMA_PUBLIC_RADAR_PLUS_GFS",
        "archive_role": "PROSPECTIVE_NATIVE",
        "collection_status": collection_status,
        "candidate_structure_state": candidate_structure_state,
        "candidate_structure_is_lpz_classification": False,
        "no_event_state_is_negative_label": False,
        "no_trackable_event_is_negative_label": False,
        "raw_radar_archived": False,
        "raw_grib_archived": False,
        "component_count": len(components),
        "missing_components": sorted(missing),
        "failed_components": sorted(failed),
        "bundle_complete": complete,
        "components": components,
        "tracking_window": {
            "frame_valid_times": tracking.get("frame_valid_times"),
            "scientific_tracking_proven": tracking.get("scientific_tracking_proven"),
            "execution_ok": tracking.get("execution_ok"),
        },
        "hierarchy_window": {
            "scientific_hierarchy_proven": hierarchy.get("scientific_hierarchy_proven"),
            "embedded_core_genesis_event_count": hierarchy.get("embedded_core_genesis_event_count"),
            "execution_ok": hierarchy.get("execution_ok"),
        },
        "interpretation": interpretation,
        "lpz_classification": None,
        "risk_score": None,
        "risk_engine_allowed": False,
    }
    return bundle


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scientific-dir", default="reports/scientific")
    p.add_argument("--output", required=True)
    p.add_argument("--run-id", default="")
    p.add_argument("--commit-sha", default="")
    a = p.parse_args()

    bundle = build_bundle(
        scientific_dir=Path(a.scientific_dir),
        run_id=str(a.run_id),
        commit_sha=str(a.commit_sha),
    )

    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "bundle_complete": bundle["bundle_complete"],
                "collection_status": bundle["collection_status"],
                "candidate_structure_state": bundle["candidate_structure_state"],
                "component_count": bundle["component_count"],
                "missing_components": bundle["missing_components"],
                "failed_components": bundle["failed_components"],
                "output": str(out),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if bundle["bundle_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
