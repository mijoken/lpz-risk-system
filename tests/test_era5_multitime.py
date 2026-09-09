from __future__ import annotations

import unittest

import numpy as np

from lpz_risk.era5_multitime import validate_era5_multitime_payload, build_time_descriptors
from lpz_risk.gfs_science import DecodedField, FieldKey


def _field(short: str, level: int, values, units: str = "%") -> DecodedField:
    arr = np.asarray(values, dtype=float)
    return DecodedField(
        key=FieldKey(short, level),
        units=units,
        values=arr,
        latitudes=np.linspace(32.0, 33.0, arr.size),
        longitudes=np.linspace(130.0, 131.0, arr.size),
        ni=arr.size,
        nj=1,
    )


def _fields(seed: float = 0.0):
    return {
        FieldKey("r", 500): _field("r", 500, [70 + seed, 80 + seed]),
        FieldKey("r", 700): _field("r", 700, [65 + seed, 75 + seed]),
        FieldKey("u", 600): _field("u", 600, [5 + seed, 6 + seed], "m s**-1"),
        FieldKey("v", 600): _field("v", 600, [2 + seed, 3 + seed], "m s**-1"),
        FieldKey("u", 850): _field("u", 850, [8 + seed, 9 + seed], "m s**-1"),
        FieldKey("v", 850): _field("v", 850, [1 + seed, 2 + seed], "m s**-1"),
        FieldKey("q", 1000): _field("q", 1000, [0.014, 0.015], "kg kg**-1"),
        FieldKey("q", 925): _field("q", 925, [0.012, 0.013], "kg kg**-1"),
        FieldKey("q", 850): _field("q", 850, [0.010, 0.011], "kg kg**-1"),
    }


class Era5MultiTimeTest(unittest.TestCase):
    def test_multiple_valid_times_are_kept_independent(self):
        payload = {
            "2023-06-01T20:00:00Z": _fields(0.0),
            "2023-06-01T21:00:00Z": _fields(1.0),
        }
        result = validate_era5_multitime_payload(
            payload,
            ["2023-06-01T20:00:00Z", "2023-06-01T21:00:00Z"],
        )
        self.assertTrue(result["multitime_payload_pass"])
        self.assertEqual(result["decoded_valid_time_count"], 2)
        rows = build_time_descriptors(payload)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(
            rows[0]["environment_descriptors"]["rh500_mean_pct"],
            rows[1]["environment_descriptors"]["rh500_mean_pct"],
        )

    def test_missing_expected_hour_fails(self):
        payload = {"2023-06-01T20:00:00Z": _fields()}
        result = validate_era5_multitime_payload(
            payload,
            ["2023-06-01T20:00:00Z", "2023-06-01T21:00:00Z"],
        )
        self.assertFalse(result["multitime_payload_pass"])
        self.assertEqual(result["missing_valid_times_utc"], ["2023-06-01T21:00:00Z"])


if __name__ == "__main__":
    unittest.main()
