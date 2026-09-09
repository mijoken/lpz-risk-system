from __future__ import annotations

import unittest

from lpz_risk.rainfall_reconstruction_merge import merge_development_rainfall_reconstruction


class RainfallReconstructionMergeTest(unittest.TestCase):
    def test_complete_single_task_merge(self):
        plan = {
            "split": "DEVELOPMENT",
            "input_unique_window_count": 1,
            "tasks": [{"task_id": "t1"}],
            "source_summary": [{"source_id": "GSMAP_STANDARD_V8_HISTORICAL"}],
        }
        manifest = {
            "split": "DEVELOPMENT",
            "anchor_provider_mapping_count": 1,
            "windows": [{"window_id": "w1"}],
            "anchor_window_mappings": [{
                "anchor_id": "a1", "local_episode_id": "e1", "primary_subdivision_code": "390030",
                "analysis_time_utc": "2023-01-01T03:00:00Z", "source_id": "GSMAP_STANDARD_V8_HISTORICAL",
                "window_id": "w1", "source_lag_seconds": 0,
            }],
        }
        episodes = {"split_local_episode_counts": {"DEVELOPMENT": 1}}
        descriptor = {
            "max_accumulation_mm": 10.0, "mean_accumulation_mm": 2.0,
            "p90_accumulation_mm": 5.0, "p95_accumulation_mm": 6.0,
            "p99_accumulation_mm": 9.0, "finite_polygon_area_km2": 100.0,
            "finite_coverage_fraction": 1.0,
        }
        reports = [{
            "phase": "2I-development-real-rainfall-reconstruction-task", "split": "DEVELOPMENT",
            "task_id": "t1", "gate": "PASS_TASK_REAL_PAYLOAD_RECONSTRUCTION",
            "risk_engine_allowed": False,
            "window_descriptors": [{"window_id": "w1", "descriptor": descriptor}],
        }]
        out = merge_development_rainfall_reconstruction(plan, manifest, episodes, reports)
        self.assertTrue(out["historical_rainfall_development_reconstruction_complete"])
        self.assertEqual(out["reconstructed_window_count"], 1)
        self.assertEqual(out["episode_representative_count"], 1)
        self.assertFalse(out["candidate_threshold_selected"])
        self.assertFalse(out["risk_engine_allowed"])

    def test_missing_task_blocks_completion(self):
        plan = {"split": "DEVELOPMENT", "input_unique_window_count": 1, "tasks": [{"task_id": "t1"}], "source_summary": [{"source_id": "GSMAP_STANDARD_V8_HISTORICAL"}]}
        manifest = {"split": "DEVELOPMENT", "anchor_provider_mapping_count": 0, "windows": [{"window_id": "w1"}], "anchor_window_mappings": []}
        episodes = {"split_local_episode_counts": {"DEVELOPMENT": 0}}
        out = merge_development_rainfall_reconstruction(plan, manifest, episodes, [])
        self.assertFalse(out["historical_rainfall_development_reconstruction_complete"])
        self.assertEqual(out["gate"], "BLOCKED_INCOMPLETE_DEVELOPMENT_RECONSTRUCTION")


if __name__ == "__main__":
    unittest.main()
