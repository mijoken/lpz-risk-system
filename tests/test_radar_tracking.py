from __future__ import annotations

import unittest

import numpy as np

from lpz_risk.radar_tracking import (
    association_metrics,
    best_one_to_one_matches,
    candidate_edges,
    extract_pixel_components,
    split_merge_candidates,
)


class RadarTrackingTests(unittest.TestCase):
    def test_extract_components_at_exact_threshold(self) -> None:
        arr = np.full((12, 12), -1, dtype=np.int8)
        arr[2:5, 2:5] = 5  # 30-50 mm/h
        arr[8:10, 8:10] = 6  # 50-80 mm/h
        components = extract_pixel_components(arr, threshold_mmph=30.0, min_pixels=2)
        self.assertEqual(len(components), 2)
        self.assertEqual(sorted(c.pixel_count for c in components), [4, 9])

    def test_overlap_metrics_identity(self) -> None:
        arr = np.full((10, 10), -1, dtype=np.int8)
        arr[2:6, 2:6] = 7
        comp = extract_pixel_components(arr, threshold_mmph=80.0)[0]
        edge = association_metrics(comp, comp)
        self.assertEqual(edge.intersection_pixels, 16)
        self.assertEqual(edge.union_pixels, 16)
        self.assertAlmostEqual(edge.iou, 1.0)
        self.assertAlmostEqual(edge.overlap_previous, 1.0)
        self.assertAlmostEqual(edge.overlap_current, 1.0)
        self.assertAlmostEqual(edge.centroid_displacement_pixels, 0.0)

    def test_partial_shift_has_overlap_and_displacement(self) -> None:
        a = np.full((12, 12), -1, dtype=np.int8)
        b = np.full((12, 12), -1, dtype=np.int8)
        a[3:7, 3:7] = 6
        b[3:7, 4:8] = 6
        prev = extract_pixel_components(a, threshold_mmph=50.0)[0]
        curr = extract_pixel_components(b, threshold_mmph=50.0)[0]
        edge = association_metrics(prev, curr)
        self.assertEqual(edge.intersection_pixels, 12)
        self.assertAlmostEqual(edge.overlap_previous, 0.75)
        self.assertAlmostEqual(edge.overlap_current, 0.75)
        self.assertAlmostEqual(edge.centroid_displacement_pixels, 1.0)
        self.assertGreater(edge.association_score, 0.5)

    def test_zero_overlap_not_a_candidate(self) -> None:
        a = np.full((20, 20), -1, dtype=np.int8)
        b = np.full((20, 20), -1, dtype=np.int8)
        a[2:5, 2:5] = 5
        b[14:17, 14:17] = 5
        prev = extract_pixel_components(a, threshold_mmph=30.0)
        curr = extract_pixel_components(b, threshold_mmph=30.0)
        self.assertEqual(candidate_edges(prev, curr), [])

    def test_best_one_to_one_selects_strongest_nonconflicting_edges(self) -> None:
        a = np.full((20, 20), -1, dtype=np.int8)
        b = np.full((20, 20), -1, dtype=np.int8)
        a[2:8, 2:8] = 5
        a[12:17, 12:17] = 5
        b[3:9, 3:9] = 5
        b[12:17, 12:17] = 5
        prev = extract_pixel_components(a, threshold_mmph=30.0)
        curr = extract_pixel_components(b, threshold_mmph=30.0)
        selected = best_one_to_one_matches(candidate_edges(prev, curr))
        self.assertEqual(len(selected), 2)
        self.assertEqual(len({e.previous_id for e in selected}), 2)
        self.assertEqual(len({e.current_id for e in selected}), 2)

    def test_split_candidate_detected(self) -> None:
        a = np.full((16, 16), -1, dtype=np.int8)
        b = np.full((16, 16), -1, dtype=np.int8)
        a[3:10, 3:10] = 5
        b[3:10, 3:6] = 5
        b[3:10, 7:10] = 5
        prev = extract_pixel_components(a, threshold_mmph=30.0)
        curr = extract_pixel_components(b, threshold_mmph=30.0)
        structure = split_merge_candidates(candidate_edges(prev, curr))
        self.assertEqual(len(structure["splits"]), 1)
        self.assertEqual(len(structure["splits"][0]["current_ids"]), 2)

    def test_merge_candidate_detected(self) -> None:
        a = np.full((16, 16), -1, dtype=np.int8)
        b = np.full((16, 16), -1, dtype=np.int8)
        a[3:10, 3:6] = 5
        a[3:10, 7:10] = 5
        b[3:10, 3:10] = 5
        prev = extract_pixel_components(a, threshold_mmph=30.0)
        curr = extract_pixel_components(b, threshold_mmph=30.0)
        structure = split_merge_candidates(candidate_edges(prev, curr))
        self.assertEqual(len(structure["merges"]), 1)
        self.assertEqual(len(structure["merges"][0]["previous_ids"]), 2)

    def test_boundary_flag_propagates(self) -> None:
        arr = np.full((10, 10), -1, dtype=np.int8)
        arr[0:3, 4:7] = 7
        comp = extract_pixel_components(arr, threshold_mmph=80.0)[0]
        self.assertTrue(comp.boundary_truncated)


if __name__ == "__main__":
    unittest.main()
