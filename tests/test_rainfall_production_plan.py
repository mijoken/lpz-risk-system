from __future__ import annotations

import unittest

from lpz_risk.rainfall_production_plan import build_development_rainfall_production_plan


class RainfallProductionPlanTest(unittest.TestCase):
    def _manifest(self):
        return {
            "split": "DEVELOPMENT",
            "future_interval_count": 0,
            "candidate_threshold_selected": False,
            "windows": [
                {
                    "window_id": "g1",
                    "source_id": "GSMAP_STANDARD_V8_HISTORICAL",
                    "primary_subdivision_code": "A",
                    "window_start_utc": "2023-01-01T00:00:00Z",
                    "window_end_utc": "2023-01-01T03:00:00Z",
                    "native_interval_seconds": 3600,
                    "native_field_count": 3,
                },
                {
                    "window_id": "g2",
                    "source_id": "GSMAP_STANDARD_V8_HISTORICAL",
                    "primary_subdivision_code": "B",
                    "window_start_utc": "2023-01-01T00:00:00Z",
                    "window_end_utc": "2023-01-01T03:00:00Z",
                    "native_interval_seconds": 3600,
                    "native_field_count": 3,
                },
                {
                    "window_id": "c1",
                    "source_id": "NOAA_CMORPH_CDR",
                    "primary_subdivision_code": "A",
                    "window_start_utc": "2023-01-01T00:00:00Z",
                    "window_end_utc": "2023-01-01T03:00:00Z",
                    "native_interval_seconds": 1800,
                    "native_field_count": 6,
                },
            ],
        }

    def test_payloads_are_deduplicated_across_polygons(self):
        out = build_development_rainfall_production_plan(self._manifest())
        gs = next(x for x in out["source_summary"] if x["source_id"] == "GSMAP_STANDARD_V8_HISTORICAL")
        self.assertEqual(gs["unique_window_count"], 2)
        self.assertEqual(gs["unique_native_field_count"], 3)
        self.assertEqual(gs["unique_payload_count"], 3)
        self.assertFalse(out["risk_engine_allowed"])
        self.assertFalse(out["candidate_threshold_selected"])

    def test_cmorph_two_halfhours_share_one_hourly_payload(self):
        out = build_development_rainfall_production_plan(self._manifest())
        cm = next(x for x in out["source_summary"] if x["source_id"] == "NOAA_CMORPH_CDR")
        self.assertEqual(cm["unique_native_field_count"], 6)
        self.assertEqual(cm["unique_payload_count"], 3)

    def test_non_development_manifest_is_rejected(self):
        m = self._manifest()
        m["split"] = "VALIDATION"
        with self.assertRaisesRegex(ValueError, "DEVELOPMENT"):
            build_development_rainfall_production_plan(m)

    def test_future_interval_manifest_is_rejected(self):
        m = self._manifest()
        m["future_interval_count"] = 1
        with self.assertRaisesRegex(ValueError, "future"):
            build_development_rainfall_production_plan(m)


if __name__ == "__main__":
    unittest.main()
