"""Temporal association primitives for radar precipitation objects.

This layer is deliberately separate from LPZ classification. It tracks exact
public-PNG threshold components across a common fixed mosaic and records overlap,
centroid displacement, split/merge candidates, and lineage edges. Association
parameters are engineering parameters to be validated historically; they are
not meteorological LPZ thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .radar_morphology import connected_components_8, exact_threshold_mask


@dataclass(frozen=True)
class PixelComponent:
    local_id: int
    pixel_count: int
    flat_indices: np.ndarray
    centroid_row: float
    centroid_col: float
    bbox_pixel: tuple[int, int, int, int]
    boundary_truncated: bool


@dataclass(frozen=True)
class AssociationEdge:
    previous_id: int
    current_id: int
    intersection_pixels: int
    union_pixels: int
    iou: float
    overlap_previous: float
    overlap_current: float
    centroid_displacement_pixels: float
    association_score: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "previous_id": self.previous_id,
            "current_id": self.current_id,
            "intersection_pixels": self.intersection_pixels,
            "union_pixels": self.union_pixels,
            "iou": self.iou,
            "overlap_previous": self.overlap_previous,
            "overlap_current": self.overlap_current,
            "centroid_displacement_pixels": self.centroid_displacement_pixels,
            "association_score": self.association_score,
        }


def extract_pixel_components(
    class_index: np.ndarray,
    *,
    threshold_mmph: float,
    min_pixels: int = 2,
) -> list[PixelComponent]:
    if class_index.ndim != 2:
        raise ValueError("class_index must be 2-D")
    if min_pixels < 1:
        raise ValueError("min_pixels must be >= 1")
    mask = exact_threshold_mask(class_index, threshold_mmph)
    h, w = class_index.shape
    out: list[PixelComponent] = []
    next_id = 1
    for pts in connected_components_8(mask):
        if len(pts) < min_pixels:
            continue
        rows = pts[:, 0].astype(np.int64)
        cols = pts[:, 1].astype(np.int64)
        flat = np.sort(rows * w + cols)
        r0, r1 = int(rows.min()), int(rows.max())
        c0, c1 = int(cols.min()), int(cols.max())
        out.append(
            PixelComponent(
                local_id=next_id,
                pixel_count=int(len(pts)),
                flat_indices=flat,
                centroid_row=float(np.mean(rows)),
                centroid_col=float(np.mean(cols)),
                bbox_pixel=(c0, r0, c1, r1),
                boundary_truncated=(r0 == 0 or c0 == 0 or r1 == h - 1 or c1 == w - 1),
            )
        )
        next_id += 1
    return out


def _intersection_size(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.intersect1d(a, b, assume_unique=True).size)


def association_metrics(previous: PixelComponent, current: PixelComponent) -> AssociationEdge:
    intersection = _intersection_size(previous.flat_indices, current.flat_indices)
    union = previous.pixel_count + current.pixel_count - intersection
    iou = intersection / union if union else 0.0
    overlap_previous = intersection / previous.pixel_count if previous.pixel_count else 0.0
    overlap_current = intersection / current.pixel_count if current.pixel_count else 0.0
    dr = current.centroid_row - previous.centroid_row
    dc = current.centroid_col - previous.centroid_col
    displacement = math.hypot(dr, dc)

    # Geometry-only association score. Overlap dominates; displacement only
    # breaks ties among plausible nearby candidates. No meteorological meaning.
    proximity = 1.0 / (1.0 + displacement)
    score = 0.50 * iou + 0.25 * overlap_previous + 0.20 * overlap_current + 0.05 * proximity
    return AssociationEdge(
        previous_id=previous.local_id,
        current_id=current.local_id,
        intersection_pixels=intersection,
        union_pixels=union,
        iou=iou,
        overlap_previous=overlap_previous,
        overlap_current=overlap_current,
        centroid_displacement_pixels=displacement,
        association_score=score,
    )


def candidate_edges(
    previous: list[PixelComponent],
    current: list[PixelComponent],
    *,
    minimum_intersection_pixels: int = 1,
) -> list[AssociationEdge]:
    """Return every overlap-based association candidate between two frames."""
    if minimum_intersection_pixels < 1:
        raise ValueError("minimum_intersection_pixels must be >= 1")
    edges: list[AssociationEdge] = []
    for prev in previous:
        for curr in current:
            edge = association_metrics(prev, curr)
            if edge.intersection_pixels >= minimum_intersection_pixels:
                edges.append(edge)
    return sorted(edges, key=lambda e: e.association_score, reverse=True)


def best_one_to_one_matches(edges: list[AssociationEdge]) -> list[AssociationEdge]:
    """Greedy geometry-only one-to-one lineage links.

    Split/merge evidence must be inspected from the complete candidate-edge set;
    this helper only creates a simple primary lineage for motion summaries.
    """
    used_prev: set[int] = set()
    used_curr: set[int] = set()
    selected: list[AssociationEdge] = []
    for edge in sorted(edges, key=lambda e: e.association_score, reverse=True):
        if edge.previous_id in used_prev or edge.current_id in used_curr:
            continue
        selected.append(edge)
        used_prev.add(edge.previous_id)
        used_curr.add(edge.current_id)
    return selected


def split_merge_candidates(edges: list[AssociationEdge]) -> dict[str, list[dict[str, object]]]:
    by_prev: dict[int, list[int]] = {}
    by_curr: dict[int, list[int]] = {}
    for edge in edges:
        by_prev.setdefault(edge.previous_id, []).append(edge.current_id)
        by_curr.setdefault(edge.current_id, []).append(edge.previous_id)
    splits = [
        {"previous_id": prev, "current_ids": sorted(set(currs))}
        for prev, currs in sorted(by_prev.items())
        if len(set(currs)) > 1
    ]
    merges = [
        {"current_id": curr, "previous_ids": sorted(set(prevs))}
        for curr, prevs in sorted(by_curr.items())
        if len(set(prevs)) > 1
    ]
    return {"splits": splits, "merges": merges}
