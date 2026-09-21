#!/usr/bin/env python3
"""F4-0: batch bridge for existing O8.1 and F3 data. No weather processing or forecast."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from build_f4_observed_origin_join import join


def _read(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"not a JSON object: {path}")
    return payload


def _write_new(path: Path, payload: dict) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2, allow_nan=False)
        fp.write("\n")


def build_batch(root: Path) -> dict:
    source = _read(root / "batch_manifest.json")
    f3_manifest = _read(root / "f3_research" / "manifest.json")
    if source.get("risk_engine_allowed") is not False:
        raise ValueError("source batch risk lock not proven")
    if (f3_manifest.get("product") != "F3_RESEARCH_BATCH"
            or f3_manifest.get("risk_engine_allowed") is not False
            or f3_manifest.get("forecast_generated") is not False
            or f3_manifest.get("source_run_id") != source.get("run_id")):
        raise ValueError("F3 manifest mismatch or research lock not proven")
    source_rows = source.get("slot_results")
    f3_rows = f3_manifest.get("slot_results")
    if not isinstance(source_rows, list) or not isinstance(f3_rows, list):
        raise ValueError("missing batch slot_results")
    if len(source_rows) != source.get("requested_slot_count") or len(f3_rows) != len(source_rows):
        raise ValueError("slot counts inconsistent")
    f3_by_file = {r.get("source_file"): r for r in f3_rows}
    if len(f3_by_file) != len(f3_rows):
        raise ValueError("duplicate F3 source file")
    root_slots = root / "slots"
    results = []
    products = []
    seen = set()
    for src in source_rows:
        slot = src.get("collection_slot_utc")
        if not isinstance(slot, str) or not slot.endswith("Z"):
            raise ValueError("O8.1 slot timestamp missing")
        parsed = datetime.fromisoformat(slot.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError("O8.1 slot must be UTC")
        name = parsed.strftime("%Y%m%dT%H%M%SZ.json")
        if name in seen or name not in f3_by_file:
            raise ValueError("source slot mapping missing or duplicate")
        seen.add(name)
        bundle = _read(root_slots / name)
        f3_row = f3_by_file[name]
        if (f3_row.get("collection_slot_utc") != slot
                or bundle.get("collection_slot_utc") != slot):
            raise ValueError("F3/O8.1 slot timestamp mismatch")
        if bundle.get("collection_status") != src.get("collection_status"):
            raise ValueError("O8.1 slot status mismatch")
        status = bundle.get("collection_status")
        row = {
            "source_file": name, "collection_slot_utc": slot,
            "source_collection_status": status,
            "join_status": None, "research_object_count": None,
            "current_origin_count": None, "output_file": None,
            "risk_engine_allowed": False, "forecast_generated": False,
        }
        if status == "COMPLETE_FEATURES":
            if f3_row.get("research_status") != "DESCRIPTIVE_ONLY" or not f3_row.get("output_file"):
                raise ValueError("F3 output missing for complete source")
            f3_file = root / f3_row["output_file"]
            if f3_file.resolve() != (root / "f3_research" / "slots" / name).resolve():
                raise ValueError("F3 output path does not match source slot")
            result = join(bundle, _read(f3_file))
            if result["research_object_count"] != f3_row.get("research_object_count"):
                raise ValueError("research object count differs from F3 manifest")
            dest = root / "f4_observed_origins" / "slots" / name
            if dest.exists():
                raise FileExistsError(dest)
            row.update(join_status="OBSERVED_INPUT_JOINED",
                       research_object_count=result["research_object_count"],
                       current_origin_count=result["current_origin_count"],
                       output_file=str(dest.relative_to(root)))
            products.append((dest, result))
        elif status in {"COMPLETE_NO_TRACKABLE_EVENT", "COMPLETE_NO_EMBEDDED_GENESIS"}:
            if (bundle.get("bundle_complete") is not True
                    or bundle.get("as_of_time_guard_pass") is not True
                    or bundle.get("risk_engine_allowed") is not False
                    or bundle.get("risk_score") is not None
                    or bundle.get("lpz_classification") is not None
                    or f3_row.get("research_status") != "NO_DOWNSTREAM_RESEARCH_OBJECT"
                    or f3_row.get("research_object_count") != 0):
                raise ValueError("invalid complete no-downstream-object slot")
            row.update(join_status="NO_F3_DOWNSTREAM_OBJECT",
                       research_object_count=0, current_origin_count=0)
        elif status == "TECHNICAL_INCOMPLETE":
            if f3_row.get("research_status") != "SOURCE_INCOMPLETE":
                raise ValueError("technical incomplete state mismatch")
            row["join_status"] = "SOURCE_INCOMPLETE"
        else:
            raise ValueError(f"unsupported O8.1 slot state: {status}")
        results.append(row)
    if len(seen) != len(f3_by_file):
        raise ValueError("unmatched F3 rows")
    dest = root / "f4_observed_origins" / "manifest.json"
    if dest.exists():
        raise FileExistsError(dest)
    manifest = {
        "schema_version": "0.1.0", "product": "F4_OBSERVED_ORIGIN_BATCH",
        "source_run_id": source.get("run_id"),
        "source_slot_count": len(results),
        "research_object_count": sum(r["research_object_count"] or 0 for r in results),
        "current_origin_count": sum(r["current_origin_count"] or 0 for r in results),
        "slot_results": results, "risk_engine_allowed": False,
        "official_risk_output": False, "forecast_generated": False,
        "interpretation": "Observed 30 mm/h origins only; no forecast, LPZ label, or negative class.",
    }
    for path, payload in products:
        _write_new(path, payload)
    _write_new(dest, manifest)
    return manifest


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch-root", required=True, type=Path)
    args = p.parse_args()
    out = build_batch(args.batch_root)
    print(json.dumps({k: out[k] for k in (
        "source_run_id", "source_slot_count", "research_object_count",
        "current_origin_count", "forecast_generated")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
