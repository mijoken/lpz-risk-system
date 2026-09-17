#!/usr/bin/env python3
"""Offline gap-estimation benchmark harness for LPZ prospective observations.

This is deliberately isolated from O8.1 collector / O9 / Primary / Risk Engine.
It evaluates reconstruction methods against *known* observations by masking
contiguous intervals, reconstructing them, and comparing reconstruction with the
held-out truth.  No reconstructed value is ever relabelled as an observation.

Input CSV (minimum):
    timestamp_utc,value
Optional additional numeric columns are accepted via --value-column.

The first baseline is intentionally simple and explainable: time interpolation.
Future JMA/GSMaP/IMERG fusion methods can implement Estimator without changing
the benchmark contract.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Protocol

GAP_MINUTES = (15, 30, 60, 120, 180)
SCHEMA_VERSION = "0.1.0-gap-estimation"


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Observation:
    time: datetime
    value: float


@dataclass
class Reconstruction:
    time: datetime
    truth: float
    estimate: float
    method: str
    provenance: str = "MODEL_ESTIMATED"


class Estimator(Protocol):
    name: str

    def estimate(self, observations: list[Observation], masked_times: set[datetime]) -> list[Reconstruction]: ...


class LinearTimeInterpolator:
    """Transparent baseline: interpolate only between real observations."""

    name = "linear_time_interpolation"

    def estimate(self, observations: list[Observation], masked_times: set[datetime]) -> list[Reconstruction]:
        truth = {o.time: o.value for o in observations}
        available = [o for o in observations if o.time not in masked_times]
        available.sort(key=lambda o: o.time)
        out: list[Reconstruction] = []
        for target in sorted(masked_times):
            before = [o for o in available if o.time < target]
            after = [o for o in available if o.time > target]
            if not before or not after:
                continue
            left, right = before[-1], after[0]
            span = (right.time - left.time).total_seconds()
            if span <= 0:
                continue
            weight = (target - left.time).total_seconds() / span
            estimate = left.value + weight * (right.value - left.value)
            out.append(Reconstruction(target, truth[target], estimate, self.name))
        return out


def load_csv(path: Path, value_column: str) -> list[Observation]:
    rows: list[Observation] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"timestamp_utc", value_column}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"missing CSV columns: {sorted(missing)}")
        for row in reader:
            try:
                value = float(row[value_column])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            rows.append(Observation(parse_utc(row["timestamp_utc"]), value))
    rows.sort(key=lambda x: x.time)
    if len(rows) < 3:
        raise ValueError("at least three valid observations are required")
    return rows


def infer_step_minutes(rows: list[Observation]) -> int:
    deltas = [int((b.time - a.time).total_seconds() // 60) for a, b in zip(rows, rows[1:])]
    positive = [d for d in deltas if d > 0]
    if not positive:
        raise ValueError("could not infer positive observation interval")
    # Mode without importing heavy dependencies.
    return max(set(positive), key=positive.count)


def mask_windows(rows: list[Observation], gap_minutes: int, step_minutes: int):
    n = max(1, math.ceil(gap_minutes / step_minutes))
    # Leave a real observation on both sides; stride by n to avoid a huge,
    # highly-overlapping benchmark while retaining broad temporal coverage.
    for start in range(1, len(rows) - n, n):
        selected = rows[start : start + n]
        if len(selected) == n:
            yield {x.time for x in selected}


def summarize(reconstructions: list[Reconstruction]) -> dict:
    if not reconstructions:
        return {"n": 0, "mae": None, "mean_absolute_percent_error": None, "bias": None}
    errors = [r.estimate - r.truth for r in reconstructions]
    absolute = [abs(x) for x in errors]
    pct = [abs(r.estimate - r.truth) / abs(r.truth) * 100.0 for r in reconstructions if abs(r.truth) > 1e-9]
    return {
        "n": len(reconstructions),
        "mae": round(mean(absolute), 4),
        "mean_absolute_percent_error": round(mean(pct), 3) if pct else None,
        "bias": round(mean(errors), 4),
    }


def run(rows: list[Observation], estimator: Estimator, gap_minutes: tuple[int, ...]) -> dict:
    step = infer_step_minutes(rows)
    results: dict[str, dict] = {}
    for gap in gap_minutes:
        all_recon: list[Reconstruction] = []
        windows = 0
        for masked in mask_windows(rows, gap, step):
            windows += 1
            all_recon.extend(estimator.estimate(rows, masked))
        results[str(gap)] = {
            "gap_minutes": gap,
            "windows_tested": windows,
            "metrics": summarize(all_recon),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark_role": "OFFLINE_HELD_OUT_GAP_RECONSTRUCTION",
        "scientific_observation_values_modified": False,
        "risk_engine_allowed": False,
        "estimator": estimator.name,
        "input": {
            "observation_count": len(rows),
            "first_time_utc": iso_utc(rows[0].time),
            "last_time_utc": iso_utc(rows[-1].time),
            "inferred_step_minutes": step,
        },
        "results_by_gap": results,
        "provenance_contract": {
            "observed": "OBSERVED_* or RECOVERED_JMA",
            "estimated": "MODEL_ESTIMATED",
            "estimated_never_promoted_to_observed": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--value-column", default="value")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--gap-minutes", nargs="*", type=int, default=list(GAP_MINUTES))
    args = parser.parse_args()

    gaps = tuple(sorted(set(args.gap_minutes)))
    if not gaps or any(x <= 0 for x in gaps):
        raise ValueError("gap minutes must be positive")

    rows = load_csv(args.input, args.value_column)
    report = run(rows, LinearTimeInterpolator(), gaps)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
