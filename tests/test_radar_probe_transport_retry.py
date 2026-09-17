from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("module_name", "script_path"),
    [
        ("radar_tracking_probe_retry_test", "scripts/radar_tracking_probe.py"),
        ("radar_morphology_probe_retry_test", "scripts/radar_morphology_probe.py"),
    ],
)
def test_tile_retry_recovers_after_transient_failure(module_name, script_path):
    mod = load_script_module(module_name, script_path)

    class FakeDecoded:
        class_index = np.array([[1, -1], [2, 3]], dtype=np.int8)
        unknown_opaque_pixel_count = 0

    calls = {"count": 0}

    def flaky_http_get(url, max_bytes):
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("synthetic transient timeout")
        return b"fake-png"

    row = {
        "basetime": "20260917034500",
        "validtime": "20260917034500",
    }

    with (
        patch.object(mod, "http_get", side_effect=flaky_http_get),
        patch.object(mod, "decode_jma_precipitation_png", return_value=FakeDecoded()),
        patch.object(mod.time, "sleep") as sleep_mock,
    ):
        result = mod.inspect_tile(row, 8, 226, 101)

    assert result["ok"] is True
    assert result["attempt_count"] == 2
    assert calls["count"] == 2
    sleep_mock.assert_called_once_with(0.5)


@pytest.mark.parametrize(
    ("module_name", "script_path"),
    [
        ("radar_tracking_probe_retry_fail_test", "scripts/radar_tracking_probe.py"),
        ("radar_morphology_probe_retry_fail_test", "scripts/radar_morphology_probe.py"),
    ],
)
def test_tile_retry_preserves_failure_after_all_attempts(module_name, script_path):
    mod = load_script_module(module_name, script_path)

    calls = {"count": 0}

    def always_fail(url, max_bytes):
        calls["count"] += 1
        raise TimeoutError(f"synthetic timeout attempt {calls['count']}")

    row = {
        "basetime": "20260917034500",
        "validtime": "20260917034500",
    }

    with (
        patch.object(mod, "http_get", side_effect=always_fail),
        patch.object(mod.time, "sleep") as sleep_mock,
    ):
        result = mod.inspect_tile(row, 8, 226, 101)

    assert result["ok"] is False
    assert result["attempt_count"] == 3
    assert calls["count"] == 3
    assert len(result["attempt_errors"]) == 3
    assert all("TimeoutError" in error for error in result["attempt_errors"])
    assert "attempt 3" in result["error"]

    assert sleep_mock.call_count == 2
    assert [call.args[0] for call in sleep_mock.call_args_list] == [0.5, 1.5]
