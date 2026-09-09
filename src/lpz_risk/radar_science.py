"""Scientific handling of JMA public precipitation-image tiles.

The public JMA PNG tiles are display products, not continuous numeric rasters.
LPZ-RISK therefore decodes only the official precipitation colour classes and
preserves each pixel as an interval. It never invents an exact mm/h value from
a colour bucket.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class PrecipitationClass:
    class_id: str
    rgb: tuple[int, int, int]
    lower_mmph: float
    upper_mmph: float | None

    def contains(self, value: float) -> bool:
        if value < self.lower_mmph:
            return False
        return self.upper_mmph is None or value < self.upper_mmph


# JMA website colour-guideline RGB values for radar/nowcast/precipitation.
# The scientific payload is an interval, not a midpoint estimate.
JMA_PRECIPITATION_CLASSES: tuple[PrecipitationClass, ...] = (
    PrecipitationClass("P00_01", (242, 242, 255), 0.0, 1.0),
    PrecipitationClass("P01_05", (160, 210, 255), 1.0, 5.0),
    PrecipitationClass("P05_10", (33, 140, 255), 5.0, 10.0),
    PrecipitationClass("P10_20", (0, 65, 255), 10.0, 20.0),
    PrecipitationClass("P20_30", (250, 245, 0), 20.0, 30.0),
    PrecipitationClass("P30_50", (255, 153, 0), 30.0, 50.0),
    PrecipitationClass("P50_80", (255, 40, 0), 50.0, 80.0),
    PrecipitationClass("P80_INF", (180, 0, 104), 80.0, None),
)

PALETTE_BY_RGB = {item.rgb: item for item in JMA_PRECIPITATION_CLASSES}


@dataclass
class RadarTileDecode:
    width: int
    height: int
    rgba: np.ndarray
    class_index: np.ndarray
    transparent_mask: np.ndarray
    unknown_opaque_mask: np.ndarray
    observed_opaque_rgbs: tuple[tuple[int, int, int], ...]
    transparent_rgbs: tuple[tuple[int, int, int], ...]

    @property
    def opaque_pixel_count(self) -> int:
        return int(np.count_nonzero(~self.transparent_mask))

    @property
    def transparent_pixel_count(self) -> int:
        return int(np.count_nonzero(self.transparent_mask))

    @property
    def unknown_opaque_pixel_count(self) -> int:
        return int(np.count_nonzero(self.unknown_opaque_mask))

    def class_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for idx, cls in enumerate(JMA_PRECIPITATION_CLASSES):
            count = int(np.count_nonzero(self.class_index == idx))
            if count:
                counts[cls.class_id] = count
        return counts

    def summary(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "opaque_pixel_count": self.opaque_pixel_count,
            "transparent_pixel_count": self.transparent_pixel_count,
            "unknown_opaque_pixel_count": self.unknown_opaque_pixel_count,
            "class_counts": self.class_counts(),
            "observed_opaque_rgbs": [list(rgb) for rgb in self.observed_opaque_rgbs],
            "transparent_rgbs": [list(rgb) for rgb in self.transparent_rgbs],
        }


def decode_jma_precipitation_png(payload: bytes) -> RadarTileDecode:
    """Decode a JMA precipitation PNG into official intensity classes.

    class_index values:
      -1 transparent / not scientifically classified here
      -2 opaque colour not in the official precipitation palette
       0..7 official precipitation classes
    """
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("payload does not have a PNG signature")

    image = Image.open(io.BytesIO(payload)).convert("RGBA")
    rgba = np.asarray(image, dtype=np.uint8)
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError(f"unexpected RGBA array shape: {rgba.shape}")

    height, width, _ = rgba.shape
    alpha = rgba[:, :, 3]
    transparent = alpha == 0
    class_index = np.full((height, width), -1, dtype=np.int8)
    rgb = rgba[:, :, :3]

    opaque = ~transparent
    for idx, precip_class in enumerate(JMA_PRECIPITATION_CLASSES):
        color_match = np.all(rgb == np.asarray(precip_class.rgb, dtype=np.uint8), axis=2)
        class_index[opaque & color_match] = idx

    unknown_opaque = opaque & (class_index < 0)

    opaque_rgbs = tuple(
        sorted(
            tuple(map(int, row))
            for row in np.unique(rgb[opaque].reshape(-1, 3), axis=0)
        )
    ) if np.any(opaque) else tuple()

    transparent_rgbs = tuple(
        sorted(
            tuple(map(int, row))
            for row in np.unique(rgb[transparent].reshape(-1, 3), axis=0)
        )
    ) if np.any(transparent) else tuple()

    return RadarTileDecode(
        width=width,
        height=height,
        rgba=rgba,
        class_index=class_index,
        transparent_mask=transparent,
        unknown_opaque_mask=unknown_opaque,
        observed_opaque_rgbs=opaque_rgbs,
        transparent_rgbs=transparent_rgbs,
    )


def class_interval(class_index: int) -> tuple[float, float | None]:
    if class_index < 0 or class_index >= len(JMA_PRECIPITATION_CLASSES):
        raise ValueError(f"invalid precipitation class index: {class_index}")
    item = JMA_PRECIPITATION_CLASSES[class_index]
    return item.lower_mmph, item.upper_mmph


def interval_definitely_at_least(class_index: np.ndarray, threshold_mmph: float) -> np.ndarray:
    """True only where the entire decoded class is >= threshold.

    This is deliberately conservative. A bucket spanning the threshold is not
    promoted to true because the exact rainfall intensity is unknown.
    """
    output = np.zeros(class_index.shape, dtype=bool)
    for idx, item in enumerate(JMA_PRECIPITATION_CLASSES):
        if item.lower_mmph >= threshold_mmph:
            output[class_index == idx] = True
    return output


def interval_possibly_at_least(class_index: np.ndarray, threshold_mmph: float) -> np.ndarray:
    """True where at least part of the decoded class reaches the threshold."""
    output = np.zeros(class_index.shape, dtype=bool)
    for idx, item in enumerate(JMA_PRECIPITATION_CLASSES):
        upper = math.inf if item.upper_mmph is None else item.upper_mmph
        if upper > threshold_mmph:
            output[class_index == idx] = True
    return output


def lonlat_to_xyz(lon: float, lat: float, zoom: int) -> tuple[int, int, int]:
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(max(-85.05112878, min(85.05112878, lat)))
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return zoom, x, y


def tile_pixel_center_lonlat(
    zoom: int,
    tile_x: int,
    tile_y: int,
    pixel_x: int,
    pixel_y: int,
    tile_size: int = 256,
) -> tuple[float, float]:
    """Return Web-Mercator lon/lat for a tile-pixel center."""
    if not (0 <= pixel_x < tile_size and 0 <= pixel_y < tile_size):
        raise ValueError("pixel index outside tile")
    n = 2**zoom
    global_x = tile_x + (pixel_x + 0.5) / tile_size
    global_y = tile_y + (pixel_y + 0.5) / tile_size
    lon = global_x / n * 360.0 - 180.0
    merc_y = math.pi * (1.0 - 2.0 * global_y / n)
    lat = math.degrees(math.atan(math.sinh(merc_y)))
    return lon, lat


def web_mercator_pixel_area_km2(lat_deg: float, zoom: int, tile_size: int = 256) -> float:
    """Approximate ground area of one Web-Mercator pixel at latitude."""
    earth_circumference_m = 2.0 * math.pi * 6378137.0
    resolution_m = (earth_circumference_m * math.cos(math.radians(lat_deg))) / (tile_size * 2**zoom)
    return (resolution_m * resolution_m) / 1_000_000.0
