#!/usr/bin/env python3
"""Capture reproducible JMA HRPN raw PNG evidence.

RESEARCH ONLY.

By default, captures the latest settled contiguous seven-frame sequence.
An exact UTC end frame can instead be supplied with --target-end.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpz_risk.jma_raw_evidence import (
    DEFAULT_BBOX,
    DEFAULT_FRAME_COUNT,
    DEFAULT_SETTLEMENT_MINUTES,
    DEFAULT_ZOOM,
    TIMES_URL,
    analysis_row_map,
    capture_sequence,
    exact_sequence,
    fetch_bytes,
    latest_settled_sequence,
)


DEFAULT_OUTPUT = Path(
    "local_data/c3_jma_raw_evidence"
)


def parse_iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--target-end",
        default="",
        help="Exact UTC final JMA frame, e.g. 2026-09-18T04:30:00Z",
    )
    parser.add_argument(
        "--frame-count",
        type=int,
        default=DEFAULT_FRAME_COUNT,
    )
    parser.add_argument(
        "--zoom",
        type=int,
        default=DEFAULT_ZOOM,
    )
    parser.add_argument(
        "--settlement-minutes",
        type=int,
        default=DEFAULT_SETTLEMENT_MINUTES,
    )
    parser.add_argument(
        "--west",
        type=float,
        default=DEFAULT_BBOX["west"],
    )
    parser.add_argument(
        "--east",
        type=float,
        default=DEFAULT_BBOX["east"],
    )
    parser.add_argument(
        "--south",
        type=float,
        default=DEFAULT_BBOX["south"],
    )
    parser.add_argument(
        "--north",
        type=float,
        default=DEFAULT_BBOX["north"],
    )

    args = parser.parse_args()

    raw, status, content_type = fetch_bytes(
        TIMES_URL
    )

    if status != 200:
        raise RuntimeError(
            f"targetTimes HTTP status={status}"
        )

    rows = json.loads(
        raw.decode("utf-8")
    )

    if not isinstance(rows, list):
        raise ValueError(
            "targetTimes_N1.json was not a list"
        )

    row_map = analysis_row_map(rows)

    if args.target_end:
        sequence = exact_sequence(
            row_map,
            parse_iso_utc(args.target_end),
            frame_count=args.frame_count,
        )
        selection_mode = "EXACT_TARGET_END"
    else:
        sequence = latest_settled_sequence(
            row_map,
            datetime.now(timezone.utc),
            frame_count=args.frame_count,
            settlement_minutes=args.settlement_minutes,
        )
        selection_mode = "LATEST_SETTLED"
    
    bbox = {
        "west": args.west,
        "east": args.east,
        "south": args.south,
        "north": args.north,
    }

    result = capture_sequence(
        sequence,
        args.output_root,
        bbox=bbox,
        zoom=args.zoom,
    )

    manifest = result["manifest"]

    summary = {
        "phase": "C-3F-JMA-raw-evidence-capture",
        "selection_mode": selection_mode,
        "target_times_http_status": status,
        "target_times_content_type": content_type,
        "capture_dir": result["capture_dir"],
        "manifest_path": result["manifest_path"],
        "source": manifest["source"],
        "frame_count": manifest["frame_count"],
        "support": manifest["support"],
        "tile_count_per_frame": manifest[
            "tile_count_per_frame"
        ],
        "expected_downloads": manifest[
            "expected_downloads"
        ],
        "successful_downloads": manifest[
            "successful_downloads"
        ],
        "failed_downloads": manifest[
            "failed_downloads"
        ],
        "raw_radar_archived": manifest[
            "raw_radar_archived"
        ],
        "risk_engine_allowed": False,
        "production_integration_allowed": False,
        "result": manifest["result"],
    }

    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )

    return (
        0
        if manifest["result"]
        == "PASS_JMA_RAW_EVIDENCE_CAPTURE"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
