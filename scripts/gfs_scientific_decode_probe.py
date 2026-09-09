#!/usr/bin/env python3
"""Phase 1C proof: download and scientifically decode evidence-driven GFS fields."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.gfs_science import (  # noqa: E402
    build_science_subset_url,
    cycle_candidates,
    decode_pressure_fields,
    expected_low_ambiguity_keys,
    kato_midlevel_rh_diagnostic,
    low_level_moisture_stack_diagnostic,
    missing_expected_keys,
    wind_field_diagnostic,
)

USER_AGENT = "lpz-risk-system/0.1.0 (+https://github.com/mijoken/lpz-risk-system)"
MAX_BYTES = 32 * 1024 * 1024
TIMEOUT_SECONDS = 50


def iso_utc(dt) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def download_grib(url: str, target: Path) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream,*/*"})
    started = time.perf_counter()
    with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        status = int(getattr(response, "status", 200))
        body = response.read(MAX_BYTES + 1)
    latency_ms = int((time.perf_counter() - started) * 1000)
    if len(body) > MAX_BYTES:
        raise ValueError(f"GFS scientific subset exceeded {MAX_BYTES} byte safety limit")
    if not body.startswith(b"GRIB"):
        raise ValueError(f"response did not begin with GRIB signature: {body[:32]!r}")
    target.write_bytes(body)
    return {"http_status": status, "bytes": len(body), "latency_ms": latency_ms}


def field_key_text(key) -> str:
    return f"{key.short_name}@{key.level_hpa}hPa"


def run() -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    success_cycle = None
    success_url = None
    transport = None
    decoded = None

    with tempfile.TemporaryDirectory(prefix="lpz-gfs-") as temp_dir:
        target = Path(temp_dir) / "gfs_science.grib2"
        for cycle in cycle_candidates(count=8):
            url = build_science_subset_url(cycle, forecast_hour=1)
            try:
                transport = download_grib(url, target)
                fields = decode_pressure_fields(target)
                missing = missing_expected_keys(fields)
                if missing:
                    attempts.append(
                        {
                            "cycle": iso_utc(cycle),
                            "transport": transport,
                            "decode": "INCOMPLETE",
                            "missing": sorted(field_key_text(k) for k in missing),
                        }
                    )
                    continue
                success_cycle = cycle
                success_url = url
                decoded = fields
                break
            except (HTTPError, URLError, TimeoutError, ValueError, OSError, RuntimeError) as exc:
                attempts.append(
                    {
                        "cycle": iso_utc(cycle),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        if decoded is None or success_cycle is None or success_url is None or transport is None:
            return {
                "schema_version": "0.1.0",
                "phase": "1C-gfs-scientific-decode-proof",
                "ok": False,
                "attempts": attempts,
                "gates": {
                    "grib_transport": False,
                    "eccodes_decode": False,
                    "required_fields_present": False,
                    "risk_engine_allowed": False,
                },
            }

        expected = expected_low_ambiguity_keys()
        summaries = {
            field_key_text(key): decoded[key].summary()
            for key in sorted(expected, key=lambda k: (k.level_hpa, k.short_name))
        }
        rh = kato_midlevel_rh_diagnostic(decoded)
        wind600 = wind_field_diagnostic(decoded, 600)
        wind850 = wind_field_diagnostic(decoded, 850)
        moisture_stack = low_level_moisture_stack_diagnostic(decoded)

        grid_sizes = sorted({field.values.size for key, field in decoded.items() if key in expected})
        grid_coordinate_match = len(grid_sizes) == 1
        required_finite = all(summary["finite_points"] > 0 for summary in summaries.values())

        gates = {
            "grib_transport": True,
            "eccodes_decode": True,
            "required_fields_present": True,
            "required_fields_have_finite_values": required_finite,
            "required_fields_share_point_count": grid_coordinate_match,
            "kato_midlevel_rh_exact": bool(rh["valid_grid_points"] > 0),
            "wind_600hpa_exact": bool(wind600.get("valid_grid_points", 0) > 0),
            "wind_850hpa_exact": bool(wind850.get("valid_grid_points", 0) > 0),
            "tahara_iwvf_raw_stack_exact": bool(moisture_stack["raw_stack_exact"]),
            "tahara_iwvf_formula": False,
            "kato_flwv500_exact": False,
            "sreh03_exact": False,
            "risk_engine_allowed": False,
        }
        proof_ok = all(
            gates[name]
            for name in (
                "grib_transport",
                "eccodes_decode",
                "required_fields_present",
                "required_fields_have_finite_values",
                "required_fields_share_point_count",
                "kato_midlevel_rh_exact",
                "wind_600hpa_exact",
                "wind_850hpa_exact",
                "tahara_iwvf_raw_stack_exact",
            )
        )

        return {
            "schema_version": "0.1.0",
            "phase": "1C-gfs-scientific-decode-proof",
            "ok": proof_ok,
            "cycle": iso_utc(success_cycle),
            "forecast_hour": 1,
            "valid_time": iso_utc(success_cycle + __import__("datetime").timedelta(hours=1)),
            "source_url": success_url,
            "transport": transport,
            "attempts_before_success": attempts,
            "expected_field_count": len(expected),
            "decoded_message_count": len(decoded),
            "field_summaries": summaries,
            "diagnostics": {
                "KATO2020_MID_RH": rh,
                "SHIMAMURA2025_WIND600_INPUT": wind600,
                "KATO2005_WIND850_INPUT": wind850,
                "TAHARA2026_IWVF_INPUT_STACK": moisture_stack,
            },
            "gates": gates,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="reports/scientific/gfs_scientific_decode.json",
    )
    args = parser.parse_args()

    report = run()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report.get("ok"), "gates": report.get("gates"), "cycle": report.get("cycle")}, indent=2))
    print(f"report={output}")
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
