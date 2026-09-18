"""C-2C-18 six-frame JMA persistence vs IMERG half-hour proof.

RESEARCH ONLY.

JMA public PNG classes remain interval-valued.
No class midpoint, no invented continuous rate, no temporal averaging
of class indices.

IMERG comparison unit is its native 0.1-degree cell.
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


from lpz_risk.radar_science import decode_jma_precipitation_png
from lpz_risk.imerg_v07 import decode_imerg_early_v07_file

from imerg_c2c11_jma_class_boundary_proof import (
    continuous_mmph_to_jma_class_index,
)


JMA_ROOT = (
    ROOT
    / "reports"
    / "gap_recovery"
    / "c2a_jma_raw"
    / "20260917T040500Z_20260917T043500Z_z6"
)

FRAME_NAMES = [
    "20260917040500",
    "20260917041000",
    "20260917041500",
    "20260917042000",
    "20260917042500",
    "20260917043000",
]

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

THRESHOLDS = [
    (1.0, 1),
    (5.0, 2),
    (10.0, 3),
    (20.0, 4),
    (30.0, 5),
    (50.0, 6),
    (80.0, 7),
]


def pixel_lonlat_arrays(zoom, tile_x, tile_y, width, height):

    n = float(2**zoom)

    px = np.arange(width, dtype=np.float64) + 0.5
    py = np.arange(height, dtype=np.float64) + 0.5

    gx = tile_x + px / width
    gy = tile_y + py / height

    lon = gx / n * 360.0 - 180.0

    merc_y = np.pi * (1.0 - 2.0 * gy / n)
    lat = np.degrees(np.arctan(np.sinh(merc_y)))

    return lon, lat


def nearest_sorted_indices(coordinates, values):

    right = np.searchsorted(coordinates, values, side="left")
    right = np.clip(right, 0, coordinates.size - 1)

    left = np.clip(right - 1, 0, coordinates.size - 1)

    use_left = (
        np.abs(values - coordinates[left])
        <= np.abs(coordinates[right] - values)
    )

    return np.where(use_left, left, right)


def decode_frame(frame_dir, lon, lat):

    cell_counts = {}

    png_files = sorted(frame_dir.glob("*.png"))

    if len(png_files) != 49:
        raise AssertionError(
            f"{frame_dir.name}: expected 49 tiles, got {len(png_files)}"
        )

    classified = 0
    unknown = 0

    for path in png_files:

        m = TILE_RE.match(path.name)

        if m is None:
            raise ValueError(path.name)

        decoded = decode_jma_precipitation_png(
            path.read_bytes()
        )

        unknown += decoded.unknown_opaque_pixel_count

        if decoded.unknown_opaque_pixel_count:
            raise AssertionError(
                f"unknown opaque colour in {path}"
            )

        valid = decoded.class_index >= 0

        classified += int(np.count_nonzero(valid))

        if not np.any(valid):
            continue

        rows, cols = np.nonzero(valid)

        plon, plat = pixel_lonlat_arrays(
            int(m.group("z")),
            int(m.group("x")),
            int(m.group("y")),
            decoded.width,
            decoded.height,
        )

        pixel_lon = plon[cols]
        pixel_lat = plat[rows]

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

        lon_idx = nearest_sorted_indices(
            lon,
            pixel_lon,
        )

        lat_idx = nearest_sorted_indices(
            lat,
            pixel_lat,
        )

        classes = decoded.class_index[
            rows,
            cols,
        ].astype(np.int16)

        flat = lat_idx * lon.size + lon_idx

        for cell, cls in zip(
            flat.tolist(),
            classes.tolist(),
        ):

            counts = cell_counts.get(cell)

            if counts is None:
                counts = np.zeros(8, dtype=np.int64)
                cell_counts[cell] = counts

            counts[cls] += 1

    return cell_counts, classified, unknown


def main():

    print("===== C-2C-18 SIX FRAME PERSISTENCE PROOF =====")
    print()

    field = decode_imerg_early_v07_file(IMERG_FILE)

    if field.source_id != "NASA_IMERG_EARLY_V07":
        raise AssertionError(field.source_id)

    if field.gauge_adjusted is not False:
        raise AssertionError("wrong Early provenance")

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

    frames = []

    for frame_name in FRAME_NAMES:

        frame_dir = JMA_ROOT / frame_name

        if not frame_dir.is_dir():
            raise FileNotFoundError(frame_dir)

        counts, classified, unknown = decode_frame(
            frame_dir,
            lon,
            lat,
        )

        frames.append(counts)

        print(
            "FRAME",
            frame_name,
            "CLASSIFIED_PIXELS=",
            classified,
            "CELLS=",
            len(counts),
            "UNKNOWN=",
            unknown,
        )

    all_cells = sorted(
        set().union(*(set(frame.keys()) for frame in frames))
    )

    comparable = []

    for cell in all_cells:

        lat_idx = cell // lon.size
        lon_idx = cell % lon.size

        icls = int(imerg_class[lat_idx, lon_idx])

        if icls < 0:
            continue

        frame_occupancies = np.full(
            (len(frames), len(THRESHOLDS)),
            np.nan,
            dtype=np.float64,
        )

        for fi, frame in enumerate(frames):

            counts = frame.get(cell)

            if counts is None:
                continue

            n = int(counts.sum())

            if n <= 0:
                continue

            for ti, (_, class_floor) in enumerate(
                THRESHOLDS
            ):
                frame_occupancies[fi, ti] = (
                    counts[class_floor:].sum() / n
                )

        comparable.append(
            (
                icls,
                frame_occupancies,
            )
        )

    if not comparable:
        raise AssertionError("no comparable cells")

    print()
    print("COMPARABLE_IMERG_CELLS =", len(comparable))

    print()
    print("===== SIX-FRAME PERSISTENCE SUMMARY =====")

    for ti, (threshold, class_floor) in enumerate(
        THRESHOLDS
    ):

        any_frame = []
        majority_frame = []
        persistence_any = []
        persistence_majority = []
        mean_spatial_occupancy = []
        imerg_yes = []

        for icls, occ_matrix in comparable:

            occ = occ_matrix[:, ti]
            valid = np.isfinite(occ)

            if not np.any(valid):
                continue

            x = occ[valid]

            any_frame.append(
                float(np.any(x > 0))
            )

            majority_frame.append(
                float(np.any(x >= 0.5))
            )

            persistence_any.append(
                float(np.mean(x > 0))
            )

            persistence_majority.append(
                float(np.mean(x >= 0.5))
            )

            mean_spatial_occupancy.append(
                float(np.mean(x))
            )

            imerg_yes.append(
                float(icls >= class_floor)
            )

        print(
            f">={threshold:g} mm/h",
            f"CELLS={len(any_frame)}",
            f"JMA_ANY_FRAME={np.mean(any_frame):.8f}",
            f"JMA_ANY_MAJORITY_FRAME={np.mean(majority_frame):.8f}",
            f"JMA_TEMPORAL_PERSISTENCE_ANY={np.mean(persistence_any):.8f}",
            f"JMA_TEMPORAL_PERSISTENCE_MAJORITY={np.mean(persistence_majority):.8f}",
            f"JMA_MEAN_SPATIAL_OCCUPANCY={np.mean(mean_spatial_occupancy):.8f}",
            f"IMERG_HALF_HOUR_CLASS={np.mean(imerg_yes):.8f}",
        )

    print()
    print("SOURCE_ID =", field.source_id)
    print("GAUGE_ADJUSTED =", field.gauge_adjusted)

    print(
        "IMERG_VALIDITY =",
        field.valid_start_utc.isoformat(),
        "->",
        field.valid_end_utc.isoformat(),
    )

    print(
        "JMA_FRAMES =",
        ",".join(FRAME_NAMES),
    )

    print()
    print(
        "RESULT=PASS_C2C18_SIX_FRAME_PERSISTENCE"
    )
    print(
        "TEMPORAL_AGGREGATION=DESCRIPTIVE_PERSISTENCE_ONLY"
    )
    print(
        "JMA_CLASS_AVERAGING=false"
    )
    print(
        "JMA_MIDPOINT_FABRICATION=false"
    )
    print(
        "DIRECT_CONTINUOUS_RATE_COMPARISON=BLOCKED"
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
