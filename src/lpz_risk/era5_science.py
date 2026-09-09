"""ERA5 pressure-level scientific decode and provenance-safe diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from lpz_risk.gfs_science import FieldKey, DecodedField, decode_pressure_fields, wind_speed, meteorological_wind_direction_deg

ERA5_REQUIRED_KEYS = {
    FieldKey("r", 500),
    FieldKey("r", 700),
    FieldKey("u", 600),
    FieldKey("v", 600),
    FieldKey("u", 850),
    FieldKey("v", 850),
    FieldKey("q", 1000),
    FieldKey("q", 925),
    FieldKey("q", 850),
}


def decode_era5_pressure_fields(path: str | Path) -> dict[FieldKey, DecodedField]:
    return decode_pressure_fields(path)


def validate_era5_required_fields(fields: dict[FieldKey, DecodedField]) -> dict[str, Any]:
    missing = sorted(
        (f"{k.short_name}@{k.level_hpa}" for k in ERA5_REQUIRED_KEYS - set(fields)),
    )
    field_summaries: list[dict[str, Any]] = []
    invalid: list[str] = []
    for key in sorted(ERA5_REQUIRED_KEYS, key=lambda k: (k.level_hpa, k.short_name)):
        if key not in fields:
            continue
        field = fields[key]
        finite = field.finite_values()
        if finite.size != field.values.size:
            invalid.append(f"{key.short_name}@{key.level_hpa}:non_finite")
        if key.short_name == "r" and finite.size and (np.min(finite) < -1.0 or np.max(finite) > 101.0):
            invalid.append(f"{key.short_name}@{key.level_hpa}:rh_range")
        if key.short_name == "q" and finite.size and (np.min(finite) < 0.0 or np.max(finite) >= 1.0):
            invalid.append(f"{key.short_name}@{key.level_hpa}:q_range")
        field_summaries.append(field.summary())

    return {
        "source": "ERA5",
        "exactness": "PROXY_REANALYSIS",
        "required_field_count": len(ERA5_REQUIRED_KEYS),
        "present_required_field_count": len(ERA5_REQUIRED_KEYS) - len(missing),
        "missing_required_fields": missing,
        "invalid_required_fields": invalid,
        "required_fields_pass": not missing and not invalid,
        "field_summaries": field_summaries,
        "risk_engine_allowed": False,
    }


def era5_environment_descriptors(fields: dict[FieldKey, DecodedField]) -> dict[str, Any]:
    validation = validate_era5_required_fields(fields)
    if not validation["required_fields_pass"]:
        raise ValueError(f"ERA5 required field gate failed: {validation}")

    rh500 = np.asarray(fields[FieldKey("r", 500)].values, dtype=float)
    rh700 = np.asarray(fields[FieldKey("r", 700)].values, dtype=float)
    u600 = np.asarray(fields[FieldKey("u", 600)].values, dtype=float)
    v600 = np.asarray(fields[FieldKey("v", 600)].values, dtype=float)
    u850 = np.asarray(fields[FieldKey("u", 850)].values, dtype=float)
    v850 = np.asarray(fields[FieldKey("v", 850)].values, dtype=float)

    q_levels = {
        level: np.asarray(fields[FieldKey("q", level)].values, dtype=float)
        for level in (1000, 925, 850)
    }
    sizes = {x.size for x in [rh500, rh700, u600, v600, u850, v850, *q_levels.values()]}
    if len(sizes) != 1:
        raise ValueError(f"ERA5 required fields have inconsistent sizes: {sizes}")

    return {
        "source": "ERA5",
        "exactness": "PROXY_REANALYSIS",
        "grid_points": int(rh500.size),
        "rh500_mean_pct": float(np.mean(rh500)),
        "rh700_mean_pct": float(np.mean(rh700)),
        "rh500_rh700_gt60_fraction": float(np.mean((rh500 > 60.0) & (rh700 > 60.0))),
        "wind600_speed_mean_mps": float(np.mean(wind_speed(u600, v600))),
        "wind600_from_direction_median_deg": float(np.median(meteorological_wind_direction_deg(u600, v600))),
        "wind850_speed_mean_mps": float(np.mean(wind_speed(u850, v850))),
        "wind850_from_direction_median_deg": float(np.median(meteorological_wind_direction_deg(u850, v850))),
        "specific_humidity_mean_kgkg": {str(level): float(np.mean(values)) for level, values in q_levels.items()},
        "spatial_semantics": "REQUEST_BBOX_CONTEXT_NOT_SUBDIVISION_POLYGON_MEAN",
        "risk_score": None,
    }
