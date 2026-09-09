from datetime import datetime, timedelta, timezone
import unittest

import numpy as np

from lpz_risk.canonical_rainfall import CanonicalRainfallField
from lpz_risk.historical_rainfall_window import (
    build_exact_accumulation_window,
    build_subdivision_window_descriptor,
)
from lpz_risk.rainfall_calibration import summarize_development_metric


def _field(source: str, start: datetime, seconds: int, value: float, path: str) -> CanonicalRainfallField:
    return CanonicalRainfallField(
        source_id=source,
        product_version="vtest",
        valid_start_utc=start,
        valid_end_utc=start + timedelta(seconds=seconds),
        accumulation_seconds=seconds,
        rain_rate_mm_per_hr=np.full((2, 2), value, dtype=float),
        longitude_deg_e=np.array([130.0, 131.0]),
        latitude_deg_n=np.array([32.0, 33.0]),
        gauge_adjusted=True,
        source_path=path,
    )


def _feature() -> dict:
    return {
        "type": "Feature",
        "id": "999999",
        "properties": {"primary_subdivision_code": "999999"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[129.5, 31.5], [131.5, 31.5], [131.5, 33.5], [129.5, 33.5], [129.5, 31.5]]],
        },
    }


class HistoricalRainfallWindowTest(unittest.TestCase):
    def test_three_hour_hourly_window_integrates_exactly(self):
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        fields = [_field("GSMAP", t0 + timedelta(hours=i), 3600, 10.0, f"g{i}") for i in range(3)]
        window = build_exact_accumulation_window(fields)
        self.assertEqual(window.native_field_count, 3)
        self.assertEqual(window.accumulation_seconds, 10800)
        self.assertTrue(np.allclose(window.accumulation_mm, 30.0))

    def test_three_hour_half_hour_window_integrates_exactly(self):
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        fields = [_field("IMERG", t0 + timedelta(minutes=30 * i), 1800, 10.0, f"i{i}") for i in range(6)]
        window = build_exact_accumulation_window(fields)
        self.assertEqual(window.native_field_count, 6)
        self.assertTrue(np.allclose(window.accumulation_mm, 30.0))

    def test_cross_source_window_rejected(self):
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        fields = [
            _field("GSMAP", t0, 3600, 1.0, "a"),
            _field("IMERG", t0 + timedelta(hours=1), 3600, 1.0, "b"),
            _field("GSMAP", t0 + timedelta(hours=2), 3600, 1.0, "c"),
        ]
        with self.assertRaisesRegex(ValueError, "cross-source"):
            build_exact_accumulation_window(fields)

    def test_wrong_duration_rejected(self):
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        fields = [_field("GSMAP", t0 + timedelta(hours=i), 3600, 1.0, str(i)) for i in range(2)]
        with self.assertRaisesRegex(ValueError, "exact target duration"):
            build_exact_accumulation_window(fields)

    def test_polygon_descriptor_is_descriptive_only(self):
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        fields = [_field("GSMAP", t0 + timedelta(hours=i), 3600, float(i + 1), str(i)) for i in range(3)]
        window = build_exact_accumulation_window(fields)
        d = build_subdivision_window_descriptor(
            window,
            primary_subdivision_code="999999",
            polygon_feature=_feature(),
            descriptive_thresholds_mm=[5.0, 10.0],
        )
        self.assertEqual(d["polygon_grid_cell_count"], 4)
        self.assertEqual(d["finite_grid_cell_count"], 4)
        self.assertAlmostEqual(d["max_accumulation_mm"], 6.0)
        self.assertFalse(d["candidate_threshold_selected"])
        self.assertIsNone(d["hard_negative_label"])
        self.assertFalse(d["risk_engine_allowed"])

    def test_development_calibration_keeps_sources_separate(self):
        records = [
            {"split": "DEVELOPMENT", "source_id": "GSMAP", "max_accumulation_mm": 10.0},
            {"split": "DEVELOPMENT", "source_id": "GSMAP", "max_accumulation_mm": 20.0},
            {"split": "DEVELOPMENT", "source_id": "IMERG", "max_accumulation_mm": 30.0},
        ]
        out = summarize_development_metric(records, metric="max_accumulation_mm")
        self.assertEqual([x["source_id"] for x in out["sources"]], ["GSMAP", "IMERG"])
        self.assertFalse(out["cross_source_averaging_performed"])
        self.assertEqual(out["threshold_selection_status"], "NOT_SELECTED_DESCRIPTIVE_DISTRIBUTION_ONLY")

    def test_validation_leakage_is_rejected(self):
        records = [{"split": "VALIDATION", "source_id": "GSMAP", "max_accumulation_mm": 10.0}]
        with self.assertRaisesRegex(ValueError, "non-DEVELOPMENT"):
            summarize_development_metric(records, metric="max_accumulation_mm")


if __name__ == "__main__":
    unittest.main()
