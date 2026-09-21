#!/usr/bin/env python3
"""F3: Convert an existing prospective feature bundle into descriptive research objects.

No LPZ prediction, classification, score, probability or official-risk output.
No weather acquisition. No assumption about descriptor geometry keys.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SOURCE_COMPONENT = "parent_precursor_features"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def adapt(bundle: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise ValueError("bundle must be an object")
    if bundle.get("risk_engine_allowed") is not False:
        raise ValueError("source risk_engine_allowed must be false")
    if bundle.get("risk_score") is not None or bundle.get("lpz_classification") is not None:
        raise ValueError("source contains risk output or LPZ classification")
    if bundle.get("bundle_complete") is not True or bundle.get("collection_status") != "COMPLETE_FEATURES":
        raise ValueError("source must be a complete feature bundle; other states require separate handling")
    if bundle.get("as_of_time_guard_pass") is not True:
        raise ValueError("source as-of time guard is not proven")
    as_of = bundle.get("prospective_as_of_utc")
    if not isinstance(as_of, str) or not as_of:
        raise ValueError("missing prospective_as_of_utc")
    components = bundle.get("components")
    if not isinstance(components, dict):
        raise ValueError("missing components")
    report = components.get(SOURCE_COMPONENT)
    if not isinstance(report, dict) or report.get("execution_ok") is not True:
        raise ValueError("missing successful parent precursor report")
    if report.get("risk_engine_allowed") is not False or report.get("risk_score") is not None or report.get("classification") is not None:
        raise ValueError("parent precursor report is not research-only")
    descriptors = report.get("descriptors")
    if not isinstance(descriptors, list) or not all(isinstance(row, dict) for row in descriptors):
        raise ValueError("descriptors must be an array of objects")
    if report.get("descriptor_count") != len(descriptors):
        raise ValueError("descriptor_count mismatch")
    source_sha256 = _digest(bundle)
    rows = []
    for index, descriptor in enumerate(descriptors):
        # Retain the entire source row; do not invent location, geometry, or forecast horizon.
        rows.append({
            "research_object_id": f"F3-{source_sha256[:16]}-{index:06d}",
            "source_descriptor_index": index,
            "source_descriptor_sha256": _digest(descriptor),
            "source_descriptor": descriptor,
            "geometry": None,
            "geometry_status": "NOT_MAPPED_FROM_UNVERIFIED_DESCRIPTOR_SCHEMA",
            "lpz_classification": None,
            "forecast_valid_time_utc": None,
            "forecast_probability": None,
        })
    return {
        "schema_version": "0.1.0",
        "product": "LPZ_RESEARCH_OBJECT_ADAPTER",
        "status": "DESCRIPTIVE_ONLY",
        "source_bundle_sha256": source_sha256,
        "source_bundle_schema_version": bundle.get("schema_version"),
        "source_archive_role": bundle.get("archive_role"),
        "source_collection_status": bundle["collection_status"],
        "source_as_of_utc": as_of,
        "source_component": SOURCE_COMPONENT,
        "research_object_count": len(rows),
        "research_objects": rows,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "forecast_generated": False,
        "interpretation": "Existing prospective parent descriptors preserved as research objects; not LPZ candidates or predictions.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path, help="existing O8.1 slot bundle JSON")
    parser.add_argument("--output", required=True, type=Path, help="new descriptive adapter JSON")
    args = parser.parse_args()
    if args.bundle.resolve() == args.output.resolve():
        parser.error("input and output paths must differ")
    if args.output.exists():
        parser.error("output already exists; refusing overwrite")
    payload = json.loads(args.bundle.read_text(encoding="utf-8"))
    result = adapt(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "research_object_count": result["research_object_count"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
