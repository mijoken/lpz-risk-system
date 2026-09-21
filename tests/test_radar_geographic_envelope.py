"""Unit tests for research-only radar geographic envelopes."""

from dataclasses import dataclass

import numpy as np

from lpz_risk.radar_geographic_envelope import (
    component_geographic_envelope,
    translate_polygon_lonlat,
)


@dataclass
class SyntheticComponent:
    flat_indices: np.ndarray
    pixel_count: int


def component(rows, cols, width=512):
    flat = np.array([r * width + c for r in rows for c in cols], dtype=np.int64)
    return SyntheticComponent(flat_indices=flat, pixel_count=int(flat.size))


def test_component_envelope_is_closed_geojson_polygon():
    comp = component(range(10, 14), range(20, 27))
    out = component_geographic_envelope(
        comp,
        mosaic_width=512,
        zoom=8,
        origin_tile_x=220,
        origin_tile_y=100,
    )
    assert out is not None
    assert out["method"] == "CONVEX_HULL_OF_COMPONENT_PIXEL_CELLS"
    assert out["exact_precipitation_contour"] is False
    assert out["source_pixel_count"] == 28
    ring = out["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    assert len(ring) >= 5
    for lon, lat in ring:
        assert -180 <= lon <= 180
        assert -90 <= lat <= 90


def test_envelope_uses_component_pixels_not_only_bbox_centroid():
    width = 512
    flat = np.array(
        [
            10 * width + 20,
            10 * width + 21,
            11 * width + 21,
            12 * width + 21,
            12 * width + 22,
        ],
        dtype=np.int64,
    )
    comp = SyntheticComponent(flat_indices=flat, pixel_count=len(flat))
    out = component_geographic_envelope(
        comp,
        mosaic_width=width,
        zoom=8,
        origin_tile_x=220,
        origin_tile_y=100,
    )
    assert out is not None
    assert out["vertex_count"] >= 4


def test_translate_polygon_moves_ring_and_preserves_closure():
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [139.0, 35.0],
            [139.2, 35.0],
            [139.2, 35.2],
            [139.0, 35.2],
            [139.0, 35.0],
        ]],
    }
    shifted = translate_polygon_lonlat(
        geometry,
        from_lon=139.1,
        from_lat=35.1,
        to_lon=139.4,
        to_lat=35.3,
    )
    ring = shifted["coordinates"][0]
    assert ring[0] == ring[-1]
    assert ring[0][0] == 139.3
    assert ring[0][1] == 35.2


def test_empty_component_returns_none():
    comp = SyntheticComponent(flat_indices=np.array([], dtype=np.int64), pixel_count=0)
    assert component_geographic_envelope(
        comp,
        mosaic_width=512,
        zoom=8,
        origin_tile_x=220,
        origin_tile_y=100,
    ) is None
