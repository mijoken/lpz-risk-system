from __future__ import annotations

import json
import unittest
from pathlib import Path

from lpz_risk.historical_rainfall_source import validate_historical_rainfall_source_registry


class HistoricalRainfallSourceTest(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(Path("config/historical_rainfall_sources.json").read_text(encoding="utf-8"))

    def test_frozen_registry_is_valid(self):
        report = validate_historical_rainfall_source_registry(self.config)
        self.assertTrue(report["execution_ok"], report["failures"])
        self.assertFalse(report["hard_negative_label_allowed"])
        self.assertFalse(report["risk_engine_allowed"])

    def test_public_machine_download_cannot_be_assumed(self):
        cfg = json.loads(json.dumps(self.config))
        for row in cfg["sources"]:
            if row["source_id"] == "JMA_ANALYZED_RAINFALL_ANNUAL_2017_PLUS":
                row["machine_public_web_download_assumed"] = True
        report = validate_historical_rainfall_source_registry(cfg)
        self.assertFalse(report["execution_ok"])

    def test_hard_negative_gate_cannot_open_before_payload(self):
        cfg = json.loads(json.dumps(self.config))
        cfg["hard_negative_label_allowed"] = True
        report = validate_historical_rainfall_source_registry(cfg)
        self.assertFalse(report["execution_ok"])


if __name__ == "__main__":
    unittest.main()
