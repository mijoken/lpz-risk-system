from __future__ import annotations

import json
import unittest
from pathlib import Path

from lpz_risk.evidence import validate_registry


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "research" / "evidence" / "scientific_evidence_registry.json"


class ScientificEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(REGISTRY.read_text(encoding="utf-8"))

    def test_registry_passes_validation(self) -> None:
        result = validate_registry(self.data)
        self.assertTrue(result.ok, msg="\n".join(result.errors))

    def test_registry_has_initial_paper_set(self) -> None:
        result = validate_registry(self.data)
        self.assertGreaterEqual(result.paper_count, 8)
        self.assertGreaterEqual(result.evidence_count, 15)

    def test_six_conditions_are_not_operational_binary_gate(self) -> None:
        item = next(
            x
            for x in self.data["evidence_items"]
            if x["evidence_id"] == "TAHARA2026_SIX_CONDITION_COVERAGE"
        )
        self.assertEqual(item["implementation_status"], "RESEARCH_ONLY")

    def test_flwv500_not_falsely_claimed_exact_from_gfs(self) -> None:
        item = next(
            x
            for x in self.data["evidence_items"]
            if x["evidence_id"] == "KATO2020_FLWV500"
        )
        self.assertTrue(item["implementation_status"].startswith("BLOCKED"))

    def test_orientation_feature_requires_both_radar_and_600hpa_wind(self) -> None:
        item = next(
            x
            for x in self.data["evidence_items"]
            if x["evidence_id"] == "SHIMAMURA2025_ORIENTATION600"
        )
        required = set(item["required_variables"])
        self.assertIn("rainband_major_axis_orientation", required)
        self.assertIn("u_wind_600hpa", required)
        self.assertIn("v_wind_600hpa", required)


if __name__ == "__main__":
    unittest.main()
