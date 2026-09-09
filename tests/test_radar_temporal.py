from __future__ import annotations

import unittest

from lpz_risk.radar_temporal import build_parent_temporal_descriptors, haversine_km


class RadarTemporalTests(unittest.TestCase):
    def test_haversine_zero(self) -> None:
        self.assertAlmostEqual(haversine_km(139.0, 35.0, 139.0, 35.0), 0.0)

    def test_descriptor_aggregates_motion_area_and_core_activity(self) -> None:
        tracking = {
            "scientific_tracking_proven": True,
            "tracking": {
                "30": {
                    "frames": [
                        {"components": [{"local_id": 1, "lineage_id": "T30-L0001", "approx_area_km2": 100.0, "centroid": {"lon": 139.0, "lat": 35.0}, "boundary_truncated": False}]},
                        {"components": [{"local_id": 1, "lineage_id": "T30-L0001", "approx_area_km2": 120.0, "centroid": {"lon": 139.1, "lat": 35.0}, "boundary_truncated": False}]},
                        {"components": [{"local_id": 1, "lineage_id": "T30-L0001", "approx_area_km2": 90.0, "centroid": {"lon": 139.2, "lat": 35.0}, "boundary_truncated": False}]},
                    ],
                    "transitions": [
                        {"primary_matches": [{"lineage_id": "T30-L0001", "centroid_displacement_km": 9.0, "centroid_speed_mps": 30.0, "iou": 0.4, "overlap_previous": 0.6, "overlap_current": 0.5}]},
                        {"primary_matches": [{"lineage_id": "T30-L0001", "centroid_displacement_km": 8.0, "centroid_speed_mps": 26.0, "iou": 0.2, "overlap_previous": 0.4, "overlap_current": 0.3}]},
                    ],
                    "lineages": [{"lineage_id": "T30-L0001", "first_frame_index": 0, "last_frame_index": 2, "frame_count": 3, "duration_minutes": 10}],
                }
            },
        }
        hierarchy = {
            "scientific_hierarchy_proven": True,
            "frames": [
                {"frame_index": 0, "children": {"50": {"assignments": []}, "80": {"assignments": []}}},
                {"frame_index": 1, "children": {"50": {"assignments": [{"parent_lineage_id": "T30-L0001"}]}, "80": {"assignments": []}}},
                {"frame_index": 2, "children": {"50": {"assignments": [{"parent_lineage_id": "T30-L0001"}]}, "80": {"assignments": [{"parent_lineage_id": "T30-L0001"}]}}},
            ],
            "genesis_events": [
                {"parent_lineage_id": "T30-L0001", "threshold_mmph": 50},
                {"parent_lineage_id": "T30-L0001", "threshold_mmph": 80},
            ],
        }
        out = build_parent_temporal_descriptors(tracking, hierarchy)
        self.assertEqual(len(out), 1)
        row = out[0]
        self.assertEqual(row["duration_minutes"], 10)
        self.assertAlmostEqual(row["matched_path_displacement_km"], 17.0)
        self.assertAlmostEqual(row["mean_speed_mps"], 28.0)
        self.assertAlmostEqual(row["median_iou"], 0.3)
        self.assertAlmostEqual(row["mean_area_km2"], 310.0 / 3.0)
        self.assertAlmostEqual(row["area_change_last_minus_first_km2"], -10.0)
        self.assertEqual(row["frames_with_50_core"], 2)
        self.assertEqual(row["frames_with_80_core"], 1)
        self.assertEqual(row["embedded_core_genesis_count"], 2)
        self.assertFalse(row["boundary_truncated_any"])

    def test_unproven_input_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_parent_temporal_descriptors({"scientific_tracking_proven": False}, {"scientific_hierarchy_proven": True})


if __name__ == "__main__":
    unittest.main()
