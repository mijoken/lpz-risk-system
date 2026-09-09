"""ERA5 multi-valid-time GRIB decoder.

Unlike the generic GFS decoder, this module preserves ERA5 valid time as a
first-class key. Historical CDS requests often contain several hourly analyses
in one GRIB payload, so using only (shortName, pressure level) would silently
overwrite earlier hours.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from eccodes import codes_get, codes_get_array, codes_grib_new_from_file, codes_release

from lpz_risk.gfs_science import DecodedField, FieldKey
from lpz_risk.era5_science import validate_era5_required_fields, era5_environment_descriptors


def _safe_int(gid: int, key: str, default: int = 0) -> int:
    try:
        return int(codes_get(gid, key))
    except Exception:
        return default


def _valid_time_utc(gid: int) -> str:
    """Return GRIB validity time as canonical UTC ISO string."""
    try:
        date = int(codes_get(gid, "validityDate"))
        hhmm = int(codes_get(gid, "validityTime"))
    except Exception:
        date = int(codes_get(gid, "dataDate"))
        hhmm = int(codes_get(gid, "dataTime"))
    year = date // 10000
    month = (date // 100) % 100
    day = date % 100
    hour = hhmm // 100
    minute = hhmm % 100
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00Z"


def decode_era5_pressure_fields_by_time(
    path: str | Path,
) -> dict[str, dict[FieldKey, DecodedField]]:
    """Decode ERA5 pressure-level messages keyed by valid time then FieldKey."""
    result: dict[str, dict[FieldKey, DecodedField]] = {}
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
                valid_time = _valid_time_utc(gid)
                key = FieldKey(short_name=short_name, level_hpa=level_hpa)
                bucket = result.setdefault(valid_time, {})
                if key in bucket:
                    raise ValueError(f"duplicate ERA5 message for {valid_time} {key}")
                values = np.asarray(codes_get_array(gid, "values"), dtype=float)
                latitudes = np.asarray(codes_get_array(gid, "latitudes"), dtype=float)
                longitudes = np.asarray(codes_get_array(gid, "longitudes"), dtype=float)
                bucket[key] = DecodedField(
                    key=key,
                    units=units,
                    values=values,
                    latitudes=latitudes,
                    longitudes=longitudes,
                    ni=_safe_int(gid, "Ni"),
                    nj=_safe_int(gid, "Nj"),
                )
            finally:
                codes_release(gid)
    if not result:
        raise ValueError("ERA5 GRIB contained no pressure-level messages")
    return dict(sorted(result.items()))


def validate_era5_multitime_payload(
    fields_by_time: dict[str, dict[FieldKey, DecodedField]],
    expected_times_utc: list[str] | None = None,
) -> dict[str, Any]:
    """Validate required fields independently for every valid time."""
    expected = sorted(expected_times_utc or [])
    actual = sorted(fields_by_time)
    missing_times = sorted(set(expected) - set(actual))
    unexpected_times = sorted(set(actual) - set(expected)) if expected else []
    per_time: dict[str, Any] = {}
    failed_times: list[str] = []
    for valid_time, fields in sorted(fields_by_time.items()):
        validation = validate_era5_required_fields(fields)
        per_time[valid_time] = validation
        if not validation["required_fields_pass"]:
            failed_times.append(valid_time)
    passed = not missing_times and not unexpected_times and not failed_times
    return {
        "expected_valid_time_count": len(expected) if expected else None,
        "decoded_valid_time_count": len(actual),
        "decoded_valid_times_utc": actual,
        "missing_valid_times_utc": missing_times,
        "unexpected_valid_times_utc": unexpected_times,
        "failed_field_validation_times_utc": failed_times,
        "per_time_required_fields": per_time,
        "multitime_payload_pass": passed,
        "risk_engine_allowed": False,
    }


def build_time_descriptors(
    fields_by_time: dict[str, dict[FieldKey, DecodedField]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for valid_time, fields in sorted(fields_by_time.items()):
        validation = validate_era5_required_fields(fields)
        if not validation["required_fields_pass"]:
            raise ValueError(f"ERA5 field validation failed at {valid_time}: {validation}")
        rows.append({
            "era5_source_time_utc": valid_time,
            "validation": validation,
            "environment_descriptors": era5_environment_descriptors(fields),
        })
    return rows
