#!/usr/bin/env python3
"""Build one prospective derived-feature bundle from audited live scientific reports.

The bundle intentionally contains derived scientific JSON only. Raw radar PNG/tiles and
GRIB payloads are never archived here. No risk score or LPZ classification is produced.
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


def _load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"component is not a JSON object: {path}")
    return payload


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scientific-dir", default="reports/scientific")
    p.add_argument("--output", required=True)
    p.add_argument("--run-id", default="")
    p.add_argument("--commit-sha", default="")
    a = p.parse_args()

    root = Path(a.scientific_dir)
    components: dict[str, dict] = {}
    missing: list[str] = []
    failed: list[str] = []
    for name, filename in COMPONENTS.items():
        path = root / filename
        if not path.exists():
            missing.append(name)
            continue
        payload = _load(path)
        components[name] = payload
        # Do not assume every historical report uses the same success key.
        for key in ("execution_ok", "scientific_decode_proven"):
            if key in payload and payload[key] is False:
                failed.append(f"{name}:{key}")

    required = set(COMPONENTS)
    complete = set(components) == required and not failed
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    bundle = {
        "schema_version": "0.1.0",
        "phase": "2E-prospective-derived-feature-archive",
        "entity_type": "PROSPECTIVE_DERIVED_FEATURE_BUNDLE",
        "generated_at_utc": generated,
        "github_run_id": str(a.run_id),
        "github_commit_sha": str(a.commit_sha),
        "source_family": "JMA_PUBLIC_RADAR_PLUS_GFS",
        "archive_role": "PROSPECTIVE_NATIVE",
        "raw_radar_archived": False,
        "raw_grib_archived": False,
        "component_count": len(components),
        "missing_components": missing,
        "failed_components": failed,
        "bundle_complete": complete,
        "components": components,
        "lpz_classification": None,
        "risk_score": None,
        "risk_engine_allowed": False,
    }

    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({
        "bundle_complete": complete,
        "component_count": len(components),
        "missing_components": missing,
        "failed_components": failed,
        "output": str(out),
    }, ensure_ascii=False, indent=2))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
