#!/usr/bin/env python3
"""F4-4 batch bridge: research-only geographic envelopes for prospective slots.

Consumes already-built F4-0 observed origins and F4-1 point-motion research
products. No weather re-acquisition, no LPZ probability, no severity, no risk
engine output, and no invented geometry when an observed envelope is missing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_f4_geographic_envelope import build


def _read(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_new(path: Path, payload: dict) -> None:
    if path.exists():
        raise FileExistsError(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2, allow_nan=False)
        fp.write("\n")


def build_batch(root: Path) -> dict:
    o8 = _read(root / "batch_manifest.json")
    origins_manifest = _read(root / "f4_observed_origins" / "manifest.json")
    motion_manifest = _read(root / "f4_research_motion" / "manifest.json")

    if o8.get("risk_engine_allowed") is not False:
        raise ValueError("O8.1 risk lock not proven")
    if (origins_manifest.get("product") != "F4_OBSERVED_ORIGIN_BATCH"
            or origins_manifest.get("risk_engine_allowed") is not False
            or origins_manifest.get("official_risk_output") is not False
            or origins_manifest.get("forecast_generated") is not False):
        raise ValueError("F4-0 manifest mismatch or research lock not proven")
    if (motion_manifest.get("product") != "F4_RESEARCH_POINT_MOTION_BATCH"
            or motion_manifest.get("risk_engine_allowed") is not False
            or motion_manifest.get("official_risk_output") is not False
            or motion_manifest.get("lpz_forecast_generated") is not False):
        raise ValueError("F4-1 manifest mismatch or research lock not proven")

    run_id = o8.get("run_id")
    if (origins_manifest.get("source_run_id") != run_id
            or motion_manifest.get("source_run_id") != run_id):
        raise ValueError("F4 upstream run mismatch")

    source_rows = o8.get("slot_results")
    origin_rows = origins_manifest.get("slot_results")
    motion_rows = motion_manifest.get("slot_results")
    expected_slots = o8.get("requested_slot_count")
    if (not isinstance(source_rows, list)
            or not isinstance(origin_rows, list)
            or not isinstance(motion_rows, list)
            or len(source_rows) != expected_slots
            or len(origin_rows) != expected_slots
            or len(motion_rows) != expected_slots):
        raise ValueError("F4 upstream slot counts disagree")

    origin_by_file = {row.get("source_file"): row for row in origin_rows}
    motion_by_file = {row.get("source_file"): row for row in motion_rows}
    if len(origin_by_file) != len(origin_rows) or len(motion_by_file) != len(motion_rows):
        raise ValueError("duplicate F4 upstream source file")

    outputs: list[tuple[Path, dict]] = []
    results: list[dict] = []
    seen: set[str] = set()

    for source_row in source_rows:
        slot = source_row.get("collection_slot_utc")
        if not isinstance(slot, str) or not slot.endswith("Z"):
            raise ValueError("invalid O8.1 slot timestamp")

        # F4 batch adapters use deterministic filenames from the UTC slot.
        name = slot.replace("-", "").replace(":", "")
        if name.endswith("Z"):
            name = name[:-1] + "Z.json"
        if "T" not in name or name in seen:
            raise ValueError("invalid or duplicate derived source filename")
        seen.add(name)

        origin_row = origin_by_file.get(name)
        motion_row = motion_by_file.get(name)
        if origin_row is None or motion_row is None:
            raise ValueError("missing F4 upstream slot mapping")
        if (origin_row.get("collection_slot_utc") != slot
                or motion_row.get("collection_slot_utc") != slot
                or origin_row.get("source_collection_status") != source_row.get("collection_status")
                or motion_row.get("source_collection_status") != source_row.get("collection_status")):
            raise ValueError("F4 upstream slot metadata mismatch")

        record = {
            "source_file": name,
            "collection_slot_utc": slot,
            "source_collection_status": source_row.get("collection_status"),
            "research_status": None,
            "research_object_count": origin_row.get("research_object_count"),
            "source_envelope_count": None,
            "projected_envelope_count": None,
            "missing_envelope_count": None,
            "feature_count": None,
            "output_file": None,
            "risk_engine_allowed": False,
            "official_risk_output": False,
            "lpz_forecast_generated": False,
            "probability_generated": False,
            "severity_generated": False,
        }

        if origin_row.get("join_status") == "OBSERVED_INPUT_JOINED":
            if motion_row.get("research_status") != "RESEARCH_POINT_BASELINE":
                raise ValueError("joined F4-0 slot lacks F4-1 research baseline")
            if origin_row.get("research_object_count") != motion_row.get("research_object_count"):
                raise ValueError("F4-0/F4-1 slot object count mismatch")

            expected_origins = (root / "f4_observed_origins" / "slots" / name).resolve()
            expected_motion = (root / "f4_research_motion" / "slots" / name).resolve()
            if ((root / origin_row["output_file"]).resolve() != expected_origins
                    or (root / motion_row["output_file"]).resolve() != expected_motion):
                raise ValueError("F4 upstream output path mismatch")

            result = build(_read(expected_origins), _read(expected_motion))
            dest = root / "f4_geographic_envelopes" / "slots" / name
            if dest.exists():
                raise FileExistsError(dest)

            record.update(
                research_status="RESEARCH_GEOGRAPHIC_ENVELOPE",
                source_envelope_count=result["source_envelope_count"],
                projected_envelope_count=result["projected_envelope_count"],
                missing_envelope_count=result["missing_envelope_count"],
                feature_count=result["feature_count"],
                output_file=str(dest.relative_to(root)),
            )
            outputs.append((dest, result))

        elif origin_row.get("join_status") == "NO_F3_DOWNSTREAM_OBJECT":
            if (motion_row.get("research_status") != "NO_DOWNSTREAM_RESEARCH_OBJECT"
                    or origin_row.get("research_object_count") != 0
                    or motion_row.get("research_object_count") != 0):
                raise ValueError("invalid no-downstream-object F4 state")
            record.update(
                research_status="NO_DOWNSTREAM_RESEARCH_OBJECT",
                source_envelope_count=0,
                projected_envelope_count=0,
                missing_envelope_count=0,
                feature_count=0,
            )

        elif origin_row.get("join_status") == "SOURCE_INCOMPLETE":
            if motion_row.get("research_status") != "SOURCE_INCOMPLETE":
                raise ValueError("F4 technical state mismatch")
            record["research_status"] = "SOURCE_INCOMPLETE"

        else:
            raise ValueError(f"unsupported F4-0 join status: {origin_row.get('join_status')}")

        results.append(record)

    if len(seen) != len(origin_by_file) or len(seen) != len(motion_by_file):
        raise ValueError("unmatched F4 upstream rows")

    manifest_path = root / "f4_geographic_envelopes" / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(manifest_path)

    manifest = {
        "schema_version": "0.1.0",
        "product": "F4_RESEARCH_GEOGRAPHIC_ENVELOPE_BATCH",
        "source_run_id": run_id,
        "source_slot_count": len(results),
        "research_object_count": sum(row["research_object_count"] or 0 for row in results),
        "source_envelope_count": sum(row["source_envelope_count"] or 0 for row in results),
        "projected_envelope_count": sum(row["projected_envelope_count"] or 0 for row in results),
        "missing_envelope_count": sum(row["missing_envelope_count"] or 0 for row in results),
        "feature_count": sum(row["feature_count"] or 0 for row in results),
        "slot_results": results,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
        "interpretation": (
            "Research-only geographic envelope batch derived from F4-0 observed "
            "threshold components and F4-1 constant-motion point baselines. "
            "Not validated LPZ occurrence, probability, severity, or exact future precipitation extent."
        ),
    }

    if manifest["research_object_count"] != origins_manifest.get("research_object_count"):
        raise ValueError("F4-0 aggregate object count mismatch")

    for path, payload in outputs:
        _write_new(path, payload)
    _write_new(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", required=True, type=Path)
    args = parser.parse_args()
    result = build_batch(args.batch_root)
    print(json.dumps({
        key: result[key] for key in (
            "source_run_id",
            "source_slot_count",
            "research_object_count",
            "source_envelope_count",
            "projected_envelope_count",
            "missing_envelope_count",
            "feature_count",
            "lpz_forecast_generated",
        )
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
