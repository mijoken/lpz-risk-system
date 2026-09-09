from __future__ import annotations

import json
import unittest
from pathlib import Path

from lpz_risk.hard_negative_candidates import build_hard_negative_candidates


def _screen(valid_time: str, code: str, max_mm: float, a80: float, a100: float, a150: float = 0.0):
    return {
        "schema_version": "0.1.0",
        "entity_type": "THREE_HOUR_RAINFALL_SCREENING_RECORD",
        "valid_time_utc": valid_time,
        "primary_subdivision_code": code,
        "source_product": "JMA_ANALYZED_RAINFALL_ANNUAL_1KM",
        "max_accumulation_mm": max_mm,
        "threshold_descriptors": [
            {"threshold_mm": 80.0, "area_km2": a80},
            {"threshold_mm": 100.0, "area_km2": a100},
            {"threshold_mm": 150.0, "area_km2": a150},
        ],
        "hard_negative_label": None,
        "lpz_classification": None,
        "risk_score": None,
    }


class HardNegativeCandidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads(Path("config/hard_negative_candidate_policy.json").read_text(encoding="utf-8"))

    def test_broad_entry_is_intentionally_wide_but_never_final_label(self):
        registry = {"realized_positive_anchors": []}
        records = [
            _screen("2024-07-01T12:00:00Z", "390030", 85.0, 20.0, 0.0),
            _screen("2024-07-01T13:00:00Z", "390030", 70.0, 550.0, 0.0),
            _screen("2024-07-01T14:00:00Z", "390030", 70.0, 100.0, 0.0),
        ]
        result = build_hard_negative_candidates(records, registry, self.policy)
        self.assertEqual(result["broad_candidate_count"], 2)
        self.assertEqual(result["entry_rejected_count"], 1)
        self.assertEqual(result["eligible_unconfirmed_candidate_count"], 2)
        self.assertFalse(result["hard_negative_label_allowed"])
        for row in result["candidates"]:
            self.assertIsNone(row["hard_negative_label"])
            self.assertIsNone(row["risk_score"])

    def test_positive_exclusion_window_blocks_candidate_without_relabeling(self):
        registry = {
            "realized_positive_anchors": [{
                "anchor_id": "A1",
                "analysis_time_utc": "2024-07-01T12:00:00Z",
                "primary_subdivision_code": "390030",
            }]
        }
        records = [
            _screen("2024-07-01T14:30:00Z", "390030", 180.0, 800.0, 600.0, 100.0),
            _screen("2024-07-01T16:00:00Z", "390030", 180.0, 800.0, 600.0, 100.0),
        ]
        result = build_hard_negative_candidates(records, registry, self.policy)
        self.assertEqual(result["broad_candidate_count"], 2)
        self.assertEqual(result["excluded_near_positive_count"], 1)
        statuses = [row["candidate_status"] for row in result["candidates"]]
        self.assertIn("EXCLUDED_NEAR_OFFICIAL_POSITIVE", statuses)
        self.assertIn("UNCONFIRMED_HARD_NEGATIVE_CANDIDATE", statuses)
        self.assertEqual(result["eligible_unconfirmed_candidate_count"], 1)

    def test_strength_tags_are_descriptive_not_labels(self):
        registry = {"realized_positive_anchors": []}
        result = build_hard_negative_candidates([
            _screen("2024-07-01T12:00:00Z", "390030", 160.0, 700.0, 550.0, 10.0)
        ], registry, self.policy)
        row = result["candidates"][0]
        self.assertIn("MAX3H_GE_150", row["strength_tags"])
        self.assertIn("AREA80_GE_500", row["strength_tags"])
        self.assertIn("AREA100_GE_500", row["strength_tags"])
        self.assertIn("RAIN_ONLY_NEAR_OFFICIAL_INTENSITY", row["strength_tags"])
        self.assertIsNone(row["hard_negative_label"])

    def test_policy_must_forbid_final_label(self):
        bad = dict(self.policy)
        bad["hard_negative_label_allowed"] = True
        with self.assertRaises(ValueError):
            build_hard_negative_candidates([], {"realized_positive_anchors": []}, bad)


if __name__ == "__main__":
    unittest.main()
