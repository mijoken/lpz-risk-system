#!/usr/bin/env python3
"""IMERG C-1 scientific content audit (research only).

Inspects one already-downloaded GPM_3IMERGHHE V07 HDF5 file. No network access,
no downloads, no production writes, and no Risk Engine integration.

Default input directory is the C-0 output directory. If --input is omitted, the
newest *.HDF5/*.h5/*.hdf5 file there is selected.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import h5py
import numpy as np

DEFAULT_DIR = Path("reports/gap_recovery/c0_imerg")
DEFAULT_OUT = Path("reports/gap_recovery/c1_imerg_scientific_audit.json")
# Broad Japan domain for a first scientific sanity check; not a production mask.
JAPAN_BBOX = (122.0, 146.0, 24.0, 46.0)  # west, east, south, north


def py(v: Any) -> Any:
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, np.ndarray):
        return [py(x) for x in v.tolist()]
    if isinstance(v, (list, tuple)):
        return [py(x) for x in v]
    return v


def attrs(ds: h5py.Dataset) -> dict[str, Any]:
    return {str(k): py(v) for k, v in ds.attrs.items()}


def choose_input(explicit: Path | None, directory: Path) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise SystemExit(f"INPUT_NOT_FOUND: {explicit}")
        return explicit
    candidates = []
    for pat in ("*.HDF5", "*.hdf5", "*.h5", "*.H5"):
        candidates.extend(directory.glob(pat))
    candidates = sorted(set(candidates), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise SystemExit(f"NO_HDF5_FOUND_UNDER: {directory}")
    return candidates[0]


def finite_stats(a: np.ndarray, fill: float | None = None) -> dict[str, Any]:
    x = np.asarray(a, dtype=np.float64)
    valid = np.isfinite(x)
    if fill is not None and math.isfinite(fill):
        valid &= x != fill
    y = x[valid]
    out: dict[str, Any] = {
        "total_cells": int(x.size),
        "valid_cells": int(y.size),
        "missing_or_nonfinite_cells": int(x.size - y.size),
        "missing_fraction": float((x.size - y.size) / x.size) if x.size else None,
    }
    if y.size:
        out.update({
            "min": float(np.min(y)),
            "max": float(np.max(y)),
            "mean": float(np.mean(y)),
            "median": float(np.median(y)),
            "p90": float(np.percentile(y, 90)),
            "p95": float(np.percentile(y, 95)),
            "p99": float(np.percentile(y, 99)),
            "positive_fraction_of_valid": float(np.count_nonzero(y > 0) / y.size),
            "ge_1_fraction_of_valid": float(np.count_nonzero(y >= 1) / y.size),
            "ge_10_fraction_of_valid": float(np.count_nonzero(y >= 10) / y.size),
            "ge_30_fraction_of_valid": float(np.count_nonzero(y >= 30) / y.size),
            "ge_50_fraction_of_valid": float(np.count_nonzero(y >= 50) / y.size),
        })
    return out


def fill_value(a: dict[str, Any]) -> float | None:
    for key in ("_FillValue", "FillValue", "missing_value"):
        if key in a:
            try:
                v = a[key]
                if isinstance(v, list):
                    v = v[0]
                return float(v)
            except Exception:
                pass
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path)
    ap.add_argument("--input-dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    path = choose_input(args.input, args.input_dir)

    report: dict[str, Any] = {
        "schema_version": "0.1.0-imerg-c1",
        "role": "RESEARCH_ONLY_SCIENTIFIC_CONTENT_AUDIT",
        "input_file": str(path),
        "risk_engine_allowed": False,
        "production_integration_allowed": False,
        "japan_bbox_deg": {"west": 122.0, "east": 146.0, "south": 24.0, "north": 46.0},
    }

    with h5py.File(path, "r") as h:
        required = ["Grid/lon", "Grid/lat", "Grid/time", "Grid/time_bnds", "Grid/precipitation"]
        missing = [x for x in required if x not in h]
        if missing:
            report["result"] = "FAIL_MISSING_REQUIRED_DATASETS"
            report["missing_required_datasets"] = missing
        else:
            lon = np.asarray(h["Grid/lon"][:], dtype=np.float64)
            lat = np.asarray(h["Grid/lat"][:], dtype=np.float64)
            time = np.asarray(h["Grid/time"][:])
            time_bnds = np.asarray(h["Grid/time_bnds"][:])
            pds = h["Grid/precipitation"]
            pa = attrs(pds)
            p = np.asarray(pds[:])

            west, east, south, north = JAPAN_BBOX
            ix = np.where((lon >= west) & (lon <= east))[0]
            iy = np.where((lat >= south) & (lat <= north))[0]
            if not ix.size or not iy.size:
                raise SystemExit("JAPAN_BBOX_NOT_ON_GRID")

            # IMERG arrays are conventionally [time, lon, lat]. Index explicitly
            # from the dataset to avoid pretending that the axes are [lat, lon].
            jp = np.asarray(pds[0, ix[0]:ix[-1] + 1, iy[0]:iy[-1] + 1])
            fv = fill_value(pa)

            def spacing(v: np.ndarray) -> dict[str, Any]:
                d = np.diff(v)
                return {
                    "min": float(np.min(v)), "max": float(np.max(v)), "count": int(v.size),
                    "median_step": float(np.median(d)) if d.size else None,
                    "min_step": float(np.min(d)) if d.size else None,
                    "max_step": float(np.max(d)) if d.size else None,
                    "strictly_increasing": bool(np.all(d > 0)) if d.size else True,
                }

            report.update({
                "grid": {"lon": spacing(lon), "lat": spacing(lat)},
                "time": {
                    "values": py(time), "attrs": attrs(h["Grid/time"]),
                    "bounds_values": py(time_bnds), "bounds_attrs": attrs(h["Grid/time_bnds"]),
                },
                "precipitation": {
                    "shape": list(p.shape), "dtype": str(p.dtype), "attrs": pa,
                    "fill_value_interpreted": fv,
                    "global_stats": finite_stats(p, fv),
                },
                "japan_subset": {
                    "lon_index_range": [int(ix[0]), int(ix[-1])],
                    "lat_index_range": [int(iy[0]), int(iy[-1])],
                    "shape": list(jp.shape),
                    "lon_min": float(lon[ix[0]]), "lon_max": float(lon[ix[-1]]),
                    "lat_min": float(lat[iy[0]]), "lat_max": float(lat[iy[-1]]),
                    "precipitation_stats": finite_stats(jp, fv),
                },
                "quality_datasets": {},
                "result": "PASS_C1_CONTENT_AUDIT",
            })

            for name in ("Grid/precipitationQualityIndex", "Grid/randomError", "Grid/probabilityLiquidPrecipitation"):
                if name in h:
                    ds = h[name]
                    aa = attrs(ds)
                    arr = np.asarray(ds[0, ix[0]:ix[-1] + 1, iy[0]:iy[-1] + 1])
                    report["quality_datasets"][name] = {
                        "shape": list(ds.shape), "dtype": str(ds.dtype), "attrs": aa,
                        "japan_stats": finite_stats(arr, fill_value(aa)),
                    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("result") == "PASS_C1_CONTENT_AUDIT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
