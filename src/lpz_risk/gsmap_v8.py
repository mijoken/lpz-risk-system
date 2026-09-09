"""Official JAXA GSMaP Gauge Standard v8 hourly binary decoder.

Specification source: JAXA/EORC DataFormatDescription_MVK_RNL_v8.0000.pdf.
Binary semantics are intentionally explicit: gzip-compressed little-endian float32,
1200 latitude lines x 3600 longitude rows, 0.1-degree grid, first cell center
(0.05E, 59.95N), hourly mean rain rate in mm/hr. Negative values are missing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import re
from pathlib import Path

import numpy as np

from .canonical_rainfall import CanonicalRainfallField

NLON = 3600
NLAT = 1200
EXPECTED_VALUES = NLON * NLAT
EXPECTED_UNCOMPRESSED_BYTES = EXPECTED_VALUES * 4
LON = np.arange(NLON, dtype=np.float64) * 0.1 + 0.05
LAT = 59.95 - np.arange(NLAT, dtype=np.float64) * 0.1
_FILENAME = re.compile(
    r"^gsmap_gauge\.(?P<date>\d{8})\.(?P<hour>\d{2})(?P<minute>\d{2})\.v(?P<version>[^.]+(?:\.[^.]+){2})\.dat(?:\.gz)?$"
)


def parse_gsmap_filename(name: str) -> tuple[datetime, str]:
    m = _FILENAME.match(Path(name).name)
    if not m:
        raise ValueError(f"unsupported GSMaP Gauge v8 filename: {name}")
    if m.group("minute") != "00":
        raise ValueError("GSMaP Standard v8 hourly minute must be 00")
    start = datetime.strptime(m.group("date") + m.group("hour"), "%Y%m%d%H").replace(tzinfo=timezone.utc)
    return start, m.group("version")


def _decode_uncompressed(raw: bytes) -> np.ndarray:
    if len(raw) != EXPECTED_UNCOMPRESSED_BYTES:
        raise ValueError(
            f"unexpected GSMaP uncompressed byte count: {len(raw)} != {EXPECTED_UNCOMPRESSED_BYTES}"
        )
    # JAXA describes longitude elements across 3600 rows and latitude across 1200
    # lines, with [1,1] at the left-top corner. C-order reshape therefore yields
    # [latitude_line, longitude_row].
    arr = np.frombuffer(raw, dtype="<f4", count=EXPECTED_VALUES).reshape(NLAT, NLON).astype(np.float64)
    # Official missing values for hourly rain rate are negative (-4, -8, -99).
    arr[arr < 0.0] = np.nan
    return arr


def decode_gsmap_gauge_v8_bytes(payload: bytes, *, filename: str, compressed: bool = True) -> CanonicalRainfallField:
    start, version = parse_gsmap_filename(filename)
    raw = gzip.decompress(payload) if compressed else payload
    rain = _decode_uncompressed(raw)
    return CanonicalRainfallField(
        source_id="GSMAP_STANDARD_V8_HISTORICAL",
        product_version=f"v{version}",
        valid_start_utc=start,
        valid_end_utc=start + timedelta(hours=1),
        accumulation_seconds=3600,
        rain_rate_mm_per_hr=rain,
        longitude_deg_e=LON.copy(),
        latitude_deg_n=LAT.copy(),
        gauge_adjusted=True,
        source_path=filename,
        source_hash_prefix=hashlib.sha256(payload).hexdigest()[:16],
        native_quality={
            "format": "gzip_little_endian_float32",
            "official_missing_values": [-4.0, -8.0, -99.0],
            "negative_values_mapped_to_nan": True,
            "temporal_semantics": "AVERAGED_00_TO_59_MINUTES_OF_SPECIFIED_UTC_HOUR",
            "grid_semantics": "GLOBAL_60N_TO_60S_0P1_DEGREE_CELL_CENTERS",
        },
    )


def decode_gsmap_gauge_v8_file(path: str | Path) -> CanonicalRainfallField:
    p = Path(path)
    return decode_gsmap_gauge_v8_bytes(p.read_bytes(), filename=p.name, compressed=p.suffix == ".gz")
