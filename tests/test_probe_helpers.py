from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "acquisition_probe.py"
SPEC = importlib.util.spec_from_file_location("acquisition_probe", SCRIPT)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class ProbeHelperTests(unittest.TestCase):
    def test_parse_jma_compact_is_utc(self) -> None:
        value = probe.parse_jma_compact("20260909065500")
        self.assertEqual(value.tzinfo, timezone.utc)
        self.assertEqual(value.hour, 6)
        self.assertEqual(value.minute, 55)

    def test_lonlat_to_xyz(self) -> None:
        z, x, y = probe.lonlat_to_xyz(135.0, 35.0, 6)
        self.assertEqual(z, 6)
        self.assertTrue(0 <= x < 64)
        self.assertTrue(0 <= y < 64)

    def test_age_seconds_clamps_future_to_zero(self) -> None:
        now = datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc)
        future = datetime(2026, 9, 9, 6, 5, tzinfo=timezone.utc)
        self.assertEqual(probe.age_seconds(future, now), 0)

    def test_latest_compact_row_does_not_assume_sort_order(self) -> None:
        # Regression test for the first Himawari probe: upstream metadata can be
        # ordered oldest -> newest, so rows[0] must never be assumed current.
        rows = [
            {"basetime": "20260907193000", "validtime": "20260907193000"},
            {"basetime": "20260909071500", "validtime": "20260909071500"},
            {"basetime": "20260909072000", "validtime": "20260909072000"},
        ]
        latest = probe.latest_compact_row(rows)
        self.assertEqual(latest["validtime"], "20260909072000")

    def test_gfs_cycle_candidates_descend_by_six_hours(self) -> None:
        now = datetime(2026, 9, 9, 7, 31, tzinfo=timezone.utc)
        cycles = probe.gfs_cycle_candidates(now, count=3)
        self.assertEqual(
            cycles,
            [
                datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 8, 18, 0, tzinfo=timezone.utc),
            ],
        )


if __name__ == "__main__":
    unittest.main()
