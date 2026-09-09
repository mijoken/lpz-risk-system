from __future__ import annotations

import json
import unittest
from pathlib import Path

from lpz_risk.historical_episodes import assign_temporal_split, build_local_positive_episodes


class HistoricalEpisodesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads(Path("config/historical_split_policy.json").read_text(encoding="utf-8"))

    def test_split_assignments_and_non_pristine_2026(self):
        self.assertEqual(assign_temporal_split("2024-07-01T12:00:00+09:00", self.policy), "DEVELOPMENT")
        self.assertEqual(assign_temporal_split("2025-07-01T12:00:00+09:00", self.policy), "VALIDATION")
        self.assertEqual(assign_temporal_split("2026-07-01T12:00:00+09:00", self.policy), "RETROSPECTIVE_TEST_NON_PRISTINE")
        self.assertEqual(assign_temporal_split("2026-09-11T12:00:00+09:00", self.policy), "PROSPECTIVE_HOLDOUT")
        self.assertFalse(self.policy["retrospective_2026_pristine"])

    def test_boundary_embargo(self):
        self.assertEqual(assign_temporal_split("2025-01-01T02:00:00+09:00", self.policy), "BOUNDARY_EMBARGO")
        self.assertEqual(assign_temporal_split("2026-09-10T02:00:00+09:00", self.policy), "BOUNDARY_EMBARGO")

    def test_local_episode_groups_only_same_code_and_short_gaps(self):
        registry = {
            "realized_positive_anchors": [
                {"anchor_id": "A1", "primary_subdivision_code": "390030", "analysis_time_utc": "2024-07-01T03:00:00Z", "analysis_time_jst": "2024-07-01T12:00:00+09:00"},
                {"anchor_id": "A2", "primary_subdivision_code": "390030", "analysis_time_utc": "2024-07-01T03:10:00Z", "analysis_time_jst": "2024-07-01T12:10:00+09:00"},
                {"anchor_id": "A3", "primary_subdivision_code": "390030", "analysis_time_utc": "2024-07-01T03:40:00Z", "analysis_time_jst": "2024-07-01T12:40:00+09:00"},
                {"anchor_id": "B1", "primary_subdivision_code": "390040", "analysis_time_utc": "2024-07-01T03:10:00Z", "analysis_time_jst": "2024-07-01T12:10:00+09:00"},
            ]
        }
        result = build_local_positive_episodes(registry, self.policy)
        self.assertEqual(result["realized_positive_anchor_count"], 4)
        self.assertEqual(result["local_episode_count"], 3)
        counts = sorted(row["anchor_count"] for row in result["episodes"])
        self.assertEqual(counts, [1, 1, 2])
        self.assertFalse(result["cross_subdivision_episode_grouping_complete"])
        self.assertFalse(result["risk_engine_allowed"])

    def test_random_row_split_policy_cannot_be_enabled(self):
        policy = json.loads(json.dumps(self.policy))
        policy["random_row_split_allowed"] = True
        with self.assertRaises(ValueError):
            build_local_positive_episodes({"realized_positive_anchors": []}, policy)


if __name__ == "__main__":
    unittest.main()
