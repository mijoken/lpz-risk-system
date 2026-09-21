"""Tests for F4-9A decoded field archive proof."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from capture_f4_decoded_field_archive import _validate_stack, write_archive


def _stack() -> np.ndarray:
    data = np.full((4, 8, 8), -1, dtype=np.int8)
    data[0, 1:3, 1:3] = 2
    data[1, 2:4, 2:4] = 3
    data[2, 3:5, 3:5] = 4
    data[3, 4:6, 4:6] = 5
    return data


def _times() -> list[str]:
    return [
        "2026-09-21T07:15:00Z",
        "2026-09-21T07:20:00Z",
        "2026-09-21T07:25:00Z",
        "2026-09-21T07:30:00Z",
    ]


def test_validate_stack_requires_exact_four_int8_frames():
    stack = _stack()
    _validate_stack(stack, _times())

    with pytest.raises(ValueError, match="four frames"):
        _validate_stack(stack[:3], _times()[:3])

    with pytest.raises(ValueError, match="dtype must be int8"):
        _validate_stack(stack.astype(np.int16), _times())

    with pytest.raises(ValueError, match="duplicate frame"):
        _validate_stack(stack, [_times()[0]] * 4)


def test_validate_stack_rejects_out_of_range_class_index():
    stack = _stack()
    stack[0, 0, 0] = 127
    with pytest.raises(ValueError, match="outside decoded JMA class range"):
        _validate_stack(stack, _times())


def test_write_archive_roundtrips_exact_class_indices_and_locks(tmp_path):
    out = tmp_path / "archive"
    stack = _stack()

    manifest = write_archive(
        output_dir=out,
        collection_slot_utc="2026-09-21T07:30:00Z",
        prospective_as_of_utc="2026-09-21T07:45:00Z",
        frame_valid_times=_times(),
        class_index=stack,
        zoom=8,
        origin_tile_x=228,
        origin_tile_y=96,
        tile_count=16,
        discovery_parent={
            "z": 6,
            "x": 57,
            "y": 24,
            "precipitation_pixels": 100,
            "max_class_index": 5,
        },
    )

    npz_path = out / "decoded_field.npz"
    manifest_path = out / "manifest.json"
    assert npz_path.is_file()
    assert manifest_path.is_file()

    with np.load(npz_path) as payload:
        assert np.array_equal(payload["class_index"], stack)
        assert payload["class_index"].dtype == np.int8
        assert payload["valid_time_unix_s"].shape == (4,)

    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted == manifest
    assert manifest["product"] == "F4_DECODED_FIELD_RESEARCH_ARCHIVE"
    assert manifest["field"]["transparent_pixels_as_zero"] is False
    assert manifest["field"]["continuous_mmph_recovered"] is False
    assert manifest["decoded_field_archived"] is True
    assert manifest["raw_radar_png_archived"] is False
    assert manifest["optical_flow_executed"] is False
    assert manifest["risk_engine_allowed"] is False
    assert manifest["validated_forecast"] is False

    digest = hashlib.sha256(npz_path.read_bytes()).hexdigest()
    assert manifest["storage"]["sha256"] == digest
    assert manifest["storage"]["compressed_file_bytes"] == npz_path.stat().st_size


def test_write_archive_is_immutable(tmp_path):
    out = tmp_path / "archive"
    kwargs = dict(
        output_dir=out,
        collection_slot_utc="2026-09-21T07:30:00Z",
        prospective_as_of_utc="2026-09-21T07:45:00Z",
        frame_valid_times=_times(),
        class_index=_stack(),
        zoom=8,
        origin_tile_x=228,
        origin_tile_y=96,
        tile_count=16,
        discovery_parent={
            "z": 6,
            "x": 57,
            "y": 24,
            "precipitation_pixels": 100,
            "max_class_index": 5,
        },
    )
    write_archive(**kwargs)
    with pytest.raises(FileExistsError, match="refusing existing output directory"):
        write_archive(**kwargs)
