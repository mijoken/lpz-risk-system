"""NASA GPM IMERG Final V07 adapter to the canonical rainfall schema."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
from pathlib import Path

import h5py
import numpy as np

from .canonical_rainfall import CanonicalRainfallField

_FILENAME = re.compile(
    r".*\.(?P<date>\d{8})-S(?P<sh>\d{2})(?P<sm>\d{2})(?P<ss>\d{2})-E(?P<eh>\d{2})(?P<em>\d{2})(?P<es>\d{2}).*\.V07[A-Z]?\.HDF5$"
)


def _time_bounds_from_filename(name: str) -> tuple[datetime, datetime]:
    m = _FILENAME.match(Path(name).name)
    if not m:
        raise ValueError(f"unsupported IMERG Final V07 filename: {name}")
    d = datetime.strptime(m.group("date"), "%Y%m%d").replace(tzinfo=timezone.utc)
    start = d.replace(hour=int(m.group("sh")), minute=int(m.group("sm")), second=int(m.group("ss")))
    end_inclusive = d.replace(hour=int(m.group("eh")), minute=int(m.group("em")), second=int(m.group("es")))
    if end_inclusive < start:
        end_inclusive += timedelta(days=1)
    # IMERG HH files use e.g. S000000-E002959: an inclusive final second for a
    # 30-minute interval. Canonical validity uses half-open [start,end).
    end = end_inclusive + timedelta(seconds=1)
    return start, end


def decode_imerg_final_v07_file(path: str | Path) -> CanonicalRainfallField:
    p = Path(path)
    start, end = _time_bounds_from_filename(p.name)
    with h5py.File(p, "r") as h:
        rain_ds = h["/Grid/precipitation"]
        lon = np.asarray(h["/Grid/lon"][...], dtype=np.float64).reshape(-1)
        lat = np.asarray(h["/Grid/lat"][...], dtype=np.float64).reshape(-1)
        raw = np.asarray(rain_ds[...], dtype=np.float64)
        # Real V07 proof shape is [time, lon, lat]. Collapse singleton time then
        # transpose to canonical [lat, lon].
        if raw.ndim == 3 and raw.shape[0] == 1:
            raw = raw[0]
        if raw.shape == (lon.size, lat.size):
            rain = raw.T
        elif raw.shape == (lat.size, lon.size):
            rain = raw
        else:
            raise ValueError(f"IMERG precipitation grid shape incompatible with lon/lat: {raw.shape}")

        fill = rain_ds.attrs.get("_FillValue", None)
        if fill is not None:
            rain[np.isclose(rain, float(np.asarray(fill).reshape(-1)[0]))] = np.nan
        rain[rain < 0.0] = np.nan
        units = rain_ds.attrs.get("units", "")
        if isinstance(units, bytes):
            units = units.decode("utf-8", errors="replace")
        if str(units).lower().replace(" ", "") not in {"mm/hr", "mmhr-1", "mmh-1"}:
            raise ValueError(f"unexpected IMERG precipitation units: {units!r}")

    return CanonicalRainfallField(
        source_id="NASA_IMERG_FINAL_V07",
        product_version="07",
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
            "native_array_order": "TIME_LON_LAT",
            "canonical_array_order": "LAT_LON",
            "negative_values_mapped_to_nan": True,
            "temporal_semantics": "HALF_HOUR_MEAN_RAIN_RATE",
        },
    )
