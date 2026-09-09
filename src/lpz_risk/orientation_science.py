"""Orientation diagnostics linking radar-object axes with environmental wind.

The line/object axis is axial (180-degree symmetry), while meteorological wind
has a 360-degree FROM direction. Comparison therefore reduces wind direction
modulo 180 and returns the acute axis mismatch in [0, 90] degrees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .gfs_science import DecodedField, FieldKey


@dataclass(frozen=True)
class LocalWindVector:
    level_hpa: int
    grid_lat: float
    grid_lon: float
    distance_deg: float
    u_mps: float
    v_mps: float
    speed_mps: float
    meteorological_from_deg: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "level_hpa": self.level_hpa,
            "grid_lat": self.grid_lat,
            "grid_lon": self.grid_lon,
            "distance_deg": self.distance_deg,
            "u_mps": self.u_mps,
            "v_mps": self.v_mps,
            "speed_mps": self.speed_mps,
            "meteorological_from_deg": self.meteorological_from_deg,
        }


def axial_orientation_deg(angle_deg: float) -> float:
    """Normalize an undirected line-axis angle to [0, 180)."""
    if not math.isfinite(angle_deg):
        raise ValueError("angle must be finite")
    return angle_deg % 180.0


def acute_axis_mismatch_deg(axis_a_deg: float, axis_b_deg: float) -> float:
    """Return acute mismatch between two undirected axes in [0, 90]."""
    a = axial_orientation_deg(axis_a_deg)
    b = axial_orientation_deg(axis_b_deg)
    diff = abs(a - b)
    return min(diff, 180.0 - diff)


def wind_axis_orientation_deg(meteorological_from_deg: float) -> float:
    """Convert 360-degree meteorological wind direction to an undirected axis."""
    return axial_orientation_deg(meteorological_from_deg)


def nearest_local_wind(
    fields: dict[FieldKey, DecodedField],
    *,
    level_hpa: int,
    lon: float,
    lat: float,
) -> LocalWindVector:
    """Return nearest valid GFS U/V vector to a target lon/lat.

    Distance is an angular grid-selection diagnostic only; it is not reported as
    a geodesic distance. Longitudes are normalized to [-180, 180) before
    comparison.
    """
    u_field = fields[FieldKey("u", level_hpa)]
    v_field = fields[FieldKey("v", level_hpa)]
    if not (
        np.array_equal(u_field.latitudes, v_field.latitudes)
        and np.array_equal(u_field.longitudes, v_field.longitudes)
        and u_field.values.size == v_field.values.size
    ):
        raise ValueError("U/V fields do not share identical coordinates")

    lats = np.asarray(u_field.latitudes, dtype=float)
    lons = ((np.asarray(u_field.longitudes, dtype=float) + 180.0) % 360.0) - 180.0
    u = np.asarray(u_field.values, dtype=float)
    v = np.asarray(v_field.values, dtype=float)
    target_lon = ((float(lon) + 180.0) % 360.0) - 180.0
    target_lat = float(lat)
    valid = (
        np.isfinite(lats) & np.isfinite(lons) & np.isfinite(u) & np.isfinite(v)
        & (np.abs(u) < 1.0e19) & (np.abs(v) < 1.0e19)
    )
    if not np.any(valid):
        raise ValueError("no finite local wind grid point")

    # Longitude degree spacing contracts physically with latitude; weight the
    # angular selection so nearest-grid choice better reflects local geometry.
    coslat = max(0.05, math.cos(math.radians(target_lat)))
    dlon = (lons - target_lon) * coslat
    dlat = lats - target_lat
    d2 = np.where(valid, dlon * dlon + dlat * dlat, np.inf)
    idx = int(np.argmin(d2))
    uu = float(u[idx]); vv = float(v[idx])
    speed = math.hypot(uu, vv)
    from_deg = (math.degrees(math.atan2(-uu, -vv)) + 360.0) % 360.0
    return LocalWindVector(
        level_hpa=level_hpa,
        grid_lat=float(lats[idx]),
        grid_lon=float(lons[idx]),
        distance_deg=float(math.sqrt(float(d2[idx]))),
        u_mps=uu,
        v_mps=vv,
        speed_mps=speed,
        meteorological_from_deg=from_deg,
    )


def orientation_consistency(
    rain_axis_deg: float,
    wind_from_deg: float,
) -> dict[str, float]:
    wind_axis = wind_axis_orientation_deg(wind_from_deg)
    mismatch = acute_axis_mismatch_deg(rain_axis_deg, wind_axis)
    return {
        "rain_axis_deg": axial_orientation_deg(rain_axis_deg),
        "wind_from_deg": wind_from_deg % 360.0,
        "wind_axis_deg": wind_axis,
        "acute_mismatch_deg": mismatch,
    }
