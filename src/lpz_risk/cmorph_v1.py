"""NOAA/NCEI CMORPH CDR Version 1 canonical decoder.

The NCEI CDR 8-km/30-min product is distributed as hourly NetCDF files named
CMORPH_V1.0_ADJ_8km-30min_YYYYMMDDHH.nc. One file contains native half-hour
precipitation-rate fields. This adapter preserves those native intervals and
never treats CMORPH as an exact substitute for radar or GSMaP/IMERG.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re

import netCDF4
import numpy as np

from .canonical_rainfall import CanonicalRainfallField

_FILENAME = re.compile(r"^CMORPH_V1\.0_ADJ_8km-30min_(?P<stamp>\d{10})\.nc$")


def parse_cmorph_filename(name: str) -> datetime:
    m = _FILENAME.match(Path(name).name)
    if not m:
        raise ValueError(f"unsupported CMORPH CDR filename: {name}")
    return datetime.strptime(m.group("stamp"), "%Y%m%d%H").replace(tzinfo=timezone.utc)


def _axis_index(dimensions: tuple[str, ...], candidates: tuple[str, ...]) -> int:
    lowered = [d.lower() for d in dimensions]
    for c in candidates:
        if c in lowered:
            return lowered.index(c)
    for i, d in enumerate(lowered):
        if any(c in d for c in candidates):
            return i
    raise ValueError(f"could not identify axis {candidates} in dimensions {dimensions}")


def _as_utc_datetime(value) -> datetime:
    return datetime(
        int(value.year), int(value.month), int(value.day), int(value.hour), int(value.minute), int(value.second),
        tzinfo=timezone.utc,
    )


def decode_cmorph_cdr_v1_bytes(payload: bytes, *, filename: str) -> list[CanonicalRainfallField]:
    file_hour = parse_cmorph_filename(filename)
    if len(payload) < 1024:
        raise ValueError("CMORPH NetCDF payload unexpectedly small")

    with netCDF4.Dataset("inmemory.nc", memory=payload) as ds:
        if "cmorph" not in ds.variables:
            raise ValueError("CMORPH NetCDF missing 'cmorph' variable")
        for coord in ("lon", "lat", "time"):
            if coord not in ds.variables:
                raise ValueError(f"CMORPH NetCDF missing {coord!r} coordinate")

        lon = np.asarray(ds.variables["lon"][:], dtype=float).reshape(-1)
        lat = np.asarray(ds.variables["lat"][:], dtype=float).reshape(-1)
        time_var = ds.variables["time"]
        if not hasattr(time_var, "units"):
            raise ValueError("CMORPH time variable has no units")
        times = netCDF4.num2date(
            time_var[:],
            units=time_var.units,
            calendar=getattr(time_var, "calendar", "standard"),
            only_use_cftime_datetimes=False,
            only_use_python_datetimes=True,
        )
        times = [_as_utc_datetime(t) for t in np.atleast_1d(times)]

        var = ds.variables["cmorph"]
        dims = tuple(var.dimensions)
        t_axis = _axis_index(dims, ("time",))
        lon_axis = _axis_index(dims, ("lon", "longitude"))
        lat_axis = _axis_index(dims, ("lat", "latitude"))
        if len({t_axis, lon_axis, lat_axis}) != 3 or len(dims) != 3:
            raise ValueError(f"unexpected CMORPH variable dimensions: {dims}")

        raw = var[:]
        if np.ma.isMaskedArray(raw):
            data = np.ma.filled(raw.astype(float), np.nan)
        else:
            data = np.asarray(raw, dtype=float)
        data = np.moveaxis(data, (t_axis, lat_axis, lon_axis), (0, 1, 2))
        if data.shape[0] != len(times) or data.shape[1:] != (lat.size, lon.size):
            raise ValueError(
                f"CMORPH coordinate/data shape mismatch: data={data.shape}, time={len(times)}, lat={lat.size}, lon={lon.size}"
            )

        units = str(getattr(var, "units", "")).lower().replace(" ", "")
        if units and not ("mm/hr" in units or "mmh-1" in units or "mm/hour" in units or "mmhr-1" in units):
            raise ValueError(f"unexpected CMORPH precipitation units: {getattr(var, 'units', None)!r}")

        finite = np.isfinite(data)
        data[(finite) & (data < 0.0)] = np.nan

        fields: list[CanonicalRainfallField] = []
        for i, start in enumerate(times):
            # Native CDR high-resolution product uses 30-minute temporal resolution.
            end = start + timedelta(minutes=30)
            fields.append(CanonicalRainfallField(
                source_id="NOAA_CMORPH_CDR",
                product_version="v1.0",
                valid_start_utc=start,
                valid_end_utc=end,
                accumulation_seconds=1800,
                rain_rate_mm_per_hr=np.asarray(data[i], dtype=float),
                longitude_deg_e=lon.copy(),
                latitude_deg_n=lat.copy(),
                gauge_adjusted=True,
                source_path=filename,
                source_hash_prefix=hashlib.sha256(payload).hexdigest()[:16],
                native_quality={
                    "format": "netCDF",
                    "dataset": "cmorph",
                    "native_dimensions": list(dims),
                    "canonical_array_order": "LAT_LON",
                    "bias_corrected": True,
                    "temporal_resolution_seconds": 1800,
                    "negative_values_mapped_to_nan": True,
                },
            ))

    if len(fields) != 2:
        raise ValueError(f"expected two 30-minute fields per hourly CMORPH file, got {len(fields)}")
    if fields[0].valid_start_utc != file_hour or fields[1].valid_start_utc != file_hour + timedelta(minutes=30):
        raise ValueError("CMORPH native time coordinates do not match filename hour")
    return fields


def decode_cmorph_cdr_v1_file(path: str | Path) -> list[CanonicalRainfallField]:
    p = Path(path)
    return decode_cmorph_cdr_v1_bytes(p.read_bytes(), filename=p.name)
