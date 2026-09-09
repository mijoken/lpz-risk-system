"""Conservative episode control and temporal split assignment for JMA positives.

This module intentionally groups anchors only within the same official primary
subdivision. Cross-subdivision meteorological episode linkage remains open until
historical precipitation/object geometry can support it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

JST = timezone(timedelta(hours=9))


def _parse(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return dt


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{prefix}-" + hashlib.sha256(raw).hexdigest()[:16]


def _split_boundaries(policy: dict[str, Any]) -> list[datetime]:
    starts = []
    for row in policy["temporal_splits"]:
        starts.append(_parse(row["start_jst"]).astimezone(JST))
    # First boundary is beginning of dataset policy, not an internal split.
    return sorted(starts)[1:]


def assign_temporal_split(time_jst: str, policy: dict[str, Any]) -> str:
    dt = _parse(time_jst).astimezone(JST)
    embargo = timedelta(hours=float(policy.get("boundary_embargo_hours", 0)))
    for boundary in _split_boundaries(policy):
        if boundary - embargo <= dt < boundary + embargo:
            return "BOUNDARY_EMBARGO"

    for row in policy["temporal_splits"]:
        start = _parse(row["start_jst"]).astimezone(JST)
        end_raw = row.get("end_jst_exclusive")
        end = _parse(end_raw).astimezone(JST) if end_raw else None
        if dt >= start and (end is None or dt < end):
            return str(row["split"])
    raise ValueError(f"timestamp outside frozen split policy: {time_jst}")


def build_local_positive_episodes(positive_registry: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    if policy.get("random_row_split_allowed") is not False:
        raise ValueError("random row split must remain forbidden")
    grouping = policy["local_episode_grouping"]
    if grouping["scope"] != "SAME_PRIMARY_SUBDIVISION_ONLY":
        raise ValueError("unsupported episode grouping scope")
    max_gap = timedelta(minutes=int(grouping["maximum_consecutive_anchor_gap_minutes"]))

    anchors = list(positive_registry.get("realized_positive_anchors") or [])
    by_code: dict[str, list[dict[str, Any]]] = {}
    for anchor in anchors:
        by_code.setdefault(str(anchor["primary_subdivision_code"]), []).append(anchor)

    episodes: list[dict[str, Any]] = []
    anchor_rows: list[dict[str, Any]] = []

    for code in sorted(by_code):
        rows = sorted(by_code[code], key=lambda a: (a["analysis_time_utc"], a["anchor_id"]))
        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        previous: datetime | None = None
        for anchor in rows:
            dt = _parse(anchor["analysis_time_utc"]).astimezone(timezone.utc)
            if previous is None or dt - previous <= max_gap:
                current.append(anchor)
            else:
                groups.append(current)
                current = [anchor]
            previous = dt
        if current:
            groups.append(current)

        for group in groups:
            start = _parse(group[0]["analysis_time_utc"]).astimezone(timezone.utc)
            end = _parse(group[-1]["analysis_time_utc"]).astimezone(timezone.utc)
            anchor_ids = [str(a["anchor_id"]) for a in group]
            episode_id = _stable_id("JMALEP", {
                "primary_subdivision_code": code,
                "start_utc": start.isoformat(),
                "end_utc": end.isoformat(),
                "anchor_ids": anchor_ids,
                "maximum_gap_minutes": int(grouping["maximum_consecutive_anchor_gap_minutes"]),
            })
            splits = {assign_temporal_split(a["analysis_time_jst"], policy) for a in group}
            if len(splits) != 1:
                # Any episode straddling a split boundary must never be allowed into
                # two independent sets. Quarantine the whole local episode.
                episode_split = "BOUNDARY_EMBARGO"
            else:
                episode_split = next(iter(splits))

            episodes.append({
                "entity_type": "LOCAL_POSITIVE_EPISODE",
                "local_episode_id": episode_id,
                "primary_subdivision_code": code,
                "start_time_utc": start.isoformat().replace("+00:00", "Z"),
                "end_time_utc": end.isoformat().replace("+00:00", "Z"),
                "duration_minutes_between_first_last_anchor": int((end - start).total_seconds() // 60),
                "anchor_count": len(group),
                "anchor_ids": anchor_ids,
                "temporal_split": episode_split,
                "cross_subdivision_grouping_complete": False,
                "risk_score": None,
            })
            for anchor in group:
                anchor_rows.append({
                    "anchor_id": anchor["anchor_id"],
                    "local_episode_id": episode_id,
                    "primary_subdivision_code": code,
                    "analysis_time_utc": anchor["analysis_time_utc"],
                    "analysis_time_jst": anchor["analysis_time_jst"],
                    "temporal_split": episode_split,
                })

    if len(anchor_rows) != len(anchors):
        raise AssertionError("not every realized-positive anchor was assigned to one local episode")
    ids = [row["anchor_id"] for row in anchor_rows]
    if len(ids) != len(set(ids)):
        raise AssertionError("anchor assigned more than once")

    split_anchor_counts: dict[str, int] = {}
    split_episode_counts: dict[str, int] = {}
    for row in anchor_rows:
        split_anchor_counts[row["temporal_split"]] = split_anchor_counts.get(row["temporal_split"], 0) + 1
    for row in episodes:
        split_episode_counts[row["temporal_split"]] = split_episode_counts.get(row["temporal_split"], 0) + 1

    prospective_start = _parse(policy["prospective_holdout_freeze_jst"]).astimezone(JST)
    prefreeze_prospective = [
        r for r in anchor_rows
        if r["temporal_split"] == "PROSPECTIVE_HOLDOUT" and _parse(r["analysis_time_jst"]).astimezone(JST) < prospective_start
    ]
    if prefreeze_prospective:
        raise AssertionError("pre-freeze data entered prospective holdout")

    return {
        "schema_version": "0.1.0",
        "phase": "2D-positive-local-episodes-and-temporal-splits",
        "policy_status": policy["policy_status"],
        "realized_positive_anchor_count": len(anchors),
        "local_episode_count": len(episodes),
        "split_anchor_counts": split_anchor_counts,
        "split_local_episode_counts": split_episode_counts,
        "episodes": sorted(episodes, key=lambda r: (r["start_time_utc"], r["primary_subdivision_code"], r["local_episode_id"])),
        "anchor_episode_assignments": sorted(anchor_rows, key=lambda r: (r["analysis_time_utc"], r["primary_subdivision_code"], r["anchor_id"])),
        "cross_subdivision_episode_grouping_complete": False,
        "prospective_holdout_pristine_by_policy": True,
        "retrospective_2026_pristine": False,
        "hard_negative_split_assignment_complete": False,
        "risk_engine_allowed": False,
    }
