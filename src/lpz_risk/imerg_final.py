"""Version-aware NASA GPM IMERG Final half-hour adapter.

O9 keeps the historical V07 adapter untouched.  This module is a separate re-entry
adapter whose product-version check is explicit, so a V07/V08 mixture cannot be
silently decoded as one product family.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
from pathlib import Path

import h5py
import numpy as np

from .canonical_rainfall import CanonicalRainfallField

_FILENAME = re.compile(
    r".*\.(?P<date>\d{8})-S(?P<sh>\d{2})(?P<sm>\d{2})(?P<ss>\d{2})-"
    r"E(?P<eh>\d{2})(?P<em>\d{2})(?P<es>\d{2}).*\.V(?P<version>\d{2})[A-Z]?\.HDF5$",
    re.IGNORECASE,
)


def parse_imerg_final_filename(name: str) -> tuple[datetime, datetime, str]:
    m = _FILENAME.match(Path(name).name)
    if not m:
        raise ValueError(f"unsupported IMERG Final filename: {name}")
    d = datetime.strptime(m.group("date"), "%Y%m%d").replace(tzinfo=timezone.utc)
    start = d.replace(
        hour=int(m.group("sh")), minute=int(m.group("sm")), second=int(m.group("ss"))
    )
    end_inclusive = d.replace(
        hour=int(m.group("eh")), minute=int(m.group("em")), second=int(m.group("es"))
    )
    if end_inclusive < start:
        end_inclusive += timedelta(days=1)
    return start, end_inclusive + timedelta(seconds=1), m.group("version")


def decode_imerg_final_file(
    path: str | Path,
    *,
    expected_version: str | None = None,
) -> CanonicalRainfallField:
    """Decode one Final half-hour file and reject a product-version mismatch.

    O9 will call this with ``expected_version='08'``.  The generic option exists so
    the same decoder can be regression-tested against known Final-family fixtures;
    it is not permission to mix versions within one scientific rebuild.
    """
    p = Path(path)
    start, end, version = parse_imerg_final_filename(p.name)
    if expected_version is not None and version != str(expected_version).zfill(2):
        raise ValueError(
            f"IMERG Final version mismatch: expected V{str(expected_version).zfill(2)}, "
            f"filename is V{version}: {p.name}"
        )

    with h5py.File(p, "r") as h:
        required = ("/Grid/precipitation", "/Grid/lon", "/Grid/lat")
        missing = [x for x in required if x not in h]
        if missing:
            raise ValueError(
                "IMERG Final payload schema is not compatible with the frozen V07/V08 "
                f"rebuild reader; missing datasets: {missing}"
            )

        rain_ds = h["/Grid/precipitation"]
        lon = np.asarray(h["/Grid/lon"][...], dtype=np.float64).reshape(-1)
        lat = np.asarray(h["/Grid/lat"][...], dtype=np.float64).reshape(-1)
        raw = np.asarray(rain_ds[...], dtype=np.float64)

        if raw.ndim == 3 and raw.shape[0] == 1:
            raw = raw[0]
        if raw.shape == (lon.size, lat.size):
            rain = raw.T
            native_order = "TIME_LON_LAT"
        elif raw.shape == (lat.size, lon.size):
            rain = raw
            native_order = "TIME_LAT_LON_OR_LAT_LON"
        else:
            raise ValueError(
                f"IMERG precipitation grid shape incompatible with lon/lat: {raw.shape}; "
                f"lon={lon.size}; lat={lat.size}"
            )

        fill = rain_ds.attrs.get("_FillValue", None)
        if fill is not None:
            fill_value = float(np.asarray(fill).reshape(-1)[0])
            rain[np.isclose(rain, fill_value)] = np.nan
        rain[rain < 0.0] = np.nan

        units = rain_ds.attrs.get("units", "")
        if isinstance(units, bytes):
            units = units.decode("utf-8", errors="replace")
        normalized_units = str(units).lower().replace(" ", "")
        if normalized_units not in {"mm/hr", "mmhr-1", "mmh-1"}:
            raise ValueError(f"unexpected IMERG precipitation units: {units!r}")

    return CanonicalRainfallField(
        source_id=f"NASA_IMERG_FINAL_V{version}",
        product_version=version,
        valid_start_utc=start,
        valid_end_utc=end,
        accumulation_seconds=int((end - start).total_seconds()),
        rain_rate_mm_per_hr=rain,
        longitude_deg_e=lon,
        latitude_deg_n=lat,
        gauge_adjusted=True,
        source_path=p.name,
        source_hash_prefix=hashlib.sha256(p.read_bytes()).hexdigest()[:16],
        native_quality={
            "dataset": "/Grid/precipitation",
            "native_array_order": native_order,
            "canonical_array_order": "LAT_LON",
            "negative_values_mapped_to_nan": True,
            "temporal_semantics": "HALF_HOUR_MEAN_RAIN_RATE",
            "o9_expected_product_family": "NASA_GPM_IMERG_FINAL",
            "o9_version_mixing_allowed": False,
        },
    )
