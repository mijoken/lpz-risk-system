"""C-2C-16 real-data JMA/IMERG spatial connection proof.

RESEARCH ONLY.

This proof:
- reuses the existing JMA PNG decoder;
- reuses the existing Web-Mercator pixel geolocation;
- reuses the existing IMERG V07 canonical decoder;
- reuses the C-2C-11 continuous->JMA-class mapper;
- never converts JMA classes to invented midpoint rain rates;
- performs no interpolation or IMERG upsampling;
- processes only scientifically classified JMA pixels.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from lpz_risk.radar_science import (
    JMA_PRECIPITATION_CLASSES,
    decode_jma_precipitation_png,
)

from lpz_risk.imerg_v07 import decode_imerg_early_v07_file

from imerg_c2c11_jma_class_boundary_proof import (
    continuous_mmph_to_jma_class_index,
)


JMA_FRAME = (
    ROOT
    / "reports"
    / "gap_recovery"
    / "c2a_jma_raw"
    / "20260917T040500Z_20260917T043500Z_z6"
    / "20260917040500"
)

IMERG_FILE = (
    ROOT
    / "reports"
    / "gap_recovery"
    / "c2b_imerg_target"
    / "3B-HHR-E.MS.MRG.3IMERG.20260917-S040000-E042959.0240.V07C.HDF5"
)

TILE_RE = re.compile(r"z(?P<z>\d+)_(?P<x>\d+)_(?P<y>\d+)\.png$")


def pixel_lonlat_arrays(
    zoom: int,
    tile_x: int,
    tile_y: int,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized equivalent of tile_pixel_center_lonlat()."""

    n = float(2**zoom)

    px = np.arange(width, dtype=np.float64) + 0.5
    py = np.arange(height, dtype=np.float64) + 0.5

    global_x = tile_x + px / width
    global_y = tile_y + py / height

    lon_1d = global_x / n * 360.0 - 180.0

    merc_y = np.pi * (1.0 - 2.0 * global_y / n)
    lat_1d = np.degrees(np.arctan(np.sinh(merc_y)))

    return lon_1d, lat_1d


def nearest_sorted_indices(
    coordinates: np.ndarray,
    values: np.ndarray,
) -> np.ndarray:
    """Return nearest indices in an ascending regular coordinate vector."""

    coordinates = np.asarray(coordinates, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)

    if coordinates.ndim != 1:
        raise ValueError("coordinates must be 1-D")

    if np.any(np.diff(coordinates) <= 0):
        raise ValueError("coordinates must be strictly ascending")

    right = np.searchsorted(coordinates, values, side="left")
    right = np.clip(right, 0, coordinates.size - 1)

    left = np.clip(right - 1, 0, coordinates.size - 1)

    choose_left = (
        np.abs(values - coordinates[left])
        <= np.abs(coordinates[right] - values)
    )

    return np.where(choose_left, left, right)


