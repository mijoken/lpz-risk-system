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

    def test_manifest_groups_by_date_and_subdivision_with_official_bbox(self):
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
            "spatial_sampling": {
                "status": "PROVEN_JMA_PRIMARY_SUBDIVISION_BBOX",
                "bbox_padding_degrees": 0.5,
            },
        }
        geometry = {
            "geometry_complete_for_required_codes": True,
            "regions": [
                {"primary_subdivision_code": "400000", "bbox": [130.0, 32.0, 131.0, 33.0]},
                {"primary_subdivision_code": "400001", "bbox": [131.0, 33.0, 132.0, 34.0]},
            ],
        }
        report = build_era5_request_manifest(registry, config, geometry)
        self.assertEqual(report["snapshot_mapping_count"], 4)
        self.assertEqual(report["unique_era5_source_time_count"], 2)
        self.assertEqual(report["request_day_count"], 1)
        self.assertEqual(report["date_subdivision_request_count"], 2)
        self.assertEqual(report["unique_primary_subdivision_count"], 2)
        self.assertEqual(report["future_source_time_count"], 0)
        self.assertEqual(report["maximum_source_lag_minutes"], 50)
        self.assertEqual(report["spatial_sampling_gate"], "PROVEN_JMA_PRIMARY_SUBDIVISION_BBOX")
        self.assertEqual(report["authenticated_download_gate"], "BLOCKED_PENDING_CDS_CREDENTIAL")
        req = next(r for r in report["requests"] if r["primary_subdivision_code"] == "400000")
        self.assertEqual(req["padded_bbox_west_south_east_north"], [129.5, 31.5, 131.5, 33.5])
        self.assertEqual(req["cds_area_north_west_south_east"], [33.5, 129.5, 31.5, 131.5])
        self.assertFalse(req["download_allowed_in_ordinary_ci"])
        self.assertFalse(report["risk_engine_allowed"])

    def test_missing_geometry_code_is_rejected(self):
        registry = {
            "realized_positive_anchors": [{
                "anchor_id": "A1",
                "primary_subdivision_code": "400000",
                "snapshot_offsets_minutes": [0],
                "snapshot_times_utc": ["2025-08-10T03:40:00Z"],
            }]
        }
        config = {
            "provider": "COPERNICUS_CDS_ERA5",
            "dataset": "reanalysis-era5-pressure-levels",
            "pressure_levels_hpa": [850],
            "variables": ["u_component_of_wind"],
            "spatial_sampling": {"status": "PROVEN_JMA_PRIMARY_SUBDIVISION_BBOX", "bbox_padding_degrees": 0.5},
        }
        geometry = {"geometry_complete_for_required_codes": True, "regions": []}
        with self.assertRaises(ValueError):
            build_era5_request_manifest(registry, config, geometry)


if __name__ == "__main__":
    unittest.main()
