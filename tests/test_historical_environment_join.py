from __future__ import annotations

import unittest

from lpz_risk.historical_environment_join import build_era5_snapshot_feature_table


def _env(rh500=70.0):
    return {
        "rh500_mean_pct": rh500,
        "rh700_mean_pct": 80.0,
        "rh500_rh700_gt60_fraction": 1.0,
        "wind600_speed_mean_mps": 12.0,
        "wind600_from_direction_median_deg": 240.0,
        "wind850_speed_mean_mps": 10.0,
        "wind850_from_direction_median_deg": 210.0,
        "specific_humidity_mean_kgkg": {"1000": 0.015, "925": 0.013, "850": 0.011},
        "spatial_semantics": "REQUEST_BBOX_CONTEXT_NOT_SUBDIVISION_POLYGON_MEAN",
    }


def _request(date="2023-06-01", code="390030", times=None):
    return {
        "date": date,
        "primary_subdivision_code": code,
        "times_utc": list(times or ["20:00", "21:00"]),
    }


class HistoricalEnvironmentJoinTest(unittest.TestCase):
    def test_complete_join(self):
        manifest = {
            "execution_ok": True,
            "date_subdivision_request_count": 1,
            "requests": [_request()],
            "snapshot_mapping_count": 2,
            "snapshot_mappings": [
                {"anchor_id": "A", "primary_subdivision_code": "390030", "snapshot_offset_minutes": -60, "requested_snapshot_time_utc": "2023-06-01T20:20:00Z", "era5_source_time_utc": "2023-06-01T20:00:00Z", "source_lag_minutes": 20, "future_source_time_used": False},
                {"anchor_id": "A", "primary_subdivision_code": "390030", "snapshot_offset_minutes": 0, "requested_snapshot_time_utc": "2023-06-01T21:20:00Z", "era5_source_time_utc": "2023-06-01T21:00:00Z", "source_lag_minutes": 20, "future_source_time_used": False},
            ],
        }
        descriptors = [{
            "phase": "2B-era5-batch-request",
            "request_index": 0,
            "request_key": "0000_2023-06-01_390030",
            "primary_subdivision_code": "390030",
            "downloaded_bytes": 100,
            "cds_area_north_west_south_east": [34, 132, 32, 134],
            "multitime_validation": {"multitime_payload_pass": True},
            "time_descriptors": [
                {"era5_source_time_utc": "2023-06-01T20:00:00Z", "environment_descriptors": _env(70.0), "validation": {}},
                {"era5_source_time_utc": "2023-06-01T21:00:00Z", "environment_descriptors": _env(71.0), "validation": {}},
            ],
        }]
        result = build_era5_snapshot_feature_table(manifest, descriptors)
        self.assertTrue(result["available_window_complete"])
        self.assertTrue(result["historical_environment_reconstruction_complete"])
        self.assertEqual(result["snapshot_feature_row_count"], 2)
        self.assertEqual(result["hard_missing_snapshot_key_count"], 0)
        self.assertEqual(result["pending_source_availability_snapshot_count"], 0)
        self.assertIsNone(result["snapshot_features"][0]["risk_score"])

    def test_true_missing_hour_blocks_available_window(self):
        manifest = {
            "execution_ok": True,
            "date_subdivision_request_count": 1,
            "requests": [_request(times=["21:00"])],
            "snapshot_mapping_count": 1,
            "snapshot_mappings": [
                {"anchor_id": "A", "primary_subdivision_code": "390030", "snapshot_offset_minutes": 0, "requested_snapshot_time_utc": "2023-06-01T21:20:00Z", "era5_source_time_utc": "2023-06-01T21:00:00Z", "source_lag_minutes": 20, "future_source_time_used": False},
            ],
        }
        result = build_era5_snapshot_feature_table(manifest, [])
        self.assertFalse(result["available_window_complete"])
        self.assertFalse(result["historical_environment_reconstruction_complete"])
        self.assertEqual(result["hard_missing_snapshot_key_count"], 1)
        self.assertEqual(result["hard_missing_request_indices"], [0])

    def test_recent_source_lag_tail_does_not_poison_available_window(self):
        manifest = {
            "execution_ok": True,
            "date_subdivision_request_count": 2,
            "requests": [
                _request(date="2023-06-01", code="390030", times=["20:00"]),
                _request(date="2026-09-08", code="210010", times=["04:00"]),
            ],
            "snapshot_mapping_count": 2,
            "snapshot_mappings": [
                {"anchor_id": "OLD", "primary_subdivision_code": "390030", "snapshot_offset_minutes": 0, "requested_snapshot_time_utc": "2023-06-01T20:20:00Z", "era5_source_time_utc": "2023-06-01T20:00:00Z", "source_lag_minutes": 20, "future_source_time_used": False},
                {"anchor_id": "NEW", "primary_subdivision_code": "210010", "snapshot_offset_minutes": 0, "requested_snapshot_time_utc": "2026-09-08T04:20:00Z", "era5_source_time_utc": "2026-09-08T04:00:00Z", "source_lag_minutes": 20, "future_source_time_used": False},
            ],
        }
        descriptors = [{
            "phase": "2B-era5-batch-request",
            "request_index": 0,
            "request_key": "R0",
            "primary_subdivision_code": "390030",
            "multitime_validation": {"multitime_payload_pass": True},
            "time_descriptors": [
                {"era5_source_time_utc": "2023-06-01T20:00:00Z", "environment_descriptors": _env(), "validation": {}}
            ],
        }]
        result = build_era5_snapshot_feature_table(
            manifest,
            descriptors,
            pending_source_availability_indices=[1],
            pending_source_availability_reasons={1: "latest date available for this dataset is: 2026-09-04 14:00"},
        )
        self.assertTrue(result["available_window_complete"])
        self.assertFalse(result["historical_environment_reconstruction_complete"])
        self.assertEqual(result["snapshot_feature_row_count"], 1)
        self.assertEqual(result["pending_source_availability_request_indices"], [1])
        self.assertEqual(result["pending_source_availability_snapshot_count"], 1)
        self.assertEqual(result["hard_missing_snapshot_key_count"], 0)
        self.assertTrue(result["source_availability_tail_open"])


if __name__ == "__main__":
    unittest.main()
