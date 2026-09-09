#!/usr/bin/env python3
"""Validate Phase 2 historical reconstruction and hard-negative guardrails."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.historical_policy import (  # noqa: E402
    validate_hard_negative_policy,
    validate_reconstruction_matrix,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", default="config/historical_reconstruction_matrix.json")
    parser.add_argument("--negative-policy", default="config/hard_negative_policy.json")
    parser.add_argument("--output", default="reports/historical/historical_policy_validation.json")
    args = parser.parse_args()

    matrix = json.loads(Path(args.matrix).read_text(encoding="utf-8"))
    policy = json.loads(Path(args.negative_policy).read_text(encoding="utf-8"))
    errors = [
        *validate_reconstruction_matrix(matrix),
        *validate_hard_negative_policy(policy),
    ]
    report = {
        "schema_version": "0.1.0",
        "phase": "2A-historical-policy-validation",
        "execution_ok": not errors,
        "error_count": len(errors),
        "errors": errors,
        "gates": {
            "reconstruction_exactness_policy": not validate_reconstruction_matrix(matrix),
            "hard_negative_policy": not validate_hard_negative_policy(policy),
            "hard_negative_registry": False,
            "historical_feature_reconstruction": False,
            "final_holdout_frozen": False,
            "risk_engine_allowed": False,
        },
        "risk_engine_allowed": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"report={output}")
    return 0 if report["execution_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
