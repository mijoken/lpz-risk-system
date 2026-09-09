from __future__ import annotations

import unittest

import numpy as np

from lpz_risk.historical_rainfall import (
    accumulate_three_hour,
    accumulation_descriptors,
    build_three_hour_screening_record,
)


class HistoricalRainfallTest(unittest.TestCase):
    def test_three_hour_sum_is_exact(self):
        fields = [np.full((2, 2), 10.0), np.full((2, 2), 20.0), np.full((2, 2), 30.0)]
        out = accumulate_three_hour(fields)
        np.testing.assert_allclose(out, np.full((2, 2), 60.0))

    def test_descriptor_area_is_not_a_label(self):
        field = np.zeros((30, 30), dtype=float)
        field[:25, :25] = 105.0
        desc = accumulation_descriptors(field, cell_area_km2=1.0)
        row100 = next(x for x in desc["threshold_descriptors"] if x["threshold_mm"] == 100.0)
        self.assertEqual(row100["cell_count"], 625)
        self.assertEqual(row100["area_km2"], 625.0)
        self.assertTrue(row100["area_ge_500km2"])
        self.assertIsNone(desc["hard_negative_label"])
        self.assertIsNone(desc["lpz_classification"])
        self.assertIsNone(desc["risk_score"])

    def test_variable_cell_area_supported(self):
        field = np.array([[100.0, 0.0], [100.0, 0.0]])
        area = np.array([[2.0, 2.0], [3.0, 3.0]])
        desc = accumulation_descriptors(field, cell_area_km2=area)
        row100 = next(x for x in desc["threshold_descriptors"] if x["threshold_mm"] == 100.0)
        self.assertEqual(row100["area_km2"], 5.0)

    def test_invalid_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            accumulate_three_hour([np.zeros((2, 2)), np.zeros((2, 2))])
        with self.assertRaises(ValueError):
            accumulate_three_hour([np.zeros((2, 2)), np.zeros((3, 3)), np.zeros((2, 2))])
        with self.assertRaises(ValueError):
            accumulation_descriptors(np.array([[np.nan]]), cell_area_km2=1.0)

    def test_screening_record_provenance(self):
        fields = [np.full((2, 2), 40.0), np.full((2, 2), 40.0), np.full((2, 2), 40.0)]
        row = build_three_hour_screening_record(
            fields,
            cell_area_km2=1.0,
            valid_time_utc="2025-08-10T03:00:00Z",
            primary_subdivision_code="400010",
        )
        self.assertEqual(row["source_product"], "JMA_ANALYZED_RAINFALL_ANNUAL_1KM")
        self.assertEqual(row["max_accumulation_mm"], 120.0)
        self.assertIsNone(row["hard_negative_label"])


if __name__ == "__main__":
    unittest.main()
