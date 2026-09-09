from __future__ import annotations

import unittest

from lpz_risk.precipitation_source_policy import select_precipitation_source, source_disagreement_record


class PrecipitationSourcePolicyTest(unittest.TestCase):
    def test_primary_wins_when_available(self):
        r = select_precipitation_source({
            "JMA_ANALYZED_RAINFALL_HISTORICAL": True,
            "GSMAP_HISTORICAL": True,
            "NOAA_CMORPH_CDR": True,
        })
        self.assertEqual(r["selected_source_id"], "JMA_ANALYZED_RAINFALL_HISTORICAL")
        self.assertFalse(r["backup_used"])
        self.assertIsNone(r["risk_score"])

    def test_gsmap_is_explicit_backup(self):
        r = select_precipitation_source({
            "JMA_ANALYZED_RAINFALL_HISTORICAL": False,
            "GSMAP_HISTORICAL": True,
            "NOAA_CMORPH_CDR": True,
        })
        self.assertEqual(r["selected_source_id"], "GSMAP_HISTORICAL")
        self.assertTrue(r["backup_used"])

    def test_cmorph_is_secondary_backup(self):
        r = select_precipitation_source({"NOAA_CMORPH_CDR": True})
        self.assertEqual(r["selected_source_id"], "NOAA_CMORPH_CDR")

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
