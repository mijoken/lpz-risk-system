from __future__ import annotations

import gzip
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import h5py
import numpy as np

from lpz_risk.canonical_rainfall import CanonicalRainfallField, integrate_consecutive_fields
from lpz_risk.gsmap_v8 import (
    EXPECTED_UNCOMPRESSED_BYTES,
    LAT,
    LON,
    decode_gsmap_gauge_v8_bytes,
)
from lpz_risk.imerg_v07 import decode_imerg_final_v07_file


class CanonicalRainfallTest(unittest.TestCase):
    def _field(self, source: str, start: datetime, seconds: int, rate: float) -> CanonicalRainfallField:
        return CanonicalRainfallField(
            source_id=source,
            product_version="x",
            valid_start_utc=start,
            valid_end_utc=start + timedelta(seconds=seconds),
            accumulation_seconds=seconds,
            rain_rate_mm_per_hr=np.full((2, 3), rate),
            longitude_deg_e=np.array([130.0, 130.1, 130.2]),
            latitude_deg_n=np.array([35.1, 35.0]),
            gauge_adjusted=True,
            source_path="synthetic",
        )

    def test_native_interval_integration(self):
        t = datetime(2025, 1, 1, tzinfo=timezone.utc)
        hourly = self._field("A", t, 3600, 10.0)
        self.assertTrue(np.allclose(hourly.accumulation_mm, 10.0))
        halfhour = self._field("A", t, 1800, 10.0)
        self.assertTrue(np.allclose(halfhour.accumulation_mm, 5.0))

    def test_consecutive_integral_and_cross_source_block(self):
        t = datetime(2025, 1, 1, tzinfo=timezone.utc)
        fs = [self._field("A", t + timedelta(minutes=30 * i), 1800, 2.0) for i in range(6)]
        self.assertTrue(np.allclose(integrate_consecutive_fields(fs), 6.0))
        mixed = fs[:]
        mixed[-1] = self._field("B", t + timedelta(minutes=150), 1800, 2.0)
        with self.assertRaisesRegex(ValueError, "cross-source"):
            integrate_consecutive_fields(mixed)

    def test_gap_blocked(self):
        t = datetime(2025, 1, 1, tzinfo=timezone.utc)
        fs = [self._field("A", t, 1800, 1.0), self._field("A", t + timedelta(hours=1), 1800, 1.0)]
        with self.assertRaisesRegex(ValueError, "exactly consecutive"):
            integrate_consecutive_fields(fs)


class GsmapV8Test(unittest.TestCase):
    def test_official_binary_geometry_and_missing(self):
        # Full official 4,320,000-cell payload; compresses very small because mostly zero.
        a = np.zeros((1200, 3600), dtype="<f4")
        a[0, 0] = 1.25
        a[0, 1] = -4.0
        a[-1, -1] = 9.5
        raw = a.tobytes(order="C")
        self.assertEqual(len(raw), EXPECTED_UNCOMPRESSED_BYTES)
        payload = gzip.compress(raw)
        f = decode_gsmap_gauge_v8_bytes(
            payload,
            filename="gsmap_gauge.20230101.0000.v8.0000.0.dat.gz",
        )
        self.assertEqual(f.rain_rate_mm_per_hr.shape, (1200, 3600))
        self.assertEqual(float(f.rain_rate_mm_per_hr[0, 0]), 1.25)
        self.assertTrue(np.isnan(f.rain_rate_mm_per_hr[0, 1]))
        self.assertEqual(float(f.rain_rate_mm_per_hr[-1, -1]), 9.5)
        self.assertAlmostEqual(float(LON[0]), 0.05)
        self.assertAlmostEqual(float(LON[-1]), 359.95)
        self.assertAlmostEqual(float(LAT[0]), 59.95)
        self.assertAlmostEqual(float(LAT[-1]), -59.95)
        self.assertEqual(f.accumulation_seconds, 3600)
        self.assertEqual(f.valid_end_utc - f.valid_start_utc, timedelta(hours=1))

    def test_wrong_size_fails(self):
        with self.assertRaisesRegex(ValueError, "byte count"):
            decode_gsmap_gauge_v8_bytes(
                gzip.compress(b"\x00" * 16),
                filename="gsmap_gauge.20230101.0000.v8.0000.0.dat.gz",
            )


class ImergV07Test(unittest.TestCase):
    def test_hdf_lon_lat_transpose_and_halfhour_integration(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "3B-HHR.MS.MRG.3IMERG.20250701-S000000-E002959.0000.V07B.HDF5"
            with h5py.File(p, "w") as h:
                g = h.create_group("Grid")
                g.create_dataset("lon", data=np.array([130.05, 130.15], dtype=np.float32))
                g.create_dataset("lat", data=np.array([34.95, 35.05, 35.15], dtype=np.float32))
                d = g.create_dataset(
                    "precipitation",
                    data=np.array([[[1.0, 2.0, 3.0], [4.0, -9999.9, 6.0]]], dtype=np.float32),
                )
                d.attrs["units"] = "mm/hr"
                d.attrs["_FillValue"] = np.float32(-9999.9)
            f = decode_imerg_final_v07_file(p)
            self.assertEqual(f.rain_rate_mm_per_hr.shape, (3, 2))
            self.assertEqual(float(f.rain_rate_mm_per_hr[0, 0]), 1.0)
            self.assertEqual(float(f.rain_rate_mm_per_hr[0, 1]), 4.0)
            self.assertTrue(np.isnan(f.rain_rate_mm_per_hr[1, 1]))
            self.assertEqual(f.accumulation_seconds, 1800)
            self.assertAlmostEqual(float(f.accumulation_mm[0, 0]), 0.5)


if __name__ == "__main__":
    unittest.main()
