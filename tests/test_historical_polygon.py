from __future__ import annotations

import unittest

import numpy as np

from lpz_risk.historical_polygon import (
    mask_grid_centres,
    point_in_geojson_geometry,
    spherical_latlon_cell_areas_km2,
)


class HistoricalPolygonTest(unittest.TestCase):
    def test_polygon_with_hole(self):
        geometry = {
            "type": "Polygon",
            "coordinates": [
                [[130, 30], [134, 30], [134, 34], [130, 34], [130, 30]],
                [[131, 31], [132, 31], [132, 32], [131, 32], [131, 31]],
            ],
        }
        self.assertTrue(point_in_geojson_geometry(130.5, 30.5, geometry))
        self.assertFalse(point_in_geojson_geometry(131.5, 31.5, geometry))
        self.assertFalse(point_in_geojson_geometry(140.0, 40.0, geometry))

    def test_geometry_collection_and_grid_mask(self):
        geometry = {
            "type": "GeometryCollection",
            "geometries": [
                {"type": "Polygon", "coordinates": [[[130, 30], [131, 30], [131, 31], [130, 31], [130, 30]]]},
                {"type": "Polygon", "coordinates": [[[133, 33], [134, 33], [134, 34], [133, 34], [133, 33]]]},
            ],
        }
        lat = np.array([[30.5, 30.5], [33.5, 33.5]])
        lon = np.array([[130.5, 132.0], [132.0, 133.5]])
        mask = mask_grid_centres(lat, lon, geometry)
        np.testing.assert_array_equal(mask, np.array([[True, False], [False, True]]))

    def test_cell_area_decreases_toward_higher_latitude(self):
        lat = np.array([30.0, 40.0])
        lon = np.array([130.0, 131.0])
        area = spherical_latlon_cell_areas_km2(lat, lon)
        self.assertEqual(area.shape, (2, 2))
        self.assertTrue(np.all(area > 0.0))
        self.assertGreater(area[0, 0], area[1, 0])

    def test_non_monotonic_grid_is_rejected(self):
        with self.assertRaises(ValueError):
            spherical_latlon_cell_areas_km2(np.array([30.0, 31.0, 30.5]), np.array([130.0, 131.0]))


if __name__ == "__main__":
    unittest.main()
