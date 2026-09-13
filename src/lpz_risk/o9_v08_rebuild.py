"""Pure scientific core for O9-D IMERG Final V08 rainfall rebuilding.

This module contains no network, Earthdata, ERA5, matching, or risk code.  It
receives exactly 58 V08 half-hour CanonicalRainfallField objects for one UTC
region-day and reproduces the frozen Phase 2L-C/K rolling-3h semantics:

- native interval = 30 minutes, mean rain rate in mm/hr
- each interval contributes rate * 0.5 mm
- six consecutive intervals = exact 3-hour accumulation
- 53 rolling starts from previous-day 21:30 UTC through target-day 23:30 UTC
- mean/max/p90/p95 computed spatially for each 3-hour field
- retain the maximum of each statistic; strict greater-than preserves earliest
  winning window on ties
- no interpolation and no cross-version/source mixture
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

import numpy as np

from .canonical_rainfall import CanonicalRainfallField, integrate_consecutive_fields

EXPECTED_VERSION = "08"
EXPECTED_SLOT_COUNT = 58
EXPECTED_ROLLING_WINDOWS = 53
SLOTS_PER_WINDOW = 6
NATIVE_SLOT_MINUTES = 30
STATS = ("mean", "max", "p90", "p95")


def normalize_utc_day(value: str | datetime) -> datetime:
    if isinstance(value, str):
        dt = datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        dt = value
        if dt.tzinfo is None:
            raise ValueError("target day datetime must be timezone-aware")
        dt = dt.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return dt


def expected_slot_starts(day: str | datetime) -> list[datetime]:
    d = normalize_utc_day(day)
    first = d - timedelta(hours=2, minutes=30)
    return [first + timedelta(minutes=30 * i) for i in range(EXPECTED_SLOT_COUNT)]


def expected_rolling_starts(day: str | datetime) -> list[datetime]:
    slots = expected_slot_starts(day)
    return slots[:EXPECTED_ROLLING_WINDOWS]


def _same_grid(a: CanonicalRainfallField, b: CanonicalRainfallField) -> bool:
    return (
        a.rain_rate_mm_per_hr.shape == b.rain_rate_mm_per_hr.shape
        and a.longitude_deg_e.shape == b.longitude_deg_e.shape
        and a.latitude_deg_n.shape == b.latitude_deg_n.shape
        and np.allclose(a.longitude_deg_e, b.longitude_deg_e)
        and np.allclose(a.latitude_deg_n, b.latitude_deg_n)
    )


def validate_exact_v08_fields(
    day: str | datetime,
    fields: Iterable[CanonicalRainfallField],
) -> list[CanonicalRainfallField]:
    ordered = sorted(list(fields), key=lambda f: f.valid_start_utc)
    if len(ordered) != EXPECTED_SLOT_COUNT:
        raise ValueError(f"expected {EXPECTED_SLOT_COUNT} V08 half-hour fields, got {len(ordered)}")

    expected = expected_slot_starts(day)
    starts = [f.valid_start_utc.astimezone(timezone.utc) for f in ordered]
    if starts != expected:
        missing = [x.isoformat() for x in expected if x not in starts]
        extra = [x.isoformat() for x in starts if x not in expected]
        raise ValueError(f"exact V08 slot sequence mismatch; missing={missing[:5]} extra={extra[:5]}")

    first = ordered[0]
    for i, f in enumerate(ordered):
        if str(f.product_version).zfill(2) != EXPECTED_VERSION:
            raise ValueError(f"non-V08 field at index {i}: {f.product_version!r}")
        if f.source_id != "NASA_IMERG_FINAL_V08":
            raise ValueError(f"unexpected source_id at index {i}: {f.source_id!r}")
        if f.accumulation_seconds != 1800:
            raise ValueError(f"native interval must be 1800s at index {i}")
        if i and ordered[i - 1].valid_end_utc != f.valid_start_utc:
            raise ValueError(f"non-consecutive V08 fields at index {i}")
        if not _same_grid(first, f):
            raise ValueError(f"IMERG V08 grid changed within target day at index {i}")
    return ordered


def bbox_indices(
    field: CanonicalRainfallField,
    bbox_wsen: tuple[float, float, float, float],
) -> tuple[np.ndarray, np.ndarray]:
    west, south, east, north = bbox_wsen
    lon = np.asarray(field.longitude_deg_e, dtype=float)
    lat = np.asarray(field.latitude_deg_n, dtype=float)
    ix = np.where((lon >= west) & (lon <= east))[0]
    iy = np.where((lat >= south) & (lat <= north))[0]
    if ix.size == 0 or iy.size == 0:
        raise ValueError(f"empty IMERG matched bbox {bbox_wsen}")
    return iy, ix


def compute_region_day_metrics(
    *,
    day: str | datetime,
    fields: Iterable[CanonicalRainfallField],
    bbox_wsen: tuple[float, float, float, float],
) -> dict[str, object]:
    ordered = validate_exact_v08_fields(day, fields)
    rolling = expected_rolling_starts(day)
    iy, ix = bbox_indices(ordered[0], bbox_wsen)

    best: dict[str, tuple[float, datetime, datetime]] = {}
    valid_windows = 0

    for start_index, start in enumerate(rolling):
        six = ordered[start_index:start_index + SLOTS_PER_WINDOW]
        if len(six) != SLOTS_PER_WINDOW:
            raise AssertionError("incomplete six-slot rolling window")
        accum = integrate_consecutive_fields(six)
        sub = np.asarray(accum[np.ix_(iy, ix)], dtype=float)
        vals = sub[np.isfinite(sub) & (sub >= 0.0)]
        if vals.size == 0:
            continue
        valid_windows += 1
        stats = {
            "mean": float(vals.mean()),
            "max": float(vals.max()),
            "p90": float(np.percentile(vals, 90)),
            "p95": float(np.percentile(vals, 95)),
        }
        for name, value in stats.items():
            previous = best.get(name)
            if previous is None or value > previous[0]:
                best[name] = (value, start, start + timedelta(hours=3))

    if valid_windows != EXPECTED_ROLLING_WINDOWS:
        raise ValueError(
            f"expected {EXPECTED_ROLLING_WINDOWS} valid rolling windows, got {valid_windows}"
        )

    out: dict[str, object] = {
        "rolling_window_count": valid_windows,
        "source_id": "NASA_IMERG_FINAL_V08",
        "imerg_final_version": EXPECTED_VERSION,
    }
    for name in STATS:
        value, start, end = best[name]
        out[f"imerg_3h_{name}_max_mm"] = value
        out[f"imerg_3h_{name}_window_start_utc"] = start.isoformat()
        out[f"imerg_3h_{name}_window_end_utc"] = end.isoformat()
    return out
