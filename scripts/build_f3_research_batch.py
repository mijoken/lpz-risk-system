#!/usr/bin/env python3
"""F3-2: Connect archived O8.1 slots to the F3-1 research-only adapter.

Reads existing derived-feature bundles. Does not acquire weather data,
rerun scientific processing, classify LPZ, or publish a forecast.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


def load_adapter():
    path = Path(__file__).with_name("build_lpz_research_candidates.py")
    spec = importlib.util.spec_from_file_location("f3_research_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("F3-1 adapter could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def build_batch(root: Path) -> dict:
    batch_path = root / "batch_manifest.json"
    if not batch_path.is_file():
        raise FileNotFoundError(batch_path)

    batch = json.loads(batch_path.read_text(encoding="utf-8"))

    if batch.get("risk_engine_allowed") is not False:
        raise ValueError("O8.1 batch Risk Engine lock not proven")

    slots_dir = root / "slots"
    output_root = root / "f3_research"
    output_manifest = output_root / "manifest.json"

    if output_manifest.exists():
        raise FileExistsError(
            "F3-2 manifest already exists; refusing overwrite"
        )

    adapter = load_adapter()
    results = []

    for slot_path in sorted(slots_dir.glob("*.json")):
        bundle = json.loads(slot_path.read_text(encoding="utf-8"))

        status = bundle.get("collection_status")
        slot = bundle.get("collection_slot_utc")

        row = {
            "source_file": slot_path.name,
            "collection_slot_utc": slot,
            "source_collection_status": status,
            "research_status": None,
            "research_object_count": None,
            "output_file": None,
            "risk_engine_allowed": False,
            "forecast_generated": False,
        }

        if status == "COMPLETE_FEATURES":
            # F3-1 independently verifies completeness, as-of time,
            # descriptor integrity and Risk Engine invariants.
            result = adapter.adapt(bundle)

            output_path = (
                output_root / "slots" / slot_path.name
            )

            if output_path.exists():
                raise FileExistsError(output_path)

            write_json(output_path, result)

            row["research_status"] = "DESCRIPTIVE_ONLY"
            row["research_object_count"] = result[
                "research_object_count"
            ]
            row["output_file"] = str(
                output_path.relative_to(root)
            )

        elif status in {
            "COMPLETE_NO_TRACKABLE_EVENT",
            "COMPLETE_NO_EMBEDDED_GENESIS",
        }:
            if (
                bundle.get("bundle_complete") is not True
                or bundle.get("as_of_time_guard_pass") is not True
                or bundle.get("risk_engine_allowed") is not False
                or bundle.get("risk_score") is not None
                or bundle.get("lpz_classification") is not None
            ):
                raise ValueError(
                    f"Invalid complete no-event slot: {slot_path.name}"
                )

            row["research_status"] = (
                "NO_DOWNSTREAM_RESEARCH_OBJECT"
            )
            row["research_object_count"] = 0

        elif status == "TECHNICAL_INCOMPLETE":
            row["research_status"] = "SOURCE_INCOMPLETE"

        else:
            raise ValueError(
                f"Unknown collection status in {slot_path.name}: "
                f"{status}"
            )

        results.append(row)

    manifest = {
        "schema_version": "0.1.0",
        "product": "F3_RESEARCH_BATCH",
        "source_run_id": batch.get("run_id"),
        "source_batch_state": batch.get("state"),
        "source_slot_count": len(results),
        "research_object_count": sum(
            row["research_object_count"] or 0
            for row in results
        ),
        "slot_results": results,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "forecast_generated": False,
        "interpretation": (
            "Descriptive research objects only; no LPZ "
            "classification, forecast or negative labels."
        ),
    }

    write_json(output_manifest, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batch-root",
        type=Path,
        required=True,
    )
    args = parser.parse_args()

    result = build_batch(args.batch_root)

    print(
        json.dumps(
            {
                "product": result["product"],
                "source_slot_count": result["source_slot_count"],
                "research_object_count": result[
                    "research_object_count"
                ],
                "forecast_generated": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
