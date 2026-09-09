from __future__ import annotations

import unittest

from lpz_risk.parent_precursor import build_parent_precursor_descriptors


class ParentPrecursorTests(unittest.TestCase):
    def setUp(self):
        self.temporal = {
            "execution_ok": True,
            "descriptors": [
                {
                    "parent_lineage_id": "P1",
                    "duration_minutes": 15,
                    "median_speed_mps": 4.0,
                    "median_iou": 0.6,
                    "embedded_core_genesis_count": 3,
                    "boundary_truncated_any": False,
                },
                {
                    "parent_lineage_id": "P2",
                    "duration_minutes": 5,
                    "median_speed_mps": 20.0,
                    "median_iou": 0.1,
                    "embedded_core_genesis_count": 0,
                    "boundary_truncated_any": False,
                },
            ],
        }
        self.inflow = {
            "execution_ok": True,
            "scientific_inflow_geometry_proven": True,
            "events": [
                {
                    "parent_lineage_id": "P1",
                    "threshold_mmph": 50,
                    "parent_boundary_truncated": False,
                    "along_motion_km": -2.0,
                    "along_inflow_km": 1.0,
                    "genesis_vs_inflow_from_angle_deg": 20.0,
                    "local_wind_850hpa": {"speed_mps": 10.0},
                },
                {
                    "parent_lineage_id": "P1",
                    "threshold_mmph": 50,
                    "parent_boundary_truncated": False,
                    "along_motion_km": 3.0,
                    "along_inflow_km": -1.0,
                    "genesis_vs_inflow_from_angle_deg": 140.0,
                    "local_wind_850hpa": {"speed_mps": 12.0},
                },
                {
                    "parent_lineage_id": "P1",
                    "threshold_mmph": 80,
                    "parent_boundary_truncated": False,
                    "along_motion_km": -1.0,
                    "along_inflow_km": 2.0,
                    "genesis_vs_inflow_from_angle_deg": 10.0,
                    "local_wind_850hpa": {"speed_mps": 14.0},
                },
            ],
        }

    def test_join_and_counts(self):
        rows = build_parent_precursor_descriptors(self.temporal, self.inflow)
        self.assertEqual(len(rows), 2)
        p1 = next(r for r in rows if r["parent_lineage_id"] == "P1")
        self.assertEqual(p1["genesis_event_count"], 3)
        self.assertEqual(p1["core50_genesis_usable_count"], 2)
        self.assertEqual(p1["core50_genesis_behind_motion_count"], 1)
        self.assertEqual(p1["core50_genesis_upstream_inflow_count"], 1)
        self.assertEqual(p1["core50_genesis_behind_and_upstream_count"], 1)
        self.assertAlmostEqual(p1["core50_genesis_median_along_motion_km"], 0.5)
        self.assertAlmostEqual(p1["core50_genesis_median_850hpa_wind_speed_mps"], 11.0)
        self.assertEqual(p1["core80_genesis_usable_count"], 1)
        self.assertIsNone(p1["classification"])
        self.assertIsNone(p1["risk_score"])

    def test_parent_without_genesis_is_retained(self):
        rows = build_parent_precursor_descriptors(self.temporal, self.inflow)
        p2 = next(r for r in rows if r["parent_lineage_id"] == "P2")
        self.assertEqual(p2["genesis_event_count"], 0)
        self.assertEqual(p2["core50_genesis_usable_count"], 0)
        self.assertIsNone(p2["core50_genesis_upstream_inflow_fraction"])

    def test_boundary_truncated_events_excluded_from_usable(self):
        bad = dict(self.inflow)
        bad["events"] = [dict(self.inflow["events"][0], parent_boundary_truncated=True)]
        rows = build_parent_precursor_descriptors(self.temporal, bad)
        p1 = next(r for r in rows if r["parent_lineage_id"] == "P1")
        self.assertEqual(p1["genesis_event_count"], 1)
        self.assertEqual(p1["usable_genesis_event_count"], 0)

    def test_reject_invalid_inputs(self):
        with self.assertRaises(ValueError):
            build_parent_precursor_descriptors({"execution_ok": False}, self.inflow)
        with self.assertRaises(ValueError):
            build_parent_precursor_descriptors(self.temporal, {"execution_ok": False})


if __name__ == "__main__":
    unittest.main()
