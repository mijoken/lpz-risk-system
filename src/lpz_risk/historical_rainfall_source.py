"""Guardrails for historical JMA analyzed-rainfall source status.

The historical annual access path is known, but no payload is considered usable
until an actual historical file has been acquired and audited. This module keeps
that distinction machine-enforceable.
"""

from __future__ import annotations

from typing import Any


def validate_historical_rainfall_source_registry(config: dict[str, Any]) -> dict[str, Any]:
    sources = {row["source_id"]: row for row in config.get("sources", [])}
    annual = sources.get("JMA_ANALYZED_RAINFALL_ANNUAL_2017_PLUS")
    current = sources.get("JMA_ANALYZED_RAINFALL_CURRENT_GRIB2")
    failures: list[str] = []

    if annual is None:
        failures.append("annual historical analyzed-rainfall source missing")
    else:
        if annual.get("resolution") != "1km":
            failures.append("annual historical analyzed-rainfall resolution must remain 1km")
        if annual.get("coverage_start") != "2017-01-01":
            failures.append("annual historical analyzed-rainfall coverage_start changed")
        if annual.get("machine_public_web_download_assumed") is not False:
            failures.append("public machine-download route must not be assumed before proof")
        if annual.get("status") != "ACCESS_PATH_IDENTIFIED_PAYLOAD_NOT_ACQUIRED":
            failures.append("annual historical source status changed before payload audit")

    if current is None:
        failures.append("current analyzed-rainfall GRIB2 specification source missing")
    else:
        pattern = str(current.get("filename_pattern", ""))
        if "Ggis1km_Prr60lv_ANAL_grib2.bin" not in pattern:
            failures.append("current analyzed-rainfall GRIB2 filename pattern changed")
        if current.get("format") != "GRIB2":
            failures.append("current analyzed-rainfall format must remain GRIB2")

    if config.get("hard_negative_label_allowed") is not False:
        failures.append("hard-negative labeling cannot open before rainfall payload audit")
    if config.get("risk_engine_allowed") is not False:
        failures.append("risk engine must remain disabled")

    return {
        "schema_version": "0.1.0",
        "phase": "2B-historical-rainfall-source-validation",
        "execution_ok": not failures,
        "failures": failures,
        "payload_gate": config.get("payload_gate"),
        "hard_negative_label_allowed": False,
        "risk_engine_allowed": False,
    }
