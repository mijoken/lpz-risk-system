#!/usr/bin/env python3
"""Extract continuous numeric features from canonical prospective daily archives.

Purpose
-------
Prepare Stage-A inputs for ``gap_estimation_harness.py`` without modifying O8.1,
O9, Primary, ERA5, or Risk Engine. Only COMPLETE canonical slots are eligible.
Explicit gaps and technical-incomplete slots are excluded rather than imputed.

The extractor discovers numeric leaf values inside each slot ``bundle`` and emits
one CSV per feature only when the feature has enough observations and at least one
continuous run long enough for held-out gap tests.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

UTC = timezone.utc


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iter_numeric_leaves(value: Any, prefix: str = "") -> Iterable[tuple[str, float]]:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        yield prefix or "value", float(value)
        return
    if isinstance(value, dict):
        for key in sorted(value):
            child = value[key]
            name = f"{prefix}.{key}" if prefix else str(key)
            yield from iter_numeric_leaves(child, name)
        return
    # Lists are intentionally ignored for Stage A because positional semantics
    # (e.g. object arrays) are not stable scalar features across slots.


def read_archive(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no}: canonical row is not an object")
            rows.append(obj)
    return rows


def continuous_run_lengths(times: list[datetime], step_minutes: int = 15) -> list[int]:
    if not times:
        return []
    times = sorted(set(times))
    runs: list[int] = []
    current = 1
    for left, right in zip(times, times[1:]):
        delta = int((right - left).total_seconds() // 60)
        if delta == step_minutes:
            current += 1
        else:
            runs.append(current)
            current = 1
    runs.append(current)
    return runs


def safe_name(feature: str) -> str:
    keep = []
    for ch in feature:
        if ch.isalnum() or ch in "-_":
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep).strip("_")[:180]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", nargs="+", required=True, type=Path, help="Canonical .jsonl.gz archives")
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument("--min-observations", type=int, default=24)
    ap.add_argument("--min-continuous-slots", type=int, default=14,
                    help="14 slots gives room for a 180-minute gap plus boundary observations")
    ap.add_argument("--top", type=int, default=30,
                    help="Write at most this many best-covered numeric features")
    args = ap.parse_args()

    feature_rows: dict[str, list[tuple[datetime, float, str, str]]] = defaultdict(list)
    slot_counts = {"complete": 0, "explicit_gap": 0, "technical_incomplete": 0, "other": 0}

    for archive in sorted(args.input):
        for row in read_archive(archive):
            state = str(row.get("slot_state") or "")
            if state == "COMPLETE":
                slot_counts["complete"] += 1
            elif state == "EXPLICIT_GAP":
                slot_counts["explicit_gap"] += 1
                continue
            elif state == "TECHNICAL_INCOMPLETE":
                slot_counts["technical_incomplete"] += 1
                continue
            else:
                slot_counts["other"] += 1
                continue

            slot_raw = row.get("collection_slot_utc")
            bundle = row.get("bundle")
            if not isinstance(slot_raw, str) or not isinstance(bundle, dict):
                continue
            slot = parse_utc(slot_raw)
            role = str(row.get("selected_archive_role") or "")
            for feature, numeric in iter_numeric_leaves(bundle):
                feature_rows[feature].append((slot, numeric, role, archive.name))

    candidates: list[dict[str, Any]] = []
    for feature, values in feature_rows.items():
        # One value per slot; deterministic first value if duplicates somehow exist.
        by_time: dict[datetime, tuple[float, str, str]] = {}
        for t, v, role, source in sorted(values, key=lambda x: (x[0], x[3])):
            by_time.setdefault(t, (v, role, source))
        times = sorted(by_time)
        runs = continuous_run_lengths(times)
        candidates.append({
            "feature": feature,
            "observation_count": len(times),
            "longest_continuous_slots": max(runs) if runs else 0,
            "continuous_run_count": len(runs),
            "rows": by_time,
        })

    eligible = [c for c in candidates
                if c["observation_count"] >= args.min_observations
                and c["longest_continuous_slots"] >= args.min_continuous_slots]
    eligible.sort(key=lambda c: (-c["longest_continuous_slots"], -c["observation_count"], c["feature"]))
    selected = eligible[: max(0, args.top)]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_features: list[dict[str, Any]] = []
    for rank, item in enumerate(selected, 1):
        filename = f"{rank:02d}_{safe_name(item['feature'])}.csv"
        out = args.output_dir / filename
        with out.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["timestamp_utc", "value", "archive_role", "source_archive", "feature_path"])
            for t in sorted(item["rows"]):
                value, role, source = item["rows"][t]
                writer.writerow([iso_utc(t), repr(value), role, source, item["feature"]])
        manifest_features.append({
            "rank": rank,
            "feature_path": item["feature"],
            "csv": filename,
            "observation_count": item["observation_count"],
            "longest_continuous_slots": item["longest_continuous_slots"],
            "longest_continuous_minutes": (item["longest_continuous_slots"] - 1) * 15,
            "continuous_run_count": item["continuous_run_count"],
        })

    manifest = {
        "schema_version": "0.1.0-gap-stage-a-extractor",
        "role": "OFFLINE_GAP_ESTIMATION_STAGE_A_INPUT",
        "input_archives": [str(p) for p in sorted(args.input)],
        "slot_counts": slot_counts,
        "numeric_feature_count_discovered": len(candidates),
        "eligible_feature_count": len(eligible),
        "selected_feature_count": len(selected),
        "selection": {
            "min_observations": args.min_observations,
            "min_continuous_slots": args.min_continuous_slots,
            "top": args.top,
        },
        "features": manifest_features,
        "estimated_values_created": False,
        "risk_engine_allowed": False,
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
