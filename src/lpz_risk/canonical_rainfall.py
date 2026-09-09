"""Canonical source-aware historical rainfall structures.

The canonical layer preserves each provider's native temporal semantics. It never
silently averages or substitutes sources and never assigns LPZ/hard-negative labels.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np


@dataclass(frozen=True)
class CanonicalRainfallField:
    source_id: str
    product_version: str
    valid_start_utc: datetime
    valid_end_utc: datetime
    accumulation_seconds: int
    rain_rate_mm_per_hr: np.ndarray
    longitude_deg_e: np.ndarray
    latitude_deg_n: np.ndarray
    gauge_adjusted: bool
    source_path: str
    source_hash_prefix: str | None = None
    native_quality: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.valid_start_utc.tzinfo is None or self.valid_end_utc.tzinfo is None:
            raise ValueError("canonical rainfall times must be timezone-aware")
        if self.valid_end_utc <= self.valid_start_utc:
            raise ValueError("valid_end_utc must be after valid_start_utc")
        if self.accumulation_seconds <= 0:
            raise ValueError("accumulation_seconds must be positive")
        expected = int((self.valid_end_utc - self.valid_start_utc).total_seconds())
        if expected != self.accumulation_seconds:
            raise ValueError("accumulation_seconds does not match validity interval")
        rain = np.asarray(self.rain_rate_mm_per_hr, dtype=float)
        lon = np.asarray(self.longitude_deg_e, dtype=float)
        lat = np.asarray(self.latitude_deg_n, dtype=float)
        if rain.ndim != 2 or lon.ndim != 1 or lat.ndim != 1:
            raise ValueError("rain must be 2-D and lon/lat must be 1-D")
        if rain.shape != (lat.size, lon.size):
            raise ValueError("rain shape must be (latitude, longitude)")
        valid = np.isfinite(rain)
        if np.any(rain[valid] < 0):
            raise ValueError("finite canonical rain rates must be non-negative")
        if np.any(~np.isfinite(lon)) or np.any(~np.isfinite(lat)):
            raise ValueError("lon/lat must be finite")

    @property
    def accumulation_mm(self) -> np.ndarray:
        """Integrate native mean rain rate over this field's exact validity interval."""
        return np.asarray(self.rain_rate_mm_per_hr, dtype=float) * (self.accumulation_seconds / 3600.0)

    def descriptor(self) -> dict[str, Any]:
        a = np.asarray(self.rain_rate_mm_per_hr, dtype=float)
        finite = a[np.isfinite(a)]
        return {
            "schema_version": "0.1.0",
            "entity_type": "CANONICAL_RAINFALL_FIELD",
            "source_id": self.source_id,
            "product_version": self.product_version,
            "valid_start_utc": self.valid_start_utc.astimezone(timezone.utc).isoformat(),
            "valid_end_utc": self.valid_end_utc.astimezone(timezone.utc).isoformat(),
            "accumulation_seconds": self.accumulation_seconds,
            "native_value_semantics": "MEAN_RAIN_RATE_MM_PER_HR_OVER_VALID_INTERVAL",
            "gauge_adjusted": self.gauge_adjusted,
            "grid_shape": list(a.shape),
            "longitude_count": int(self.longitude_deg_e.size),
            "latitude_count": int(self.latitude_deg_n.size),
            "finite_count": int(finite.size),
            "missing_count": int(a.size - finite.size),
            "rain_rate_min_mm_per_hr": None if not finite.size else float(finite.min()),
            "rain_rate_max_mm_per_hr": None if not finite.size else float(finite.max()),
            "source_path": self.source_path,
            "source_hash_prefix": self.source_hash_prefix,
            "native_quality": self.native_quality,
            "hard_negative_label": None,
            "lpz_classification": None,
            "risk_score": None,
            "risk_engine_allowed": False,
        }


def integrate_consecutive_fields(fields: list[CanonicalRainfallField]) -> np.ndarray:
    """Integrate consecutive native intervals without resampling or source mixing."""
    if not fields:
        raise ValueError("at least one field is required")
    source = fields[0].source_id
    shape = fields[0].rain_rate_mm_per_hr.shape
    ordered = sorted(fields, key=lambda f: f.valid_start_utc)
    for i, f in enumerate(ordered):
        if f.source_id != source:
            raise ValueError("cross-source accumulation is prohibited")
        if f.rain_rate_mm_per_hr.shape != shape:
            raise ValueError("grid shape mismatch")
        if i and ordered[i - 1].valid_end_utc != f.valid_start_utc:
            raise ValueError("validity intervals must be exactly consecutive")
    stack = np.stack([f.accumulation_mm for f in ordered], axis=0)
    # If any native interval is missing, resulting accumulation is missing there.
    return np.sum(stack, axis=0)
