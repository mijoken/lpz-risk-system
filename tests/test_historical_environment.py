from __future__ import annotations

import unittest

from lpz_risk.historical_environment import floor_to_hour, build_era5_request_manifest


class HistoricalEnvironmentTest(unittest.TestCase):
    def test_floor_to_hour_never_uses_future_time(self):
        row = floor_to_hour("2025-08-10T03:50:00Z")
        self.assertEqual(row["era5_source_time_utc"], "2025-08-10T03:00:00Z")
        self.assertEqual(row["source_lag_minutes"], 50)
        self.assertFalse(row["future_source_time_used"])

    def test_exact_hour_has_zero_lag(self):
        row = floor_to_hour("2025-08-10T03:00:00Z")
        self.assertEqual(row["era5_source_time_utc"], "2025-08-10T03:00:00Z")
        self.assertEqual(row["source_lag_minutes"], 0)

    def test_manifest_deduplicates_source_times_and_stays_blocked_without_geometry(self):
        registry = {
            "realized_positive_anchors": [
                {
                    "anchor_id": "A1",
                    "primary_subdivision_code": "400000",
                    "snapshot_offsets_minutes": [-60, -30, 0],
                    "snapshot_times_utc": [
                        "2025-08-10T02:50:00Z",
                        "2025-08-10T03:20:00Z",
                        "2025-08-10T03:50:00Z",
                    ],
                },
                {
                    "anchor_id": "A2",
                    "primary_subdivision_code": "400001",
                    "snapshot_offsets_minutes": [0],
                    "snapshot_times_utc": ["2025-08-10T03:40:00Z"],
                },
            ]
        }
        config = {
            "provider": "COPERNICUS_CDS_ERA5",
            "dataset": "reanalysis-era5-pressure-levels",
            "pressure_levels_hpa": [850, 700, 600, 500],
            "variables": ["relative_humidity", "u_component_of_wind", "v_component_of_wind"],
            "spatial_sampling": {"status": "PENDING_PRIMARY_SUBDIVISION_GEOMETRY"},
        }
        report = build_era5_request_manifest(registry, config)
        self.assertEqual(report["snapshot_mapping_count"], 4)
        self.assertEqual(report["unique_era5_source_time_count"], 2)
        self.assertEqual(report["request_day_count"], 1)
        self.assertEqual(report["future_source_time_count"], 0)
        self.assertEqual(report["maximum_source_lag_minutes"], 50)
        self.assertEqual(report["spatial_sampling_gate"], "PENDING_PRIMARY_SUBDIVISION_GEOMETRY")
        self.assertFalse(report["requests"][0]["download_allowed"])
        self.assertFalse(report["risk_engine_allowed"])


if __name__ == "__main__":
    unittest.main()
