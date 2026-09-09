#!/usr/bin/env python3
"""Validate the Scientific Evidence Engine registry and write a machine report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.evidence import load_registry, validate_registry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--registry",
        default="research/evidence/scientific_evidence_registry.json",
    )
    parser.add_argument(
        "--output",
        default="reports/evidence/scientific_evidence_validation.json",
    )
    args = parser.parse_args()

    data = load_registry(args.registry)
    result = validate_registry(data)

    payload = {
        "ok": result.ok,
        "paper_count": result.paper_count,
        "evidence_count": result.evidence_count,
        "required_variable_count": result.required_variable_count,
        "errors": list(result.errors),
        "warnings": list(result.warnings),
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))

    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
