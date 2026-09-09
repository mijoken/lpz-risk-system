from __future__ import annotations

import math
import unittest

from lpz_risk.radar_inflow_geometry import enrich_genesis_with_inflow, inflow_relative_geometry


class InflowRelativeGeometryTests(unittest.TestCase):
    def test_north_upstream(self):
        row = inflow_relative_geometry(
            parent_lon=140.0,
            parent_lat=35.0,
            child_lon=140.0,
            child_lat=35.1,
            wind_from_deg=0.0,
        )
        self.assertGreater(row["along_inflow_km"], 0.0)
        self.assertTrue(row["upstream_side"])
        self.assertAlmostEqual(row["cross_inflow_km"], 0.0, places=6)
        self.assertAlmostEqual(row["genesis_vs_inflow_from_angle_deg"], 0.0, places=6)

    def test_south_is_downwind_for_northerly(self):
        row = inflow_relative_geometry(
            parent_lon=140.0,
            parent_lat=35.0,
            child_lon=140.0,
            child_lat=34.9,
            wind_from_deg=0.0,
        )
        self.assertLess(row["along_inflow_km"], 0.0)
        self.assertTrue(row["downwind_side"])
        self.assertAlmostEqual(row["genesis_vs_inflow_from_angle_deg"], 180.0, places=6)

    def test_east_upstream_for_easterly(self):
        row = inflow_relative_geometry(
            parent_lon=140.0,
            parent_lat=35.0,
            child_lon=140.1,
            child_lat=35.0,
            wind_from_deg=90.0,
        )
        self.assertGreater(row["along_inflow_km"], 0.0)
        self.assertTrue(row["upstream_side"])
        self.assertAlmostEqual(row["cross_inflow_km"], 0.0, places=6)

    def test_left_cross_sign(self):
        # For a north-pointing inflow vector, west is left.
        row = inflow_relative_geometry(
            parent_lon=140.0,
            parent_lat=35.0,
            child_lon=139.9,
            child_lat=35.0,
            wind_from_deg=0.0,
        )
        self.assertGreater(row["cross_inflow_km"], 0.0)
        self.assertAlmostEqual(row["along_inflow_km"], 0.0, places=6)
        self.assertAlmostEqual(row["genesis_vs_inflow_from_angle_deg"], 90.0, places=6)

    def test_enrichment_preserves_parent_motion_geometry(self):
        events = [{
            "valid_time": "2026-09-09T09:00:00Z",
            "threshold_mmph": 80,
            "parent_centroid": {"lon": 140.0, "lat": 35.0},
            "child_centroid": {"lon": 140.0, "lat": 35.1},
            "along_motion_km": -2.0,
        }]
        winds = [{
            "level_hpa": 850,
            "meteorological_from_deg": 0.0,
            "speed_mps": 12.0,
        }]
        out = enrich_genesis_with_inflow(events, winds)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["along_motion_km"], -2.0)
        self.assertGreater(out[0]["along_inflow_km"], 0.0)
        self.assertEqual(out[0]["local_wind_850hpa"]["level_hpa"], 850)

    def test_reject_nonfinite(self):
        with self.assertRaises(ValueError):
            inflow_relative_geometry(
                parent_lon=math.nan,
                parent_lat=35.0,
                child_lon=140.0,
                child_lat=35.0,
                wind_from_deg=0.0,
            )


if __name__ == "__main__":
    unittest.main()
