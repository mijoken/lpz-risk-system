from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from lpz_risk.imerg_final import decode_imerg_final_file, parse_imerg_final_filename


def make_file(tmp_path: Path, version: str = "08") -> Path:
    path = tmp_path / f"3B-HHR.MS.MRG.3IMERG.20250101-S000000-E002959.0000.V{version}B.HDF5"
    with h5py.File(path, "w") as h:
        g = h.create_group("Grid")
        g.create_dataset("lon", data=np.array([139.0, 140.0]))
        g.create_dataset("lat", data=np.array([35.0, 36.0, 37.0]))
        ds = g.create_dataset(
            "precipitation",
            data=np.array([[[1.0, 2.0, 3.0], [4.0, -9999.0, 6.0]]]),
        )
        ds.attrs["units"] = "mm/hr"
        ds.attrs["_FillValue"] = -9999.0
    return path


def test_parse_v08_filename_half_open_interval(tmp_path: Path):
    p = make_file(tmp_path)
    start, end, version = parse_imerg_final_filename(p.name)
    assert version == "08"
    assert start.isoformat() == "2025-01-01T00:00:00+00:00"
    assert end.isoformat() == "2025-01-01T00:30:00+00:00"


def test_decode_v08_transposes_lon_lat_to_canonical_lat_lon(tmp_path: Path):
    p = make_file(tmp_path)
    field = decode_imerg_final_file(p, expected_version="08")
    assert field.source_id == "NASA_IMERG_FINAL_V08"
    assert field.product_version == "08"
    assert field.accumulation_seconds == 1800
    assert field.rain_rate_mm_per_hr.shape == (3, 2)
    assert field.rain_rate_mm_per_hr[0, 0] == 1.0
    assert field.rain_rate_mm_per_hr[2, 1] == 6.0
    assert np.isnan(field.rain_rate_mm_per_hr[1, 1])
    assert field.native_quality["o9_version_mixing_allowed"] is False


def test_v07_payload_is_rejected_when_o9_requires_v08(tmp_path: Path):
    p = make_file(tmp_path, version="07")
    with pytest.raises(ValueError, match="version mismatch"):
        decode_imerg_final_file(p, expected_version="08")


def test_incompatible_payload_schema_fails_before_rebuild(tmp_path: Path):
    p = tmp_path / "3B-HHR.MS.MRG.3IMERG.20250101-S000000-E002959.0000.V08B.HDF5"
    with h5py.File(p, "w") as h:
        h.create_group("Grid")
    with pytest.raises(ValueError, match="missing datasets"):
        decode_imerg_final_file(p, expected_version="08")
