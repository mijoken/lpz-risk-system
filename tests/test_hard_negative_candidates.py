from __future__ import annotations

import json
import unittest
from pathlib import Path

from lpz_risk.hard_negative_candidates import build_hard_negative_candidates


class HardNegativeCandidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads(Path("config/hard_negative_candidate_policy.json").read_text(encoding="utf-8"))

    def test_zero_cost_policy_blocks_generation_until_satellite_thresholds_are_frozen(self):
        with self.assertRaisesRegex(RuntimeError, "GSMaP/IMERG thresholds are calibrated"):
            build_hard_negative_candidates([], {"realized_positive_anchors": []}, self.policy)

    def test_policy_forbids_reuse_of_jma_1km_thresholds(self):
        self.assertFalse(self.policy["candidate_generation"]["absolute_jma_1km_threshold_rule_enabled"])
        forbidden = set(self.policy["forbidden"])
        self.assertIn("reuse_JMA_1km_80_100_150mm_or_500km2_thresholds_as_satellite_equivalents", forbidden)

    def test_primary_and_secondary_free_sources_are_explicit(self):
        self.assertEqual(self.policy["source_required"], "GSMAP_STANDARD_V8_HISTORICAL")
        self.assertEqual(self.policy["independent_confirmation_source"], "NASA_IMERG_FINAL_V07")

    def test_final_hard_negative_label_remains_forbidden(self):
        self.assertFalse(self.policy["hard_negative_label_allowed"])
        self.assertFalse(self.policy["risk_engine_allowed"])

    def test_bad_policy_cannot_open_final_label(self):
        bad = dict(self.policy)
        bad["hard_negative_label_allowed"] = True
        with self.assertRaises(ValueError):
            build_hard_negative_candidates([], {"realized_positive_anchors": []}, bad)


if __name__ == "__main__":
    unittest.main()
