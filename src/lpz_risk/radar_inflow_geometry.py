"""Embedded-core genesis geometry relative to low-level environmental inflow.

The descriptor is intentionally separate from parent-system translation.
Positive along_inflow_km means the new child core lies toward the
meteorological wind-FROM direction (the upstream / inflow side) relative to the
current parent centroid. This is descriptive evidence only; it must not be
labeled back-building without historical validation.
"""

from __future__ import annotations

import math
from typing import Any


def _local_offset_km(
    *,
    origin_lon: float,
    origin_lat: float,
    target_lon: float,
    target_lat: float,
) -> tuple[float, float]:
    """Return local east/north displacement in km for nearby points."""
    mean_lat = math.radians((float(origin_lat) + float(target_lat)) / 2.0)
    east_km = (float(target_lon) - float(origin_lon)) * 111.320 * math.cos(mean_lat)
    north_km = (float(target_lat) - float(origin_lat)) * 110.574
    return east_km, north_km


def inflow_relative_geometry(
    *,
    parent_lon: float,
    parent_lat: float,
    child_lon: float,
    child_lat: float,
    wind_from_deg: float,
) -> dict[str, float | bool]:
    """Project child genesis displacement onto the meteorological inflow axis.

    `wind_from_deg` is the standard meteorological FROM direction clockwise from
    north. Therefore the positive inflow unit vector points geographically
    toward the direction from which the air arrives (upstream), not downwind.
    """
    values = (parent_lon, parent_lat, child_lon, child_lat, wind_from_deg)
    if not all(math.isfinite(float(v)) for v in values):
        raise ValueError("all geometry and wind inputs must be finite")

    east_km, north_km = _local_offset_km(
        origin_lon=parent_lon,
        origin_lat=parent_lat,
        target_lon=child_lon,
        target_lat=child_lat,
    )
    relative_distance_km = math.hypot(east_km, north_km)

    theta = math.radians(float(wind_from_deg) % 360.0)
    inflow_east = math.sin(theta)
    inflow_north = math.cos(theta)

    along = east_km * inflow_east + north_km * inflow_north
    # Positive cross is left of the upstream-pointing inflow vector.
    cross = inflow_east * north_km - inflow_north * east_km

    if relative_distance_km <= 1e-12:
        angular_mismatch = 0.0
    else:
        dot = max(-1.0, min(1.0, along / relative_distance_km))
        angular_mismatch = math.degrees(math.acos(dot))

    return {
        "child_relative_distance_km": relative_distance_km,
        "along_inflow_km": along,
        "cross_inflow_km": cross,
        "upstream_side": along > 0.0,
        "downwind_side": along < 0.0,
        "genesis_vs_inflow_from_angle_deg": angular_mismatch,
    }


def enrich_genesis_with_inflow(
    genesis_events: list[dict[str, Any]],
    local_winds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach one pre-sampled local wind vector to each genesis event."""
    if len(genesis_events) != len(local_winds):
        raise ValueError("genesis_events and local_winds must have equal length")

    out: list[dict[str, Any]] = []
    for event, wind in zip(genesis_events, local_winds):
        parent = event.get("parent_centroid") or {}
        child = event.get("child_centroid") or {}
        from_deg = wind.get("meteorological_from_deg")
        if None in (parent.get("lon"), parent.get("lat"), child.get("lon"), child.get("lat"), from_deg):
            raise ValueError("missing centroid or wind direction in inflow enrichment")

        geometry = inflow_relative_geometry(
            parent_lon=float(parent["lon"]),
            parent_lat=float(parent["lat"]),
            child_lon=float(child["lon"]),
            child_lat=float(child["lat"]),
            wind_from_deg=float(from_deg),
        )
        out.append({
            **event,
            "local_wind_850hpa": dict(wind),
            **geometry,
        })
    return out
