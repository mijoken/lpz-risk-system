#!/usr/bin/env python3
"""Acquire official JMA LPZ CSVs and build a conservative source registry.

Phase 2A does NOT guess the semantic meaning of unseen CSV columns. It records
headers, row hashes, source metadata, and machine-detectable datetime candidates.
After the live header audit, a separate mapping step may promote rows into
normalized positive cases.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.historical_cases import ingest_source_rows  # noqa: E402

USER_AGENT = "lpz-risk-system/0.1.0 (+https://github.com/mijoken/lpz-risk-system)"
TIMEOUT_SECONDS = 30
MAX_BYTES = 4 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def download(url: str) -> tuple[bytes, dict[str, Any]]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,text/plain,*/*"})
    with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        body = response.read(MAX_BYTES + 1)
        status = int(getattr(response, "status", 200))
        content_type = response.headers.get("Content-Type")
        last_modified = response.headers.get("Last-Modified")
    if len(body) > MAX_BYTES:
        raise ValueError("historical CSV exceeded byte safety limit")
    return body, {
        "http_status": status,
        "bytes": len(body),
        "content_type": content_type,
        "last_modified": last_modified,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/historical_case_sources.json")
    parser.add_argument("--output", default="reports/historical/historical_case_source_registry.json")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    source_results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for source in config["positive_sources"]:
        source_id = str(source["source_id"])
        url = str(source["url"])
        year = int(source["year"])
        try:
            payload, transport = download(url)
            parsed = ingest_source_rows(source_id, year, payload)
            source_results.append({
                "source": source,
                "transport": transport,
                "parsed": parsed,
            })
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            failures.append({"source_id": source_id, "url": url, "error": f"{type(exc).__name__}: {exc}"})

    total_rows = sum(int(item["parsed"]["row_count"]) for item in source_results)
    report = {
        "schema_version": "0.1.0",
        "phase": "2A-historical-case-registry-source-audit",
        "generated_at": utc_now(),
        "execution_ok": not failures and len(source_results) == len(config["positive_sources"]),
        "source_count_expected": len(config["positive_sources"]),
        "source_count_success": len(source_results),
        "total_source_rows": total_rows,
        "sources": source_results,
        "failures": failures,
        "positive_semantic_mapping_complete": False,
        "hard_negative_registry_complete": False,
        "snapshot_offsets_minutes": config["snapshot_offsets_minutes"],
        "risk_engine_allowed": False,
        "gates": {
            "official_positive_source_transport": not failures,
            "actual_csv_header_audit": bool(source_results),
            "positive_semantic_mapping": False,
            "hard_negative_selection": False,
            "historical_snapshot_reconstruction": False,
            "final_holdout_frozen": False,
            "risk_engine_allowed": False
        }
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "execution_ok": report["execution_ok"],
        "source_count_success": report["source_count_success"],
        "total_source_rows": report["total_source_rows"],
        "headers": {item["source"]["source_id"]: item["parsed"]["headers"] for item in source_results},
        "failures": failures,
        "gates": report["gates"],
    }, ensure_ascii=False, indent=2))
    print(f"report={output}")
    return 0 if report["execution_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
