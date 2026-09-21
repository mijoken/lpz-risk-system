"""F4-9B frozen field-motion mechanics contract tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_f4_9b_field_motion import (
    _latest_definite_ge30,
    _motion_input,
    _validate_spec,
    run_model,
)


SPEC_PATH = ROOT / "config" / "f4_9b_field_motion_spec.json"


def _spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def _stack() -> np.ndarray:
    data = np.full((4, 8, 8), -1, dtype=np.int8)
    data[0, 1:3, 1:3] = 2
    data[1, 2:4, 2:4] = 3
    data[2, 3:5, 3:5] = 5
    data[3, 4:6, 4:6] = 6
    return data


def test_frozen_spec_has_required_terminal_locks():
    spec = _spec()
    _validate_spec(spec)

    assert spec["motion_estimation"]["alternate_motion_methods_allowed"] is False
    assert spec["extrapolation"]["timesteps"] == [3, 6]
    assert spec["extrapolation"]["lead_minutes"] == [15, 30]
    assert spec["extrapolation"]["interp_order"] == 0
    assert spec["baseline"]["name"] == "EULERIAN_PERSISTENCE"
    assert spec["prohibited"]["parameter_tuning_during_f4_9c"] is True
    assert spec["prohibited"]["create_f4_10_or_later"] is True
    assert spec["go_no_go"]["otherwise"] == "NO_GO_AND_CLOSE_F4"


def test_motion_input_preserves_class_coordinates_and_masks_background():
    stack = _stack()
    motion = _motion_input(stack)

    assert motion.shape == stack.shape
    assert motion.dtype == np.float32
    assert np.array_equal(motion.mask, stack < 0)
    assert float(motion[3, 4, 4]) == 6.0


def test_latest_event_mask_is_definite_ge30_only():
    stack = _stack()
    stack[-1, 0, 0] = 4
    stack[-1, 0, 1] = 5
    stack[-1, 0, 2] = 7

    mask = _latest_definite_ge30(stack)
    assert mask.dtype == np.float32
    assert mask[0, 0] == 0.0
    assert mask[0, 1] == 1.0
    assert mask[0, 2] == 1.0
    assert mask[7, 7] == 0.0


def test_run_model_uses_frozen_parameters_and_outputs_two_leads():
    stack = _stack()
    calls = {}

    def fake_lk(input_images, **kwargs):
        calls["motion_shape"] = input_images.shape
        calls["motion_mask_count"] = int(np.count_nonzero(input_images.mask))
        calls["lk_kwargs"] = kwargs
        return np.zeros((2, 8, 8), dtype=np.float32)

    def fake_extrapolate(precip, velocity, timesteps, **kwargs):
        calls["precip"] = precip.copy()
        calls["velocity"] = velocity.copy()
        calls["timesteps"] = list(timesteps)
        calls["extrap_kwargs"] = kwargs
        return np.stack([precip, precip], axis=0).astype(np.float32)

    result = run_model(
        stack,
        _spec(),
        dense_lucaskanade=fake_lk,
        semilagrangian_extrapolate=fake_extrapolate,
    )

    assert calls["motion_shape"] == (4, 8, 8)
    assert calls["lk_kwargs"] == {
        "lk_kwargs": None,
        "fd_method": "shitomasi",
        "fd_kwargs": None,
        "interp_method": "idwinterp2d",
        "interp_kwargs": None,
        "dense": True,
        "nr_std_outlier": 3,
        "k_outlier": 30,
        "size_opening": 3,
        "decl_scale": 20,
        "verbose": False,
    }
    assert calls["timesteps"] == [3, 6]
    assert calls["extrap_kwargs"] == {
        "outval": 0.0,
        "allow_nonfinite_values": False,
        "vel_timestep": 1.0,
        "n_iter": 1,
        "interp_order": 0,
        "return_displacement": False,
    }
    assert result["velocity"].shape == (2, 8, 8)
    assert result["forecast_ge30"].shape == (2, 8, 8)
    assert result["persistence_ge30"].shape == (2, 8, 8)
    assert result["lead_minutes"].tolist() == [15, 30]
    assert np.array_equal(result["forecast_ge30"], result["persistence_ge30"])


def test_spec_rejects_posthoc_method_change():
    spec = _spec()
    spec["motion_estimation"]["parameters"]["fd_method"] = "blob"
    with pytest.raises(ValueError, match="Lucas-Kanade parameter contract changed"):
        _validate_spec(spec)


def test_bad_lead_contract_is_rejected():
    spec = _spec()
    spec["extrapolation"]["timesteps"] = [1, 2]
    with pytest.raises(ValueError, match="lead-time contract changed"):
        _validate_spec(spec)
