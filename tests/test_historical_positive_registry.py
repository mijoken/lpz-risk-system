from __future__ import annotations

import unittest

from lpz_risk.historical_positive_registry import (
    EXPECTED_HEADERS,
    build_positive_registry,
    normalize_detection_row,
)


def source_block(rows):
    return {
        "source": {"source_id": "JMA_LPZ_2025", "year": 2025},
        "parsed": {"headers": EXPECTED_HEADERS, "rows": rows},
    }


def row(raw, row_number=3, sha="a" * 64):
    return {"row_number": row_number, "row_sha256": sha, "raw": raw}


class HistoricalPositiveRegistryTest(unittest.TestCase):
    def test_normalizes_realized_detection(self):
        raw = {
            "年": "2025", "月": "8", "日": "7", "時": "4", "分": "50",
            "府県予報区": "石川県", "一次細分区域": "加賀", "一次細分区域コード": "170010",
            "実況基準到達": "0", "10分先基準到達": "10", "20分先基準到達": "", "30分先基準到達": "30",
        }
        out = normalize_detection_row(source_block([]), row(raw))
        self.assertTrue(out["realized_current_time_positive"])
        self.assertEqual(out["criterion_reached_offsets_minutes"], [0, 10, 30])
        self.assertEqual(out["analysis_time_jst"], "2025-08-07T04:50:00+09:00")
        self.assertEqual(out["analysis_time_utc"], "2025-08-06T19:50:00Z")
        self.assertIsNone(out["event_episode_id"])

    def test_forecast_only_row_not_promoted_to_realized_anchor(self):
        raw = {
            "年": "2025", "月": "6", "日": "9", "時": "19", "分": "0",
            "府県予報区": "鹿児島県（奄美地方除く）", "一次細分区域": "大隅地方", "一次細分区域コード": "460020",
            "実況基準到達": "", "10分先基準到達": "", "20分先基準到達": "", "30分先基準到達": "30",
        }
        audit = {"execution_ok": True, "sources": [source_block([row(raw)])]}
        registry = build_positive_registry(audit, [-180, -60, 0])
        self.assertEqual(registry["detection_row_count"], 1)
        self.assertEqual(registry["realized_positive_anchor_count"], 0)
        self.assertEqual(registry["forecast_only_detection_row_count"], 1)

    def test_anchor_snapshot_schedule_uses_realized_time(self):
        raw = {
            "年": "2025", "月": "8", "日": "7", "時": "4", "分": "50",
            "府県予報区": "石川県", "一次細分区域": "加賀", "一次細分区域コード": "170010",
            "実況基準到達": "0", "10分先基準到達": "", "20分先基準到達": "", "30分先基準到達": "",
        }
        audit = {"execution_ok": True, "sources": [source_block([row(raw)])]}
        registry = build_positive_registry(audit, [-180, -120, -60, 0])
        anchor = registry["realized_positive_anchors"][0]
        self.assertEqual(anchor["snapshot_times_utc"], [
            "2025-08-06T16:50:00Z",
            "2025-08-06T17:50:00Z",
            "2025-08-06T18:50:00Z",
            "2025-08-06T19:50:00Z",
        ])
        self.assertEqual(anchor["episode_grouping_status"], "NOT_GROUPED")

    def test_rejects_unexpected_headers(self):
        bad = source_block([])
        bad["parsed"]["headers"] = ["年"]
        raw = {"年": "2025"}
        with self.assertRaises(ValueError):
            normalize_detection_row(bad, row(raw))

    def test_rejects_marker_column_mismatch(self):
        raw = {
            "年": "2025", "月": "8", "日": "7", "時": "4", "分": "50",
            "府県予報区": "石川県", "一次細分区域": "加賀", "一次細分区域コード": "170010",
            "実況基準到達": "", "10分先基準到達": "20", "20分先基準到達": "", "30分先基準到達": "",
        }
        with self.assertRaises(ValueError):
            normalize_detection_row(source_block([]), row(raw))


if __name__ == "__main__":
    unittest.main()
