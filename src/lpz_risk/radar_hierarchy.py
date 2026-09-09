"""Hierarchy primitives for nested public-PNG precipitation thresholds.

The exact 30/50/80 mm/h masks are nested by construction. This module maps
stronger child cores to broader parent precipitation envelopes using pixel
containment/intersection. The hierarchy is descriptive and is not an LPZ gate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .radar_tracking import PixelComponent


@dataclass(frozen=True)
class ChildParentAssignment:
    child_id: int
    parent_id: int
    intersection_pixels: int
    child_coverage: float
    parent_coverage: float

    def to_dict(self) -> dict[str, int | float]:
        return {
            "child_id": self.child_id,
            "parent_id": self.parent_id,
            "intersection_pixels": self.intersection_pixels,
            "child_coverage": self.child_coverage,
            "parent_coverage": self.parent_coverage,
        }


def _intersection_size(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.intersect1d(a, b, assume_unique=True).size)


def assign_children_to_parents(
    parents: list[PixelComponent],
    children: list[PixelComponent],
) -> tuple[list[ChildParentAssignment], list[int]]:
    """Assign each child to the parent with maximum pixel intersection.

    Returns assignments and child IDs that had zero overlap with every parent.
    For correctly nested exact-threshold masks, unassigned children should be
    empty; retaining this output makes containment failures explicit.
    """
    assignments: list[ChildParentAssignment] = []
    unassigned: list[int] = []

    for child in children:
        candidates: list[tuple[int, PixelComponent]] = []
        for parent in parents:
            intersection = _intersection_size(parent.flat_indices, child.flat_indices)
            if intersection > 0:
                candidates.append((intersection, parent))
        if not candidates:
            unassigned.append(child.local_id)
            continue
        intersection, parent = max(candidates, key=lambda item: (item[0], item[1].pixel_count))
        assignments.append(
            ChildParentAssignment(
                child_id=child.local_id,
                parent_id=parent.local_id,
                intersection_pixels=intersection,
                child_coverage=intersection / child.pixel_count if child.pixel_count else 0.0,
                parent_coverage=intersection / parent.pixel_count if parent.pixel_count else 0.0,
            )
        )
    return assignments, unassigned


def validate_nested_hierarchy(assignments: list[ChildParentAssignment], unassigned: list[int]) -> dict[str, object]:
    """Summarize whether every child is fully contained in one parent."""
    fully_contained = [a for a in assignments if abs(a.child_coverage - 1.0) <= 1e-12]
    return {
        "assigned_child_count": len(assignments),
        "unassigned_child_ids": list(unassigned),
        "fully_contained_child_count": len(fully_contained),
        "all_children_assigned": len(unassigned) == 0,
        "all_assigned_children_fully_contained": len(fully_contained) == len(assignments),
    }
