#!/usr/bin/env python3
"""Authenticate zero-cost historical precipitation providers without exposing secrets."""

from __future__ import annotations

import argparse
import ftplib
import json
import os
from pathlib import Path


def _gsmap_probe() -> dict:
    user = os.environ.get("GSMAP_FTP_USERNAME")
    password = os.environ.get("GSMAP_FTP_PASSWORD")
    host = os.environ.get("GSMAP_FTP_HOST", "hokusai.eorc.jaxa.jp")
    if not user or not password:
        return {
            "source_id": "GSMAP_STANDARD_V8",
            "gate": "BLOCKED_MISSING_GITHUB_SECRETS",
            "credential_present": False,
            "host": host,
            "secret_value_recorded": False,
        }

    try:
        with ftplib.FTP(timeout=45) as ftp:
            ftp.connect(host, 21)
            ftp.login(user, password)
            root = ftp.nlst()
        return {
            "source_id": "GSMAP_STANDARD_V8",
            "gate": "GSMAP_FTP_AUTH_PASS",
            "credential_present": True,
            "host": host,
            "root_entries": sorted(root)[:50],
            "root_entry_count": len(root),
            "standard_directory_visible": any(str(x).rstrip("/").endswith("standard") for x in root),
            "secret_value_recorded": False,
        }
    except Exception as exc:
        return {
            "source_id": "GSMAP_STANDARD_V8",
            "gate": "BLOCKED_GSMAP_FTP_AUTH_OR_TRANSPORT",
            "credential_present": True,
            "host": host,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "secret_value_recorded": False,
        }


def _imerg_probe() -> dict:
    username = os.environ.get("EARTHDATA_USERNAME")
    password = os.environ.get("EARTHDATA_PASSWORD")
    if not username or not password:
        return {
            "source_id": "NASA_IMERG_FINAL_V07",
            "gate": "BLOCKED_MISSING_GITHUB_SECRETS",
            "credential_present": False,
            "secret_value_recorded": False,
        }

    try:
        import earthaccess

        auth = earthaccess.login(strategy="environment")
        if not bool(getattr(auth, "authenticated", False)):
            raise RuntimeError("earthaccess authentication returned authenticated=False")

        granules = earthaccess.search_data(
            short_name="GPM_3IMERGHH_07",
            bounding_box=(129.0, 30.0, 146.0, 46.0),
            temporal=("2025-07-01T00:00:00Z", "2025-07-01T01:00:00Z"),
            count=1,
        )
        return {
            "source_id": "NASA_IMERG_FINAL_V07",
            "gate": "EARTHDATA_AUTH_AND_IMERG_SEARCH_PASS" if granules else "BLOCKED_IMERG_SEARCH_EMPTY",
            "credential_present": True,
            "authenticated": True,
            "granule_count": len(granules),
            "short_name": "GPM_3IMERGHH_07",
            "secret_value_recorded": False,
        }
    except Exception as exc:
        return {
            "source_id": "NASA_IMERG_FINAL_V07",
            "gate": "BLOCKED_EARTHDATA_AUTH_OR_IMERG_SEARCH",
            "credential_present": True,
            "authenticated": False,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "secret_value_recorded": False,
        }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", default="reports/historical/free_precipitation_auth_probe.json")
    args = p.parse_args()

    report = {
        "schema_version": "0.1.0",
        "phase": "2E-zero-cost-precip-auth",
        "zero_cost_required": True,
        "providers": [_gsmap_probe(), _imerg_probe()],
        "risk_score": None,
        "lpz_classification": None,
        "risk_engine_allowed": False,
    }
    report["all_required_auth_pass"] = all(
        x["gate"] in {"GSMAP_FTP_AUTH_PASS", "EARTHDATA_AUTH_AND_IMERG_SEARCH_PASS"}
        for x in report["providers"]
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_required_auth_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
