from __future__ import annotations

import json
import unittest
from pathlib import Path

from lpz_risk.historical_policy import (
    validate_hard_negative_policy,
    validate_reconstruction_matrix,
)

ROOT = Path(__file__).resolve().parents[1]


class HistoricalPolicyTest(unittest.TestCase):
    def setUp(self):
        self.matrix = json.loads((ROOT / "config/historical_reconstruction_matrix.json").read_text(encoding="utf-8"))
        self.policy = json.loads((ROOT / "config/hard_negative_policy.json").read_text(encoding="utf-8"))

    def test_current_policies_are_valid(self):
        self.assertEqual(validate_reconstruction_matrix(self.matrix), [])
        self.assertEqual(validate_hard_negative_policy(self.policy), [])

    def test_xrain_cannot_be_marked_available_without_proof(self):
        altered = json.loads(json.dumps(self.matrix))
        altered["sources"]["DIAS_XRAIN_CXMP"]["status"] = "AVAILABLE"
        self.assertTrue(any("XRAIN" in error for error in validate_reconstruction_matrix(altered)))

    def test_high_resolution_feature_cannot_be_opened_prematurely(self):
        altered = json.loads(json.dumps(self.matrix))
        for row in altered["feature_capabilities"]:
            if row["feature_id"] == "multi_frame_parent_tracking":
                row["historical_status"] = "DERIVABLE"
        self.assertTrue(any("high-resolution" in error for error in validate_reconstruction_matrix(altered)))

    def test_random_row_split_is_forbidden(self):
        altered = json.loads(json.dumps(self.policy))
        altered["split_policy"]["no_random_row_split"] = False
        self.assertTrue(any("random row split" in error for error in validate_hard_negative_policy(altered)))

    def test_negative_registry_cannot_be_claimed_built_yet(self):
        altered = json.loads(json.dumps(self.policy))
        altered["negative_registry_built"] = True
        self.assertTrue(any("negative_registry_built" in error for error in validate_hard_negative_policy(altered)))


if __name__ == "__main__":
    unittest.main()
