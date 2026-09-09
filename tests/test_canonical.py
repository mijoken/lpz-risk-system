from __future__ import annotations

import math
import unittest

from lpz_risk.canonical import (
    degrees_minutes_to_decimal,
    jma_wind_direction_degrees,
    meteorological_wind_to_uv,
    normalize_amedas_station,
)


class CanonicalTests(unittest.TestCase):
    def test_degrees_minutes_to_decimal(self) -> None:
        self.assertAlmostEqual(degrees_minutes_to_decimal([35, 30.0]), 35.5)
        self.assertAlmostEqual(degrees_minutes_to_decimal([139, 45.0]), 139.75)

    def test_jma_wind_direction_codes(self) -> None:
        self.assertIsNone(jma_wind_direction_degrees(0))
        self.assertEqual(jma_wind_direction_degrees(2), 45.0)
        self.assertEqual(jma_wind_direction_degrees(8), 180.0)
        self.assertEqual(jma_wind_direction_degrees(16), 0.0)

    def test_meteorological_wind_from_north_moves_south(self) -> None:
        u, v = meteorological_wind_to_uv(10.0, 0.0)
        self.assertAlmostEqual(u or 0.0, 0.0, places=8)
        self.assertAlmostEqual(v or 0.0, -10.0, places=8)

    def test_meteorological_wind_from_west_moves_east(self) -> None:
        u, v = meteorological_wind_to_uv(10.0, 270.0)
        self.assertAlmostEqual(u or 0.0, 10.0, places=8)
        self.assertAlmostEqual(v or 0.0, 0.0, places=8)

    def test_normalize_amedas_station(self) -> None:
        observation = {
            "temp": [27.1, 0],
            "humidity": [81, 0],
            "precipitation1h": [12.5, 0],
            "wind": [8.0, 0],
            "windDirection": [8, 0],
        }
        meta = {
            "lat": [35, 30.0],
            "lon": [139, 45.0],
            "alt": 5,
            "kjName": "試験地点",
            "enName": "Test Station",
        }
        row = normalize_amedas_station("99999", observation, meta, "2026-09-09T07:20:00Z")
        self.assertEqual(row.station_id, "99999")
        self.assertAlmostEqual(row.latitude_deg or 0, 35.5)
        self.assertAlmostEqual(row.longitude_deg or 0, 139.75)
        self.assertEqual(row.wind_direction_deg_from, 180.0)
        self.assertAlmostEqual(row.wind_u_ms or 0, 0.0, places=8)
        self.assertAlmostEqual(row.wind_v_ms or 0, 8.0, places=8)
        self.assertEqual(row.qc["wind"], 0)


if __name__ == "__main__":
    unittest.main()
