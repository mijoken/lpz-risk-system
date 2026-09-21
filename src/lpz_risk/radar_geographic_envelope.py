"""Geographic envelopes for tracked radar pixel components.

The envelope is a convex hull of the actual threshold-component pixel cells
within the fixed Web-Mercator tracking mosaic. It is intentionally an
*envelope*, not an exact precipitation contour and not an LPZ forecast.
"""

from __future__ import annotations

import math
from typing import Iterable


def _convex_hull(points: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    pts = sorted(set(points))
    if len(pts) <= 1:
        return pts

    def cross(o: tuple[int, int], a: tuple[int, int], b: tuple[int, int]) -> int:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[int, int]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: list[tuple[int, int]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def _grid_vertex_lonlat(
    col: int,
    row: int,
    *,
    zoom: int,
    origin_tile_x: int,
    origin_tile_y: int,
    tile_size: int = 256,
) -> tuple[float, float]:
    if zoom < 0 or tile_size <= 0:
        raise ValueError("invalid Web-Mercator grid")
    world_pixels = tile_size * (2**zoom)
    gx = origin_tile_x * tile_size + col
    gy = origin_tile_y * tile_size + row
    lon = gx / world_pixels * 360.0 - 180.0
    merc_y = math.pi * (1.0 - 2.0 * gy / world_pixels)
    lat = math.degrees(math.atan(math.sinh(merc_y)))
    return lon, lat


def _thin_hull(points: list[tuple[int, int]], max_vertices: int) -> list[tuple[int, int]]:
    if max_vertices < 4:
        raise ValueError("max_vertices must be >= 4")
    if len(points) <= max_vertices:
        return points
    # Convex-hull order is preserved. This is display-size control only.
    selected: list[tuple[int, int]] = []
    n = len(points)
    for i in range(max_vertices):
        idx = min(n - 1, round(i * n / max_vertices))
        point = points[idx]
        if not selected or point != selected[-1]:
            selected.append(point)
    return selected


def component_geographic_envelope(
    component,
    *,
    mosaic_width: int,
    zoom: int,
    origin_tile_x: int,
    origin_tile_y: int,
    tile_size: int = 256,
    max_vertices: int = 96,
) -> dict | None:
    """Return a small GeoJSON geographic envelope for one tracked component.

    The hull is built from the outer corners of the actual component pixels.
    It therefore preserves the component's observed geographic extent better
    than a centroid or pixel bbox, while remaining explicitly approximate:
    concavities and holes are filled by the convex hull.
    """
    if mosaic_width <= 0:
        raise ValueError("mosaic_width must be positive")

    flat = [int(v) for v in component.flat_indices]
    if not flat:
        return None

    pixel_set = set(flat)
    boundary_cells: list[tuple[int, int]] = []
    for idx in flat:
        row, col = divmod(idx, mosaic_width)
        if (
            idx - mosaic_width not in pixel_set
            or idx + mosaic_width not in pixel_set
            or (col > 0 and idx - 1 not in pixel_set)
            or (col + 1 < mosaic_width and idx + 1 not in pixel_set)
            or col == 0
            or col + 1 == mosaic_width
        ):
            boundary_cells.append((row, col))

    grid_corners: list[tuple[int, int]] = []
    for row, col in boundary_cells:
        grid_corners.extend(
            [
                (col, row),
                (col + 1, row),
                (col + 1, row + 1),
                (col, row + 1),
            ]
        )

    hull = _convex_hull(grid_corners)
    if len(hull) < 3:
        return None
    hull = _thin_hull(hull, max_vertices)

    ring = [
        list(
            _grid_vertex_lonlat(
                col,
                row,
                zoom=zoom,
                origin_tile_x=origin_tile_x,
                origin_tile_y=origin_tile_y,
                tile_size=tile_size,
            )
        )
        for col, row in hull
    ]
    ring.append(ring[0])

    return {
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "method": "CONVEX_HULL_OF_COMPONENT_PIXEL_CELLS",
        "exact_precipitation_contour": False,
        "source_pixel_count": int(component.pixel_count),
        "vertex_count": len(ring) - 1,
        "interpretation": (
            "Observed geographic envelope of the threshold component. "
            "Concavities/holes are not preserved; this is not an LPZ forecast footprint."
        ),
    }


def translate_polygon_lonlat(
    geometry: dict,
    *,
    from_lon: float,
    from_lat: float,
    to_lon: float,
    to_lat: float,
) -> dict:
    """Translate a small Polygon by the centroid displacement in lon/lat space."""
    if geometry.get("type") != "Polygon":
        raise ValueError("geometry must be a GeoJSON Polygon")
    values = [from_lon, from_lat, to_lon, to_lat]
    if not all(math.isfinite(float(v)) for v in values):
        raise ValueError("nonfinite centroid displacement")
    dlon = ((float(to_lon) - float(from_lon) + 180.0) % 360.0) - 180.0
    dlat = float(to_lat) - float(from_lat)

    out_rings: list[list[list[float]]] = []
    for ring in geometry.get("coordinates", []):
        if not isinstance(ring, list) or len(ring) < 4:
            raise ValueError("invalid polygon ring")
        shifted: list[list[float]] = []
        for coord in ring:
            if not isinstance(coord, list) or len(coord) < 2:
                raise ValueError("invalid polygon coordinate")
            lon = ((float(coord[0]) + dlon + 180.0) % 360.0) - 180.0
            lat = float(coord[1]) + dlat
            if not (-90.0 <= lat <= 90.0):
                raise ValueError("translated polygon outside latitude range")
            shifted.append([lon, lat])
        out_rings.append(shifted)
    return {"type": "Polygon", "coordinates": out_rings}
