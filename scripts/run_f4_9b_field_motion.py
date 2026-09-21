#!/usr/bin/env python3
"""F4-9B frozen field-motion mechanics.

Reads one F4-9A decoded-field archive and applies the pre-frozen local
Lucas-Kanade + semi-Lagrangian specification. This stage never reads future
observations and never scores forecast skill.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
import sys
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


DEFAULT_SPEC = ROOT / "config" / "f4_9b_field_motion_spec.json"
FROZEN_NUMPY_VERSION = "2.4.6"
FROZEN_OPENCV_HEADLESS_VERSION = "4.14.0.94"
FROZEN_SCIPY_VERSION = "1.17.1"

FROZEN_MOTION_PARAMETERS = {
    "feature_detection": {
        "method": "shitomasi",
        "max_corners": 1000,
        "quality_level": 0.01,
        "min_distance": 10,
        "block_size": 5,
        "buffer_mask": 5,
        "use_harris": False,
        "k": 0.04,
    },
    "tracking": {
        "winsize": [50, 50],
        "nr_levels": 3,
        "criteria": [3, 10, 0],
        "flags": 0,
        "min_eig_thr": 0.0001,
    },
    "nr_std_outlier": 3,
    "k_outlier": 30,
    "size_opening": 3,
    "decl_scale": 20,
    "interpolation": {
        "method": "idw",
        "power": 0.5,
        "k": 20,
        "dist_offset": 0.5,
        "chunk_points": 100000,
    },
}
FROZEN_EXTRAPOLATION = {
    "library": "lpz_local_semilagrangian_nearest",
    "reference": "pySTEPS 1.21.5 semilagrangian mechanics",
    "field_advected": "latest_definite_ge_30mmph_binary_mask",
    "timesteps": [3, 6],
    "lead_minutes": [15, 30],
    "vel_timestep": 1,
    "outval": 0.0,
    "allow_nonfinite_values": False,
    "n_iter": 1,
    "velocity_interp_order": 1,
    "field_interp_order": 0,
    "return_displacement": False,
    "numerical_binary_decode_threshold": 0.5,
}


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

    environment = spec["environment"]
    if environment.get("implementation") != "LPZ_LOCAL_PYSTEPS_ALIGNED":
        raise ValueError("F4-9B implementation contract changed")
    if environment.get("reference_pysteps_version") != "1.21.5":
        raise ValueError("reference pySTEPS version contract changed")
    if environment.get("numpy_version") != FROZEN_NUMPY_VERSION:
        raise ValueError("numpy version contract changed")
    if environment.get("opencv_python_headless_version") != FROZEN_OPENCV_HEADLESS_VERSION:
        raise ValueError("opencv-python-headless version contract changed")
    if environment.get("scipy_version") != FROZEN_SCIPY_VERSION:
        raise ValueError("scipy version contract changed")
    if environment.get("production_pyproject_modified") is not False:
        raise ValueError("production dependency isolation contract changed")

    motion = spec["motion_estimation"]
    if motion.get("library") != "lpz_local_lucas_kanade_dense":
        raise ValueError("unexpected motion method")
    if motion.get("alternate_motion_methods_allowed") is not False:
        raise ValueError("alternate motion method unexpectedly allowed")
    if motion.get("parameters") != FROZEN_MOTION_PARAMETERS:
        raise ValueError("Lucas-Kanade parameter contract changed")

    if spec.get("extrapolation") != FROZEN_EXTRAPOLATION:
        raise ValueError("extrapolation contract changed")

    prohibited = spec.get("prohibited") or {}
    if not prohibited or not all(bool(value) for value in prohibited.values()):
        raise ValueError("F4-9B anti-tuning prohibition missing")

    locks = spec.get("locks") or {}
    for key in (
        "risk_engine_allowed",
        "lpz_forecast_generated",
        "probability_generated",
        "severity_generated",
        "validated_forecast",
    ):
        if locks.get(key) is not False:
            raise ValueError(f"F4-9B scientific lock mismatch: {key}")
    if locks.get("specification_frozen") is not True:
        raise ValueError("F4-9B specification is not frozen")


def _validate_archive(manifest: dict, class_index: np.ndarray) -> None:
    if manifest.get("product") != "F4_DECODED_FIELD_RESEARCH_ARCHIVE":
        raise ValueError("input is not an F4-9A decoded field archive")
    if manifest.get("schema_version") != "0.1.0":
        raise ValueError("unexpected F4-9A archive schema")
    if manifest.get("risk_engine_allowed") is not False:
        raise ValueError("input archive Risk Engine lock missing")
    if manifest.get("validated_forecast") is not False:
        raise ValueError("input archive validation lock missing")
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


def _runtime_versions() -> dict:
    numpy_version = importlib.metadata.version("numpy")
    opencv = importlib.metadata.version("opencv-python-headless")
    scipy = importlib.metadata.version("scipy")
    if numpy_version != FROZEN_NUMPY_VERSION:
        raise RuntimeError(
            f"numpy version mismatch: expected {FROZEN_NUMPY_VERSION}, got {numpy_version}"
        )
    if opencv != FROZEN_OPENCV_HEADLESS_VERSION:
        raise RuntimeError(
            f"opencv-python-headless version mismatch: expected "
            f"{FROZEN_OPENCV_HEADLESS_VERSION}, got {opencv}"
        )
    if scipy != FROZEN_SCIPY_VERSION:
        raise RuntimeError(
            f"scipy version mismatch: expected {FROZEN_SCIPY_VERSION}, got {scipy}"
        )
    return {
        "numpy": numpy_version,
        "opencv_python_headless": opencv,
        "scipy": scipy,
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

    versions = _runtime_versions()
    from lpz_risk.f4_field_motion import run_frozen_field_motion
    result = run_frozen_field_motion(class_index, spec)

    output_dir.mkdir(parents=True, exist_ok=False)
    forecast_path = output_dir / "field_motion_forecast.npz"
    np.savez_compressed(
        forecast_path,
        velocity_pixels_per_timestep=result["velocity"],
        forecast_ge30=result["forecast_ge30"],
        persistence_ge30=result["persistence_ge30"],
        lead_minutes=result["lead_minutes"],
    )

    output_manifest = {
        "schema_version": "1.0.0",
        "product": "F4_FIELD_MOTION_FROZEN_MECHANICS",
        "research_stage": "F4-9B",
        "spec_file": str(spec_path.relative_to(ROOT)),
        "spec_sha256": _sha256(spec_path),
        "input_archive": str(archive_dir),
        "input_archive_product": manifest["product"],
        "input_collection_slot_utc": manifest["collection_slot_utc"],
        "input_decoded_field_sha256": actual_sha,
        "runtime_versions": versions,
        "motion_method": spec["motion_estimation"]["library"],
        "motion_reference": spec["motion_estimation"]["reference"],
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
    print(json.dumps({
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
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
