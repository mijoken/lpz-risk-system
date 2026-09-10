import unittest

from lpz_risk.rainfall_source_disagreement import (
    CMORPH,
    IMERG,
    analyze_dual_source_episode_representatives,
)


class TestRainfallSourceDisagreement(unittest.TestCase):
    def _rows(self, n=65):
        rows=[]
        for i in range(n):
            for source, scale in ((IMERG, 1.0), (CMORPH, 0.8)):
                v=float(i+1)*scale
                rows.append({
                    'local_episode_id': f'E{i:03d}',
                    'source_id': source,
                    'primary_subdivision_code': '000000',
                    'analysis_time_utc': f'2023-01-{(i%28)+1:02d}T00:00:00Z',
                    'max_accumulation_mm': v,
                    'mean_accumulation_mm': v/2,
                    'p90_accumulation_mm': v*0.8,
                    'p95_accumulation_mm': v*0.9,
                    'p99_accumulation_mm': v*0.98,
                })
        return rows

    def test_complete_pair_analysis_is_descriptive_only(self):
        out=analyze_dual_source_episode_representatives(self._rows())
        self.assertEqual(out['paired_episode_count'],65)
        self.assertEqual(out['gate'],'PASS_COMPLETE_DUAL_SOURCE_DEVELOPMENT_DESCRIPTIVE_ANALYSIS')
        self.assertFalse(out['candidate_threshold_selected'])
        self.assertIsNone(out['hard_negative_label'])
        self.assertFalse(out['risk_engine_allowed'])
        self.assertAlmostEqual(out['metric_analyses']['max_accumulation_mm']['pearson'],1.0,places=10)
        self.assertAlmostEqual(out['metric_analyses']['max_accumulation_mm']['spearman'],1.0,places=10)

    def test_missing_provider_episode_fails_closed(self):
        rows=self._rows()
        rows=[r for r in rows if not (r['local_episode_id']=='E064' and r['source_id']==IMERG)]
        with self.assertRaises(ValueError):
            analyze_dual_source_episode_representatives(rows)

    def test_duplicate_provider_episode_fails_closed(self):
        rows=self._rows()
        rows.append(dict(rows[0]))
        with self.assertRaises(ValueError):
            analyze_dual_source_episode_representatives(rows)


if __name__ == '__main__':
    unittest.main()
