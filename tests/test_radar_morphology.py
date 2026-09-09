from __future__ import annotations

import unittest

import numpy as np

from lpz_risk.radar_morphology import (
    connected_components_8,
    exact_threshold_mask,
    extract_objects_from_mosaic,
)


class RadarMorphologyTests(unittest.TestCase):
    def test_exact_threshold_boundaries(self) -> None:
        classes = np.array([[4, 5, 6, 7]], dtype=np.int8)  # 20-30, 30-50, 50-80, 80+
        self.assertEqual(exact_threshold_mask(classes, 30.0).tolist(), [[False, True, True, True]])
        self.assertEqual(exact_threshold_mask(classes, 50.0).tolist(), [[False, False, True, True]])
        self.assertEqual(exact_threshold_mask(classes, 80.0).tolist(), [[False, False, False, True]])

    def test_non_palette_boundary_rejected(self) -> None:
        with self.assertRaises(ValueError):
            exact_threshold_mask(np.array([[7]], dtype=np.int8), 40.0)

    def test_eight_connected_diagonal_pixels_join(self) -> None:
        mask = np.array([[True, False], [False, True]])
        comps = connected_components_8(mask)
        self.assertEqual(len(comps), 1)
        self.assertEqual(len(comps[0]), 2)

    def test_two_separate_objects(self) -> None:
        mask = np.zeros((5, 5), dtype=bool)
        mask[0, 0] = True
        mask[4, 4] = True
        self.assertEqual(len(connected_components_8(mask)), 2)

    def test_horizontal_object_orientation_is_east_west(self) -> None:
        arr = np.full((64, 64), -1, dtype=np.int8)
        arr[30:33, 10:50] = 6
        objects = extract_objects_from_mosaic(
            arr,
            zoom=8,
            origin_tile_x=220,
            origin_tile_y=100,
            threshold_mmph=50.0,
        )
        self.assertEqual(len(objects), 1)
        obj = objects[0]
        self.assertGreater(obj.aspect_ratio or 0.0, 5.0)
        self.assertTrue(80.0 <= (obj.orientation_deg or 0.0) <= 100.0)
        self.assertFalse(obj.boundary_truncated)

    def test_vertical_object_orientation_is_north_south(self) -> None:
        arr = np.full((64, 64), -1, dtype=np.int8)
        arr[8:55, 31:34] = 7
        obj = extract_objects_from_mosaic(
            arr,
            zoom=8,
            origin_tile_x=220,
            origin_tile_y=100,
            threshold_mmph=80.0,
        )[0]
        angle = obj.orientation_deg or 0.0
        self.assertTrue(angle <= 10.0 or angle >= 170.0)
        self.assertGreater(obj.aspect_ratio or 0.0, 5.0)

    def test_boundary_truncation_flag(self) -> None:
        arr = np.full((32, 32), -1, dtype=np.int8)
        arr[0:5, 10:20] = 5
        obj = extract_objects_from_mosaic(
            arr,
            zoom=8,
            origin_tile_x=220,
            origin_tile_y=100,
            threshold_mmph=30.0,
        )[0]
        self.assertTrue(obj.boundary_truncated)

    def test_min_pixels_filters_noise(self) -> None:
        arr = np.full((16, 16), -1, dtype=np.int8)
        arr[2, 2] = 7
        arr[8:11, 8:11] = 7
        objects = extract_objects_from_mosaic(
            arr,
            zoom=8,
            origin_tile_x=220,
            origin_tile_y=100,
            threshold_mmph=80.0,
            min_pixels=2,
        )
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0].pixel_count, 9)


if __name__ == "__main__":
    unittest.main()
