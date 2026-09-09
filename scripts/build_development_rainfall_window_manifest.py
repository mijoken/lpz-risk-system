#!/usr/bin/env python3
"""Build a de-duplicated DEVELOPMENT source-native 3-hour rainfall manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lpz_risk.rainfall_window_manifest import build_development_rainfall_window_manifest


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--episode-registry", required=True)
    p.add_argument("--output", default="reports/historical/development_rainfall_window_manifest.json")
    a = p.parse_args()
    episode = json.loads(Path(a.episode_registry).read_text(encoding="utf-8"))
    result = build_development_rainfall_window_manifest(episode)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "development_anchor_count": result["development_anchor_count"],
        "provider_count": result["provider_count"],
        "anchor_provider_mapping_count": result["anchor_provider_mapping_count"],
        "unique_request_window_count": result["unique_request_window_count"],
        "future_interval_count": result["future_interval_count"],
        "source_summary": result["source_summary"],
        "candidate_threshold_selected": result["candidate_threshold_selected"],
        "risk_engine_allowed": result["risk_engine_allowed"],
        "output": str(out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
