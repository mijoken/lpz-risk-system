"""Evidence-driven GFS GRIB2 acquisition and low-ambiguity scientific decoding.

Phase 1C deliberately starts with fields that can be reproduced directly from
pressure-level GFS GRIB2 messages. Higher-risk transformations (500 m AGL
interpolation, SREH storm motion, omega -> geometric w, LFC/EL) remain gated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import numpy as np
from eccodes import (
    codes_get,
    codes_get_array,
    codes_grib_new_from_file,
    codes_release,
)


GFS_SECONDARY_FILTER = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25b.pl"
DEFAULT_BBOX = {"leftlon": 120.0, "rightlon": 150.0, "toplat": 50.0, "bottomlat": 20.0}
LOW_LEVELS = (1000, 975, 950, 925, 900)


@dataclass(frozen=True)
class FieldKey:
    short_name: str
    level_hpa: int


@dataclass
class DecodedField:
    key: FieldKey
    units: str
    values: np.ndarray
    latitudes: np.ndarray
    longitudes: np.ndarray
    ni: int
    nj: int

    def finite_values(self) -> np.ndarray:
        arr = np.asarray(self.values, dtype=float)
        mask = np.isfinite(arr) & (np.abs(arr) < 1.0e19)
        return arr[mask]

    def summary(self) -> dict[str, Any]:
        finite = self.finite_values()
        if finite.size == 0:
            return {
                "short_name": self.key.short_name,
                "level_hpa": self.key.level_hpa,
                "units": self.units,
                "points": int(self.values.size),
                "finite_points": 0,
                "min": None,
                "max": None,
                "mean": None,
            }
        return {
            "short_name": self.key.short_name,
            "level_hpa": self.key.level_hpa,
            "units": self.units,
            "points": int(self.values.size),
            "finite_points": int(finite.size),
            "min": float(np.min(finite)),
            "max": float(np.max(finite)),
            "mean": float(np.mean(finite)),
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def cycle_candidates(now: datetime | None = None, count: int = 8) -> list[datetime]:
    ref = (now or utc_now()).astimezone(timezone.utc)
    floored = ref.replace(hour=(ref.hour // 6) * 6, minute=0, second=0, microsecond=0)
    return [floored - timedelta(hours=6 * i) for i in range(count)]


def build_science_subset_url(
    cycle: datetime,
    *,
    forecast_hour: int = 1,
    bbox: dict[str, float] | None = None,
) -> str:
    """Build a NOMADS GFS secondary-variable subset URL for Phase 1C fields."""
    box = dict(DEFAULT_BBOX if bbox is None else bbox)
    hh = cycle.strftime("%H")
    ymd = cycle.strftime("%Y%m%d")
    fff = f"{forecast_hour:03d}"

    params: list[tuple[str, str]] = [
        ("file", f"gfs.t{hh}z.pgrb2b.0p25.f{fff}"),
    ]

    for level in sorted(set(LOW_LEVELS + (850, 700, 600, 500)), reverse=True):
        params.append((f"lev_{level}_mb", "on"))

    for variable in ("RH", "SPFH", "UGRD", "VGRD"):
        params.append((f"var_{variable}", "on"))

    params.extend(
        [
            ("subregion", ""),
            ("leftlon", str(box["leftlon"])),
            ("rightlon", str(box["rightlon"])),
            ("toplat", str(box["toplat"])),
            ("bottomlat", str(box["bottomlat"])),
            ("dir", f"/gfs.{ymd}/{hh}/atmos"),
        ]
    )
    return f"{GFS_SECONDARY_FILTER}?{urlencode(params)}"


def _safe_int(gid: int, key: str, default: int = 0) -> int:
    try:
        return int(codes_get(gid, key))
    except Exception:
        return default


def decode_pressure_fields(path: str | Path) -> dict[FieldKey, DecodedField]:
    """Decode isobaric GRIB2 messages into keyed NumPy arrays."""
    fields: dict[FieldKey, DecodedField] = {}
    with Path(path).open("rb") as handle:
        while True:
            gid = codes_grib_new_from_file(handle)
            if gid is None:
                break
            try:
                type_of_level = str(codes_get(gid, "typeOfLevel"))
                if type_of_level not in {"isobaricInhPa", "isobaricInPa"}:
                    continue

                raw_level = float(codes_get(gid, "level"))
                level_hpa = int(round(raw_level / 100.0)) if type_of_level == "isobaricInPa" else int(round(raw_level))
                short_name = str(codes_get(gid, "shortName"))
                units = str(codes_get(gid, "units"))
                values = np.asarray(codes_get_array(gid, "values"), dtype=float)
                latitudes = np.asarray(codes_get_array(gid, "latitudes"), dtype=float)
                longitudes = np.asarray(codes_get_array(gid, "longitudes"), dtype=float)
                ni = _safe_int(gid, "Ni")
                nj = _safe_int(gid, "Nj")
                key = FieldKey(short_name=short_name, level_hpa=level_hpa)
                fields[key] = DecodedField(
                    key=key,
                    units=units,
                    values=values,
                    latitudes=latitudes,
                    longitudes=longitudes,
                    ni=ni,
                    nj=nj,
                )
            finally:
                codes_release(gid)
    return fields


def expected_low_ambiguity_keys() -> set[FieldKey]:
    keys = {
        FieldKey("r", 500),
        FieldKey("r", 700),
        FieldKey("u", 600),
        FieldKey("v", 600),
        FieldKey("u", 850),
        FieldKey("v", 850),
    }
    for level in LOW_LEVELS:
        keys.add(FieldKey("q", level))
        keys.add(FieldKey("u", level))
        keys.add(FieldKey("v", level))
    return keys


def missing_expected_keys(fields: dict[FieldKey, DecodedField]) -> set[FieldKey]:
    return expected_low_ambiguity_keys() - set(fields)


def specific_humidity_to_mixing_ratio(q: np.ndarray | float) -> np.ndarray:
    """Convert specific humidity kg/kg to water-vapor mixing ratio kg/kg."""
    arr = np.asarray(q, dtype=float)
    if np.any((arr < 0.0) | (arr >= 1.0)):
        raise ValueError("specific humidity must satisfy 0 <= q < 1")
    return arr / (1.0 - arr)


def meteorological_wind_direction_deg(u: np.ndarray | float, v: np.ndarray | float) -> np.ndarray:
    """Return meteorological FROM direction in degrees clockwise from north."""
    u_arr = np.asarray(u, dtype=float)
    v_arr = np.asarray(v, dtype=float)
    return (np.degrees(np.arctan2(-u_arr, -v_arr)) + 360.0) % 360.0


def wind_speed(u: np.ndarray | float, v: np.ndarray | float) -> np.ndarray:
    return np.hypot(np.asarray(u, dtype=float), np.asarray(v, dtype=float))


def _aligned_values(
    fields: dict[FieldKey, DecodedField],
    keys: list[FieldKey],
) -> list[np.ndarray]:
    selected = [fields[key] for key in keys]
    sizes = {field.values.size for field in selected}
    if len(sizes) != 1:
        raise ValueError(f"field sizes differ for alignment: {sizes}")
    reference_lat = selected[0].latitudes
    reference_lon = selected[0].longitudes
    for field in selected[1:]:
        if not np.array_equal(reference_lat, field.latitudes) or not np.array_equal(reference_lon, field.longitudes):
            raise ValueError("GRIB fields do not share identical grid coordinates")
    return [np.asarray(field.values, dtype=float) for field in selected]


def kato_midlevel_rh_diagnostic(fields: dict[FieldKey, DecodedField]) -> dict[str, Any]:
    """Reproduce the low-ambiguity RH500/RH700 >60% part of Kato (2020)."""
    rh500, rh700 = _aligned_values(fields, [FieldKey("r", 500), FieldKey("r", 700)])
    valid = (
        np.isfinite(rh500)
        & np.isfinite(rh700)
        & (np.abs(rh500) < 1.0e19)
        & (np.abs(rh700) < 1.0e19)
    )
    satisfied = valid & (rh500 > 60.0) & (rh700 > 60.0)
    valid_count = int(np.count_nonzero(valid))
    satisfied_count = int(np.count_nonzero(satisfied))
    return {
        "evidence_id": "KATO2020_MID_RH",
        "exact_reproduction": True,
        "thresholds": {"rh500_pct": 60.0, "rh700_pct": 60.0, "operator": ">"},
        "valid_grid_points": valid_count,
        "satisfied_grid_points": satisfied_count,
        "satisfied_fraction": (satisfied_count / valid_count) if valid_count else None,
    }


def wind_field_diagnostic(fields: dict[FieldKey, DecodedField], level_hpa: int) -> dict[str, Any]:
    u, v = _aligned_values(fields, [FieldKey("u", level_hpa), FieldKey("v", level_hpa)])
    valid = (
        np.isfinite(u)
        & np.isfinite(v)
        & (np.abs(u) < 1.0e19)
        & (np.abs(v) < 1.0e19)
    )
    speed = wind_speed(u[valid], v[valid])
    direction = meteorological_wind_direction_deg(u[valid], v[valid])
    if speed.size == 0:
        return {"level_hpa": level_hpa, "valid_grid_points": 0}

    # Circular mean of meteorological directions.
    radians = np.radians(direction)
    mean_angle = (math.degrees(math.atan2(np.mean(np.sin(radians)), np.mean(np.cos(radians)))) + 360.0) % 360.0
    return {
        "level_hpa": level_hpa,
        "valid_grid_points": int(speed.size),
        "wind_speed_mps_mean": float(np.mean(speed)),
        "wind_speed_mps_max": float(np.max(speed)),
        "meteorological_from_direction_deg_circular_mean": float(mean_angle),
    }


def low_level_moisture_stack_diagnostic(fields: dict[FieldKey, DecodedField]) -> dict[str, Any]:
    """Validate the q/u/v stack needed for Tahara (2026) IWVF.

    This intentionally does NOT integrate IWVF yet. The paper's pressure-limit
    sign convention and GFS specific-humidity -> mixing-ratio conversion are
    retained explicitly for the next gated step.
    """
    levels: list[dict[str, Any]] = []
    for level in LOW_LEVELS:
        q, u, v = _aligned_values(
            fields,
            [FieldKey("q", level), FieldKey("u", level), FieldKey("v", level)],
        )
        valid = (
            np.isfinite(q)
            & np.isfinite(u)
            & np.isfinite(v)
            & (q >= 0.0)
            & (q < 1.0)
            & (np.abs(u) < 1.0e19)
            & (np.abs(v) < 1.0e19)
        )
        if np.count_nonzero(valid) == 0:
            levels.append({"level_hpa": level, "valid_grid_points": 0})
            continue
        mixing_ratio = specific_humidity_to_mixing_ratio(q[valid])
        levels.append(
            {
                "level_hpa": level,
                "valid_grid_points": int(np.count_nonzero(valid)),
                "specific_humidity_kgkg_mean": float(np.mean(q[valid])),
                "mixing_ratio_kgkg_mean": float(np.mean(mixing_ratio)),
                "wind_speed_mps_mean": float(np.mean(wind_speed(u[valid], v[valid]))),
            }
        )
    return {
        "evidence_ids": ["TAHARA2026_IWVF_1000_900", "TAHARA2026_IWVF_DIV"],
        "raw_stack_exact": all(row.get("valid_grid_points", 0) > 0 for row in levels),
        "iwvf_formula_executed": False,
        "reason_formula_still_gated": "pressure-integration sign convention and exact reproduction check remain open",
        "levels": levels,
    }
