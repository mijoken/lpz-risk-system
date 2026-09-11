#!/usr/bin/env python3
"""Phase 2L-I: open the frozen 2025 validation Positive registry only.

This is the first post-freeze read of validation-year outcome labels.

It deliberately:
- reads only the JMA 2025 official LPZ CSV,
- does NOT read 2026 retrospective/prospective data,
- does NOT read ERA5,
- does NOT read validation rainfall outcomes beyond the official LPZ label CSV,
- does NOT alter the frozen Primary hypothesis,
- does NOT select thresholds,
- does NOT enable the risk engine.

Outputs are local research inputs for later rainfall-matched validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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
from lpz_risk.historical_positive_registry import build_positive_registry  # noqa: E402
from lpz_risk.historical_episodes import build_local_positive_episodes  # noqa: E402


USER_AGENT = "lpz-risk-system/0.1.0 (+https://github.com/mijoken/lpz-risk-system)"
TIMEOUT_SECONDS = 30
MAX_BYTES = 4 * 1024 * 1024

EXPECTED_FREEZE_GATE = (
    "PASS_PHASE2L_H_DISCOVERY_AND_VALIDATION_PROTOCOL_FREEZE_"
    "PRIMARY_Q850_T0H"
)
PASS_GATE = "PASS_PHASE2L_I_2025_VALIDATION_POSITIVE_REGISTRY_OPENED"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    # Validate before canonical write.
    json.loads(text)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def download(url: str) -> tuple[bytes, dict[str, Any]]:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/csv,text/plain,*/*",
        },
    )
    with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        body = response.read(MAX_BYTES + 1)
        status = int(getattr(response, "status", 200))
        content_type = response.headers.get("Content-Type")
        last_modified = response.headers.get("Last-Modified")

    if len(body) > MAX_BYTES:
        raise ValueError("JMA validation CSV exceeded byte safety limit")

    return body, {
        "http_status": status,
        "bytes": len(body),
        "content_type": content_type,
        "last_modified": last_modified,
        "sha256": sha256_bytes(body),
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--case-config",
        default="config/historical_case_sources.json",
    )
    p.add_argument(
        "--split-policy",
        default="config/historical_split_policy.json",
    )
    p.add_argument(
        "--freeze",
        default=(
            "research/phase2/"
            "phase2l_h_validation_protocol_freeze_20260911.json"
        ),
    )
    p.add_argument(
        "--output-dir",
        default="local_data/phase2l_i_2025_validation_positive_registry",
    )
    a = p.parse_args()

    case_config_path = Path(a.case_config)
    split_policy_path = Path(a.split_policy)
    freeze_path = Path(a.freeze)
    outdir = Path(a.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if freeze.get("gate") != EXPECTED_FREEZE_GATE:
        raise ValueError(
            "Phase 2L-H freeze gate mismatch: "
            f"{freeze.get('gate')}"
        )
    if (
        freeze.get("validation_period", {}).get("year") != 2025
        or freeze.get("validation_period", {}).get("status_at_freeze")
        != "UNTOUCHED_FOR_THIS_ANALYSIS"
    ):
        raise ValueError("2025 validation freeze metadata is not intact")
    if freeze.get("primary_hypothesis", {}).get("metric") != "q850_mean_kgkg":
        raise ValueError("frozen Primary metric changed unexpectedly")
    if freeze.get("primary_hypothesis", {}).get("contrast") != "t+0h":
        raise ValueError("frozen Primary contrast changed unexpectedly")

    case_config = json.loads(case_config_path.read_text(encoding="utf-8"))
    split_policy = json.loads(split_policy_path.read_text(encoding="utf-8"))

    sources_2025 = [
        row
        for row in case_config["positive_sources"]
        if str(row.get("source_id")) == "JMA_LPZ_2025"
        and int(row.get("year")) == 2025
    ]
    if len(sources_2025) != 1:
        raise ValueError(
            f"expected exactly one JMA_LPZ_2025 source, got {len(sources_2025)}"
        )

    source = sources_2025[0]
    url = str(source["url"])

    payload, transport = download(url)
    parsed = ingest_source_rows("JMA_LPZ_2025", 2025, payload)

    source_audit = {
        "schema_version": "0.1.0",
        "phase": "2L-I-2025-validation-positive-source-audit",
        "generated_at": utc_now(),
        "execution_ok": True,
        "source_count_expected": 1,
        "source_count_success": 1,
        "total_source_rows": int(parsed["row_count"]),
        "sources": [
            {
                "source": source,
                "transport": transport,
                "parsed": parsed,
            }
        ],
        "failures": [],
        "snapshot_offsets_minutes": list(
            case_config["snapshot_offsets_minutes"]
        ),
        "validation_year_opened": 2025,
        "retrospective_2026_read": False,
        "prospective_holdout_read": False,
        "risk_engine_allowed": False,
    }

    positive_registry = build_positive_registry(
        source_audit,
        list(case_config["snapshot_offsets_minutes"]),
    )

    episodes = build_local_positive_episodes(
        positive_registry,
        split_policy,
    )

    assignment_by_anchor = {
        str(r["anchor_id"]): r
        for r in episodes["anchor_episode_assignments"]
    }

    anchor_rows: list[dict[str, Any]] = []
    for anchor in positive_registry["realized_positive_anchors"]:
        aid = str(anchor["anchor_id"])
        assignment = assignment_by_anchor[aid]
        anchor_rows.append(
            {
                "anchor_id": aid,
                "local_episode_id": assignment["local_episode_id"],
                "analysis_time_utc": anchor["analysis_time_utc"],
                "analysis_time_jst": anchor["analysis_time_jst"],
                "date_utc_direct": str(anchor["analysis_time_utc"])[:10],
                "forecast_area": anchor["forecast_area"],
                "primary_subdivision": anchor["primary_subdivision"],
                "primary_subdivision_code": str(
                    anchor["primary_subdivision_code"]
                ).zfill(6),
                "temporal_split": assignment["temporal_split"],
                "label_provenance": "JMA_OFFICIAL_LPZ_CASE_CSV_2025",
            }
        )

    split_counts: dict[str, int] = {}
    for row in anchor_rows:
        split_counts[row["temporal_split"]] = (
            split_counts.get(row["temporal_split"], 0) + 1
        )

    invalid_split_rows = [
        row
        for row in anchor_rows
        if row["temporal_split"]
        not in {"VALIDATION", "BOUNDARY_EMBARGO"}
    ]
    if invalid_split_rows:
        raise AssertionError(
            "2025 source produced rows outside VALIDATION/BOUNDARY_EMBARGO: "
            f"{invalid_split_rows[:5]}"
        )

    validation_anchors = [
        r for r in anchor_rows if r["temporal_split"] == "VALIDATION"
    ]

    # Collapse to validation region-days only; episode multiplicity is preserved.
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in validation_anchors:
        key = (
            row["date_utc_direct"],
            row["primary_subdivision_code"],
        )
        slot = grouped.setdefault(
            key,
            {
                "date_utc": key[0],
                "primary_subdivision_code": key[1],
                "anchor_ids": [],
                "local_episode_ids": [],
                "analysis_times_utc": [],
            },
        )
        slot["anchor_ids"].append(row["anchor_id"])
        slot["local_episode_ids"].append(row["local_episode_id"])
        slot["analysis_times_utc"].append(row["analysis_time_utc"])

    region_day_rows: list[dict[str, Any]] = []
    for key in sorted(grouped):
        slot = grouped[key]
        region_day_rows.append(
            {
                "date_utc": slot["date_utc"],
                "primary_subdivision_code": slot["primary_subdivision_code"],
                "anchor_count": len(set(slot["anchor_ids"])),
                "local_episode_count": len(
                    set(slot["local_episode_ids"])
                ),
                "anchor_ids": "|".join(
                    sorted(set(slot["anchor_ids"]))
                ),
                "local_episode_ids": "|".join(
                    sorted(set(slot["local_episode_ids"]))
                ),
                "analysis_times_utc": "|".join(
                    sorted(set(slot["analysis_times_utc"]))
                ),
                "role": "VALIDATION_POSITIVE_REGION_DAY",
            }
        )

    source_audit_path = outdir / "phase2l_i_2025_source_audit.json"
    positive_registry_path = (
        outdir / "phase2l_i_2025_positive_registry.json"
    )
    episodes_path = outdir / "phase2l_i_2025_local_episodes.json"
    anchors_csv_path = outdir / "phase2l_i_2025_positive_anchors.csv"
    region_days_csv_path = (
        outdir / "phase2l_i_2025_positive_region_days.csv"
    )
    report_path = outdir / "phase2l_i_2025_validation_open_report.json"

    write_json(source_audit_path, source_audit)
    write_json(positive_registry_path, positive_registry)
    write_json(episodes_path, episodes)

    anchor_fields = [
        "anchor_id",
        "local_episode_id",
        "analysis_time_utc",
        "analysis_time_jst",
        "date_utc_direct",
        "forecast_area",
        "primary_subdivision",
        "primary_subdivision_code",
        "temporal_split",
        "label_provenance",
    ]
    write_csv(anchors_csv_path, anchor_rows, anchor_fields)

    region_day_fields = [
        "date_utc",
        "primary_subdivision_code",
        "anchor_count",
        "local_episode_count",
        "anchor_ids",
        "local_episode_ids",
        "analysis_times_utc",
        "role",
    ]
    write_csv(
        region_days_csv_path,
        region_day_rows,
        region_day_fields,
    )

    report = {
        "schema_version": "1.0.0",
        "phase": "2L-I-2025-validation-positive-registry-open",
        "gate": PASS_GATE,
        "freeze_gate_verified": True,
        "freeze_primary_metric": "q850_mean_kgkg",
        "freeze_primary_contrast": "t+0h",
        "jma_source_id": "JMA_LPZ_2025",
        "jma_source_url": url,
        "jma_payload_sha256": transport["sha256"],
        "jma_source_row_count": int(parsed["row_count"]),
        "realized_positive_anchor_count_all_2025_source": int(
            positive_registry["realized_positive_anchor_count"]
        ),
        "local_episode_count_all_2025_source": int(
            episodes["local_episode_count"]
        ),
        "split_anchor_counts": split_counts,
        "validation_positive_anchor_count": len(validation_anchors),
        "validation_positive_region_day_count": len(region_day_rows),
        "boundary_embargo_anchor_count": int(
            split_counts.get("BOUNDARY_EMBARGO", 0)
        ),
        "environment_variables_read": False,
        "validation_rainfall_matching_performed": False,
        "threshold_selected": False,
        "primary_hypothesis_changed": False,
        "retrospective_2026_read": False,
        "prospective_holdout_read": False,
        "risk_engine_allowed": False,
        "outputs": {
            "source_audit": str(source_audit_path),
            "positive_registry": str(positive_registry_path),
            "local_episodes": str(episodes_path),
            "positive_anchors_csv": str(anchors_csv_path),
            "positive_region_days_csv": str(region_days_csv_path),
        },
    }
    write_json(report_path, report)

    print("=" * 92)
    print("LPZ PHASE 2L-I — 2025 VALIDATION POSITIVE REGISTRY OPEN")
    print("=" * 92)
    print("Freeze gate                     : VERIFIED")
    print("Frozen Primary                  : q850_mean_kgkg @ t+0h")
    print(f"JMA 2025 source rows            : {int(parsed['row_count'])}")
    print(
        "Realized Positive anchors      : "
        f"{positive_registry['realized_positive_anchor_count']}"
    )
    print(
        "Local Positive episodes        : "
        f"{episodes['local_episode_count']}"
    )
    print(f"Split anchor counts             : {split_counts}")
    print(
        "Validation Positive anchors    : "
        f"{len(validation_anchors)}"
    )
    print(
        "Validation Positive region-days: "
        f"{len(region_day_rows)}"
    )
    print(
        "Boundary embargo anchors       : "
        f"{split_counts.get('BOUNDARY_EMBARGO', 0)}"
    )
    print("")
    print("ERA5/environment read           : NO")
    print("Rainfall matching performed     : NO")
    print("Primary changed                 : NO")
    print("Threshold selected              : NO")
    print("2026 retrospective read         : NO")
    print("Prospective holdout read        : NO")
    print("Risk engine                     : NOT ALLOWED")
    print("")
    print(f"Positive region-days            : {region_days_csv_path}")
    print(f"Report                          : {report_path}")
    print("")
    print(f"Gate                            : {PASS_GATE}")
    print("=" * 92)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
