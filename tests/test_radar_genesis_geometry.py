from __future__ import annotations

import unittest

from lpz_risk.radar_genesis_geometry import relative_motion_geometry


class RadarGenesisGeometryTests(unittest.TestCase):
    def test_child_ahead_of_eastward_motion_is_positive_along(self) -> None:
        g = relative_motion_geometry(
            previous_parent_row=10.0,
            previous_parent_col=10.0,
            current_parent_row=10.0,
            current_parent_col=12.0,
            child_row=10.0,
            child_col=15.0,
            latitude_deg=35.0,
            zoom=8,
            elapsed_seconds=300.0,
        )
        self.assertGreater(g["along_motion_km"], 0.0)
        self.assertFalse(g["negative_along_motion"])
        self.assertAlmostEqual(g["parent_motion_direction_deg"], 90.0)

    def test_child_behind_eastward_motion_is_negative_along(self) -> None:
        g = relative_motion_geometry(
            previous_parent_row=10.0,
            previous_parent_col=10.0,
            current_parent_row=10.0,
            current_parent_col=12.0,
            child_row=10.0,
            child_col=8.0,
            latitude_deg=35.0,
            zoom=8,
            elapsed_seconds=300.0,
        )
        self.assertLess(g["along_motion_km"], 0.0)
        self.assertTrue(g["negative_along_motion"])

    def test_northward_motion_direction(self) -> None:
        g = relative_motion_geometry(
            previous_parent_row=12.0,
            previous_parent_col=10.0,
            current_parent_row=10.0,
            current_parent_col=10.0,
            child_row=8.0,
            child_col=10.0,
            latitude_deg=35.0,
            zoom=8,
            elapsed_seconds=300.0,
        )
        self.assertAlmostEqual(g["parent_motion_direction_deg"], 0.0)
        self.assertGreater(g["along_motion_km"], 0.0)

    def test_stationary_parent_returns_no_along_axis(self) -> None:
        g = relative_motion_geometry(
            previous_parent_row=10.0,
            previous_parent_col=10.0,
            current_parent_row=10.0,
            current_parent_col=10.0,
            child_row=8.0,
            child_col=12.0,
            latitude_deg=35.0,
            zoom=8,
            elapsed_seconds=300.0,
        )
        self.assertIsNone(g["along_motion_km"])
        self.assertIsNone(g["parent_motion_direction_deg"])
        self.assertEqual(g["parent_motion_speed_mps"], 0.0)

    def test_nonpositive_elapsed_rejected(self) -> None:
        with self.assertRaises(ValueError):
            relative_motion_geometry(
                previous_parent_row=0.0,
                previous_parent_col=0.0,
                current_parent_row=1.0,
                current_parent_col=1.0,
                child_row=1.0,
                child_col=1.0,
                latitude_deg=35.0,
                zoom=8,
                elapsed_seconds=0.0,
            )


if __name__ == "__main__":
    unittest.main()
