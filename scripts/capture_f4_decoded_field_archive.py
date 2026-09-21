#!/usr/bin/env python3
"""F4-9A local research archive for decoded JMA HRPN z8 precipitation fields.

This stage archives the exact four-frame class-index mosaics that are already
constructed transiently by the O8.1 replay/tracking path. It does NOT archive
raw PNG bytes, reconstruct continuous mm/h, run optical flow, alter O8.1
bundles, or enable the Risk Engine.

The stored field semantics are deliberately conservative:
- int8 JMA precipitation class indices are preserved exactly;
- -1 remains unclassified/transparent and is NOT converted to zero rainfall;
- the official class interval metadata are recorded in the JSON manifest;
- continuous precipitation intensity is NOT claimed.

The output is intended for local research storage under local_data/ and is not
an O8.1 production artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.radar_science import JMA_PRECIPITATION_CLASSES


DEFAULT_TARGET_AGE_MINUTES = 60


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load script module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REPLAY = _load_script(
    "lpz_f49a_replay",
    ROOT / "scripts" / "o8_1_slot_replay_proof.py",
)


def iso_utc(dt: datetime) -> str:
    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def compact_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _palette_rows() -> list[dict[str, Any]]:
    rows = []
    for index, item in enumerate(JMA_PRECIPITATION_CLASSES):
        rows.append(
            {
                "class_index": index,
                "class_id": item.class_id,
                "lower_mmph": item.lower_mmph,
                "upper_mmph": item.upper_mmph,
                "rgb": list(item.rgb),
            }
        )
    return rows


def _validate_stack(class_index: np.ndarray, frame_valid_times: list[str]) -> None:
    if not isinstance(class_index, np.ndarray):
        raise TypeError("class_index must be numpy array")
    if class_index.dtype != np.int8:
        raise ValueError(f"class_index dtype must be int8, got {class_index.dtype}")
    if class_index.ndim != 3:
        raise ValueError("class_index must have shape (time, row, col)")
    if class_index.shape[0] != 4:
        raise ValueError("exact F4 field archive requires four frames")
    if class_index.shape[1] <= 0 or class_index.shape[2] <= 0:
        raise ValueError("field spatial dimensions must be non-empty")
    if len(frame_valid_times) != class_index.shape[0]:
        raise ValueError("frame time count disagrees with stack")
    if len(set(frame_valid_times)) != len(frame_valid_times):
        raise ValueError("duplicate frame valid times")
    max_allowed = len(JMA_PRECIPITATION_CLASSES) - 1
    if np.any(class_index < -1) or np.any(class_index > max_allowed):
        raise ValueError("class_index outside decoded JMA class range")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_archive(
    *,
    output_dir: Path,
    collection_slot_utc: str,
    prospective_as_of_utc: str,
    frame_valid_times: list[str],
    class_index: np.ndarray,
    zoom: int,
    origin_tile_x: int,
    origin_tile_y: int,
    tile_count: int,
    discovery_parent: dict[str, Any],
) -> dict[str, Any]:
    """Write immutable compressed field archive and manifest."""
    _validate_stack(class_index, frame_valid_times)

    if output_dir.exists():
        raise FileExistsError(f"refusing existing output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)

    npz_path = output_dir / "decoded_field.npz"
    manifest_path = output_dir / "manifest.json"

    valid_time_unix_s = np.array(
        [
            int(
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                .astimezone(timezone.utc)
                .timestamp()
            )
            for value in frame_valid_times
        ],
        dtype=np.int64,
    )

    np.savez_compressed(
        npz_path,
        class_index=class_index,
        valid_time_unix_s=valid_time_unix_s,
    )

    raw_bytes = int(class_index.nbytes + valid_time_unix_s.nbytes)
    compressed_bytes = int(npz_path.stat().st_size)
    manifest = {
        "schema_version": "0.1.0",
        "product": "F4_DECODED_FIELD_RESEARCH_ARCHIVE",
        "research_stage": "F4-9A",
        "collection_slot_utc": collection_slot_utc,
        "prospective_as_of_utc": prospective_as_of_utc,
        "source_product": "JMA_HRPN_ANALYSIS_PUBLIC_PNG",
        "frame_valid_times": frame_valid_times,
        "frame_count": int(class_index.shape[0]),
        "frame_interval_seconds": 300,
        "field": {
            "array_name": "class_index",
            "dtype": str(class_index.dtype),
            "shape": list(map(int, class_index.shape)),
            "unclassified_value": -1,
            "semantics": "JMA_PUBLIC_PRECIPITATION_CLASS_INDEX",
            "transparent_pixels_as_zero": False,
            "continuous_mmph_recovered": False,
            "palette": _palette_rows(),
        },
        "fixed_mosaic": {
            "zoom": int(zoom),
            "origin_tile_x": int(origin_tile_x),
            "origin_tile_y": int(origin_tile_y),
            "tile_count": int(tile_count),
        },
        "discovery_parent": discovery_parent,
        "storage": {
            "format": "NPZ_COMPRESSED",
            "file": npz_path.name,
            "sha256": _sha256(npz_path),
            "logical_array_bytes": raw_bytes,
            "compressed_file_bytes": compressed_bytes,
            "compression_ratio": (
                raw_bytes / compressed_bytes if compressed_bytes > 0 else None
            ),
        },
        "raw_radar_png_archived": False,
        "decoded_field_archived": True,
        "o8_1_bundle_modified": False,
        "optical_flow_executed": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
        "risk_engine_allowed": False,
        "validated_forecast": False,
        "interpretation": (
            "Local research archive of exact decoded JMA HRPN class-index mosaics. "
            "Class intervals are preserved without conversion to continuous rainfall. "
            "The -1 background remains unclassified/transparent, not zero rain. "
            "No optical-flow or LPZ forecast claim is made."
        ),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def capture(
    *,
    target_valid_time: str,
    target_age_minutes: int,
    output_root: Path,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    rows = REPLAY.TRACK.load_json(REPLAY.TRACK.NOWC_TIMES)
    if not isinstance(rows, list):
        raise ValueError("targetTimes_N1.json was not a list")

    row_map = REPLAY.exact_analysis_rows(rows)
    slots = REPLAY.recoverable_slots(row_map, now)
    target = REPLAY.resolve_target(
        slots,
        now,
        target_valid_time,
        target_age_minutes,
    )
    sequence = REPLAY.exact_sequence(row_map, target)

    morphology, parent = REPLAY.morphology_for_target(sequence[-1])
    if morphology.get("execution_ok") is not True:
        raise RuntimeError("exact target morphology failed")
    if parent is None:
        raise RuntimeError("target slot has no precipitation discovery parent")

    parent_x = int(parent["x"])
    parent_y = int(parent["y"])
    mosaics: list[np.ndarray] = []
    frame_valid_times: list[str] = []
    origin_x = origin_y = tile_count = None
    shape = None

    for row in sequence:
        mosaic, meta = REPLAY.TRACK.build_fixed_mosaic(row, parent_x, parent_y)
        if mosaic.dtype != np.int8:
            mosaic = mosaic.astype(np.int8, copy=False)
        current_shape = tuple(map(int, mosaic.shape))
        if shape is None:
            shape = current_shape
            origin_x = int(meta["origin_tile_x"])
            origin_y = int(meta["origin_tile_y"])
            tile_count = int(meta["tile_count"])
        if current_shape != shape:
            raise RuntimeError("fixed mosaic shape changed across exact frames")
        if (
            int(meta["origin_tile_x"]) != origin_x
            or int(meta["origin_tile_y"]) != origin_y
            or int(meta["tile_count"]) != tile_count
        ):
            raise RuntimeError("fixed mosaic geometry changed across exact frames")
        mosaics.append(mosaic)
        frame_valid_times.append(
            iso_utc(REPLAY.TRACK.parse_compact(str(row["validtime"])))
        )

    assert origin_x is not None
    assert origin_y is not None
    assert tile_count is not None
    stack = np.stack(mosaics, axis=0).astype(np.int8, copy=False)

    slot_name = compact_utc(target)
    output_dir = output_root / f"{slot_name}_z{REPLAY.TRACK.TRACKING_ZOOM}"
    prospective_as_of = target + REPLAY.timedelta(
        minutes=REPLAY.SETTLEMENT_LAG_MINUTES
    )
    return write_archive(
        output_dir=output_dir,
        collection_slot_utc=iso_utc(target),
        prospective_as_of_utc=iso_utc(prospective_as_of),
        frame_valid_times=frame_valid_times,
        class_index=stack,
        zoom=REPLAY.TRACK.TRACKING_ZOOM,
        origin_tile_x=origin_x,
        origin_tile_y=origin_y,
        tile_count=tile_count,
        discovery_parent={
            "z": int(parent["z"]),
            "x": parent_x,
            "y": parent_y,
            "precipitation_pixels": int(parent["precipitation_pixels"]),
            "max_class_index": int(parent["max_class_index"]),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-valid-time", default="")
    parser.add_argument(
        "--target-age-minutes",
        type=int,
        default=DEFAULT_TARGET_AGE_MINUTES,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "local_data" / "f4_decoded_field",
    )
    args = parser.parse_args()

    result = capture(
        target_valid_time=args.target_valid_time,
        target_age_minutes=args.target_age_minutes,
        output_root=args.output_root,
    )
    print(
        json.dumps(
            {
                "product": result["product"],
                "collection_slot_utc": result["collection_slot_utc"],
                "frame_valid_times": result["frame_valid_times"],
                "field_shape": result["field"]["shape"],
                "compressed_file_bytes": result["storage"][
                    "compressed_file_bytes"
                ],
                "compression_ratio": result["storage"]["compression_ratio"],
                "risk_engine_allowed": result["risk_engine_allowed"],
                "validated_forecast": result["validated_forecast"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
