from __future__ import annotations

import io
import unittest

import numpy as np
from PIL import Image

from lpz_risk.radar_science import (
    JMA_PRECIPITATION_CLASSES,
    class_interval,
    decode_jma_precipitation_png,
    interval_definitely_at_least,
    interval_possibly_at_least,
    tile_pixel_center_lonlat,
    web_mercator_pixel_area_km2,
)


class RadarScienceTests(unittest.TestCase):
    def _make_png(self, rgba_rows: list[list[tuple[int, int, int, int]]]) -> bytes:
        arr = np.asarray(rgba_rows, dtype=np.uint8)
        image = Image.fromarray(arr, mode="RGBA")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def test_official_palette_has_eight_intervals(self) -> None:
        self.assertEqual(len(JMA_PRECIPITATION_CLASSES), 8)
        self.assertEqual(JMA_PRECIPITATION_CLASSES[0].lower_mmph, 0.0)
        self.assertEqual(JMA_PRECIPITATION_CLASSES[-1].lower_mmph, 80.0)
        self.assertIsNone(JMA_PRECIPITATION_CLASSES[-1].upper_mmph)

    def test_decode_preserves_bucket_not_midpoint(self) -> None:
        color = JMA_PRECIPITATION_CLASSES[5].rgb
        payload = self._make_png([[(color[0], color[1], color[2], 255)]])
        decoded = decode_jma_precipitation_png(payload)
        self.assertEqual(decoded.class_index[0, 0], 5)
        self.assertEqual(class_interval(5), (30.0, 50.0))

    def test_transparent_pixel_not_silently_zero(self) -> None:
        payload = self._make_png([[(255, 255, 255, 0)]])
        decoded = decode_jma_precipitation_png(payload)
        self.assertEqual(decoded.class_index[0, 0], -1)
        self.assertEqual(decoded.transparent_pixel_count, 1)
        self.assertEqual(decoded.unknown_opaque_pixel_count, 0)

    def test_unknown_opaque_colour_is_flagged(self) -> None:
        payload = self._make_png([[(1, 2, 3, 255)]])
        decoded = decode_jma_precipitation_png(payload)
        self.assertEqual(decoded.class_index[0, 0], -2)
        self.assertEqual(decoded.unknown_opaque_pixel_count, 1)

    def test_conservative_threshold_masks(self) -> None:
        classes = np.asarray([[3, 4, 5]], dtype=np.int8)  # 10-20, 20-30, 30-50
        definite20 = interval_definitely_at_least(classes, 20.0)
        possible20 = interval_possibly_at_least(classes, 20.0)
        np.testing.assert_array_equal(definite20, np.asarray([[False, True, True]]))
        np.testing.assert_array_equal(possible20, np.asarray([[False, True, True]]))

        definite25 = interval_definitely_at_least(classes, 25.0)
        possible25 = interval_possibly_at_least(classes, 25.0)
        np.testing.assert_array_equal(definite25, np.asarray([[False, False, True]]))
        np.testing.assert_array_equal(possible25, np.asarray([[False, True, True]]))

    def test_tile_pixel_center_is_geographic(self) -> None:
        lon, lat = tile_pixel_center_lonlat(6, 56, 25, 128, 128)
        self.assertTrue(135.0 < lon < 140.0)
        self.assertTrue(30.0 < lat < 40.0)

    def test_web_mercator_pixel_area_decreases_at_high_latitude(self) -> None:
        equator = web_mercator_pixel_area_km2(0.0, 8)
        japan = web_mercator_pixel_area_km2(35.0, 8)
        self.assertGreater(equator, japan)
        self.assertGreater(japan, 0.0)


if __name__ == "__main__":
    unittest.main()
