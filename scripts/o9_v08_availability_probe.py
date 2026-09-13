#!/usr/bin/env python3
"""O9-A — metadata-only proof of official NASA IMERG Final V08 availability.

This probe intentionally does not download rainfall payloads, read ERA5, perform
matching, or execute the frozen Primary.  Full temporal coverage is a separate
O9-C gate; finding one official V08 granule only opens the coverage-check stage.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SHORT_NAME = "GPM_3IMERGHH"
VERSION = "08"
PASS_GATE = "PASS_O9_A_V08_OFFICIAL_FINAL_AVAILABILITY"
WAIT_GATE = "WAIT_O9_A_IMERG_FINAL_V08_NOT_FOUND"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_granule_summary(g: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    # earthaccess granules expose UMM metadata in current releases, but keep the
    # probe defensive because the client representation may evolve.
    umm = getattr(g, "umm", None)
    if isinstance(umm, dict):
        out["granule_ur"] = umm.get("GranuleUR")
        temporal = umm.get("TemporalExtent", {})
        if isinstance(temporal, dict):
            rng = temporal.get("RangeDateTime", {})
            if isinstance(rng, dict):
                out["beginning_datetime"] = rng.get("BeginningDateTime")
                out["ending_datetime"] = rng.get("EndingDateTime")
        collection = umm.get("CollectionReference", {})
        if isinstance(collection, dict):
            out["collection_short_name"] = collection.get("ShortName")
            out["collection_version"] = collection.get("Version")
    concept_id = getattr(g, "concept_id", None)
    if concept_id:
        out["concept_id"] = str(concept_id)
    return out


def probe(
    *,
    start_utc: str = "2025-10-01T00:00:00Z",
    end_utc: str = "2025-10-01T01:00:00Z",
) -> dict[str, Any]:
    import earthaccess

    auth = earthaccess.login()
    authenticated = bool(getattr(auth, "authenticated", False))
    if not authenticated:
        return {
            "schema_version": "1.0.0",
            "phase": "O9-A-v08-official-final-availability",
            "gate": "WAIT_O9_A_EARTHDATA_AUTHENTICATION_REQUIRED",
            "generated_at_utc": utc_now(),
            "short_name": SHORT_NAME,
            "imerg_final_version": VERSION,
            "official_final_product": True,
            "metadata_result_count": 0,
            "authenticated": False,
            "risk_engine_allowed": False,
        }

    granules = earthaccess.search_data(
        short_name=SHORT_NAME,
        version=VERSION,
        temporal=(start_utc, end_utc),
        count=5,
    )
    count = len(granules)
    return {
        "schema_version": "1.0.0",
        "phase": "O9-A-v08-official-final-availability",
        "gate": PASS_GATE if count >= 1 else WAIT_GATE,
        "generated_at_utc": utc_now(),
        "short_name": SHORT_NAME,
        "imerg_final_version": VERSION,
        "official_final_product": True,
        "product_identity_basis": (
            "NASA_EARTHDATA_EXACT_SHORT_NAME_GPM_3IMERGHH_AND_VERSION_08_METADATA_QUERY"
        ),
        "probe_temporal_start_utc": start_utc,
        "probe_temporal_end_utc": end_utc,
        "metadata_result_count": int(count),
        "representative_granule": _safe_granule_summary(granules[0]) if count else None,
        "full_required_coverage_proven": False,
        "next_gate": "O9-C_FULL_REQUIRED_V08_COVERAGE",
        "validation_era5_environment_read": False,
        "primary_confirmatory_test_run": False,
        "risk_engine_allowed": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start-utc", default="2025-10-01T00:00:00Z")
    ap.add_argument("--end-utc", default="2025-10-01T01:00:00Z")
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    try:
        report = probe(start_utc=args.start_utc, end_utc=args.end_utc)
    except Exception as exc:  # noqa: BLE001
        report = {
            "schema_version": "1.0.0",
            "phase": "O9-A-v08-official-final-availability",
            "gate": "WAIT_O9_A_METADATA_PROBE_ERROR",
            "generated_at_utc": utc_now(),
            "short_name": SHORT_NAME,
            "imerg_final_version": VERSION,
            "official_final_product": True,
            "metadata_result_count": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "validation_era5_environment_read": False,
            "primary_confirmatory_test_run": False,
            "risk_engine_allowed": False,
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"O9-A gate={report['gate']}")
    return 0 if report["gate"] == PASS_GATE else 3


if __name__ == "__main__":
    raise SystemExit(main())
