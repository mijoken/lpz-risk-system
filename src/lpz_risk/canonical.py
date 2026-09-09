from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


CANONICAL_SCHEMA_VERSION = "0.1.0"


@dataclass(slots=True)
class SourceHealth:
    source_id: str
    status: str
    probe_type: str
    data_time: str | None
    data_age_seconds: int | None
    latency_ms: int | None
    bytes_received: int | None
    parse_status: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RadarFrameManifest:
    source_id: str
    valid_time: str
    base_time: str
    member: str
    element: str
    tile_scheme: str = "web_mercator_xyz"
    source_kind: str = "jma_png_tile"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SurfaceStationObservation:
    station_id: str
    station_name_ja: str | None
    station_name_en: str | None
    observation_time: str
    latitude_deg: float | None
    longitude_deg: float | None
    altitude_m: float | None
    temperature_c: float | None = None
    humidity_pct: float | None = None
    precipitation_1h_mm: float | None = None
    wind_speed_ms: float | None = None
    wind_direction_code: int | None = None
    wind_direction_deg_from: float | None = None
    wind_u_ms: float | None = None
    wind_v_ms: float | None = None
    qc: dict[str, int | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def degrees_minutes_to_decimal(value: Any) -> float | None:
    if not isinstance(value, list) or len(value) < 2:
        return None
    try:
        degrees = float(value[0])
        minutes = float(value[1])
    except (TypeError, ValueError):
        return None
    sign = -1.0 if degrees < 0 else 1.0
    return degrees + sign * minutes / 60.0


def value_and_qc(payload: dict[str, Any], key: str) -> tuple[float | int | None, int | None]:
    raw = payload.get(key)
    if not isinstance(raw, list) or not raw:
        return None, None
    value = raw[0]
    qc = raw[1] if len(raw) > 1 else None
    if value is None:
        return None, int(qc) if isinstance(qc, (int, float)) else None
    if isinstance(value, (int, float)):
        value_out: float | int = value
    else:
        try:
            value_out = float(value)
        except (TypeError, ValueError):
            return None, int(qc) if isinstance(qc, (int, float)) else None
    return value_out, int(qc) if isinstance(qc, (int, float)) else None


def jma_wind_direction_degrees(code: int | float | None) -> float | None:
    """Convert JMA map wind-direction code to meteorological degrees FROM north.

    JMA's map convention uses 0 for calm, 1=NNE, 2=NE, ..., 15=NNW,
    16=N. Calm has no meaningful direction and returns None.
    """
    if code is None:
        return None
    try:
        value = int(code)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return None
    if not 1 <= value <= 16:
        return None
    return (value * 22.5) % 360.0


def meteorological_wind_to_uv(speed_ms: float | int | None, direction_from_deg: float | None) -> tuple[float | None, float | None]:
    """Convert meteorological wind (direction wind comes FROM) to east/north u,v.

    u > 0 is eastward, v > 0 is northward.
    """
    if speed_ms is None or direction_from_deg is None:
        return None, None
    speed = float(speed_ms)
    rad = math.radians(float(direction_from_deg))
    u = -speed * math.sin(rad)
    v = -speed * math.cos(rad)
    return u, v


def normalize_amedas_station(
    station_id: str,
    observation: dict[str, Any],
    station_meta: dict[str, Any] | None,
    observation_time: str,
) -> SurfaceStationObservation:
    meta = station_meta or {}

    temp, temp_qc = value_and_qc(observation, "temp")
    humidity, humidity_qc = value_and_qc(observation, "humidity")
    precip1h, precip_qc = value_and_qc(observation, "precipitation1h")
    wind_speed, wind_qc = value_and_qc(observation, "wind")
    wind_direction, direction_qc = value_and_qc(observation, "windDirection")

    direction_code = int(wind_direction) if isinstance(wind_direction, (int, float)) else None
    direction_deg = jma_wind_direction_degrees(direction_code)
    u, v = meteorological_wind_to_uv(wind_speed, direction_deg)

    return SurfaceStationObservation(
        station_id=station_id,
        station_name_ja=meta.get("kjName"),
        station_name_en=meta.get("enName"),
        observation_time=observation_time,
        latitude_deg=degrees_minutes_to_decimal(meta.get("lat")),
        longitude_deg=degrees_minutes_to_decimal(meta.get("lon")),
        altitude_m=float(meta["alt"]) if isinstance(meta.get("alt"), (int, float)) else None,
        temperature_c=float(temp) if isinstance(temp, (int, float)) else None,
        humidity_pct=float(humidity) if isinstance(humidity, (int, float)) else None,
        precipitation_1h_mm=float(precip1h) if isinstance(precip1h, (int, float)) else None,
        wind_speed_ms=float(wind_speed) if isinstance(wind_speed, (int, float)) else None,
        wind_direction_code=direction_code,
        wind_direction_deg_from=direction_deg,
        wind_u_ms=u,
        wind_v_ms=v,
        qc={
            "temp": temp_qc,
            "humidity": humidity_qc,
            "precipitation1h": precip_qc,
            "wind": wind_qc,
            "windDirection": direction_qc,
        },
    )


def source_health_from_probe(row: dict[str, Any]) -> SourceHealth:
    return SourceHealth(
        source_id=str(row.get("source_id", "unknown")),
        status=str(row.get("status", "UNKNOWN")),
        probe_type=str(row.get("probe_type", "UNKNOWN")),
        data_time=row.get("data_time"),
        data_age_seconds=row.get("data_age_seconds"),
        latency_ms=row.get("latency_ms"),
        bytes_received=row.get("bytes_received"),
        parse_status=str(row.get("parse_status", "UNKNOWN")),
        error=row.get("error"),
    )
