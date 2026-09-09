from __future__ import annotations

import json
import unittest
from pathlib import Path

from lpz_risk.evidence import validate_registry


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "research" / "evidence" / "scientific_evidence_registry.json"
REQUIREMENTS = ROOT / "config" / "scientific_variable_requirements.json"


class ScientificEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        cls.requirements = json.loads(REQUIREMENTS.read_text(encoding="utf-8"))

    def test_registry_and_requirements_pass_validation(self) -> None:
        result = validate_registry(self.data, self.requirements)
        self.assertTrue(result.ok, msg="\n".join(result.errors))

    def test_registry_has_initial_paper_set(self) -> None:
        result = validate_registry(self.data, self.requirements)
        self.assertGreaterEqual(result.paper_count, 8)
        self.assertGreaterEqual(result.evidence_count, 15)
        self.assertGreaterEqual(result.requirement_count, 8)

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
        requirement = next(
            x
            for x in self.requirements["requirements"]
            if x["requirement_id"] == "REQ_KATO_FLWV500"
        )
        self.assertTrue(requirement["reproduction_status"].startswith("BLOCKED"))
        self.assertNotEqual(requirement["levels_hpa"], [950])

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

    def test_sreh_does_not_use_precomputed_hlcy_as_exact_substitute(self) -> None:
        requirement = next(
            x
            for x in self.requirements["requirements"]
            if x["requirement_id"] == "REQ_SREH03"
        )
        self.assertNotIn("HLCY", requirement["upstream_parameters"])
        self.assertTrue(requirement["reproduction_status"].startswith("PENDING"))

    def test_iwvf_retains_full_1000_900_pressure_stack(self) -> None:
        requirement = next(
            x
            for x in self.requirements["requirements"]
            if x["requirement_id"] == "REQ_IWVF_1000_900"
        )
        self.assertTrue({1000, 975, 950, 925, 900}.issubset(set(requirement["levels_hpa"])))

    def test_700hpa_vvel_is_not_declared_exact_before_conversion(self) -> None:
        requirement = next(
            x
            for x in self.requirements["requirements"]
            if x["requirement_id"] == "REQ_ASCENT_700"
        )
        self.assertTrue(requirement["reproduction_status"].startswith("PENDING"))


if __name__ == "__main__":
    unittest.main()
