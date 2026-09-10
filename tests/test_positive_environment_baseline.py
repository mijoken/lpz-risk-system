import unittest

from lpz_risk.positive_environment_baseline import (
    CMORPH,
    IMERG,
    OFFSETS,
    RAIN_METRICS,
    build_development_positive_environment_baseline,
)


class TestPositiveEnvironmentBaseline(unittest.TestCase):
    def _rain_rows(self, n=3):
        rows = []
        for i in range(n):
            for source, scale in ((IMERG, 1.0), (CMORPH, 0.8)):
                base = float(i + 1) * 10.0 * scale
                rows.append(
                    {
                        "local_episode_id": f"E{i:03d}",
                        "source_id": source,
                        "anchor_id": f"A{i:03d}",
                        "primary_subdivision_code": "000000",
                        "analysis_time_utc": (
                            f"2023-07-{i + 1:02d}T03:00:00Z"
                        ),
                        "representative_policy": (
                            "EARLIEST_REALIZED_POSITIVE_ANCHOR_PER_"
                            "LOCAL_EPISODE_PROVIDER"
                        ),
                        "max_accumulation_mm": base,
                        "mean_accumulation_mm": base / 2.0,
                        "p90_accumulation_mm": base * 0.80,
                        "p95_accumulation_mm": base * 0.90,
                        "p99_accumulation_mm": base * 0.98,
                        "finite_polygon_area_km2": 100.0,
                        "finite_coverage_fraction": 1.0,
                        "risk_score": None,
                    }
                )
        return rows

    def _era5(self, n=3):
        rows = []
        for i in range(n):
            for offset in OFFSETS:
                rows.append(
                    {
                        "anchor_id": f"A{i:03d}",
                        "primary_subdivision_code": "000000",
                        "snapshot_offset_minutes": offset,
                        "requested_snapshot_time_utc": (
                            "2023-07-01T00:00:00Z"
                        ),
                        "era5_source_time_utc": "2023-07-01T00:00:00Z",
                        "source_lag_minutes": 0,
                        "future_source_time_used": False,
                        "source": "ERA5",
                        "exactness": "PROXY_REANALYSIS",
                        "rh500_mean_pct": 70.0 + i + offset / 1000.0,
                        "rh700_mean_pct": 80.0 + i + offset / 1000.0,
                        "rh500_rh700_gt60_fraction": 0.80 + i * 0.01,
                        "wind600_speed_mean_mps": (
                            10.0 + i + offset / 600.0
                        ),
                        "wind600_from_direction_median_deg": 350.0,
                        "wind850_speed_mean_mps": (
                            12.0 + i + offset / 600.0
                        ),
                        "wind850_from_direction_median_deg": 10.0,
                        "q1000_mean_kgkg": (
                            0.018 + i * 0.0001 + offset / 1_000_000.0
                        ),
                        "q925_mean_kgkg": (
                            0.016 + i * 0.0001 + offset / 1_000_000.0
                        ),
                        "q850_mean_kgkg": (
                            0.014 + i * 0.0001 + offset / 1_000_000.0
                        ),
                        "spatial_semantics": (
                            "REQUEST_BBOX_CONTEXT_NOT_SUBDIVISION_"
                            "POLYGON_MEAN"
                        ),
                        "risk_score": None,
                    }
                )
        return {
            "source": "ERA5",
            "available_window_complete": True,
            "risk_engine_allowed": False,
            "snapshot_features": rows,
        }

    def test_complete_baseline_is_descriptive_only(self):
        out = build_development_positive_environment_baseline(
            self._rain_rows(),
            self._era5(),
            expected_episode_count=3,
        )
        self.assertEqual(
            out["gate"],
            "PASS_COMPLETE_DEVELOPMENT_POSITIVE_ENVIRONMENT_BASELINE",
        )
        self.assertEqual(out["episode_count"], 3)
        self.assertEqual(out["era5_snapshot_count"], 18)
        self.assertFalse(out["source_fusion_used"])
        self.assertFalse(out["gsmap_used"])
        self.assertFalse(out["convergence_inferred"])
        self.assertFalse(out["candidate_threshold_selected"])
        self.assertIsNone(out["hard_negative_label"])
        self.assertFalse(out["validation_data_used"])
        self.assertFalse(out["risk_engine_allowed"])
        t0 = out["episode_rows"][0]["era5_snapshots"][-1]
        self.assertAlmostEqual(
            t0["wind850_600_direction_difference_deg"], 20.0
        )
        self.assertEqual(
            out["convergence_feature_status"],
            "NOT_AVAILABLE_IN_CURRENT_ERA5_DESCRIPTOR_DO_NOT_INFER",
        )
        for metric in RAIN_METRICS:
            self.assertIn(
                metric,
                out["rainfall_source_native_distributions"][IMERG],
            )
            self.assertIn(
                metric,
                out["rainfall_source_native_distributions"][CMORPH],
            )

    def test_provider_identity_mismatch_fails_closed(self):
        rows = self._rain_rows()
        for row in rows:
            if (
                row["local_episode_id"] == "E002"
                and row["source_id"] == CMORPH
            ):
                row["anchor_id"] = "WRONG"
        with self.assertRaises(ValueError):
            build_development_positive_environment_baseline(
                rows,
                self._era5(),
                expected_episode_count=3,
            )

    def test_missing_era5_offset_fails_closed(self):
        era5 = self._era5()
        era5["snapshot_features"] = [
            row
            for row in era5["snapshot_features"]
            if not (
                row["anchor_id"] == "A002"
                and row["snapshot_offset_minutes"] == -90
            )
        ]
        with self.assertRaises(ValueError):
            build_development_positive_environment_baseline(
                self._rain_rows(),
                era5,
                expected_episode_count=3,
            )


if __name__ == "__main__":
    unittest.main()