def main() -> None:

    print("===== C-2C-16 REAL DATA SPATIAL CONNECTION PROOF =====")
    print()

    if not JMA_FRAME.is_dir():
        raise FileNotFoundError(JMA_FRAME)

    if not IMERG_FILE.is_file():
        raise FileNotFoundError(IMERG_FILE)

    field = decode_imerg_early_v07_file(IMERG_FILE)

    rain = np.asarray(field.rain_rate_mm_per_hr, dtype=np.float64)
    imerg_lon = np.asarray(field.longitude_deg_e, dtype=np.float64)
    imerg_lat = np.asarray(field.latitude_deg_n, dtype=np.float64)

    if rain.shape != (imerg_lat.size, imerg_lon.size):
        raise AssertionError("canonical IMERG shape invariant failed")

    imerg_class = continuous_mmph_to_jma_class_index(rain)

    confusion = np.zeros((8, 8), dtype=np.int64)

    total_png_pixels = 0
    classified_jma_pixels = 0
    transparent_pixels = 0
    unknown_opaque_pixels = 0
    outside_imerg_domain = 0
    imerg_missing_pixels = 0
    comparable_pixels = 0

    exact_agreement = 0
    within_one_class = 0

    jma_class_counts = np.zeros(8, dtype=np.int64)
    imerg_class_counts = np.zeros(8, dtype=np.int64)

    png_files = sorted(JMA_FRAME.glob("*.png"))

    if len(png_files) != 49:
        raise AssertionError(
            f"expected 49 JMA PNG tiles, found {len(png_files)}"
        )

    for png_path in png_files:

        match = TILE_RE.match(png_path.name)

        if match is None:
            raise ValueError(f"unexpected tile filename: {png_path.name}")

        zoom = int(match.group("z"))
        tile_x = int(match.group("x"))
        tile_y = int(match.group("y"))

        decoded = decode_jma_precipitation_png(png_path.read_bytes())

        total_png_pixels += decoded.width * decoded.height
        transparent_pixels += decoded.transparent_pixel_count
        unknown_opaque_pixels += decoded.unknown_opaque_pixel_count

        if decoded.unknown_opaque_pixel_count:
            raise AssertionError(
                f"unknown opaque JMA colour in {png_path.name}"
            )

        valid_jma = decoded.class_index >= 0

        classified_count = int(np.count_nonzero(valid_jma))
        classified_jma_pixels += classified_count

        if classified_count == 0:
            continue

        lon_1d, lat_1d = pixel_lonlat_arrays(
            zoom,
            tile_x,
            tile_y,
            decoded.width,
            decoded.height,
        )

        rows, cols = np.nonzero(valid_jma)

        lon_values = lon_1d[cols]
        lat_values = lat_1d[rows]

        inside = (
            (lon_values >= imerg_lon[0])
            & (lon_values <= imerg_lon[-1])
            & (lat_values >= imerg_lat[0])
            & (lat_values <= imerg_lat[-1])
        )

        outside_imerg_domain += int(np.count_nonzero(~inside))

        if not np.any(inside):
            continue

        rows = rows[inside]
        cols = cols[inside]
        lon_values = lon_values[inside]
        lat_values = lat_values[inside]

        lon_idx = nearest_sorted_indices(imerg_lon, lon_values)
        lat_idx = nearest_sorted_indices(imerg_lat, lat_values)

        jma_cls = decoded.class_index[rows, cols].astype(np.int16)
        imerg_cls = imerg_class[lat_idx, lon_idx].astype(np.int16)

        finite_pair = imerg_cls >= 0

        imerg_missing_pixels += int(np.count_nonzero(~finite_pair))

        if not np.any(finite_pair):
            continue

        jma_cls = jma_cls[finite_pair]
        imerg_cls = imerg_cls[finite_pair]

        comparable_pixels += int(jma_cls.size)

        exact_agreement += int(np.count_nonzero(jma_cls == imerg_cls))

        within_one_class += int(
            np.count_nonzero(np.abs(jma_cls - imerg_cls) <= 1)
        )

        np.add.at(confusion, (jma_cls, imerg_cls), 1)

        jma_class_counts += np.bincount(
            jma_cls,
            minlength=8,
        )[:8]

        imerg_class_counts += np.bincount(
            imerg_cls,
            minlength=8,
        )[:8]

    if comparable_pixels <= 0:
        raise AssertionError("no comparable JMA/IMERG pixels")

    print("JMA_FRAME =", JMA_FRAME)
    print("IMERG_FILE =", IMERG_FILE.name)

    print(
        "IMERG_VALIDITY =",
        field.valid_start_utc.isoformat(),
        "->",
        field.valid_end_utc.isoformat(),
    )

    print("IMERG_SHAPE =", rain.shape)
    print("JMA_TILE_COUNT =", len(png_files))
    print("TOTAL_JMA_PNG_PIXELS =", total_png_pixels)
    print("CLASSIFIED_JMA_PIXELS =", classified_jma_pixels)
    print("TRANSPARENT_JMA_PIXELS =", transparent_pixels)
    print("UNKNOWN_OPAQUE_JMA_PIXELS =", unknown_opaque_pixels)
    print("OUTSIDE_IMERG_DOMAIN =", outside_imerg_domain)
    print("IMERG_MISSING_AT_JMA_PIXELS =", imerg_missing_pixels)
    print("COMPARABLE_PIXELS =", comparable_pixels)

    print()

    exact_rate = exact_agreement / comparable_pixels
    within_one_rate = within_one_class / comparable_pixels

    print("EXACT_CLASS_AGREEMENT =", exact_rate)
    print("WITHIN_ONE_CLASS_AGREEMENT =", within_one_rate)

    print()
    print("===== CLASS COUNTS =====")

    for idx, precip_class in enumerate(JMA_PRECIPITATION_CLASSES):
        print(
            idx,
            precip_class.class_id,
            "JMA=",
            int(jma_class_counts[idx]),
            "IMERG=",
            int(imerg_class_counts[idx]),
        )

    print()
    print("===== CONFUSION MATRIX =====")
    print("rows=JMA classes, columns=IMERG classes")
    print(confusion)

    print()
    print("===== THRESHOLD OCCUPANCY =====")

    thresholds = [
        (1.0, 1),
        (5.0, 2),
        (10.0, 3),
        (20.0, 4),
        (30.0, 5),
        (50.0, 6),
        (80.0, 7),
    ]

    for threshold, class_floor in thresholds:

        jma_n = int(jma_class_counts[class_floor:].sum())
        imerg_n = int(imerg_class_counts[class_floor:].sum())

        print(
            f">={threshold:g} mm/h",
            f"JMA={jma_n}",
            f"IMERG={imerg_n}",
            f"JMA_FRAC={jma_n / comparable_pixels:.8f}",
            f"IMERG_FRAC={imerg_n / comparable_pixels:.8f}",
        )

    print()
    print("RESULT=PASS_C2C16_REAL_DATA_SPATIAL_CONNECTION")
    print("INTERPRETATION_GATE=DESCRIPTIVE_ONLY")
    print("DIRECT_CONTINUOUS_RATE_COMPARISON=BLOCKED")
    print("JMA_MIDPOINT_FABRICATION=false")
    print("SPATIAL_INTERPOLATION=false")
    print("RISK_ENGINE_ALLOWED=false")
    print("PRODUCTION_INTEGRATION_ALLOWED=false")


if __name__ == "__main__":
    main()
