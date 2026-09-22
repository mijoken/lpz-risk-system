from __future__ import annotations

import numpy as np

from scripts.audit_f4_20260921_imerg_late_3h import summarize


def test_imerg_late_3h_summary_detects_connected_high_accumulation_area():
    lat=np.array([36.65,36.75,36.85,36.95,37.05],dtype=float)
    lon=np.array([141.0,141.1,141.2,141.3,141.4,141.5],dtype=float)
    accum=np.full((lat.size,lon.size),20.0,dtype=float)
    accum[1:4,1:5]=110.0
    accum[2,3]=170.0

    out=summarize(accum,lon,lat)
    assert out["max_3h_mm"]==170.0
    assert out["source_native_threshold_descriptors_mm"]["100"]["cell_count"]==12
    largest=out["source_native_threshold_descriptors_mm"]["100"]["largest_component"]
    assert largest is not None
    assert largest["cell_count"]==12
    assert largest["area_km2"]>500.0
    assert out["source_native_threshold_descriptors_mm"]["150"]["cell_count"]==1


def test_imerg_late_3h_summary_respects_nan_cells():
    lat=np.array([37.0,37.1],dtype=float)
    lon=np.array([142.0,142.1],dtype=float)
    accum=np.array([[np.nan,80.0],[100.0,150.0]],dtype=float)
    out=summarize(accum,lon,lat)
    assert out["valid_cell_count"]==3
    assert out["max_3h_mm"]==150.0
    assert out["source_native_threshold_descriptors_mm"]["100"]["cell_count"]==2
