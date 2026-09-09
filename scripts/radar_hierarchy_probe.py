#!/usr/bin/env python3
"""Phase 1C live proof for hierarchical precipitation-system structure.

The probe consumes the already-produced radar_tracking.json to reuse its exact
four frame times and fixed z8 footprint. It reconstructs only those 16 tiles per
frame, then maps >=50 and >=80 mm/h child cores into >=30 mm/h parent envelopes.

This is descriptive temporal structure, not an LPZ classifier or back-building
claim. Core genesis inside an already-existing parent is logged as evidence for
later historical study only.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.radar_hierarchy import assign_children_to_parents, validate_nested_hierarchy  # noqa: E402
from lpz_risk.radar_science import decode_jma_precipitation_png  # noqa: E402
from lpz_risk.radar_tracking import extract_pixel_components  # noqa: E402

USER_AGENT = "lpz-risk-system/0.1.0 (+https://github.com/mijoken/lpz-risk-system)"
NOWC_TIMES = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"
TIMEOUT_SECONDS = 20
MAX_TILE_BYTES = 2 * 1024 * 1024
WORKERS = 8
ZOOM = 8
TILE_SIZE = 256


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def http_get(url: str, max_bytes: int) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Cache-Control": "no-cache"})
    with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError(f"response exceeded {max_bytes} byte limit")
    return body


def load_json_url(url: str) -> Any:
    return json.loads(http_get(url, 2 * 1024 * 1024).decode("utf-8"))


def tile_url(row: dict[str, Any], x: int, y: int) -> str:
    return (
        "https://www.jma.go.jp/bosai/jmatile/data/nowc/"
        f"{row['basetime']}/none/{row['validtime']}/surf/hrpns/{ZOOM}/{x}/{y}.png"
    )


def fetch_tile(row: dict[str, Any], x: int, y: int) -> tuple[int, int, np.ndarray, int]:
    decoded = decode_jma_precipitation_png(http_get(tile_url(row, x, y), MAX_TILE_BYTES))
    return x, y, decoded.class_index, decoded.unknown_opaque_pixel_count


def build_mosaic(row: dict[str, Any], origin_x: int, origin_y: int) -> np.ndarray:
    tiles = [(origin_x + dx, origin_y + dy) for dy in range(4) for dx in range(4)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda xy: fetch_tile(row, xy[0], xy[1]), tiles))
    unknown = sum(item[3] for item in results)
    if unknown:
        raise RuntimeError(f"unknown opaque pixels={unknown} at {row['validtime']}")
    by_xy = {(x, y): arr for x, y, arr, _ in results}
    mosaic = np.full((4 * TILE_SIZE, 4 * TILE_SIZE), -1, dtype=np.int8)
    for dy in range(4):
        for dx in range(4):
            mosaic[dy*TILE_SIZE:(dy+1)*TILE_SIZE, dx*TILE_SIZE:(dx+1)*TILE_SIZE] = by_xy[(origin_x+dx, origin_y+dy)]
    return mosaic


def lineages_by_frame(track_block: dict[str, Any]) -> list[dict[int, str]]:
    return [
        {int(comp["local_id"]): str(comp["lineage_id"]) for comp in frame["components"]}
        for frame in track_block["frames"]
    ]


def first_frame_by_lineage(frame_maps: list[dict[int, str]]) -> dict[str, int]:
    first: dict[str, int] = {}
    for idx, fmap in enumerate(frame_maps):
        for lineage in fmap.values():
            first.setdefault(lineage, idx)
    return first


def run(tracking_path: Path) -> dict[str, Any]:
    base = {
        "schema_version": "0.1.0",
        "phase": "1C-radar-hierarchy-proof",
        "feature_id": "parent_envelope_embedded_core_hierarchy_public_png",
        "parent_threshold_mmph": 30,
        "child_thresholds_mmph": [50, 80],
        "operational_gate": False,
        "backbuilding_claim": False,
        "risk_engine_allowed": False,
    }
    try:
        tracking = json.loads(tracking_path.read_text(encoding="utf-8"))
        if not tracking.get("scientific_tracking_proven"):
            raise ValueError("tracking proof is not scientifically proven")
        times = [parse_iso(v) for v in tracking["frame_valid_times"]]
        origin_x = int(tracking["fixed_mosaic"]["origin_tile_x"])
        origin_y = int(tracking["fixed_mosaic"]["origin_tile_y"])

        rows = load_json_url(NOWC_TIMES)
        if not isinstance(rows, list):
            raise ValueError("targetTimes_N1.json was not a list")
        row_by_time = {
            datetime.strptime(str(r["validtime"]), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc): r
            for r in rows
            if r.get("validtime") and "hrpns" in r.get("elements", [])
        }
        selected_rows = []
        for dt in times:
            if dt not in row_by_time:
                raise RuntimeError(f"tracking frame no longer present in targetTimes_N1: {iso_utc(dt)}")
            selected_rows.append(row_by_time[dt])

        parent_lineages = lineages_by_frame(tracking["tracking"]["30"])
        child_lineages = {
            threshold: lineages_by_frame(tracking["tracking"][str(threshold)])
            for threshold in (50, 80)
        }
        child_first = {
            threshold: first_frame_by_lineage(child_lineages[threshold])
            for threshold in (50, 80)
        }

        frames_out: list[dict[str, Any]] = []
        genesis_events: list[dict[str, Any]] = []
        all_nested_ok = True

        for idx, (dt, row) in enumerate(zip(times, selected_rows)):
            mosaic = build_mosaic(row, origin_x, origin_y)
            parents = extract_pixel_components(mosaic, threshold_mmph=30.0, min_pixels=2)
            parent_by_id = {p.local_id: p for p in parents}
            frame_out: dict[str, Any] = {
                "frame_index": idx,
                "valid_time": iso_utc(dt),
                "parent_count": len(parents),
                "children": {},
            }

            for threshold in (50, 80):
                children = extract_pixel_components(mosaic, threshold_mmph=float(threshold), min_pixels=2)
                assignments, unassigned = assign_children_to_parents(parents, children)
                validation = validate_nested_hierarchy(assignments, unassigned)
                all_nested_ok = all_nested_ok and bool(validation["all_children_assigned"]) and bool(validation["all_assigned_children_fully_contained"])
                child_by_id = {c.local_id: c for c in children}
                rows_out: list[dict[str, Any]] = []

                for a in assignments:
                    child_lineage = child_lineages[threshold][idx].get(a.child_id)
                    parent_lineage = parent_lineages[idx].get(a.parent_id)
                    if child_lineage is None or parent_lineage is None:
                        raise RuntimeError("local-id / lineage mismatch between hierarchy and tracking outputs")
                    is_first = child_first[threshold].get(child_lineage) == idx
                    parent_existed_previous = False
                    if idx > 0:
                        parent_existed_previous = parent_lineage in set(parent_lineages[idx - 1].values())
                    embedded_genesis = bool(is_first and parent_existed_previous)
                    row_out = {
                        **a.to_dict(),
                        "child_lineage_id": child_lineage,
                        "parent_lineage_id": parent_lineage,
                        "child_pixel_count": child_by_id[a.child_id].pixel_count,
                        "parent_pixel_count": parent_by_id[a.parent_id].pixel_count,
                        "child_first_observed_in_tracking_window": is_first,
                        "parent_lineage_existed_previous_frame": parent_existed_previous,
                        "embedded_core_genesis_within_existing_parent": embedded_genesis,
                    }
                    rows_out.append(row_out)
                    if embedded_genesis:
                        genesis_events.append({
                            "valid_time": iso_utc(dt),
                            "threshold_mmph": threshold,
                            "child_lineage_id": child_lineage,
                            "parent_lineage_id": parent_lineage,
                            "child_pixel_count": child_by_id[a.child_id].pixel_count,
                            "parent_pixel_count": parent_by_id[a.parent_id].pixel_count,
                        })

                frame_out["children"][str(threshold)] = {
                    "child_count": len(children),
                    "assignment_count": len(assignments),
                    "validation": validation,
                    "assignments": rows_out,
                }
            frames_out.append(frame_out)

        by_threshold = {
            str(th): sum(1 for event in genesis_events if event["threshold_mmph"] == th)
            for th in (50, 80)
        }
        parent_lineages_with_genesis = sorted({event["parent_lineage_id"] for event in genesis_events})
        return {
            **base,
            "execution_ok": True,
            "scientific_hierarchy_proven": all_nested_ok,
            "frame_valid_times": [iso_utc(dt) for dt in times],
            "fixed_mosaic": {"zoom": ZOOM, "origin_tile_x": origin_x, "origin_tile_y": origin_y, "tile_count": 16},
            "frames": frames_out,
            "embedded_core_genesis_event_count": len(genesis_events),
            "embedded_core_genesis_by_threshold": by_threshold,
            "parent_lineages_with_embedded_genesis": parent_lineages_with_genesis,
            "genesis_events": genesis_events,
            "interpretation": "A child-core birth inside a parent lineage already present one frame earlier is a temporal structural observation, not yet a back-building classification.",
            "gates": {
                "nested_threshold_integrity": all_nested_ok,
                "parent_child_mapping": True,
                "embedded_core_genesis_logging": True,
                "backbuilding": False,
                "stationarity": False,
                "historical_validation": False,
                "risk_engine_allowed": False,
            },
        }
    except Exception as exc:
        return {
            **base,
            "execution_ok": False,
            "scientific_hierarchy_proven": False,
            "error": f"{type(exc).__name__}: {exc}",
            "gates": {"parent_child_mapping": False, "risk_engine_allowed": False},
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking", default="reports/scientific/radar_tracking.json")
    parser.add_argument("--output", default="reports/scientific/radar_hierarchy.json")
    args = parser.parse_args()
    report = run(Path(args.tracking))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "execution_ok": report.get("execution_ok"),
        "scientific_hierarchy_proven": report.get("scientific_hierarchy_proven"),
        "embedded_core_genesis_event_count": report.get("embedded_core_genesis_event_count"),
        "embedded_core_genesis_by_threshold": report.get("embedded_core_genesis_by_threshold"),
        "gates": report.get("gates"),
    }, indent=2))
    print(f"report={output}")
    return 0 if report.get("execution_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
