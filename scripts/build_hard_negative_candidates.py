#!/usr/bin/env python3
"""Build an UNCONFIRMED hard-negative candidate registry from rainfall screening records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lpz_risk.hard_negative_candidates import build_hard_negative_candidates


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--screening-records", required=True, help="JSON containing a list or {'records': [...]} of THREE_HOUR_RAINFALL_SCREENING_RECORD entities")
    p.add_argument("--positive-registry", required=True)
    p.add_argument("--policy", default="config/hard_negative_candidate_policy.json")
    p.add_argument("--output", default="reports/historical/hard_negative_candidate_registry.json")
    a = p.parse_args()

    raw = json.loads(Path(a.screening_records).read_text(encoding="utf-8"))
    records = raw if isinstance(raw, list) else raw.get("records", [])
    positive = json.loads(Path(a.positive_registry).read_text(encoding="utf-8"))
    policy = json.loads(Path(a.policy).read_text(encoding="utf-8"))
    result = build_hard_negative_candidates(records, positive, policy)

    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "screening_record_count": result["screening_record_count"],
        "broad_candidate_count": result["broad_candidate_count"],
        "excluded_near_positive_count": result["excluded_near_positive_count"],
        "eligible_unconfirmed_candidate_count": result["eligible_unconfirmed_candidate_count"],
        "hard_negative_registry_complete": result["hard_negative_registry_complete"],
        "hard_negative_label_allowed": result["hard_negative_label_allowed"],
        "risk_engine_allowed": result["risk_engine_allowed"],
        "output": str(out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
