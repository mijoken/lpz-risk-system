from __future__ import annotations

import unittest

import numpy as np

from lpz_risk.radar_hierarchy import assign_children_to_parents, validate_nested_hierarchy
from lpz_risk.radar_tracking import extract_pixel_components


class RadarHierarchyTests(unittest.TestCase):
    def test_child_is_fully_contained_in_parent(self) -> None:
        arr = np.full((20, 20), -1, dtype=np.int8)
        arr[2:15, 2:15] = 5
        arr[6:10, 7:11] = 7
        parents = extract_pixel_components(arr, threshold_mmph=30.0)
        children = extract_pixel_components(arr, threshold_mmph=80.0)
        assignments, unassigned = assign_children_to_parents(parents, children)
        self.assertEqual(unassigned, [])
        self.assertEqual(len(assignments), 1)
        self.assertAlmostEqual(assignments[0].child_coverage, 1.0)
        self.assertEqual(assignments[0].parent_id, parents[0].local_id)

    def test_two_cores_map_to_same_parent(self) -> None:
        arr = np.full((30, 30), -1, dtype=np.int8)
        arr[2:25, 2:25] = 5
        arr[5:8, 5:8] = 6
        arr[18:22, 18:22] = 7
        parents = extract_pixel_components(arr, threshold_mmph=30.0)
        cores = extract_pixel_components(arr, threshold_mmph=50.0)
        assignments, unassigned = assign_children_to_parents(parents, cores)
        self.assertEqual(unassigned, [])
        self.assertEqual(len(assignments), 2)
        self.assertEqual({a.parent_id for a in assignments}, {parents[0].local_id})
        self.assertTrue(all(abs(a.child_coverage - 1.0) < 1e-12 for a in assignments))

    def test_two_parents_receive_correct_children(self) -> None:
        arr = np.full((30, 30), -1, dtype=np.int8)
        arr[2:10, 2:10] = 5
        arr[5:7, 5:7] = 7
        arr[18:28, 18:28] = 5
        arr[21:24, 21:24] = 7
        parents = extract_pixel_components(arr, threshold_mmph=30.0)
        children = extract_pixel_components(arr, threshold_mmph=80.0)
        assignments, unassigned = assign_children_to_parents(parents, children)
        self.assertEqual(unassigned, [])
        self.assertEqual(len(assignments), 2)
        self.assertEqual(len({a.parent_id for a in assignments}), 2)

    def test_unassigned_child_is_explicit(self) -> None:
        parent_arr = np.full((20, 20), -1, dtype=np.int8)
        child_arr = np.full((20, 20), -1, dtype=np.int8)
        parent_arr[2:6, 2:6] = 5
        child_arr[12:15, 12:15] = 7
        parents = extract_pixel_components(parent_arr, threshold_mmph=30.0)
        children = extract_pixel_components(child_arr, threshold_mmph=80.0)
        assignments, unassigned = assign_children_to_parents(parents, children)
        self.assertEqual(assignments, [])
        self.assertEqual(unassigned, [children[0].local_id])

    def test_validation_summary(self) -> None:
        arr = np.full((12, 12), -1, dtype=np.int8)
        arr[1:11, 1:11] = 5
        arr[4:8, 4:8] = 6
        parents = extract_pixel_components(arr, threshold_mmph=30.0)
        children = extract_pixel_components(arr, threshold_mmph=50.0)
        assignments, unassigned = assign_children_to_parents(parents, children)
        summary = validate_nested_hierarchy(assignments, unassigned)
        self.assertTrue(summary["all_children_assigned"])
        self.assertTrue(summary["all_assigned_children_fully_contained"])


if __name__ == "__main__":
    unittest.main()
