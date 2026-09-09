from __future__ import annotations

import unittest
from datetime import datetime, timezone

from lpz_risk.historical_cases import (
    decode_csv_bytes,
    ingest_source_rows,
    snapshot_times,
    stable_row_hash,
)


class HistoricalCasesTest(unittest.TestCase):
    def test_utf8_csv_ingestion_preserves_raw_and_hashes(self):
        payload = (
            "解析日時,地域,値\n"
            "2025-08-10 03:20,福岡県,1\n"
            "2025-08-10 03:30,福岡県,2\n"
        ).encode("utf-8")
        report = ingest_source_rows("TEST", 2025, payload)
        self.assertEqual(report["headers"], ["解析日時", "地域", "値"])
        self.assertEqual(report["row_count"], 2)
        self.assertEqual(report["duplicate_row_hash_count"], 0)
        self.assertEqual(report["rows_with_datetime_candidates"], 2)
        self.assertEqual(report["semantic_mapping_status"], "PENDING_HEADER_AUDIT")
        self.assertEqual(report["rows"][0]["raw"]["地域"], "福岡県")

    def test_jma_update_preamble_is_not_treated_as_header(self):
        text = (
            "最終更新時刻:20260909193000\n"
            "年,月,日,時,分,地域\n"
            "2026,9,9,18,40,福岡県\n"
        )
        report = ingest_source_rows("JMA_TEST", 2026, text.encode("cp932"))
        self.assertEqual(report["header_line_number"], 2)
        self.assertEqual(report["headers"], ["年", "月", "日", "時", "分", "地域"])
        self.assertEqual(report["row_count"], 1)
        self.assertEqual(report["rows"][0]["row_number"], 3)
        self.assertEqual(report["rows"][0]["raw"]["地域"], "福岡県")
        self.assertEqual(report["source_metadata"]["last_updated_compact"], "20260909193000")
        self.assertTrue(report["source_metadata"]["last_updated_jst"].startswith("2026-09-09T19:30:00"))

    def test_cp932_decode(self):
        text = "解析日時,地域\n2025/08/10 03:20,福岡県\n"
        decoded, encoding = decode_csv_bytes(text.encode("cp932"))
        self.assertIn("福岡県", decoded)
        self.assertIn(encoding, {"cp932", "shift_jis"})

    def test_hash_is_stable_but_source_scoped(self):
        row = {"a": "1", "b": "2"}
        self.assertEqual(stable_row_hash("A", row), stable_row_hash("A", row))
        self.assertNotEqual(stable_row_hash("A", row), stable_row_hash("B", row))

    def test_snapshot_schedule_is_utc_and_exact(self):
        anchor = datetime(2025, 8, 10, 3, 0, tzinfo=timezone.utc)
        values = snapshot_times(anchor, [-180, -60, 0])
        self.assertEqual(values, [
            "2025-08-10T00:00:00Z",
            "2025-08-10T02:00:00Z",
            "2025-08-10T03:00:00Z",
        ])

    def test_blank_payload_rejected(self):
        with self.assertRaises(ValueError):
            ingest_source_rows("TEST", 2025, b"")


if __name__ == "__main__":
    unittest.main()
