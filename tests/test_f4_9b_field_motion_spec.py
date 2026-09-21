"""F4-9B frozen field-motion specification and mechanics tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from run_f4_9b_field_motion import _validate_spec

SPEC_PATH = ROOT / "config" / "f4_9b_field_motion_spec.json"


def _spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def _stack() -> np.ndarray:
    data = np.full((4, 16, 16), -1, dtype=np.int8)
    data[0, 3:8, 2:7] = 5
    data[1, 3:8, 4:9] = 5
    data[2, 3:8, 6:11] = 6
    data[3, 3:8, 8:13] = 6
    return data


def test_frozen_spec_has_terminal_locks_and_no_model_branching():
    spec = _spec()
    _validate_spec(spec)

    assert spec["environment"]["implementation"] == "LPZ_LOCAL_PYSTEPS_ALIGNED"
    assert spec["environment"]["reference_pysteps_version"] == "1.21.5"
    assert spec["environment"]["production_pyproject_modified"] is False
    assert spec["motion_estimation"]["alternate_motion_methods_allowed"] is False
    assert spec["extrapolation"]["timesteps"] == [3, 6]
    assert spec["extrapolation"]["lead_minutes"] == [15, 30]
    assert spec["baseline"]["name"] == "EULERIAN_PERSISTENCE"
    assert spec["prohibited"]["parameter_tuning_during_f4_9c"] is True
    assert spec["prohibited"]["alternate_optical_flow_model"] is True
    assert spec["prohibited"]["create_f4_10_or_later"] is True
    assert spec["go_no_go"]["otherwise"] == "NO_GO_AND_CLOSE_F4"


def test_motion_signal_encoding_has_no_physical_rainfall_claim():
    spec = _spec()
    motion_input = spec["input_contract"]["motion_input"]
    assert motion_input["physical_rainfall_interpretation"] is False
    assert motion_input["continuous_mmph_reconstruction"] is False
    assert motion_input["mask_rule"] == "none"
    assert "class_index 0..7 -> 1..8" in motion_input["encoding"]


def test_spec_rejects_posthoc_lk_parameter_change():
    spec = _spec()
    spec["motion_estimation"]["parameters"]["feature_detection"]["quality_level"] = 0.02
    with pytest.raises(ValueError, match="Lucas-Kanade parameter contract changed"):
        _validate_spec(spec)


def test_spec_rejects_posthoc_extrapolation_change():
    spec = _spec()
    spec["extrapolation"]["timesteps"] = [2, 6]
    with pytest.raises(ValueError, match="extrapolation contract changed"):
        _validate_spec(spec)


def test_spec_rejects_runtime_version_change():
    spec = _spec()
    spec["environment"]["scipy_version"] = "999"
    with pytest.raises(ValueError, match="scipy version contract changed"):
        _validate_spec(spec)


def test_optional_mechanics_encoding_and_semilagrangian():
    pytest.importorskip("cv2")
    pytest.importorskip("scipy")
    from lpz_risk.f4_field_motion import (
        latest_definite_ge30,
        motion_signal_stack,
        semilagrangian_nearest,
    )

    stack = _stack()
    signal = motion_signal_stack(stack)
    assert signal.dtype == np.float32
    assert np.count_nonzero(np.ma.getmaskarray(signal)) == 0
    assert float(signal[0, 0, 0]) == 0.0
    assert float(signal[0, 3, 2]) == 6.0

    event = latest_definite_ge30(stack)
    assert event.dtype == np.float32
    assert event[3, 9] == 1.0
    assert event[0, 0] == 0.0

    field = np.zeros((32, 32), dtype=np.float32)
    field[15, 10] = 1.0
    velocity = np.zeros((2, 32, 32), dtype=np.float32)
    velocity[0, :, :] = 1.0
    forecast = semilagrangian_nearest(
        field,
        velocity,
        [3.0, 6.0],
        vel_timestep=1.0,
        outval=0.0,
        n_iter=1,
        velocity_interp_order=1,
        field_interp_order=0,
    )
    assert forecast.shape == (2, 32, 32)
    assert forecast[0, 15, 13] == pytest.approx(1.0)
    assert forecast[1, 15, 16] == pytest.approx(1.0)


def test_optional_lucas_kanade_detects_positive_x_translation():
    pytest.importorskip("cv2")
    pytest.importorskip("scipy")
    from lpz_risk.f4_field_motion import (
        estimate_dense_lucas_kanade,
        motion_signal_stack,
    )

    data = np.full((4, 96, 96), -1, dtype=np.int8)
    origins = [(20, 15), (20, 17), (20, 19), (20, 21)]
    for frame, (row, col) in enumerate(origins):
        for dy, dx, cls in (
            (0, 0, 5),
            (0, 22, 6),
            (22, 0, 7),
            (22, 22, 5),
        ):
            data[frame, row + dy : row + dy + 9, col + dx : col + dx + 9] = cls

    velocity = estimate_dense_lucas_kanade(
        motion_signal_stack(data),
        _spec()["motion_estimation"]["parameters"],
    )
    assert velocity.shape == (2, 96, 96)
    assert np.all(np.isfinite(velocity))
    assert float(np.median(velocity[0, 15:70, 10:70])) > 0.5
