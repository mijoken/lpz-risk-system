#!/usr/bin/env python3
"""Build a safe Phase 2L-O5 bootstrap source-health report for Pages deploy.

This is deployment plumbing only. It deliberately does not probe live weather
sources and does not authenticate to Earthdata. O6 replaces this bootstrap with
the production Source Health pipeline.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "data_sources.json"
DEFAULT_OUTPUT = ROOT / "reports" / "public" / "o5_bootstrap_source_health.json"
EXPECTED_VALIDATION = "DEFERRED_PENDING_IMERG_FINAL_V08"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    json.loads(text)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    sources = config.get("sources")
    if not isinstance(sources, list) or not sources:
        raise RuntimeError("config/data_sources.json has no sources")

    live_rows = []
    mandatory_count = 0
    for source in sources:
        source_id = str(source.get("id") or "")
        name = str(source.get("name") or source_id)
        role = str(source.get("role") or "UNKNOWN")
        if not source_id:
            raise RuntimeError("source without id in data_sources.json")
        if role == "LIVE_MANDATORY":
            mandatory_count += 1
        live_rows.append(
            {
                "source_id": source_id,
                "source_name": name,
                "role": role,
                "health": "UNKNOWN",
                "probe_status": None,
                "data_time": None,
                "data_age_seconds": None,
                "freshness_limit_seconds": None,
                "reason": "NOT_PROBED_IN_O5_DEPLOY_ONLY",
                "error": None,
            }
        )

    report = {
        "schema_version": "1.0.0",
        "phase": "2L-O5-pages-deploy-bootstrap-source-health",
        "generated_at_utc": utc_now(),
        "gate": "BOOTSTRAP_PUBLIC_STATUS_ONLY",
        "purpose": (
            "Provide a safe non-live source-health input so GitHub Pages deployment "
            "can be tested before the O6 production Source Health cycle is enabled."
        ),
        "live_source_health": live_rows,
        "earthdata_imerg_research_source": {
            "source_id": "nasa_earthdata_imerg",
            "authentication": "UNKNOWN",
            "imerg_final_v07_metadata": "UNKNOWN",
            "imerg_final_v08_metadata": "NOT_PROBED_IN_O5",
            "v8_available": False,
            "health": "UNKNOWN",
            "operational_requirement": "RESEARCH_DEFERRED_NOT_LIVE_MANDATORY",
        },
        "summary": {
            "configured_live_mandatory_count": mandatory_count,
            "live_mandatory_pass_count": 0,
            "configured_supplementary_count": len(live_rows) - mandatory_count,
            "operational_source_ready": False,
            "research_validation_status": EXPECTED_VALIDATION,
            "imerg_final_v08_available_by_metadata_probe": False,
            "2025_era5_environment_opened": False,
            "primary_confirmatory_test_run": False,
            "risk_engine_allowed": False,
        },
        "policy": {
            "bootstrap_is_not_live_source_health": True,
            "o6_must_replace_bootstrap_before_production_monitoring": True,
            "risk_engine_remains_locked": True,
        },
    }

    atomic_write_json(args.output.resolve(), report)
    print(f"O5 bootstrap source health written: {args.output.resolve()}")
    print("Live source probes                 : NOT RUN")
    print("Earthdata authentication           : NOT RUN")
    print("Risk engine                        : NOT ALLOWED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
