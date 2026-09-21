#!/usr/bin/env python3
"""F4-1: batch research point baseline derived from existing O8.1 + F3.

No weather re-acquisition, no recalibration, no LPZ forecast or negative labels.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_f4_research_motion_baseline import project


def _read(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"expected JSON object: {path}")
    return obj


def _write(path: Path, obj: dict) -> None:
    if path.exists():
        raise FileExistsError(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as out:
        json.dump(obj, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write("\n")


def build_batch(root: Path) -> dict:
    o8 = _read(root / "batch_manifest.json")
    f3 = _read(root / "f3_research" / "manifest.json")
    f4 = _read(root / "f4_observed_origins" / "manifest.json")
    if (o8.get("risk_engine_allowed") is not False
            or f3.get("risk_engine_allowed") is not False
            or f3.get("forecast_generated") is not False
            or f4.get("risk_engine_allowed") is not False
            or f4.get("forecast_generated") is not False
            or f3.get("source_run_id") != o8.get("run_id")
            or f4.get("source_run_id") != o8.get("run_id")):
        raise ValueError("upstream run mismatch or research lock not proven")
    slots = o8.get("slot_results")
    joined_rows = f4.get("slot_results")
    f3_rows = f3.get("slot_results")
    if (not isinstance(slots, list) or not isinstance(joined_rows, list)
            or not isinstance(f3_rows, list)
            or len(slots) != o8.get("requested_slot_count")
            or len(slots) != len(joined_rows)
            or len(slots) != len(f3_rows)):
        raise ValueError("upstream slot counts disagree")

    joined_by_file = {r["source_file"]: r for r in joined_rows}
    f3_by_file = {r["source_file"]: r for r in f3_rows}
    if len(joined_by_file) != len(slots) or len(f3_by_file) != len(slots):
        raise ValueError("duplicate/missing upstream slot")
    outputs = []
    results = []
    seen = set()
    for row in joined_rows:
        name = row["source_file"]
        if (name in seen or Path(name).name != name
                or not name.endswith(".json")):
            raise ValueError("invalid or duplicate source slot name")
        seen.add(name)
        src = _read(root / "slots" / name)
        f3_row = f3_by_file[name]
        if (row["collection_slot_utc"] != src.get("collection_slot_utc")
                or f3_row["collection_slot_utc"] != row["collection_slot_utc"]
                or row["source_collection_status"] != src.get("collection_status")):
            raise ValueError("slot or source status mismatch")
        record = {
            "source_file": name,
            "collection_slot_utc": row["collection_slot_utc"],
            "source_collection_status": row["source_collection_status"],
            "research_status": None,
            "research_object_count": row["research_object_count"],
            "projected_object_count": None,
            "output_file": None,
            "risk_engine_allowed": False,
            "lpz_forecast_generated": False,
        }
        if row["join_status"] == "OBSERVED_INPUT_JOINED":
            expected_f3 = (root / "f3_research" / "slots" / name).resolve()
            expected_f4 = (root / "f4_observed_origins" / "slots" / name).resolve()
            if ((root / f3_row["output_file"]).resolve() != expected_f3
                    or (root / row["output_file"]).resolve() != expected_f4):
                raise ValueError("upstream output path mismatch")
            existing_join = _read(expected_f4)
            if (existing_join.get("risk_engine_allowed") is not False
                    or existing_join.get("forecast_generated") is not False
                    or existing_join.get("current_origin_count") != row["current_origin_count"]):
                raise ValueError("F4-0 source contract mismatch")
            baseline = project(src, _read(expected_f3))
            if baseline["research_object_count"] != row["research_object_count"]:
                raise ValueError("F4-1 object count mismatch")
            dest = root / "f4_research_motion" / "slots" / name
            if dest.exists():
                raise FileExistsError(dest)
            record.update(research_status="RESEARCH_POINT_BASELINE",
                          projected_object_count=baseline["projected_object_count"],
                          output_file=str(dest.relative_to(root)))
            outputs.append((dest, baseline))
        elif row["join_status"] == "NO_F3_DOWNSTREAM_OBJECT":
            if (f3_row["research_status"] != "NO_DOWNSTREAM_RESEARCH_OBJECT"
                    or row["research_object_count"] != 0
                    or row["current_origin_count"] != 0):
                raise ValueError("invalid no-downstream-object status")
            record.update(research_status="NO_DOWNSTREAM_RESEARCH_OBJECT",
                          projected_object_count=0)
        elif row["join_status"] == "SOURCE_INCOMPLETE":
            if f3_row["research_status"] != "SOURCE_INCOMPLETE":
                raise ValueError("technical state mismatch")
            record["research_status"] = "SOURCE_INCOMPLETE"
        else:
            raise ValueError(f"unknown F4-0 state: {row['join_status']}")
        results.append(record)
    output_manifest = root / "f4_research_motion" / "manifest.json"
    if output_manifest.exists():
        raise FileExistsError(output_manifest)
    manifest = {
        "schema_version": "0.1.0",
        "product": "F4_RESEARCH_POINT_MOTION_BATCH",
        "source_run_id": o8["run_id"],
        "source_slot_count": len(results),
        "research_object_count": sum(r["research_object_count"] or 0 for r in results),
        "projected_object_count": sum(r["projected_object_count"] or 0 for r in results),
        "slot_results": results,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "interpretation": "Research-only future point baseline, not LPZ occurrence, probability or extent.",
    }
    if manifest["research_object_count"] != f4.get("research_object_count"):
        raise ValueError("F4-0 object count mismatch")
    for path, obj in outputs:
        _write(path, obj)
    _write(output_manifest, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", required=True, type=Path)
    args = parser.parse_args()
    result = build_batch(args.batch_root)
    print(json.dumps({key: result[key] for key in (
        "source_run_id", "source_slot_count", "research_object_count",
        "projected_object_count", "lpz_forecast_generated")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
