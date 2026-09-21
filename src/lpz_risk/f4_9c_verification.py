"""F4-9C prospective component-level verification primitives.

The comparison unit is one non-boundary source >=30 mm/h connected component
at one frozen lead (+15 or +30 min from prospective as-of).

The optical-flow and persistence masks are compared with ALL non-boundary
future >=30 mm/h components in the same fixed z8 mosaic. The maximum pixel IoU
is the identity-free best-IoU endpoint. No source/target identity is required.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from .f4_field_motion import semilagrangian_nearest
from .radar_morphology import TILE_SIZE, connected_components_8


EARTH_RADIUS_M = 6378137.0
MIN_COMPONENT_PIXELS = 2


def _pixel_centroid_lonlat(
    flat_indices: np.ndarray,
    *,
    width: int,
    zoom: int,
    origin_tile_x: int,
    origin_tile_y: int,
) -> tuple[float, float] | None:
    if flat_indices.size == 0:
        return None
    rows, cols = np.divmod(flat_indices.astype(np.int64), int(width))
    world_px = TILE_SIZE * (2**int(zoom))
    global_px = origin_tile_x * TILE_SIZE + cols.astype(float) + 0.5
    global_py = origin_tile_y * TILE_SIZE + rows.astype(float) + 0.5
    lon = global_px / world_px * 360.0 - 180.0
    merc_y = math.pi * (1.0 - 2.0 * global_py / world_px)
    lat = np.degrees(np.arctan(np.sinh(merc_y)))
    return float(np.mean(lon)), float(np.mean(lat))


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    h = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * (EARTH_RADIUS_M / 1000.0) * math.asin(min(1.0, math.sqrt(h)))


def _domain_diagonal_km(
    *,
    height: int,
    width: int,
    zoom: int,
    origin_tile_x: int,
    origin_tile_y: int,
) -> float:
    def lonlat(row: float, col: float) -> tuple[float, float]:
        world_px = TILE_SIZE * (2**int(zoom))
        gx = origin_tile_x * TILE_SIZE + col
        gy = origin_tile_y * TILE_SIZE + row
        lon = gx / world_px * 360.0 - 180.0
        merc_y = math.pi * (1.0 - 2.0 * gy / world_px)
        lat = math.degrees(math.atan(math.sinh(merc_y)))
        return lon, lat

    return _haversine_km(lonlat(0.0, 0.0), lonlat(float(height), float(width)))


def component_label_map(
    event_mask: np.ndarray,
    *,
    exclude_boundary: bool = True,
    min_pixels: int = MIN_COMPONENT_PIXELS,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    if event_mask.ndim != 2:
        raise ValueError("event_mask must be 2-D")
    if min_pixels < 1:
        raise ValueError("min_pixels must be positive")

    h, w = event_mask.shape
    label_map = np.zeros((h, w), dtype=np.uint16)
    rows: list[dict[str, Any]] = []
    next_id = 1

    for points in connected_components_8(np.asarray(event_mask, dtype=bool)):
        if len(points) < min_pixels:
            continue
        rr = points[:, 0]
        cc = points[:, 1]
        boundary = bool(
            int(rr.min()) == 0
            or int(cc.min()) == 0
            or int(rr.max()) == h - 1
            or int(cc.max()) == w - 1
        )
        if exclude_boundary and boundary:
            continue
        if next_id >= np.iinfo(np.uint16).max:
            raise ValueError("too many source components for uint16 label map")
        label_map[rr, cc] = next_id
        flat = np.ravel_multi_index((rr, cc), (h, w)).astype(np.int64)
        rows.append(
            {
                "component_id": next_id,
                "pixel_count": int(len(points)),
                "boundary_truncated": boundary,
                "flat_indices": np.sort(flat),
            }
        )
        next_id += 1
    return label_map, rows


def advect_component_labels(
    source_label_map: np.ndarray,
    velocity: np.ndarray,
    *,
    timesteps: list[int],
    vel_timestep: float,
    outval: float,
    n_iter: int,
    velocity_interp_order: int,
) -> np.ndarray:
    forecast = semilagrangian_nearest(
        source_label_map.astype(np.float32),
        velocity,
        [float(value) for value in timesteps],
        vel_timestep=float(vel_timestep),
        outval=float(outval),
        n_iter=int(n_iter),
        velocity_interp_order=int(velocity_interp_order),
        field_interp_order=0,
    )
    rounded = np.rint(forecast)
    if np.any(np.abs(forecast - rounded) > 1e-6):
        raise ValueError("nearest-neighbor label advection produced non-integer labels")
    return rounded.astype(np.uint16)


def _best_iou(
    predicted_flat: np.ndarray,
    target_components: list[dict[str, Any]],
) -> tuple[float, int | None, int]:
    if predicted_flat.size == 0 or not target_components:
        return 0.0, None, 0

    best_iou = 0.0
    best_id = None
    best_intersection = 0
    predicted_flat = np.asarray(predicted_flat, dtype=np.int64)

    for target in target_components:
        target_flat = np.asarray(target["flat_indices"], dtype=np.int64)
        intersection = int(
            np.intersect1d(predicted_flat, target_flat, assume_unique=True).size
        )
        union = int(predicted_flat.size + target_flat.size - intersection)
        iou = intersection / union if union else 0.0
        key = (iou, intersection, -int(target["component_id"]))
        current = (
            best_iou,
            best_intersection,
            -(int(best_id) if best_id is not None else 10**9),
        )
        if key > current:
            best_iou = float(iou)
            best_id = int(target["component_id"])
            best_intersection = intersection
    return best_iou, best_id, best_intersection


def score_component_prediction(
    predicted_flat: np.ndarray,
    target_components: list[dict[str, Any]],
    *,
    height: int,
    width: int,
    zoom: int,
    origin_tile_x: int,
    origin_tile_y: int,
) -> dict[str, Any]:
    predicted_flat = np.sort(np.asarray(predicted_flat, dtype=np.int64))
    best_iou, best_target_id, intersection = _best_iou(
        predicted_flat, target_components
    )
    predicted_centroid = _pixel_centroid_lonlat(
        predicted_flat,
        width=width,
        zoom=zoom,
        origin_tile_x=origin_tile_x,
        origin_tile_y=origin_tile_y,
    )
    penalty = _domain_diagonal_km(
        height=height,
        width=width,
        zoom=zoom,
        origin_tile_x=origin_tile_x,
        origin_tile_y=origin_tile_y,
    )

    if predicted_centroid is None or not target_components:
        nearest_distance = penalty
        nearest_target_id = None
    else:
        distances = []
        for target in target_components:
            target_centroid = _pixel_centroid_lonlat(
                np.asarray(target["flat_indices"], dtype=np.int64),
                width=width,
                zoom=zoom,
                origin_tile_x=origin_tile_x,
                origin_tile_y=origin_tile_y,
            )
            if target_centroid is None:
                continue
            distances.append(
                (
                    _haversine_km(predicted_centroid, target_centroid),
                    int(target["component_id"]),
                )
            )
        if distances:
            nearest_distance, nearest_target_id = min(distances)
        else:
            nearest_distance, nearest_target_id = penalty, None

    return {
        "predicted_pixel_count": int(predicted_flat.size),
        "best_iou": float(best_iou),
        "best_target_component_id": best_target_id,
        "best_intersection_pixel_count": int(intersection),
        "any_overlap": bool(intersection > 0),
        "predicted_centroid_lon_lat": (
            list(predicted_centroid) if predicted_centroid is not None else None
        ),
        "nearest_target_centroid_distance_km": float(nearest_distance),
        "nearest_target_component_id": nearest_target_id,
        "empty_prediction_penalty_applied": predicted_centroid is None,
        "no_target_component_penalty_applied": not bool(target_components),
        "distance_penalty_km": float(penalty),
    }
