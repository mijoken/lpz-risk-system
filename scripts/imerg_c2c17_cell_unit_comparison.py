"""C-2C-17 IMERG-cell-unit categorical comparison proof.

RESEARCH ONLY.

Comparison unit:
    one native IMERG 0.1-degree grid cell

JMA public PNG:
    remains interval-valued categorical information.
    No midpoint or invented continuous rainfall rate.

IMERG Early V07:
    remains native half-hour mean rain rate.
    No spatial interpolation / upsampling.

This is a same-window descriptive comparison, not an accuracy validation.
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

TILE_RE = re.compile(
    r"z(?P<z>\d+)_(?P<x>\d+)_(?P<y>\d+)\.png$"
)


def pixel_lonlat_arrays(
    zoom: int,
    tile_x: int,
    tile_y: int,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:

    n = float(2**zoom)

    px = np.arange(width, dtype=np.float64) + 0.5
    py = np.arange(height, dtype=np.float64) + 0.5

    global_x = tile_x + px / width
    global_y = tile_y + py / height

    lon = global_x / n * 360.0 - 180.0

    merc_y = np.pi * (1.0 - 2.0 * global_y / n)
    lat = np.degrees(np.arctan(np.sinh(merc_y)))

    return lon, lat


def nearest_sorted_indices(
    coordinates: np.ndarray,
    values: np.ndarray,
) -> np.ndarray:

    coordinates = np.asarray(coordinates, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)

    right = np.searchsorted(coordinates, values, side="left")
    right = np.clip(right, 0, coordinates.size - 1)

    left = np.clip(right - 1, 0, coordinates.size - 1)

    choose_left = (
        np.abs(values - coordinates[left])
        <= np.abs(coordinates[right] - values)
    )

    return np.where(choose_left, left, right)


def main() -> None:

    print("===== C-2C-17 IMERG CELL UNIT COMPARISON =====")
    print()

    field = decode_imerg_early_v07_file(IMERG_FILE)

    if field.source_id != "NASA_IMERG_EARLY_V07":
        raise AssertionError(
            f"wrong provenance: {field.source_id}"
        )

    if field.gauge_adjusted is not False:
        raise AssertionError(
            "IMERG Early must have gauge_adjusted=False"
        )

    rain = np.asarray(
        field.rain_rate_mm_per_hr,
        dtype=np.float64,
    )

    lon = np.asarray(
        field.longitude_deg_e,
        dtype=np.float64,
    )

    lat = np.asarray(
        field.latitude_deg_n,
        dtype=np.float64,
    )

    imerg_class = continuous_mmph_to_jma_class_index(rain)

    # key = flattened native IMERG cell index
    # value = eight JMA class pixel counts
    cell_counts: dict[int, np.ndarray] = {}

    total_classified_pixels = 0
    transparent_pixels = 0
    unknown_pixels = 0

    png_files = sorted(JMA_FRAME.glob("*.png"))

    if len(png_files) != 49:
        raise AssertionError(
            f"expected 49 tiles, found {len(png_files)}"
        )

    for png_path in png_files:

        match = TILE_RE.match(png_path.name)

        if match is None:
            raise ValueError(png_path.name)

        zoom = int(match.group("z"))
        tile_x = int(match.group("x"))
        tile_y = int(match.group("y"))

        decoded = decode_jma_precipitation_png(
            png_path.read_bytes()
        )

        transparent_pixels += decoded.transparent_pixel_count
        unknown_pixels += decoded.unknown_opaque_pixel_count

        if decoded.unknown_opaque_pixel_count:
            raise AssertionError(
                f"unknown opaque colour: {png_path.name}"
            )

        valid = decoded.class_index >= 0

        total_classified_pixels += int(
            np.count_nonzero(valid)
        )

        if not np.any(valid):
            continue

        lon_1d, lat_1d = pixel_lonlat_arrays(
            zoom,
            tile_x,
            tile_y,
            decoded.width,
            decoded.height,
        )

        rows, cols = np.nonzero(valid)

        pixel_lon = lon_1d[cols]
        pixel_lat = lat_1d[rows]

        inside = (
            (pixel_lon >= lon[0])
            & (pixel_lon <= lon[-1])
            & (pixel_lat >= lat[0])
            & (pixel_lat <= lat[-1])
        )

        rows = rows[inside]
        cols = cols[inside]
        pixel_lon = pixel_lon[inside]
        pixel_lat = pixel_lat[inside]

        lon_idx = nearest_sorted_indices(lon, pixel_lon)
        lat_idx = nearest_sorted_indices(lat, pixel_lat)

        classes = decoded.class_index[
            rows,
            cols,
        ].astype(np.int16)

        flat_cells = lat_idx * lon.size + lon_idx

        for flat_cell, cls in zip(
            flat_cells.tolist(),
            classes.tolist(),
        ):
            counts = cell_counts.get(flat_cell)

            if counts is None:
                counts = np.zeros(8, dtype=np.int64)
                cell_counts[flat_cell] = counts

            counts[cls] += 1

    records = []

    for flat_cell, counts in cell_counts.items():

        lat_idx = flat_cell // lon.size
        lon_idx = flat_cell % lon.size

        icls = int(imerg_class[lat_idx, lon_idx])

        if icls < 0:
            continue

        n = int(counts.sum())

        modal_class = int(np.argmax(counts))

        present = np.flatnonzero(counts > 0)
        max_class = int(present[-1])

        occupancy = np.array(
            [
                counts[1:].sum(),
                counts[2:].sum(),
                counts[3:].sum(),
                counts[4:].sum(),
                counts[5:].sum(),
                counts[6:].sum(),
                counts[7:].sum(),
            ],
            dtype=np.float64,
        ) / n

        records.append(
            (
                lat_idx,
                lon_idx,
                n,
                modal_class,
                max_class,
                icls,
                occupancy,
            )
        )

    if not records:
        raise AssertionError("no comparable IMERG cells")

    cell_n = len(records)

    modal_confusion = np.zeros(
        (8, 8),
        dtype=np.int64,
    )

    max_confusion = np.zeros(
        (8, 8),
        dtype=np.int64,
    )

    modal_exact = 0
    modal_within_one = 0

    pixel_counts = []

    occupancy_matrix = []

    imerg_threshold_matrix = []

    thresholds = [
        (1.0, 1),
        (5.0, 2),
        (10.0, 3),
        (20.0, 4),
        (30.0, 5),
        (50.0, 6),
        (80.0, 7),
    ]

    for (
        lat_idx,
        lon_idx,
        n,
        modal_class,
        max_class,
        icls,
        occupancy,
    ) in records:

        modal_confusion[modal_class, icls] += 1
        max_confusion[max_class, icls] += 1

        modal_exact += int(modal_class == icls)

        modal_within_one += int(
            abs(modal_class - icls) <= 1
        )

        pixel_counts.append(n)
        occupancy_matrix.append(occupancy)

        imerg_threshold_matrix.append(
            [
                float(icls >= class_floor)
                for _, class_floor in thresholds
            ]
        )

    pixel_counts = np.asarray(
        pixel_counts,
        dtype=np.int64,
    )

    occupancy_matrix = np.asarray(
        occupancy_matrix,
        dtype=np.float64,
    )

    imerg_threshold_matrix = np.asarray(
        imerg_threshold_matrix,
        dtype=np.float64,
    )

    print("SOURCE_ID =", field.source_id)
    print("GAUGE_ADJUSTED =", field.gauge_adjusted)

    print(
        "IMERG_VALIDITY =",
        field.valid_start_utc.isoformat(),
        "->",
        field.valid_end_utc.isoformat(),
    )

    print("JMA_FRAME = 2026-09-17T04:05:00Z")
    print()

    print("JMA_TILE_COUNT =", len(png_files))
    print(
        "TOTAL_CLASSIFIED_JMA_PIXELS =",
        total_classified_pixels,
    )
    print(
        "TRANSPARENT_JMA_PIXELS =",
        transparent_pixels,
    )
    print(
        "UNKNOWN_OPAQUE_JMA_PIXELS =",
        unknown_pixels,
    )

    print("COMPARABLE_IMERG_CELLS =", cell_n)

    print(
        "JMA_PIXELS_PER_IMERG_CELL_MIN =",
        int(pixel_counts.min()),
    )

    print(
        "JMA_PIXELS_PER_IMERG_CELL_MEDIAN =",
        float(np.median(pixel_counts)),
    )

    print(
        "JMA_PIXELS_PER_IMERG_CELL_MAX =",
        int(pixel_counts.max()),
    )

    print()
    print("===== MODAL CLASS COMPARISON =====")

    print(
        "MODAL_EXACT_AGREEMENT =",
        modal_exact / cell_n,
    )

    print(
        "MODAL_WITHIN_ONE_CLASS =",
        modal_within_one / cell_n,
    )

    print(
        "rows=JMA modal class, columns=IMERG class"
    )

    print(modal_confusion)

    print()
    print("===== MAXIMUM JMA CLASS VS IMERG =====")

    print(
        "rows=JMA maximum observed class, "
        "columns=IMERG class"
    )

    print(max_confusion)

    print()
    print("===== CELL-UNIT THRESHOLD SUMMARY =====")

    for k, (threshold, class_floor) in enumerate(
        thresholds
    ):

        jma_occ = occupancy_matrix[:, k]

        imerg_yes = imerg_threshold_matrix[:, k]

        print(
            f">={threshold:g} mm/h",
            f"JMA_MEAN_CELL_OCCUPANCY={jma_occ.mean():.8f}",
            f"JMA_CELLS_ANY={np.mean(jma_occ > 0):.8f}",
            f"JMA_CELLS_MAJORITY={np.mean(jma_occ >= 0.5):.8f}",
            f"IMERG_CELLS={imerg_yes.mean():.8f}",
        )

    print()
    print(
        "RESULT=PASS_C2C17_IMERG_CELL_UNIT_COMPARISON"
    )
    print(
        "COMPARISON_UNIT=NATIVE_IMERG_0P1_DEGREE_CELL"
    )
    print(
        "JMA_VALUE_SEMANTICS=INTERVAL_CLASS_ONLY"
    )
    print(
        "IMERG_VALUE_SEMANTICS=HALF_HOUR_MEAN_RAIN_RATE"
    )
    print(
        "DIRECT_CONTINUOUS_RATE_COMPARISON=BLOCKED"
    )
    print(
        "JMA_MIDPOINT_FABRICATION=false"
    )
    print(
        "SPATIAL_INTERPOLATION=false"
    )
    print(
        "RISK_ENGINE_ALLOWED=false"
    )
    print(
        "PRODUCTION_INTEGRATION_ALLOWED=false"
    )


if __name__ == "__main__":
    main()
