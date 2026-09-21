#!/usr/bin/env python3
"""F4-9B frozen field-motion mechanics.

Reads one F4-9A decoded-field archive and applies the pre-frozen specification:
- pySTEPS Lucas-Kanade dense motion from all four class-index frames;
- no class midpoint conversion;
- class_index < 0 masked for motion estimation;
- latest definite >=30 mm/h binary mask advected by semi-Lagrangian transport;
- +15/+30 min leads only;
- Eulerian persistence emitted as the mandatory baseline.

This script does NOT read future observations and does NOT score forecast skill.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "config" / "f4_9b_field_motion_spec.json"


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_spec(spec: dict) -> None:
    if spec.get("product") != "F4_FIELD_MOTION_SPEC_FREEZE":
        raise ValueError("unexpected F4-9B spec product")
    if spec.get("research_stage") != "F4-9B":
        raise ValueError("unexpected F4-9B research stage")
    locks = spec.get("locks") or {}
    required_false = (
        "risk_engine_allowed",
        "lpz_forecast_generated",
        "probability_generated",
        "severity_generated",
        "validated_forecast",
    )
    if any(locks.get(key) is not False for key in required_false):
        raise ValueError("F4-9B scientific lock mismatch")
    if locks.get("specification_frozen") is not True:
        raise ValueError("F4-9B specification is not frozen")

    motion = spec["motion_estimation"]
    if motion["library"] != "pysteps.motion.lucaskanade.dense_lucaskanade":
        raise ValueError("unexpected motion method")
    if motion.get("alternate_motion_methods_allowed") is not False:
        raise ValueError("alternate motion method unexpectedly allowed")

    extrap = spec["extrapolation"]
    if extrap["library"] != "pysteps.extrapolation.semilagrangian.extrapolate":
        raise ValueError("unexpected extrapolation method")
    if extrap["timesteps"] != [3, 6] or extrap["lead_minutes"] != [15, 30]:
        raise ValueError("lead-time contract changed")
    if extrap["interp_order"] != 0:
        raise ValueError("binary-mask interpolation contract changed")

    prohibited = spec.get("prohibited") or {}
    if not all(bool(value) for value in prohibited.values()):
        raise ValueError("F4-9B anti-tuning prohibition missing")


def _validate_archive(manifest: dict, class_index: np.ndarray) -> None:
    if manifest.get("product") != "F4_DECODED_FIELD_RESEARCH_ARCHIVE":
        raise ValueError("input is not an F4-9A decoded field archive")
    if manifest.get("schema_version") != "0.1.0":
        raise ValueError("unexpected F4-9A archive schema")
    if manifest.get("risk_engine_allowed") is not False:
        raise ValueError("input archive Risk Engine lock missing")
    if manifest.get("validated_forecast") is not False:
        raise ValueError("input archive validation lock missing")
    if manifest.get("raw_radar_png_archived") is not False:
        raise ValueError("unexpected raw-radar archive semantics")
    if manifest.get("decoded_field_archived") is not True:
        raise ValueError("decoded field archive flag missing")
    if manifest.get("field", {}).get("continuous_mmph_recovered") is not False:
        raise ValueError("continuous rainfall unexpectedly claimed")
    if manifest.get("field", {}).get("transparent_pixels_as_zero") is not False:
        raise ValueError("transparent-pixel semantics changed")
    if class_index.dtype != np.int8:
        raise ValueError("class_index must be int8")
    if class_index.ndim != 3 or class_index.shape[0] != 4:
        raise ValueError("F4-9B requires exact four-frame stack")
    if list(map(int, class_index.shape)) != manifest["field"]["shape"]:
        raise ValueError("archive manifest shape mismatch")
    if int(manifest["fixed_mosaic"]["zoom"]) != 8:
        raise ValueError("F4-9B requires z8 mosaic")


def _runtime_versions(spec: dict) -> dict:
    expected_pysteps = spec["environment"]["pysteps_version"]
    expected_opencv = spec["environment"]["opencv_python_headless_version"]
    actual_pysteps = importlib.metadata.version("pysteps")
    actual_opencv = importlib.metadata.version("opencv-python-headless")
    if actual_pysteps != expected_pysteps:
        raise RuntimeError(
            f"pysteps version mismatch: expected {expected_pysteps}, got {actual_pysteps}"
        )
    if actual_opencv != expected_opencv:
        raise RuntimeError(
            f"opencv-python-headless version mismatch: expected {expected_opencv}, got {actual_opencv}"
        )
    return {
        "pysteps": actual_pysteps,
        "opencv_python_headless": actual_opencv,
        "numpy": np.__version__,
    }


def _motion_input(class_index: np.ndarray) -> np.ma.MaskedArray:
    values = class_index.astype(np.float32, copy=False)
    mask = class_index < 0
    return np.ma.array(values, mask=mask, copy=False)


def _latest_definite_ge30(class_index: np.ndarray) -> np.ndarray:
    # Frozen from JMA class intervals: P30_50/P50_80/P80_INF are indices 5..7.
    return (class_index[-1] >= 5).astype(np.float32)


def run_model(
    class_index: np.ndarray,
    spec: dict,
    *,
    dense_lucaskanade,
    semilagrangian_extrapolate,
) -> dict:
    _validate_spec(spec)

    params = spec["motion_estimation"]["parameters"]
    motion_field = dense_lucaskanade(
        _motion_input(class_index),
        lk_kwargs=params["lk_kwargs"],
        fd_method=params["fd_method"],
        fd_kwargs=params["fd_kwargs"],
        interp_method=params["interp_method"],
        interp_kwargs=params["interp_kwargs"],
        dense=params["dense"],
        nr_std_outlier=params["nr_std_outlier"],
        k_outlier=params["k_outlier"],
        size_opening=params["size_opening"],
        decl_scale=params["decl_scale"],
        verbose=params["verbose"],
    )
    motion_field = np.asarray(motion_field, dtype=np.float32)
    expected_shape = (2, class_index.shape[1], class_index.shape[2])
    if motion_field.shape != expected_shape:
        raise RuntimeError(
            f"unexpected dense motion shape {motion_field.shape}, expected {expected_shape}"
        )
    if not np.all(np.isfinite(motion_field)):
        raise RuntimeError("motion field contains non-finite values")

    latest_mask = _latest_definite_ge30(class_index)
    extrap = spec["extrapolation"]
    forecast = semilagrangian_extrapolate(
        latest_mask,
        motion_field,
        extrap["timesteps"],
        outval=float(extrap["outval"]),
        allow_nonfinite_values=bool(extrap["allow_nonfinite_values"]),
        vel_timestep=float(extrap["vel_timestep"]),
        n_iter=int(extrap["n_iter"]),
        interp_order=int(extrap["interp_order"]),
        return_displacement=bool(extrap["return_displacement"]),
    )
    forecast = np.asarray(forecast, dtype=np.float32)
    expected_forecast_shape = (
        len(extrap["timesteps"]),
        class_index.shape[1],
        class_index.shape[2],
    )
    if forecast.shape != expected_forecast_shape:
        raise RuntimeError(
            f"unexpected forecast shape {forecast.shape}, expected {expected_forecast_shape}"
        )
    if not np.all(np.isfinite(forecast)):
        raise RuntimeError("forecast contains non-finite values")

    threshold = float(extrap["numerical_binary_decode_threshold"])
    forecast_mask = (forecast >= threshold).astype(np.uint8)
    persistence = np.repeat(
        latest_mask.astype(np.uint8)[None, :, :],
        len(extrap["timesteps"]),
        axis=0,
    )
    return {
        "velocity": motion_field,
        "forecast_ge30": forecast_mask,
        "persistence_ge30": persistence,
        "lead_minutes": np.asarray(extrap["lead_minutes"], dtype=np.int16),
    }


def execute(archive_dir: Path, output_dir: Path, spec_path: Path) -> dict:
    if output_dir.exists():
        raise FileExistsError(f"refusing existing output directory: {output_dir}")
    spec = _read_json(spec_path)
    _validate_spec(spec)

    manifest_path = archive_dir / "manifest.json"
    npz_path = archive_dir / "decoded_field.npz"
    manifest = _read_json(manifest_path)
    expected_sha = manifest.get("storage", {}).get("sha256")
    actual_sha = _sha256(npz_path)
    if expected_sha != actual_sha:
        raise ValueError("input decoded_field.npz SHA256 mismatch")

    with np.load(npz_path) as payload:
        class_index = np.asarray(payload["class_index"])
        valid_time_unix_s = np.asarray(payload["valid_time_unix_s"])
    _validate_archive(manifest, class_index)
    if valid_time_unix_s.shape != (4,):
        raise ValueError("input valid_time_unix_s must have four entries")

    versions = _runtime_versions(spec)
    from pysteps.motion.lucaskanade import dense_lucaskanade
    from pysteps.extrapolation.semilagrangian import extrapolate

    result = run_model(
        class_index,
        spec,
        dense_lucaskanade=dense_lucaskanade,
        semilagrangian_extrapolate=extrapolate,
    )

    output_dir.mkdir(parents=True, exist_ok=False)
    forecast_path = output_dir / "field_motion_forecast.npz"
    np.savez_compressed(
        forecast_path,
        velocity_pixels_per_timestep=result["velocity"],
        forecast_ge30=result["forecast_ge30"],
        persistence_ge30=result["persistence_ge30"],
        lead_minutes=result["lead_minutes"],
    )

    spec_sha = _sha256(spec_path)
    output_manifest = {
        "schema_version": "1.0.0",
        "product": "F4_FIELD_MOTION_FROZEN_MECHANICS",
        "research_stage": "F4-9B",
        "spec_file": str(spec_path.relative_to(ROOT)),
        "spec_sha256": spec_sha,
        "input_archive": str(archive_dir),
        "input_archive_product": manifest["product"],
        "input_collection_slot_utc": manifest["collection_slot_utc"],
        "input_decoded_field_sha256": actual_sha,
        "runtime_versions": versions,
        "motion_method": spec["motion_estimation"]["library"],
        "extrapolation_method": spec["extrapolation"]["library"],
        "lead_minutes": spec["extrapolation"]["lead_minutes"],
        "velocity_shape": list(map(int, result["velocity"].shape)),
        "forecast_shape": list(map(int, result["forecast_ge30"].shape)),
        "forecast_positive_pixels": [
            int(np.count_nonzero(row)) for row in result["forecast_ge30"]
        ],
        "persistence_positive_pixels": [
            int(np.count_nonzero(row)) for row in result["persistence_ge30"]
        ],
        "forecast_file": forecast_path.name,
        "forecast_sha256": _sha256(forecast_path),
        "future_observations_read": False,
        "forecast_skill_scored": False,
        "parameter_tuning_performed": False,
        "alternate_model_evaluated": False,
        "production_pyproject_modified": False,
        "risk_engine_allowed": False,
        "lpz_forecast_generated": False,
        "probability_generated": False,
        "severity_generated": False,
        "validated_forecast": False,
        "specification_frozen": True,
        "next_stage": "F4-9C_PROSPECTIVE_HEAD_TO_HEAD_ONLY",
        "interpretation": (
            "Mechanics proof for the pre-frozen F4-9B field-motion model only. "
            "No future truth was read and no forecast skill was evaluated."
        ),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(output_manifest, ensure_ascii=False, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    return output_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    args = parser.parse_args()

    result = execute(args.archive_dir, args.output_dir, args.spec)
    print(
        json.dumps(
            {
                "product": result["product"],
                "input_collection_slot_utc": result["input_collection_slot_utc"],
                "runtime_versions": result["runtime_versions"],
                "lead_minutes": result["lead_minutes"],
                "velocity_shape": result["velocity_shape"],
                "forecast_shape": result["forecast_shape"],
                "forecast_positive_pixels": result["forecast_positive_pixels"],
                "persistence_positive_pixels": result["persistence_positive_pixels"],
                "future_observations_read": result["future_observations_read"],
                "forecast_skill_scored": result["forecast_skill_scored"],
                "risk_engine_allowed": result["risk_engine_allowed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
