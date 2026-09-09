from __future__ import annotations

import unittest

from lpz_risk.precipitation_source_policy import (
    select_precipitation_source,
    source_disagreement_record,
    validate_zero_cost_required_sources,
)


class PrecipitationSourcePolicyTest(unittest.TestCase):
    def test_gsmap_is_free_primary(self):
        r = select_precipitation_source({
            "GSMAP_STANDARD_V8_HISTORICAL": True,
            "NASA_IMERG_FINAL_V07": True,
            "NOAA_CMORPH_CDR": True,
            "ERA5_LAND_TOTAL_PRECIPITATION": True,
        })
        self.assertEqual(r["selected_source_id"], "GSMAP_STANDARD_V8_HISTORICAL")
        self.assertFalse(r["backup_used"])
        self.assertFalse(r["jma_1km_threshold_reuse_allowed"])
        self.assertIsNone(r["risk_score"])

    def test_imerg_is_secondary_free_source(self):
        r = select_precipitation_source({
            "GSMAP_STANDARD_V8_HISTORICAL": False,
            "NASA_IMERG_FINAL_V07": True,
            "NOAA_CMORPH_CDR": True,
        })
        self.assertEqual(r["selected_source_id"], "NASA_IMERG_FINAL_V07")
        self.assertTrue(r["backup_used"])

    def test_cmorph_is_tertiary_backup(self):
        r = select_precipitation_source({"NOAA_CMORPH_CDR": True})
        self.assertEqual(r["selected_source_id"], "NOAA_CMORPH_CDR")

    def test_era5_land_is_last_resort(self):
        r = select_precipitation_source({"ERA5_LAND_TOTAL_PRECIPITATION": True})
        self.assertEqual(r["selected_source_id"], "ERA5_LAND_TOTAL_PRECIPITATION")

    def test_paid_jma_media_cannot_be_required(self):
        r = validate_zero_cost_required_sources([
            "GSMAP_STANDARD_V8_HISTORICAL",
            "JMA_ANALYZED_RAINFALL_HISTORICAL_PAID_MEDIA",
        ])
        self.assertFalse(r["zero_cost_policy_pass"])
        self.assertEqual(
            r["prohibited_required_source_ids"],
            ["JMA_ANALYZED_RAINFALL_HISTORICAL_PAID_MEDIA"],
        )

    def test_free_stack_passes_zero_cost_gate(self):
        r = validate_zero_cost_required_sources([
            "GSMAP_STANDARD_V8_HISTORICAL",
            "NASA_IMERG_FINAL_V07",
            "NOAA_CMORPH_CDR",
            "ERA5_LAND_TOTAL_PRECIPITATION",
        ])
        self.assertTrue(r["zero_cost_policy_pass"])
        self.assertEqual(r["prohibited_required_source_ids"], [])
        self.assertEqual(r["unknown_required_source_ids"], [])

    def test_disagreement_is_diagnostic_not_average(self):
        r = source_disagreement_record(primary_value_mm=100.0, backup_value_mm=80.0)
        self.assertTrue(r["comparison_available"])
        self.assertEqual(r["difference_mm"], -20.0)
        self.assertEqual(r["absolute_difference_mm"], 20.0)
        self.assertAlmostEqual(r["ratio_backup_to_primary"], 0.8)
        self.assertEqual(r["comparison_semantics"], "DIAGNOSTIC_ONLY_NOT_SOURCE_AVERAGING")
        self.assertIsNone(r["risk_score"])


if __name__ == "__main__":
    unittest.main()
