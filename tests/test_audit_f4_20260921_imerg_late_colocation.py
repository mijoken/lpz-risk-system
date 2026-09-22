from __future__ import annotations

import numpy as np

from scripts.audit_f4_20260921_imerg_late_colocation import (
    component_overlap,
    overlap_summary,
)


def test_overlap_summary_detects_thresholds_only_inside_f4_touched_cells():
    lon=np.array([142.0,142.1,142.2,142.3],dtype=float)
    lat=np.array([37.0,37.1,37.2],dtype=float)
    accum=np.array([
        [10.0,55.0,70.0,10.0],
        [20.0,85.0,120.0,20.0],
        [30.0,45.0,160.0,30.0],
    ])
    touched=np.array([1,2,5,6],dtype=np.int64)
    out=overlap_summary(accum,lon,lat,touched)
    assert out["touched_native_cell_count"]==4
    assert out["threshold_overlap"]["50"]["overlap_native_cell_count"]==4
    assert out["threshold_overlap"]["80"]["overlap_native_cell_count"]==2
    assert out["threshold_overlap"]["100"]["overlap_native_cell_count"]==1
    assert out["threshold_overlap"]["150"]["overlap_native_cell_count"]==0


def test_component_overlap_marks_only_component_touched_by_f4():
    lon=np.array([142.0,142.1,142.2,142.3],dtype=float)
    lat=np.array([37.0,37.1,37.2],dtype=float)
    accum=np.array([
        [60.0,60.0,0.0,0.0],
        [60.0,60.0,0.0,70.0],
        [0.0,0.0,0.0,70.0],
    ])
    # Touch only the left 2x2 >=50 component.
    touched=np.array([0,1,4,5],dtype=np.int64)
    comps=component_overlap(accum,lon,lat,touched,50.0)
    assert len(comps)==2
    intersecting=[x for x in comps if x["spatially_intersects_f4_mask"]]
    assert len(intersecting)==1
    assert intersecting[0]["f4_touched_native_cell_count"]==4
    assert max(x["area_km2"] for x in comps)>0
