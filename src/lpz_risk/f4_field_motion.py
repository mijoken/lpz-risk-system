"""Frozen F4-9B local field-motion implementation.

The algorithm follows the published/default mechanics of pySTEPS 1.21.5
Lucas-Kanade dense motion and semi-Lagrangian extrapolation, but is implemented
locally so the Windows research path does not require building pySTEPS Cython
extensions. Only the F4-9B frozen parameter contract is supported.
"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np
from scipy.ndimage import map_coordinates
from scipy.spatial import cKDTree


def masked_class_stack(class_index: np.ndarray) -> np.ma.MaskedArray:
    values = class_index.astype(np.float32, copy=False)
    return np.ma.array(values, mask=class_index < 0, copy=False)


def latest_definite_ge30(class_index: np.ndarray) -> np.ndarray:
    return (class_index[-1] >= 5).astype(np.float32)


def _fill_and_scale_uint8(image: np.ma.MaskedArray) -> np.ndarray:
    valid = image.compressed()
    if valid.size == 0:
        return np.zeros(image.shape, dtype=np.uint8)
    lo = float(valid.min())
    hi = float(valid.max())
    filled = image.filled(lo).astype(np.float32, copy=False)
    if hi - lo <= 1e-8:
        return np.zeros(image.shape, dtype=np.uint8)
    scaled = (filled - lo) / (hi - lo) * 255.0
    return np.clip(scaled, 0.0, 255.0).astype(np.uint8)


def _morph_opening(image: np.ma.MaskedArray, size: int) -> np.ma.MaskedArray:
    if size <= 0:
        return image.copy()
    out = image.copy()
    valid = out.compressed()
    if valid.size == 0:
        return out
    lo = float(valid.min())
    field_bin = (out.filled(lo) > lo).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    opened = cv2.morphologyEx(field_bin, cv2.MORPH_OPEN, kernel)
    removed = (field_bin - opened) > 0
    data = out.data.copy()
    data[removed] = lo
    return np.ma.array(data, mask=np.ma.getmaskarray(out), copy=False)


def _detect_shitomasi(image: np.ma.MaskedArray, params: dict[str, Any]) -> np.ndarray:
    work = image.copy()
    mask = np.ma.getmaskarray(work).astype(np.uint8)
    buffer_mask = int(params["buffer_mask"])
    if buffer_mask > 0:
        mask = cv2.dilate(
            mask,
            np.ones((buffer_mask, buffer_mask), dtype=np.uint8),
            iterations=1,
        )
    img8 = _fill_and_scale_uint8(work)
    allowed = ((mask == 0).astype(np.uint8))
    points = cv2.goodFeaturesToTrack(
        img8,
        maxCorners=int(params["max_corners"]),
        qualityLevel=float(params["quality_level"]),
        minDistance=float(params["min_distance"]),
        mask=allowed,
        blockSize=int(params["block_size"]),
        useHarrisDetector=bool(params["use_harris"]),
        k=float(params["k"]),
    )
    if points is None:
        return np.empty((0, 2), dtype=np.float32)
    return points[:, 0, :].astype(np.float32, copy=False)


def _track_lk(
    previous: np.ma.MaskedArray,
    current: np.ma.MaskedArray,
    points: np.ndarray,
    params: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    if points.size == 0:
        empty = np.empty((0, 2), dtype=np.float64)
        return empty, empty
    prev8 = _fill_and_scale_uint8(previous)
    curr8 = _fill_and_scale_uint8(current)
    criteria = tuple(int(x) for x in params["criteria"])
    p1, status, _err = cv2.calcOpticalFlowPyrLK(
        prev8,
        curr8,
        points.astype(np.float32, copy=False),
        None,
        winSize=tuple(int(x) for x in params["winsize"]),
        maxLevel=int(params["nr_levels"]),
        criteria=criteria,
        flags=int(params["flags"]),
        minEigThreshold=float(params["min_eig_thr"]),
    )
    if p1 is None or status is None:
        empty = np.empty((0, 2), dtype=np.float64)
        return empty, empty
    keep = np.atleast_1d(status.squeeze()) == 1
    if not np.any(keep):
        empty = np.empty((0, 2), dtype=np.float64)
        return empty, empty
    p0 = points[keep, :].astype(np.float64, copy=False)
    p1 = p1[keep, :].astype(np.float64, copy=False)
    return p0, p1 - p0


def _local_outliers(
    uv: np.ndarray,
    xy: np.ndarray,
    threshold: float,
    k: int,
) -> np.ndarray:
    n = uv.shape[0]
    if n < 3:
        return np.zeros(n, dtype=bool)
    query_k = min(n, int(k) + 1)
    tree = cKDTree(xy)
    _distance, indices = tree.query(xy, k=query_k)
    if indices.ndim == 1:
        indices = indices[:, None]
    output = np.zeros(n, dtype=bool)
    for i in range(n):
        neighbours = uv[indices[i, 1:], :]
        if neighbours.shape[0] < 2:
            continue
        centered = neighbours - np.mean(neighbours, axis=0)
        covariance = np.cov(centered.T)
        if np.ndim(covariance) != 2 or covariance.shape != (2, 2):
            continue
        try:
            inv = np.linalg.inv(covariance)
        except np.linalg.LinAlgError:
            continue
        delta = uv[i, :] - np.mean(neighbours, axis=0)
        distance = math.sqrt(max(0.0, float(delta @ inv @ delta.T)))
        output[i] = distance > float(threshold)
    return output


def _decluster(
    xy: np.ndarray,
    uv: np.ndarray,
    scale: float,
) -> tuple[np.ndarray, np.ndarray]:
    if xy.shape[0] == 0 or scale <= 1:
        return xy, uv
    reduced = np.floor(xy / float(scale))
    unique = np.unique(reduced, axis=0)
    out_xy = []
    out_uv = []
    for cell in unique:
        selected = np.all(reduced == cell, axis=1)
        out_xy.append(np.median(xy[selected, :], axis=0))
        out_uv.append(np.median(uv[selected, :], axis=0))
    return np.asarray(out_xy, dtype=np.float64), np.asarray(out_uv, dtype=np.float64)


def _idw_dense(
    xy: np.ndarray,
    uv: np.ndarray,
    height: int,
    width: int,
    params: dict[str, Any],
) -> np.ndarray:
    if xy.shape[0] == 0:
        return np.zeros((2, height, width), dtype=np.float32)
    tree = cKDTree(xy)
    neighbours = min(int(params["k"]), xy.shape[0])
    power = float(params["power"])
    offset = float(params["dist_offset"])
    chunk_points = int(params["chunk_points"])
    total = height * width
    flat = np.empty((total, 2), dtype=np.float32)

    for start in range(0, total, chunk_points):
        stop = min(total, start + chunk_points)
        idx = np.arange(start, stop, dtype=np.int64)
        yy = idx // width
        xx = idx % width
        query = np.column_stack((xx, yy))
        dist, inds = tree.query(query, k=neighbours)
        if neighbours == 1:
            dist = dist[:, None]
            inds = inds[:, None]
        weights = 1.0 / np.power(dist + offset, power)
        weights /= np.sum(weights, axis=1, keepdims=True)
        flat[start:stop, :] = np.sum(uv[inds, :] * weights[..., None], axis=1)

    dense = flat.reshape(height, width, 2)
    return np.moveaxis(dense, -1, 0).astype(np.float32, copy=False)


def estimate_dense_lucas_kanade(
    input_images: np.ma.MaskedArray,
    parameters: dict[str, Any],
) -> np.ndarray:
    if input_images.ndim != 3 or input_images.shape[0] < 2:
        raise ValueError("Lucas-Kanade input must be (T,H,W) with T>=2")

    feature_params = parameters["feature_detection"]
    tracking_params = parameters["tracking"]
    size_opening = int(parameters["size_opening"])
    xy_parts: list[np.ndarray] = []
    uv_parts: list[np.ndarray] = []

    for i in range(input_images.shape[0] - 1):
        previous = _morph_opening(input_images[i], size_opening)
        current = _morph_opening(input_images[i + 1], size_opening)
        points = _detect_shitomasi(previous, feature_params)
        xy, uv = _track_lk(previous, current, points, tracking_params)
        if xy.shape[0]:
            xy_parts.append(xy)
            uv_parts.append(uv)

    height, width = input_images.shape[1:]
    if not xy_parts:
        return np.zeros((2, height, width), dtype=np.float32)

    xy = np.concatenate(xy_parts, axis=0)
    uv = np.concatenate(uv_parts, axis=0)
    outliers = _local_outliers(
        uv,
        xy,
        float(parameters["nr_std_outlier"]),
        int(parameters["k_outlier"]),
    )
    xy = xy[~outliers]
    uv = uv[~outliers]
    xy, uv = _decluster(xy, uv, float(parameters["decl_scale"]))
    return _idw_dense(
        xy,
        uv,
        height,
        width,
        parameters["interpolation"],
    )


def semilagrangian_nearest(
    field: np.ndarray,
    velocity: np.ndarray,
    timesteps: list[float],
    *,
    vel_timestep: float,
    outval: float,
    n_iter: int,
    velocity_interp_order: int,
    field_interp_order: int,
) -> np.ndarray:
    if field.ndim != 2:
        raise ValueError("field must be two-dimensional")
    if velocity.shape != (2, field.shape[0], field.shape[1]):
        raise ValueError("velocity shape mismatch")
    if not np.all(np.isfinite(field)) or not np.all(np.isfinite(velocity)):
        raise ValueError("field and velocity must be finite")
    if sorted(timesteps) != list(timesteps) or any(
        b <= a for a, b in zip(timesteps[:-1], timesteps[1:])
    ):
        raise ValueError("timesteps must be strictly increasing")

    yy, xx = np.meshgrid(
        np.arange(field.shape[0], dtype=np.float64),
        np.arange(field.shape[1], dtype=np.float64),
        indexing="ij",
    )
    coords = np.stack([xx, yy])
    displacement = np.zeros_like(velocity, dtype=np.float64)
    timestep_diff = np.hstack([[timesteps[0]], np.diff(timesteps)])
    velocity_inc = velocity.astype(np.float64, copy=True) * (
        timestep_diff[0] / float(vel_timestep)
    )
    outputs = []

    def interpolate_motion(query_displacement: np.ndarray, td: float) -> np.ndarray:
        warped = coords + query_displacement
        sample = [warped[1], warped[0]]
        u = map_coordinates(
            velocity[0],
            sample,
            mode="nearest",
            order=int(velocity_interp_order),
            prefilter=False,
        )
        v = map_coordinates(
            velocity[1],
            sample,
            mode="nearest",
            order=int(velocity_interp_order),
            prefilter=False,
        )
        result = np.stack([u, v]).astype(np.float64, copy=False)
        if n_iter > 1:
            result /= float(n_iter)
        result *= float(td) / float(vel_timestep)
        return result

    for td in timestep_diff:
        if n_iter > 0:
            for _ in range(int(n_iter)):
                velocity_inc = interpolate_motion(
                    displacement - velocity_inc / 2.0,
                    float(td),
                )
                displacement -= velocity_inc
                velocity_inc = interpolate_motion(displacement, float(td))
        else:
            velocity_inc = interpolate_motion(displacement, float(td))
            displacement -= velocity_inc

        warped = coords + displacement
        sample = [warped[1], warped[0]]
        advected = map_coordinates(
            field,
            sample,
            mode="constant",
            cval=float(outval),
            order=int(field_interp_order),
            prefilter=False,
        )
        outputs.append(advected.astype(np.float32, copy=False))

    return np.stack(outputs, axis=0)


def run_frozen_field_motion(
    class_index: np.ndarray,
    spec: dict[str, Any],
) -> dict[str, np.ndarray]:
    motion_input = masked_class_stack(class_index)
    velocity = estimate_dense_lucas_kanade(
        motion_input,
        spec["motion_estimation"]["parameters"],
    )
    latest = latest_definite_ge30(class_index)
    extrap = spec["extrapolation"]
    forecast = semilagrangian_nearest(
        latest,
        velocity,
        [float(x) for x in extrap["timesteps"]],
        vel_timestep=float(extrap["vel_timestep"]),
        outval=float(extrap["outval"]),
        n_iter=int(extrap["n_iter"]),
        velocity_interp_order=int(extrap["velocity_interp_order"]),
        field_interp_order=int(extrap["field_interp_order"]),
    )
    threshold = float(extrap["numerical_binary_decode_threshold"])
    forecast_mask = (forecast >= threshold).astype(np.uint8)
    persistence = np.repeat(
        latest.astype(np.uint8)[None, :, :],
        len(extrap["timesteps"]),
        axis=0,
    )
    return {
        "velocity": velocity.astype(np.float32, copy=False),
        "forecast_ge30": forecast_mask,
        "persistence_ge30": persistence,
        "lead_minutes": np.asarray(extrap["lead_minutes"], dtype=np.int16),
    }
