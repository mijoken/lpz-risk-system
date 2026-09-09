#!/usr/bin/env python3
"""Scientifically decode an authenticated ERA5 GRIB proof payload."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.era5_science import (  # noqa: E402
    decode_era5_pressure_fields,
    validate_era5_required_fields,
    era5_environment_descriptors,
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", default="reports/historical/era5_probe.grib")
    p.add_argument("--output", default="reports/historical/era5_scientific_decode.json")
    a = p.parse_args()

    try:
        fields = decode_era5_pressure_fields(a.input)
        validation = validate_era5_required_fields(fields)
        if not validation["required_fields_pass"]:
            raise ValueError(f"required ERA5 fields failed validation: {validation}")
        descriptors = era5_environment_descriptors(fields)
        report = {
            "schema_version": "0.1.0",
            "phase": "2B-era5-scientific-decode",
            "execution_ok": True,
            "source": "ERA5",
            "exactness": "PROXY_REANALYSIS",
            "validation": validation,
            "environment_descriptors": descriptors,
            "historical_environment_payload_gate": "PASS_ONE_REQUEST_PROOF",
            "risk_engine_allowed": False,
        }
        ok = True
    except Exception as exc:
        report = {
            "schema_version": "0.1.0",
            "phase": "2B-era5-scientific-decode",
            "execution_ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "historical_environment_payload_gate": "FAIL",
            "risk_engine_allowed": False,
        }
        ok = False

    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "execution_ok": report.get("execution_ok"),
        "historical_environment_payload_gate": report.get("historical_environment_payload_gate"),
        "error": report.get("error"),
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
