from __future__ import annotations

import unittest

import numpy as np

from lpz_risk.gfs_science import DecodedField, FieldKey
from lpz_risk.orientation_science import (
    acute_axis_mismatch_deg,
    axial_orientation_deg,
    nearest_local_wind,
    orientation_consistency,
    wind_axis_orientation_deg,
)


class OrientationScienceTests(unittest.TestCase):
    def test_axial_normalization(self) -> None:
        self.assertAlmostEqual(axial_orientation_deg(190.0), 10.0)
        self.assertAlmostEqual(axial_orientation_deg(-10.0), 170.0)

    def test_acute_axis_mismatch_wraps(self) -> None:
        self.assertAlmostEqual(acute_axis_mismatch_deg(175.0, 5.0), 10.0)
        self.assertAlmostEqual(acute_axis_mismatch_deg(10.0, 100.0), 90.0)

    def test_wind_from_and_to_share_same_axis(self) -> None:
        self.assertAlmostEqual(wind_axis_orientation_deg(20.0), 20.0)
        self.assertAlmostEqual(wind_axis_orientation_deg(200.0), 20.0)

    def test_orientation_consistency(self) -> None:
        out = orientation_consistency(12.0, 198.0)
        self.assertAlmostEqual(out["wind_axis_deg"], 18.0)
        self.assertAlmostEqual(out["acute_mismatch_deg"], 6.0)

    def test_nearest_local_wind(self) -> None:
        lats = np.array([35.0, 35.0, 36.0, 36.0])
        lons = np.array([139.0, 140.0, 139.0, 140.0])
        u = DecodedField(FieldKey("u", 600), "m s-1", np.array([1.0, 2.0, 3.0, 4.0]), lats, lons, 2, 2)
        v = DecodedField(FieldKey("v", 600), "m s-1", np.array([0.0, -1.0, 0.0, -2.0]), lats, lons, 2, 2)
        wind = nearest_local_wind({u.key: u, v.key: v}, level_hpa=600, lon=139.8, lat=35.2)
        self.assertAlmostEqual(wind.grid_lon, 140.0)
        self.assertAlmostEqual(wind.grid_lat, 35.0)
        self.assertAlmostEqual(wind.u_mps, 2.0)
        self.assertAlmostEqual(wind.v_mps, -1.0)


if __name__ == "__main__":
    unittest.main()
