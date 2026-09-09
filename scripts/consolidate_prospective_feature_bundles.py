#!/usr/bin/env python3
"""Consolidate prospective feature bundles into one immutable daily gzip JSONL archive."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _load_bundle(path: Path) -> dict:
    p = json.loads(path.read_text(encoding="utf-8"))
    if p.get("entity_type") != "PROSPECTIVE_DERIVED_FEATURE_BUNDLE":
        raise ValueError(f"unexpected bundle entity: {path}")
    if p.get("risk_engine_allowed") is not False or p.get("risk_score") is not None:
        raise ValueError(f"operational score leaked into archive bundle: {path}")
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input-root", required=True)
    ap.add_argument("--date-utc", required=True, help="YYYY-MM-DD")
    ap.add_argument("--output-gz", required=True)
    ap.add_argument("--manifest-output", required=True)
    args = ap.parse_args()

    day = datetime.strptime(args.date_utc, "%Y-%m-%d").replace(tzinfo=timezone.utc).date()
    bundles: list[dict] = []
    errors: list[str] = []
    seen_runs: set[str] = set()

    for path in sorted(Path(args.input_root).rglob("prospective_feature_bundle.json")):
        try:
            b = _load_bundle(path)
            ts = datetime.fromisoformat(str(b["generated_at_utc"]).replace("Z", "+00:00"))
            if ts.date() != day:
                continue
            run_id = str(b.get("github_run_id", ""))
            if run_id and run_id in seen_runs:
                continue
            if run_id:
                seen_runs.add(run_id)
            bundles.append(b)
        except Exception as exc:
            errors.append(f"{path}:{type(exc).__name__}:{exc}")

    bundles.sort(key=lambda x: (x.get("generated_at_utc", ""), x.get("github_run_id", "")))
    out = Path(args.output_gz)
    out.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256()
    with gzip.open(out, "wt", encoding="utf-8", compresslevel=9) as fh:
        for b in bundles:
            line = json.dumps(b, ensure_ascii=False, separators=(",", ":")) + "\n"
            fh.write(line)
            sha.update(line.encode("utf-8"))

    expected_intervals = 96  # 15-minute cadence
    complete_count = sum(bool(b.get("bundle_complete")) for b in bundles)
    coverage = len(bundles) / expected_intervals if expected_intervals else 0.0
    manifest = {
        "schema_version": "0.1.0",
        "phase": "2E-prospective-daily-consolidation",
        "date_utc": args.date_utc,
        "expected_15min_intervals": expected_intervals,
        "bundle_count": len(bundles),
        "complete_bundle_count": complete_count,
        "coverage_fraction": coverage,
        "collector_gap_count": max(expected_intervals - len(bundles), 0),
        "parse_error_count": len(errors),
        "parse_errors": errors[:100],
        "uncompressed_jsonl_sha256": sha.hexdigest(),
        "archive_file": str(out),
        "archive_role": "PROSPECTIVE_NATIVE",
        "raw_radar_archived": False,
        "raw_grib_archived": False,
        "prospective_day_quality": "COMPLETE" if len(bundles) == expected_intervals and complete_count == expected_intervals and not errors else "INCOMPLETE_EXPLICIT_GAPS",
        "risk_engine_allowed": False
    }
    mp = Path(args.manifest_output)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    # A partial day is still archived. Only structural corruption fails.
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
