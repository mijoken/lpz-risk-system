#!/usr/bin/env python3
"""Merge chunked ERA5 descriptors and join them to positive snapshots.

Recent requests that CDS explicitly rejects because ERA5 is not published yet
are classified as PENDING_SOURCE_AVAILABILITY, not as hard data failures.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from lpz_risk.historical_environment_join import build_era5_snapshot_feature_table

_SOURCE_LAG_PATTERNS = (
    "none of the data you have requested is available yet",
    "latest date available for this dataset is",
)


def load_request_descriptors(root: Path) -> list[dict]:
    descriptors: list[dict] = []
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("phase") == "2B-era5-batch-request":
            descriptors.append(payload)
    return descriptors


def classify_failed_requests(root: Path) -> tuple[list[int], dict[int, str], list[dict]]:
    pending: list[int] = []
    reasons: dict[int, str] = {}
    hard_failures: list[dict] = []
    for path in sorted(root.rglob("summary_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for record in (payload.get("requests") or {}).values():
            if record.get("status") != "FAIL":
                continue
            index = int(record["request_index"])
            error = str(record.get("error", ""))
            lower = error.lower()
            if any(pattern in lower for pattern in _SOURCE_LAG_PATTERNS):
                pending.append(index)
                reasons[index] = error
            else:
                hard_failures.append({
                    "request_index": index,
                    "request_key": record.get("request_key"),
                    "error": error,
                    "summary_path": str(path),
                })
    return sorted(set(pending)), reasons, hard_failures


def _latest_available_from_reasons(reasons: dict[int, str]) -> str | None:
    matches: list[str] = []
    for reason in reasons.values():
        m = re.search(r"latest date available for this dataset is:\s*([^\n]+)", reason, flags=re.I)
        if m:
            matches.append(m.group(1).strip())
    return sorted(matches)[-1] if matches else None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--descriptor-root", required=True)
    p.add_argument("--output", default="reports/historical/era5_positive_snapshot_feature_table.json")
    p.add_argument("--summary-output", default="reports/historical/era5_positive_snapshot_feature_summary.json")
    a = p.parse_args()

    root = Path(a.descriptor_root)
    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    descriptors = load_request_descriptors(root)
    pending, reasons, hard_failures = classify_failed_requests(root)
    if hard_failures:
        raise ValueError(f"hard ERA5 reconstruction failures remain: {hard_failures[:5]}")

    result = build_era5_snapshot_feature_table(
        manifest,
        descriptors,
        pending_source_availability_indices=pending,
        pending_source_availability_reasons=reasons,
    )
    result["era5_latest_available_reported_by_cds"] = _latest_available_from_reasons(reasons)
    result["source_availability_policy"] = (
        "Recent ERA5 source-lag tail is not imputed or replaced with future data; "
        "it remains pending until CDS publishes the requested source times."
    )

    output = Path(a.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {k: v for k, v in result.items() if k != "snapshot_features"}
    summary["output"] = str(output)
    summary_output = Path(a.summary_output)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "request_descriptor_count": result["request_descriptor_count"],
        "expected_request_count": result["expected_request_count"],
        "snapshot_feature_row_count": result["snapshot_feature_row_count"],
        "expected_snapshot_count": result["expected_snapshot_count"],
        "pending_source_availability_request_count": result["pending_source_availability_request_count"],
        "pending_source_availability_snapshot_count": result["pending_source_availability_snapshot_count"],
        "hard_missing_request_indices": result["hard_missing_request_indices"],
        "hard_missing_snapshot_key_count": result["hard_missing_snapshot_key_count"],
        "future_source_time_count": result["future_source_time_count"],
        "available_window_complete": result["available_window_complete"],
        "historical_environment_reconstruction_complete": result["historical_environment_reconstruction_complete"],
        "era5_latest_available_reported_by_cds": result.get("era5_latest_available_reported_by_cds"),
        "risk_engine_allowed": result["risk_engine_allowed"],
        "output": str(output),
        "summary_output": str(summary_output),
    }, ensure_ascii=False, indent=2))
    return 0 if result["available_window_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
