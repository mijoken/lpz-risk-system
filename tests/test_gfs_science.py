from __future__ import annotations

import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import numpy as np

from lpz_risk.gfs_science import (
    LOW_LEVELS,
    build_science_subset_url,
    cycle_candidates,
    expected_low_ambiguity_keys,
    meteorological_wind_direction_deg,
    specific_humidity_to_mixing_ratio,
    wind_speed,
)


class GfsScienceTests(unittest.TestCase):
    def test_science_url_contains_evidence_driven_variables_and_levels(self) -> None:
        cycle = datetime(2026, 9, 9, 0, tzinfo=timezone.utc)
        url = build_science_subset_url(cycle, forecast_hour=1)
        parsed = urlparse(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        self.assertEqual(query["file"], ["gfs.t00z.pgrb2b.0p25.f001"])
        for variable in ("RH", "SPFH", "UGRD", "VGRD"):
            self.assertEqual(query[f"var_{variable}"], ["on"])
        for level in (*LOW_LEVELS, 850, 700, 600, 500):
            self.assertEqual(query[f"lev_{level}_mb"], ["on"])
        self.assertEqual(query["dir"], ["/gfs.20260909/00/atmos"])

    def test_cycle_candidates_fall_back_by_six_hours(self) -> None:
        now = datetime(2026, 9, 9, 8, 20, tzinfo=timezone.utc)
        cycles = cycle_candidates(now, count=3)
        self.assertEqual([c.hour for c in cycles], [6, 0, 18])
        self.assertEqual(cycles[2].day, 8)

    def test_specific_humidity_to_mixing_ratio(self) -> None:
        out = specific_humidity_to_mixing_ratio(np.array([0.0, 0.01]))
        self.assertAlmostEqual(float(out[0]), 0.0)
        self.assertAlmostEqual(float(out[1]), 0.01 / 0.99)

    def test_specific_humidity_range_guard(self) -> None:
        with self.assertRaises(ValueError):
            specific_humidity_to_mixing_ratio(np.array([1.0]))

    def test_meteorological_direction_from_west(self) -> None:
        direction = meteorological_wind_direction_deg(10.0, 0.0)
        self.assertAlmostEqual(float(direction), 270.0)

    def test_meteorological_direction_from_south(self) -> None:
        direction = meteorological_wind_direction_deg(0.0, 10.0)
        self.assertAlmostEqual(float(direction), 180.0)

    def test_wind_speed(self) -> None:
        speed = wind_speed(3.0, 4.0)
        self.assertAlmostEqual(float(speed), 5.0)

    def test_expected_key_set_is_complete(self) -> None:
        keys = expected_low_ambiguity_keys()
        self.assertEqual(len(keys), 21)
        self.assertTrue(all(any(k.short_name == name for k in keys) for name in ("r", "q", "u", "v")))


if __name__ == "__main__":
    unittest.main()
