from __future__ import annotations

import unittest

import numpy as np

from lpz_risk.gfs_science import FieldKey, DecodedField
from lpz_risk.era5_science import validate_era5_required_fields, era5_environment_descriptors


def _field(short: str, level: int, values) -> DecodedField:
    arr = np.asarray(values, dtype=float)
    lat = np.linspace(32.0, 33.0, arr.size)
    lon = np.linspace(130.0, 131.0, arr.size)
    return DecodedField(FieldKey(short, level), "%", arr, lat, lon, arr.size, 1)


def _complete_fields():
    fields = {
        FieldKey("r", 500): _field("r", 500, [70, 50, 80]),
        FieldKey("r", 700): _field("r", 700, [70, 70, 50]),
        FieldKey("u", 600): _field("u", 600, [5, 5, 5]),
        FieldKey("v", 600): _field("v", 600, [-5, -5, -5]),
        FieldKey("u", 850): _field("u", 850, [10, 10, 10]),
        FieldKey("v", 850): _field("v", 850, [0, 0, 0]),
        FieldKey("q", 1000): _field("q", 1000, [0.012, 0.013, 0.014]),
        FieldKey("q", 925): _field("q", 925, [0.010, 0.011, 0.012]),
        FieldKey("q", 850): _field("q", 850, [0.008, 0.009, 0.010]),
    }
    return fields


class Era5ScienceTest(unittest.TestCase):
    def test_required_field_gate_passes_complete_set(self):
        result = validate_era5_required_fields(_complete_fields())
        self.assertTrue(result["required_fields_pass"])
        self.assertEqual(result["source"], "ERA5")
        self.assertEqual(result["exactness"], "PROXY_REANALYSIS")

    def test_missing_required_field_fails(self):
        fields = _complete_fields()
        del fields[FieldKey("q", 925)]
        result = validate_era5_required_fields(fields)
        self.assertFalse(result["required_fields_pass"])
        self.assertIn("q@925", result["missing_required_fields"])

    def test_environment_descriptor_keeps_proxy_semantics(self):
        desc = era5_environment_descriptors(_complete_fields())
        self.assertEqual(desc["source"], "ERA5")
        self.assertEqual(desc["exactness"], "PROXY_REANALYSIS")
        self.assertEqual(desc["grid_points"], 3)
        self.assertAlmostEqual(desc["rh500_rh700_gt60_fraction"], 1 / 3)
        self.assertEqual(desc["spatial_semantics"], "REQUEST_BBOX_CONTEXT_NOT_SUBDIVISION_POLYGON_MEAN")
        self.assertIsNone(desc["risk_score"])


if __name__ == "__main__":
    unittest.main()
