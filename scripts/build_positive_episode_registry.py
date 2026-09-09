#!/usr/bin/env python3
"""Build conservative local positive episodes and frozen temporal split assignments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lpz_risk.historical_episodes import build_local_positive_episodes


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--positive-registry", required=True)
    p.add_argument("--policy", default="config/historical_split_policy.json")
    p.add_argument("--output", default="reports/historical/positive_episode_registry.json")
    a = p.parse_args()

    positive = json.loads(Path(a.positive_registry).read_text(encoding="utf-8"))
    policy = json.loads(Path(a.policy).read_text(encoding="utf-8"))
    result = build_local_positive_episodes(positive, policy)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "realized_positive_anchor_count": result["realized_positive_anchor_count"],
        "local_episode_count": result["local_episode_count"],
        "split_anchor_counts": result["split_anchor_counts"],
        "split_local_episode_counts": result["split_local_episode_counts"],
        "cross_subdivision_episode_grouping_complete": result["cross_subdivision_episode_grouping_complete"],
        "prospective_holdout_pristine_by_policy": result["prospective_holdout_pristine_by_policy"],
        "retrospective_2026_pristine": result["retrospective_2026_pristine"],
        "risk_engine_allowed": result["risk_engine_allowed"],
        "output": str(out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
